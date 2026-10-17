"""FastAPI app. WebSocket /ws/session: text or audio in, streamed JSON events (+ base64 TTS audio) out.
See app/voice/session.py for the message protocol."""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.activity import ActivityLog, api as activity_api
from app.call_log import LlmCallLog
from app.agent import Agent, Session
from app.auth import api as auth_api, decode_user_id
from app.config import get_settings
from app.llm_policy import chat_model_key
from app.conversations import ConversationRepo
from app.db import create_pool
from app.embeddings import build_embedder
from app.llm import LLM, select_named_llm
from app.mcp_catalog.config_builder import configs_for_user
from app.mcp_catalog.public_host import build_public_mcp_app
from app.mcp_catalog.routes import api as mcp_catalog_api
from app.mcp_catalog.self_test import run_self_test
from app.mcp_catalog.store import McpInstallStore
from app.mcp_manager import MCPManager, load_server_configs
from app.memory.store import MemoryStore
from app.oauth_providers import build_providers
from app.notifications import NotificationRepo, api as notif_api
from app.website_kb import WebsiteKB, api as website_api
from app.oauth_routes import api as oauth_api
from app.token_vault import TokenVault
from app.ttl_cache import TtlCache
from app.voice.listen import limit_for_plan, lookup_prefs
from app.voice.session import VoiceSession
from app.files_routes import api as files_api
from app.live import hub
from app.devices.routes import api as devices_api
from app.workers.routes import api as vm_api
from app.task_notice import PushSender, TaskNotices, api as push_api

logging.basicConfig(level=logging.INFO)


def build_voice_providers(s):
    """(stt, tts) or (None, None) when no Sarvam key. Tests monkeypatch this."""
    if not s.sarvam_api_key:
        logging.warning("SARVAM_API_KEY not set: voice disabled (text turns still work)")
        return None, None
    from app.voice.sarvam import SarvamSTT, SarvamTTS
    return (SarvamSTT(s.sarvam_api_key, s.sarvam_base_ws, s.stt_model),
            SarvamTTS(s.sarvam_api_key, s.sarvam_base_ws, s.tts_model, s.tts_speaker, s.tts_codec))


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    pool = await create_pool(s.database_url)
    app.state.oauth_providers = build_providers(s)
    app.state.vault = TokenVault(pool, s.token_encryption_keys, app.state.oauth_providers) \
        if s.token_encryption_keys else None
    if app.state.vault is None:
        logging.warning("TOKEN_ENCRYPTION_KEYS not set: OAuth disabled, per-user MCP servers unavailable")
    configs = load_server_configs(s.mcp_servers_file)
    app.state.pat_providers = {c.auth for c in configs if c.credential == "pat" and c.auth}
    install_store = McpInstallStore(pool, s.token_encryption_keys) if app.state.vault else None
    app.state.mcp_installs = install_store

    async def _mcp_token(uid: str, auth: str):
        if app.state.vault:
            tok = await app.state.vault.token_for_mcp(uid, auth)
            if tok:
                return tok
        if install_store:
            if auth == "razorpay-mcp":
                sec = await install_store.secrets(uid, "razorpay-mcp")
                if sec and sec.get("key_id"):
                    return {"access_token": sec["key_id"], "key_secret": sec.get("key_secret", "")}
            dcr = await install_store.valid_oauth_access(uid, auth)
            if dcr:
                return dcr
        return None

    async def _mcp_secrets(uid: str, auth: str):
        if install_store and auth == "razorpay-mcp":
            sec = await install_store.secrets(uid, "razorpay-mcp")
            if sec and sec.get("key_id"):
                return sec
        return None

    mcp = MCPManager(
        configs,
        token_provider=_mcp_token if (app.state.vault or install_store) else None,
        secret_provider=_mcp_secrets if install_store else None,
    )
    await mcp.start()

    async def prepare_user_mcp(user_id: str) -> None:
        if not install_store or not user_id or user_id.startswith("__"):
            return
        cfgs = await configs_for_user(user_id, install_store, s.mcp_servers_file)
        mcp.set_user_configs(user_id, cfgs)
        await mcp.ensure_user(user_id)

    async def mcp_self_test(user_id: str, slug: str) -> None:
        await run_self_test(mcp, install_store, user_id, slug)

    app.state.prepare_user_mcp = prepare_user_mcp
    app.state.mcp_self_test = mcp_self_test
    app.state.pool = pool
    app.state.row_cache = TtlCache(60)
    llm_key = s.llm_api_key or (s.sarvam_api_key if "sarvam.ai" in s.llm_base_url else "")
    default_llm = LLM(s.llm_model, base_url=s.llm_base_url, api_key=llm_key)
    llms = {"sarvam" if "sarvam.ai" in s.llm_base_url else "default": default_llm}
    from app.bedrock import bedrock_chat_enabled, bedrock_chat_model_id, bedrock_deep_model_id, bedrock_region, make_bedrock_llm
    if bedrock_chat_enabled(s):
        llms["claude"] = make_bedrock_llm(bedrock_chat_model_id(s), bedrock_region(s), s)
    if s.groq_api_key:
        llms["groq"] = LLM(s.groq_model, base_url=s.groq_base_url, api_key=s.groq_api_key)
    if "sarvam" not in llms and s.sarvam_api_key:
        llms["sarvam"] = LLM("sarvam-105b", base_url="https://api.sarvam.ai/v1", api_key=s.sarvam_api_key)
    app.state.llms = llms
    app.state.activity = ActivityLog(pool)
    app.state.call_log = LlmCallLog(pool)
    app.state.call_log.start()
    embedder = build_embedder(s)
    app.state.website_kb = WebsiteKB(pool, embedder)
    app.state.website_crawl = app.state.website_kb.schedule_crawl
    store = MemoryStore(pool, embedder)
    store.touch_cache = app.state.row_cache
    app.state.agent = Agent(llm=default_llm, llms=llms, activity=app.state.activity, mcp=mcp,
                            store=store, convos=ConversationRepo(pool), settings=s,
                            )
    app.state.agent.prepare_user_mcp = prepare_user_mcp
    app.state.agent.call_log = app.state.call_log
    app.state.mcp = mcp
    app.state.notifications = NotificationRepo(pool, s.notifications_retention_days)
    app.state.agent.notifications = app.state.notifications
    app.state.agent.website_kb = app.state.website_kb
    from app.artifacts import storage_from_settings
    from app.doc_tools import FileTools
    app.state.files = FileTools(s, remote=storage_from_settings(s), pool=pool)
    app.state.agent.file_tools = app.state.files
    app.state.agent.tool_blobs = app.state.files.blobs
    app.state.notices = TaskNotices(
        pool, convos=app.state.agent.convos,
        push=PushSender(pool, project_id=s.firebase_project_id,
                        service_account_json=s.firebase_service_account_json))
    try:
        await app.state.notices.setup()
    except Exception:
        logging.exception("task notices disabled")
        app.state.notices = None
    app.state.website_kb.start_refresher(app.state.vault)
    app.state.vm = None
    app.state.deep = None
    app.state.devices = None
    if os.environ.get("DEVICES_ENABLED", "false").lower() == "true":  # the user's own Mac / Windows computers
        from app.devices.service import DeviceService
        from app.devices.tools import DeviceTools
        app.state.devices = DeviceService(pool, activity=app.state.activity)
        await app.state.devices.setup()
        app.state.agent.device_tools = DeviceTools(app.state.devices)
    if os.environ.get("VM_WORKERS_ENABLED", "false").lower() == "true":
        from app.workers.service import Cfg, VMService
        from app.workers.tools import VMTools
        app.state.vm = VMService(pool, activity=app.state.activity, cfg=Cfg(
            vision_provider=s.vm_vision_provider,
            vision_api_key=s.vm_vision_api_key,
            vision_base_url=s.vm_vision_base_url,
            vision_model=s.vm_vision_model,
        ))
        await app.state.vm.setup()
        from app.workers.resolve import DestinationResolver
        app.state.vm.resolver = DestinationResolver()
        sites = None
        site_base = (s.supabase_url or "").strip()
        site_key = (s.supabase_service_role_key or "").strip()
        if site_base and site_key:
            from app.artifacts import SupabaseStorage
            sites = SupabaseStorage(site_base, site_key, s.sites_bucket or "sites")
        app.state.agent.vm_tools = VMTools(
            app.state.vm, files=app.state.files, sites=sites,
            tokens=app.state.vault.token_for_mcp if app.state.vault else None,
            deploy_token=s.vercel_token, public_base=site_base,
            sites_bucket=s.sites_bucket or "sites")
        try:
            from app.deep_tasks import DeepTasks
            deep_llm = select_named_llm(llms, default_llm, s.deep_llm_provider)
            if s.deep_llm_provider.strip().lower() in ("claude", "groq") and "claude" in llms:
                deep_llm = make_bedrock_llm(bedrock_deep_model_id(s), bedrock_region(s), s)
            app.state.deep = DeepTasks(pool, app.state.vm, app.state.agent.vm_tools, app.state.activity,
                                       deep_llm.chat_model, s.database_url, call_log=app.state.call_log,
                                       notices=app.state.notices)
            await app.state.deep.setup()
            app.state.agent.deep = app.state.deep
        except Exception:
            logging.exception("deep agent tasks disabled")
    app.state.stt, app.state.tts = build_voice_providers(s)
    app.state.settings = s
    if s.jwt_secret:
        sub = build_public_mcp_app(s.jwt_secret, prepare_user_mcp, lambda: mcp)
        app.mount("/mcp/v1", sub)
    else:
        logging.warning("JWT_SECRET unset: public /mcp/v1 host disabled")
    try:
        await pool.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS plan text NOT NULL DEFAULT 'free'")
    except Exception:
        logging.warning("users.plan column not added", exc_info=True)
    if app.state.vm is not None and app.state.deep is not None and app.state.agent.vm_tools is not None:
        app.state.agent.vm_tools.deep = app.state.deep
        hub.deep = app.state.deep
    app.state.warm = asyncio.create_task(app.state.agent.warm_up())  # no cold first turn after a deploy
    yield
    if getattr(app.state, "deep", None):
        await app.state.deep.close()
    await app.state.agent.drain()
    await app.state.call_log.close()
    await mcp.close()
    await pool.close()


app = FastAPI(title="Admeasy backend", lifespan=lifespan)
app.include_router(oauth_api)
app.include_router(notif_api)
app.include_router(vm_api)
app.include_router(devices_api)
app.include_router(files_api)
app.include_router(auth_api)
app.include_router(activity_api)
app.include_router(website_api)
app.include_router(push_api)
app.include_router(mcp_catalog_api)


@app.get("/health")
async def health():
    return {"ok": True, "mcp_tools": len(app.state.mcp.compact_index()), "llms": list(app.state.llms),
            "voice": app.state.stt is not None, "oauth": app.state.vault is not None}


@app.get("/tools")
async def tools():
    return {"index": app.state.mcp.compact_index()}


TTS_CODECS = {"mp3", "wav", "linear16", "opus", "flac", "aac", "mulaw", "alaw"}
TTS_SAMPLE_RATES = {8000, 16000, 22050, 24000}


@app.websocket("/ws/session")
async def ws_session(ws: WebSocket, user_id: str | None = None, token: str | None = None,
                     conversation_id: str | None = None,
                     tts_codec: str | None = None, tts_sample_rate: int | None = None):
    st = ws.app.state.settings
    uid = decode_user_id(token, st.jwt_secret) or (user_id if st.allow_legacy_user_id else None)
    if not uid:
        await ws.close(code=4401)
        return
    user_id = uid
    await ws.accept()
    if tts_codec is not None and tts_codec not in TTS_CODECS:
        await ws.send_json({"type": "error", "error": f"unsupported tts_codec {tts_codec!r}"})
        tts_codec = None
    if tts_sample_rate is not None and tts_sample_rate not in TTS_SAMPLE_RATES:
        await ws.send_json({"type": "error", "error": f"unsupported tts_sample_rate {tts_sample_rate}"})
        tts_sample_rate = None
    agent: Agent = ws.app.state.agent
    session = Session(user_id=user_id, conversation_id=await agent.convos.start(user_id, conversation_id))
    prefs = await lookup_prefs(ws.app.state.pool, user_id, getattr(ws.app.state, "row_cache", None))
    pref = prefs.get("preferred_llm")
    plan = prefs.get("plan") or "free"
    session.llm = chat_model_key(pref, plan, set(agent.llms))
    session.plan = plan
    limit_s = limit_for_plan(plan, free=st.listen_limit_free_s, pro=st.listen_limit_pro_s)
    vs = VoiceSession(agent=agent, session=session, send=ws.send_json, stt=ws.app.state.stt,
                      tts=ws.app.state.tts, default_language=ws.app.state.settings.default_language,
                      tts_codec=tts_codec, tts_sample_rate=tts_sample_rate,
                      listen_limit_s=limit_s, plan=plan, stt_chunk_s=st.stt_chunk_s)
    hub.bind(user_id, vs)
    await ws.send_json({"type": "session", "conversation_id": session.conversation_id,
                        "voice": ws.app.state.stt is not None, "plan": plan, "listen_limit_s": limit_s})
    notices = getattr(ws.app.state, "notices", None)
    if notices is not None:
        await notices.flush(user_id, vs.send)
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await vs.on_audio(msg["bytes"])
                continue
            try:
                data = json.loads(msg.get("text") or "{}")
            except ValueError:
                await vs.send({"type": "error", "error": "invalid JSON"})
                continue
            if not await vs.on_json(data):
                await vs.wait_turn()
                await agent.convos.end(session.conversation_id)
                await agent.maybe_summarize(session.conversation_id, force=True)
                break
    except WebSocketDisconnect:
        pass
    finally:
        hub.drop(user_id, vs)
        await vs.close()
        try:
            await ws.close()
        except Exception:
            pass
