"""The agent loop. There is NO intent routing here: every user message goes to the LLM, and the LLM
decides. Python only executes the tool calls the model emitted.

The model always sees a compact index (name + one line) of every tool. Full schemas are attached
only after it calls load_tools with those names. An optional ranker may reorder the index and
cannot remove entries.

Tool namespaces (dispatch on the *name the LLM chose*, not on user text):
  memory_*      -> native memory handlers
  web_search, fetch_url -> built-in realtime web tools
  load_tools    -> attaches full schemas for the names the model asked for
  <server>__*   -> MCP server via MCPManager
"""
import asyncio
import json
import logging
import operator
import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, AsyncIterator, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.call_log import CallLogHandler, TurnLog, prepare_row, trace_tool_call, turn_log_var
from app.evidence import facts_from_tool, ground_completion
from app.context import ContextStats, build_context, cap_history, work_block
from app.focus import collapse_loops, looping, misses_latest, parse_focus, relevant_history
from app.conversations import ConversationRepo
from app.deep_tasks import DEEP_TOOL_NAMES, DEEP_TOOL_SCHEMAS
from app.lc_tools import describe_calls, is_write, is_yes, lc_tool, to_openai
from app.llm import LLM, runnable_config
from app.llm_policy import chat_fallback_key
from app.mcp_manager import MCPManager
from app.memory.store import MemoryStore
from app.memory.tools import MEMORY_TOOL_NAMES, MEMORY_TOOL_SCHEMAS, MemoryTools
from app.tokens import count_text, truncate_to
from app.notifications import NOTIFICATION_TOOL_NAMES, NOTIFICATION_TOOL_SCHEMAS
from app.tool_index import IndexRanker, attach_schemas, format_index, index_names, one_line, rank_index, trim_to_budget
from app.website_kb import WEBSITE_TOOL_NAMES, WEBSITE_TOOL_SCHEMAS
from app.tool_progress import spoken_preflight, spoken_still_working, spoken_tool_start
from app.web_tools import WEB_TOOL_NAMES, WEB_TOOL_SCHEMAS, WebTools
from app.doc_tools import FILE_TOOL_NAMES, FILE_TOOL_SCHEMAS
from app.time_tools import CURRENT_TIME_SCHEMAS, CURRENT_TIME_TOOL_NAMES, call_current_time
from app.script_gate import clean_reply, dedupe_sentences, should_rewrite
from app.devices.tools import DEVICE_TOOL_NAMES, DEVICE_TOOL_SCHEMAS
from app.workers.tools import VM_TOOL_NAMES, VM_TOOL_SCHEMAS, handoff_payload, vm_open_event

log = logging.getLogger(__name__)

LOAD_TOOLS_SCHEMA = {"type": "function", "function": {
    "name": "load_tools",
    "description": "Attach full argument schemas for tools you want to call. Pass names exactly as listed in the "
                   "tool index. This does not run those tools.",
    "parameters": {"type": "object", "properties": {
        "names": {"type": "array", "items": {"type": "string"},
                  "description": "Tool names from the index."}},
        "required": ["names"]}}}
WEB_CALLS_PER_TURN = 2


@dataclass
class Session:
    user_id: str
    conversation_id: str
    loaded_tools: dict[str, dict] = field(default_factory=dict)  # full schemas the model loaded; oldest first
    servers: set[str] = field(default_factory=set)  # MCP servers this user can use (shared + connected accounts)
    web_calls: int = 0  # web_search/fetch_url calls in the current turn (budgeted for voice latency)
    used_tools: set[str] = field(default_factory=set)  # tools already called this turn; their schemas stay bound
    llm: str = "sarvam"  # per-user preferred chat model key ("sarvam" | "claude")
    pending_approval: str | None = None  # graph thread paused on a write or a VM handoff
    pause_kind: str | None = None  # "approval" (spoken yes/no) | "control" (I'm done / Skip)
    pending_verification: dict | None = None  # screen check already run for this resume
    language: str | None = None
    source: str = "live"  # live | eval | synthetic
    compass_version: str | None = None
    compass_hint: str | None = None
    tool_index: list[str] = field(default_factory=list)  # names only, in the order shown this turn
    goal: str = ""
    model_goal: str = ""
    entities: str = ""
    artifacts: str = ""
    blockers: str = ""
    last_answer: str = ""
    focus_for: str = ""
    tool_facts: list = field(default_factory=list)  # evidence from tools in the current turn
    plan: str = "free"  # billing plan; enables Groq failover when the primary LLM fails


class TurnState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    answer: Annotated[str, operator.add]
    rounds: Annotated[int, operator.add]
    user_text: str
    handoff: dict | None


CONTROL_DONE = ("The user finished the step on the live screen. Continue the task from where it stopped.")
CONTROL_SKIP = ("The user skipped the step on the live screen. Look through the tool index for an API or MCP tool "
                "that can do this, and try that path. If every path fails, say so plainly and do not claim the step "
                "worked. Otherwise tell them the step needs them on the screen.")
SESSION_READY = "The session is ready. Continue the task from where it stopped."


def control_note(choice: str, verification: dict | None = None) -> str:
    if choice == "done":
        note = CONTROL_DONE
    elif choice == "skip":
        note = CONTROL_SKIP
    elif choice == "session_ready":
        note = SESSION_READY
    else:
        note = choice or CONTROL_SKIP
    if verification is not None and choice in ("done", "session_ready"):
        note += "\nVERIFICATION " + json.dumps(verification, ensure_ascii=False)
        note += (" If ok is false, tell the user the sign-in or check did not succeed and do not continue as if it had."
                 " If ok is true, continue the task.")
    return note


def paused_thread(session: Session, store: dict | None) -> tuple[str | None, str | None]:
    """The parked graph thread for this user, including one remembered across a reconnect."""
    pending = session.pending_approval
    kind = session.pause_kind
    if pending:
        return pending, kind
    saved = (store or {}).get(session.user_id)
    if isinstance(saved, dict) and saved.get("conversation_id") == session.conversation_id and saved.get("thread"):
        return saved.get("thread"), saved.get("kind") or kind
    return None, kind


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {"__invalid_json__": raw}


# The one fixed utterance in the app: when the LLM itself is rate-limited there is no model to phrase a reply,
# and a voice user must not be left in silence.
RATE_LIMIT_SPOKEN = "My usage limit is reached right now. Please try again in {wait}."


def rate_limit_info(e: BaseException) -> dict | None:
    """{'retry_after_s': int|None, 'daily': bool} if e is an LLM provider 429, else None."""
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    msg = str(e)
    if status != 429 and type(e).__name__ != "RateLimitError" and "rate_limit_exceeded" not in msg:
        return None
    retry = None
    headers = getattr(getattr(e, "response", None), "headers", None) or {}
    try:
        retry = int(float(headers.get("retry-after"))) if headers.get("retry-after") else None
    except (TypeError, ValueError):
        retry = None
    return {"retry_after_s": retry, "daily": "per day" in msg or "TPD" in msg or "RPD" in msg}


def _wait_words(info: dict) -> str:
    r = info.get("retry_after_s")
    if r is None:
        return "a while" if info.get("daily") else "a minute"
    if r < 90:
        return "a minute"
    return f"about {round(r / 60)} minutes" if r < 5400 else f"about {round(r / 3600)} hours"


def llm_failover_eligible(e: BaseException) -> bool:
    """True when retrying on another provider (Groq) is reasonable."""
    if rate_limit_info(e) is not None:
        return True
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    if status in (408, 429, 500, 502, 503, 504, 529):
        return True
    name = type(e).__name__.lower()
    if any(x in name for x in ("timeout", "throttl", "serviceunavailable", "apitimeout", "connecterror")):
        return True
    msg = str(e).lower()
    return any(x in msg for x in (
        "throttl", "rate limit", "rate_limit", "overloaded", "capacity",
        "too many requests", "bedrock", "model is currently",
        "service unavailable", "503", "502", "504",
    ))


class Agent:
    def __init__(self, *, llm: LLM, mcp: MCPManager, store: MemoryStore, convos: ConversationRepo, settings,
                 llms: dict[str, LLM] | None = None, activity=None, ranker: IndexRanker | None = None):
        self.llm, self.mcp, self.store, self.convos, self.s = llm, mcp, store, convos, settings
        self.llms = llms or {}
        self.activity = activity  # ActivityLog or None
        self.ranker = ranker  # optional; may reorder the index, never used to drop tools
        self.memory_tools = MemoryTools(store)
        self.web_tools = WebTools()
        self._bg: set[asyncio.Task] = set()
        self.notifications = None  # NotificationRepo, set by main when the DB is up
        self.vm_tools = None  # workers.tools.VMTools, set by main when VM workers are enabled
        self.device_tools = None  # devices.tools.DeviceTools (the user's own Mac/PC), set by main
        self.file_tools = None  # doc_tools.FileTools, set by main
        self.tool_blobs: dict[str, str] = {}
        self.website_kb = None  # WebsiteKB, set by main
        self.deep = None  # deep_tasks.DeepTasks (long VM jobs), set by main
        self.call_log = None  # LlmCallLog, set by main
        self._graph = None
        self.paused_turns: dict[str, dict] = {}

    def _builtin_schemas(self) -> list[dict]:
        schemas = [*MEMORY_TOOL_SCHEMAS, *WEB_TOOL_SCHEMAS]
        if self.notifications:
            schemas.extend(NOTIFICATION_TOOL_SCHEMAS)
        if self.website_kb:
            schemas.extend(WEBSITE_TOOL_SCHEMAS)
        if self.vm_tools:
            schemas.extend(VM_TOOL_SCHEMAS)
        if self.device_tools:
            schemas.extend(DEVICE_TOOL_SCHEMAS)
        if getattr(self, "file_tools", None):
            schemas.extend(FILE_TOOL_SCHEMAS)
        if self.deep:
            schemas.extend(DEEP_TOOL_SCHEMAS)
        return schemas

    def index_entries(self, session: Session) -> list[dict]:
        entries = []
        for sc in self._builtin_schemas():
            fn = sc["function"]
            pinned = fn["name"] in VM_TOOL_NAMES or fn["name"] in DEVICE_TOOL_NAMES or fn["name"] in NOTIFICATION_TOOL_NAMES or fn["name"] in DEEP_TOOL_NAMES \
                or fn["name"] in WEB_TOOL_NAMES or fn["name"] in FILE_TOOL_NAMES \
                or fn["name"] in CURRENT_TIME_TOOL_NAMES
            entries.append({"name": fn["name"], "description": ("[ready, call directly] " if pinned else "") +
                            one_line(fn.get("description") or "")})
        entries.extend(self.mcp.compact_index(session.servers, user_id=session.user_id))
        return entries

    def index_view(self, session: Session, query: str) -> tuple[str, list[str], str | None, str | None]:
        """Rendered index, names in shown order, compass version, compass hint.

        The hint is recorded on the call log. It is not inserted into the prompt and it cannot hide a tool.
        """
        entries, version, hint = rank_index(self.index_entries(session), query, self.ranker)
        text = format_index(entries, self.s.index_token_budget)
        return text, index_names(text), version, hint

    def index_text(self, session: Session, query: str) -> str:
        text, _names, _version, _hint = self.index_view(session, query)
        return text

    def _tools(self, session: Session) -> list[dict]:
        # Only the loader plus schemas the model has asked for. Tools already called this turn stay
        # bound: Groq rejects a later request whose history names a tool missing from request.tools.
        # VM + notification tools are always bound (no load_tools round trip): they back core voice intents
        # ("open my computer", "read my notifications") and every extra LLM round adds ~1 s of latency.
        # Web search is always bound (foreground and background). The model still chooses whether to call it.
        pinned = (VM_TOOL_SCHEMAS if self.vm_tools else []) + (DEVICE_TOOL_SCHEMAS if self.device_tools else []) + (DEEP_TOOL_SCHEMAS if self.deep else []) + \
            (FILE_TOOL_SCHEMAS if getattr(self, "file_tools", None) else []) + \
            (NOTIFICATION_TOOL_SCHEMAS if self.notifications else []) + WEB_TOOL_SCHEMAS + CURRENT_TIME_SCHEMAS
        names = {p["function"]["name"] for p in pinned}
        return [LOAD_TOOLS_SCHEMA, *pinned, *(v for k, v in session.loaded_tools.items() if k not in names)]

    def _trim_loaded(self, session: Session) -> None:
        trim_to_budget(session.loaded_tools, self.s.schema_token_budget, LOAD_TOOLS_SCHEMA)

    def _chat_llm(self, session: Session) -> LLM:
        return self.llms.get(session.llm, self.llm)

    async def _complete_chat(self, session: Session, llm: LLM, messages: list[dict], **kwargs) -> str:
        try:
            return await llm.complete(messages, **kwargs)
        except Exception as e:
            fb = chat_fallback_key(session.llm, session.plan, set(self.llms))
            if not fb or not llm_failover_eligible(e):
                raise
            log.warning("chat LLM %s complete failed (%s); failing over to %s",
                        session.llm, type(e).__name__, fb)
            session.llm = fb
            return await self.llms[fb].complete(messages, **kwargs)

    async def _stream_chat(self, session: Session, llm: LLM, messages: list[dict], tools: list[dict] | None,
                           config, emit) -> tuple[str, list]:
        """Stream assistant output; on provider failure, Pro users retry once on Groq."""

        async def _once(active: LLM) -> tuple[str, list]:
            text, calls = "", []
            async for ev in active.stream(messages, tools, runnable_config(config, active)):
                if ev.text:
                    text += ev.text
                    emit(ev.text)
                if ev.done:
                    calls = ev.tool_calls
            return text, calls

        try:
            return await _once(llm)
        except Exception as e:
            fb = chat_fallback_key(session.llm, session.plan, set(self.llms))
            if not fb or not llm_failover_eligible(e):
                raise
            log.warning("chat LLM %s failed (%s); failing over to %s for user %s",
                        session.llm, type(e).__name__, fb, session.user_id)
            session.llm = fb
            return await _once(self.llms[fb])

    async def build(self, session: Session, text: str) -> tuple[list[dict], ContextStats]:
        prep = getattr(self, "prepare_user_mcp", None)
        if prep:
            await prep(session.user_id)
        else:
            await self.mcp.ensure_user(session.user_id)
        session.servers = await self.mcp.available_servers(session.user_id)
        await self.mcp.refresh_if_stale(session.servers)
        self._trim_loaded(session)
        summary, _ = await self.convos.latest_summary(session.conversation_id)
        turns = cap_history(await self.convos.last_turns(session.conversation_id, self.s.last_n_turns * 2),
                            self.s.history_message_tokens)
        turns = relevant_history(text, turns)
        mems = await self.store.search(session.user_id, text, top_k=self.s.memory_top_k,
                                       token_cap=self.s.memory_token_cap)
        index_text, names, version, hint = self.index_view(session, text)
        session.tool_index, session.compass_version, session.compass_hint = names, version, hint
        session.goal = " ".join((text or "").split())[:160]
        session.focus_for = session.goal
        shown_goal = session.model_goal if session.model_goal and session.model_goal != session.goal else ""
        artifact_index = ""
        files = getattr(self, "file_tools", None)
        if files is not None:
            try:
                artifact_index = await files.index_text(session.user_id)
            except Exception:
                log.warning("artifact index failed", exc_info=True)
        return build_context(user_message=text, tool_index_text=index_text, summary=summary,
                             memories=mems, turns=turns, tools=self._tools(session), cap=self.s.context_token_cap,
                             state_text=work_block(shown_goal, session.artifacts, session.blockers, session.entities,
                                                   artifact_index))

    # ---------- LangGraph turn loop ----------
    def _lc_tools(self, session: Session) -> list:
        """Currently bound tools as LangChain tools; each one runs through _execute (activity, budgets, MCP)."""
        return [lc_tool(sc, lambda n, a: self._execute(session, n, a)) for sc in self._tools(session)]

    def graph(self):
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph

    def _build_graph(self):
        agent = self

        async def model(state: TurnState, config):
            sess: Session = config["configurable"]["session"]
            w = get_stream_writer()
            tools = to_openai(agent._lc_tools(sess))
            llm = agent._chat_llm(sess)
            try:
                text, calls = await agent._stream_chat(
                    sess, llm, state["messages"], tools, config,
                    lambda t: w({"type": "token", "text": t}))
            except Exception as e:
                info = rate_limit_info(e)
                if info is None:
                    raise
                log.warning("LLM rate limited (no Groq failover): %s", e)
                spoken = RATE_LIMIT_SPOKEN.format(wait=_wait_words(info))
                w({"type": "error", "code": "rate_limited", **info, "error": "LLM provider rate limit"})
                w({"type": "token", "text": spoken})
                text, calls = spoken, []
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = [{"id": c.id, "type": "function", "function": {
                    "name": c.name, "arguments": c.arguments_json or "{}"}} for c in calls]
            return {"messages": [msg], "answer": text, "rounds": 1}

        def route(state: TurnState):
            last = state["messages"][-1]
            if not last.get("tool_calls"):
                return END
            return "tools"

        def after_tools(state: TurnState):
            # A sign-in handoff pauses in its own node so the browser tool is not run twice on resume.
            if state.get("handoff"):
                return "control"
            # `rounds` counts model calls. Execute every call up to max_tool_iterations, then summarize.
            if state["rounds"] >= agent.s.max_tool_iterations:
                return "final"
            return "model"

        async def _run_tool_call(c, bound, nested, sess, agent, approved, reply):
            if is_write(c["name"]) and not approved:
                result = json.dumps({"error": "the user did not approve this action; do not retry unless asked"})
                await trace_tool_call(nested, c["name"], c["args"], result)
                return result
            t = bound.get(c["name"])
            if t is None or "__invalid_json__" in c["args"]:
                result = await agent._execute(sess, c["name"], c["args"])
                await trace_tool_call(nested, c["name"], c["args"], result)
                return result
            if nested:
                return await t.ainvoke(c["args"], config=nested)
            return await t.ainvoke(c["args"])

        async def tools(state: TurnState, config):
            sess: Session = config["configurable"]["session"]
            w = get_stream_writer()
            calls = [{"id": c["id"], "name": c["function"]["name"],
                      "args": _parse_args(c["function"].get("arguments"))} for c in state["messages"][-1]["tool_calls"]]
            writes = [c for c in calls if is_write(c["name"])]
            approved = True
            reply = None
            if writes:
                # Hard stop before anything that changes the outside world: resumes with the user's next utterance.
                reply = interrupt({"calls": writes, "question": describe_calls(writes)})
                approved = is_yes(str(reply))
            turn = turn_log_var.get()
            if turn is not None:
                turn.approved = approved if writes else None
            llm = agent.llms.get(sess.llm, agent.llm)
            nested = runnable_config(config, llm)
            for c in calls:
                w({"type": "tool_call", "id": c["id"], "name": c["name"], "arguments": c["args"]})
                w({"type": "token", "text": spoken_tool_start(c["name"])})
                if c["name"] != "load_tools":
                    sess.used_tools.add(c["name"])
                    agent._ensure_bound(sess, c["name"])
            bound = {t.name: t for t in agent._lc_tools(sess)}

            async def run_one(c):
                task = asyncio.create_task(_run_tool_call(c, bound, nested, sess, agent, approved, reply))
                tick = 0
                while not task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=3.5)
                    except asyncio.TimeoutError:
                        w({"type": "token", "text": spoken_still_working(c["name"], tick)})
                        tick += 1
                return task.result()

            results = await asyncio.gather(*(run_one(c) for c in calls))
            out = []
            spoken = str(reply) if writes and reply is not None else None
            for c, r in zip(calls, results):
                if agent.activity:
                    agent._spawn(agent.activity.log(sess.user_id, sess.conversation_id, c["name"], c["args"], r,
                                                    approval=spoken if is_write(c["name"]) else None))
                raw = str(r)
                sess.tool_facts.append(facts_from_tool(raw))
                att = _attachment(raw)
                if att:
                    w({"type": "attachment", "name": att["name"], "url": att["url"], "mime": att.get("mime") or ""})
                    sess.artifacts = ((sess.artifacts + ", ") if sess.artifacts else "") + att["name"]
                    sess.artifacts = sess.artifacts[-200:]
                compacted = compact_tool_result(raw, agent.s.tool_result_token_cap, agent.tool_blobs)
                content = tool_model_content(c["name"], raw, compacted, getattr(agent, "file_tools", None),
                                             sess.user_id)
                out.append({"role": "tool", "tool_call_id": c["id"], "content": content, "_text": compacted})
                w({"type": "tool_result", "id": c["id"], "name": c["name"], "result": compacted})
                for side in client_events_for_tool(raw):
                    w(side)
            handoff = None
            for c, msg in zip(calls, out):
                found = handoff_payload(c["name"], msg.get("_text") or "")
                if found:
                    handoff = found
                    sess.blockers = "waiting on the user"
                    break
            return {"messages": out, "handoff": handoff}

        async def control(state: TurnState, config):
            w = get_stream_writer()
            payload = dict(state.get("handoff") or {})
            payload["kind"] = "take_control"
            w({"type": "take_control", "login_link": payload.get("login_link"),
               "terminal_link": payload.get("terminal_link"), "files_link": payload.get("files_link"),
               "signin_link": payload.get("signin_link"), "open": bool(payload.get("open"))})
            choice = interrupt(payload)
            sess: Session = config["configurable"]["session"]
            sess.blockers = ""
            verification = None
            if isinstance(choice, dict):
                verification = choice.get("verification") if isinstance(choice.get("verification"), dict) else None
                choice = choice.get("choice") or "skip"
            return {"messages": [{"role": "user", "content": control_note(str(choice or "skip"), verification)}],
                    "handoff": None}

        async def final(state: TurnState, config):
            # Out of tool rounds: one last call WITHOUT tools so the user always gets a real answer, never an error.
            sess: Session = config["configurable"]["session"]
            w = get_stream_writer()
            msgs = _flatten_tools(state["messages"]) + [{"role": "user", "content": (
                "Stop calling tools now. In 1-3 short sentences tell me what you did, what you found, and what is "
                "still pending (and how I can finish it). Do not say the task is done unless a tool result shows "
                "a file that exists, a URL that returned HTTP 200, or a screenshot.")}]
            llm = agent._chat_llm(sess)
            try:
                text, _ = await agent._stream_chat(sess, llm, msgs, None, config,
                                                   lambda t: w({"type": "token", "text": t}))
            except Exception as e:
                log.warning("final summary failed: %s", e)
                text = ""
            if not text.strip():
                text = "I did several steps but couldn't finish this in one go. Ask me to continue and I'll pick up from here."
                w({"type": "token", "text": text})
            return {"answer": text}

        g = StateGraph(TurnState)
        g.add_node("model", model)
        g.add_node("tools", tools)
        g.add_node("control", control)
        g.add_node("final", final)
        g.add_edge(START, "model")
        g.add_conditional_edges("model", route, ["tools", END])
        g.add_conditional_edges("tools", after_tools, ["model", "final", "control"])
        g.add_edge("control", "model")
        g.add_edge("final", END)
        return g.compile(checkpointer=InMemorySaver(), name="admeasy-voice-turn")

    async def run(self, session: Session, text: str, *, control: str | None = None) -> AsyncIterator[dict]:
        t0 = time.perf_counter()
        session.web_calls = 0
        session.tool_facts = []
        text = (text or "").strip()
        pending, kind = paused_thread(session, getattr(self, "paused_turns", None))
        session.pending_approval = None
        session.pause_kind = None
        if pending and control is not None and kind == "control":
            # I'm done / Skip: resume without a new user bubble. Verify before continuing.
            resume_value: str | dict = control
            verdict = session.pending_verification
            session.pending_verification = None
            if verdict is None and control in ("done", "session_ready") and self.vm_tools is not None:
                try:
                    verdict = await self.vm_tools.verify_screen(session.user_id)
                except Exception:
                    verdict = {"ok": False, "reason": "the screen could not be checked"}
            if verdict is not None:
                resume_value = {"choice": control, "verification": verdict}
            if self.deep is not None:
                self._spawn(self.deep.nudge(session.user_id, control_note(control, verdict if isinstance(verdict, dict) else None)))
            if self.vm_tools is not None and hasattr(self.vm_tools.svc, "set_screen_mode"):
                try:
                    await self.vm_tools.svc.set_screen_mode(session.user_id, "off")
                except Exception:
                    log.warning("releasing screen hold failed")
            thread, inp = pending, Command(resume=resume_value)
        elif pending:
            # Spoken reply: approval yes/no, or words while a handoff card is up.
            if not text:
                return
            thread, inp = pending, Command(resume=text)
            await self.convos.add(session.conversation_id, "user", text)
        else:
            if not text:
                return
            session.used_tools.clear()
            messages, stats = await self.build(session, text)
            yield {"type": "context", "tokens": stats.total_tokens, "cap": stats.cap, "turns_kept": stats.turns_kept,
                   "turns_dropped": stats.turns_dropped, "memories": stats.memories_kept,
                   "index_shrunk": stats.index_descriptions_shrunk}
            await self.convos.add(session.conversation_id, "user", text)
            thread = f"{session.conversation_id}:{uuid.uuid4().hex[:12]}"
            inp = {"messages": messages, "answer": "", "rounds": 0, "user_text": text, "handoff": None}
            yield {"type": "token", "text": spoken_preflight()}
        llm = self._chat_llm(session)
        source = session.source if session.source in ("live", "eval", "synthetic") else "live"
        handler = CallLogHandler(self.call_log) if self.call_log else None
        ctx = TurnLog(source=source, user_id=session.user_id, session_id=session.conversation_id, turn_id=thread,
                      model=llm.model, provider=llm.provider, compass_version=session.compass_version,
                      tool_index=list(session.tool_index or []), compass_hint=session.compass_hint,
                      language=session.language, transcript=text)
        cfg = {"configurable": {"thread_id": thread, "session": session},
               "recursion_limit": 4 * self.s.max_tool_iterations + 8, "run_name": "voice_turn",
               "metadata": {"user_id": session.user_id, "conversation_id": session.conversation_id, "source": source}}
        if handler:
            cfg["callbacks"] = [handler]
        answer, first_token_ms, paused = "", None, None
        token = turn_log_var.set(ctx)
        try:
            async for mode, chunk in self.graph().astream(inp, cfg, stream_mode=["custom", "updates"]):
                if mode == "custom":
                    if chunk.get("type") == "token":
                        if first_token_ms is None:
                            first_token_ms = round((time.perf_counter() - t0) * 1000)
                        cleaned = clean_reply(chunk.get("text") or "")
                        if not cleaned:
                            continue
                        chunk = {**chunk, "text": cleaned}
                        answer += cleaned
                    yield chunk
                elif isinstance(chunk, dict) and "__interrupt__" in chunk:
                    paused = chunk["__interrupt__"][0].value
            if paused:
                session.pending_approval = thread
                if isinstance(paused, dict) and paused.get("kind") == "take_control":
                    session.pause_kind = "control"
                    yield {"type": "take_control", "login_link": paused.get("login_link"),
                           "terminal_link": paused.get("terminal_link"), "files_link": paused.get("files_link"),
                           "signin_link": paused.get("signin_link"), "open": bool(paused.get("open"))}
                else:
                    session.pause_kind = "approval"
                    q = (" " if answer and not answer.endswith(" ") else "") + "Shall I go ahead? Please say yes or no."
                    answer += q
                    yield {"type": "approval_required", "calls": paused.get("calls") if isinstance(paused, dict) else None}
                    yield {"type": "token", "text": q}
            elif should_rewrite(answer, session.language, text):
                rewritten = await self._rewrite(session, answer, self._chat_llm(session))
                if rewritten:
                    answer = rewritten
                    yield {"type": "revision", "text": answer}
            if not paused and answer:
                answer = collapse_loops(dedupe_sentences(answer))
                if looping(answer) or misses_latest(text, answer, session.last_answer):
                    fixed = await self._refocus(session, text, answer, self._chat_llm(session))
                    if fixed and fixed != answer:
                        answer = collapse_loops(fixed)
                        yield {"type": "revision", "text": answer}
                grounded = ground_completion(answer, session.tool_facts)
                if grounded and grounded != answer:
                    answer = grounded
                    yield {"type": "revision", "text": answer}
                session.last_answer = answer
                self._spawn(self._refresh_focus(session, text, answer, self._chat_llm(session)))
            if answer.strip():
                await self.convos.add(session.conversation_id, "assistant", answer)
            yield {"type": "done", "text": answer, "first_token_ms": first_token_ms,
                   "total_ms": round((time.perf_counter() - t0) * 1000)}
            self._spawn(self.maybe_summarize(session.conversation_id))
        except asyncio.CancelledError:
            if self.call_log:
                try:
                    await self.call_log.write(prepare_row({"kind": "llm", "status": "cancelled",
                                                           "result_summary": "cancelled"}))
                except Exception:
                    log.warning("cancelled-turn log failed", exc_info=True)
            raise
        finally:
            store = getattr(self, "paused_turns", None)
            if store is not None:
                if session.pending_approval:
                    store[session.user_id] = {"thread": session.pending_approval, "kind": session.pause_kind,
                                              "conversation_id": session.conversation_id}
                else:
                    store.pop(session.user_id, None)
            if not session.pending_approval:
                await self._drop_thread(thread)
            turn_log_var.reset(token)

    async def warm_up(self) -> None:
        """Pay one-time costs at startup instead of on the first user's turn: compile the graph, open TLS/HTTP2
        pools to each LLM provider, load the embedder, and touch the DB/MCP paths a turn uses."""
        t0 = time.perf_counter()
        self.graph()
        if any(getattr(llm, "client", None) is not None for llm in [self.llm, *self.llms.values()]):
            return  # scripted test doubles: don't consume their turns
        steps = [llm.complete([{"role": "user", "content": "hi"}], max_tokens=1) for llm in {*self.llms.values(), self.llm}]
        steps.append(self.store.search("__warmup__", "hello", top_k=1, token_cap=50))
        steps.append(self.convos.latest_summary("00000000-0000-0000-0000-000000000000"))
        res = await asyncio.gather(*steps, return_exceptions=True)
        # One real end-to-end turn (graph, tool binding, provider stream, tracing client) on a throwaway session:
        # the first turn after a deploy used to take 8-13 s because all of this was lazily initialised.
        try:
            sess = Session("__warmup__", await self.convos.start("__warmup__"), source="synthetic")
            async for _ in self.run(sess, "Reply with just: ok"):
                pass
        except Exception as e:
            res = [*res, e]
        bad = [f"{type(r).__name__}: {str(r)[:120]}" for r in res if isinstance(r, BaseException)]
        log.warning("warm-up done in %d ms%s", (time.perf_counter() - t0) * 1000, f" (failed: {bad})" if bad else "")

    def _requested_names(self, args: dict) -> list[str]:
        raw = args.get("names") or []
        if isinstance(raw, str):
            raw = [raw]
        return list(dict.fromkeys(n.strip() for n in raw if isinstance(n, str) and n.strip()))

    def _schemas_for(self, names: list[str], session: Session) -> tuple[list[dict], list[str]]:
        builtins = {s["function"]["name"]: s for s in self._builtin_schemas()}
        found: dict[str, dict] = {}
        missing: list[str] = []
        mcp_names = []
        for n in names:
            if n in builtins:
                found[n] = builtins[n]
            else:
                mcp_names.append(n)
        if mcp_names:
            schemas, miss = self.mcp.full_schemas(mcp_names, session.servers, user_id=session.user_id)
            for sc in schemas:
                found[sc["function"]["name"]] = sc
            missing.extend(miss)
        return [found[n] for n in names if n in found], missing

    def _ensure_bound(self, session: Session, name: str) -> None:
        if name in session.loaded_tools:
            return
        schemas, _ = self._schemas_for([name], session)
        if schemas:
            session.loaded_tools[schemas[0]["function"]["name"]] = schemas[0]

    async def _execute(self, session: Session, name: str, args: dict) -> str:
        try:
            if "__invalid_json__" in args:
                return json.dumps({"error": "arguments were not valid JSON", "raw": args["__invalid_json__"]})
            if name in MEMORY_TOOL_NAMES:
                return await self.memory_tools.call(session.user_id, name, args)
            if name in CURRENT_TIME_TOOL_NAMES:
                return call_current_time()
            if name in WEB_TOOL_NAMES:
                session.web_calls += 1
                if session.web_calls > WEB_CALLS_PER_TURN:
                    return json.dumps({"error": "web budget for this turn is used up; answer now from the results "
                                       "you already have, or say you could not find it"})
                return await self.web_tools.call(name, args)
            if name in WEBSITE_TOOL_NAMES and self.website_kb:
                return await self.website_kb.call(session.user_id, args)
            if name in VM_TOOL_NAMES and self.vm_tools:
                return await self.vm_tools.call(session.user_id, name, args, session.conversation_id)
            if name in DEVICE_TOOL_NAMES and self.device_tools:
                return await self.device_tools.call(session.user_id, name, args, session.conversation_id)
            if name in FILE_TOOL_NAMES and getattr(self, "file_tools", None):
                return await self.file_tools.call(session.user_id, name, args)
            if name in DEEP_TOOL_NAMES and self.deep:
                return await self.deep.call(session.user_id, name, args, session.conversation_id)
            if name in NOTIFICATION_TOOL_NAMES and self.notifications:
                return await self.notifications.call(session.user_id, args)
            if name == "load_tools":
                schemas, missing = self._schemas_for(self._requested_names(args), session)
                attached, skipped, unloaded = attach_schemas(
                    session.loaded_tools, schemas, self.s.schema_token_budget, LOAD_TOOLS_SCHEMA, session.used_tools)
                return json.dumps({"loaded": attached, "unknown": missing, "skipped_for_budget": skipped,
                                   "unloaded": unloaded}, ensure_ascii=False)
            if self.mcp.has_tool(name, user_id=session.user_id):
                return await self.mcp.call_tool(name, args, user_id=session.user_id)
            return json.dumps({"error": f"unknown tool {name}"})
        except Exception as e:  # tool failure is reported to the model, never crashes the session
            log.exception("tool %s failed", name)
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    async def _refocus(self, session: Session, latest: str, answer: str, llm: LLM) -> str:
        """One cheap pass when the reply loops or follows an earlier answer."""
        try:
            text = await self._complete_chat(session, llm, [
                {"role": "system", "content": "Rewrite the reply so it does the latest user message. "
                 "Drop earlier tasks. Do not repeat a sentence. Do not add facts."},
                {"role": "user", "content": f"Latest user message:\n{latest[:2000]}\n\nReply:\n{answer[:4000]}"}],
                max_tokens=400)
        except Exception:
            log.warning("refocus failed", exc_info=True)
            return answer
        cleaned = collapse_loops(dedupe_sentences(clean_reply((text or "").strip())))
        return cleaned or answer

    async def _refresh_focus(self, session: Session, user_text: str, answer: str, llm: LLM) -> None:
        """The model writes the structured task state. A newer turn discards a stale write."""
        stamp = session.focus_for
        try:
            raw = await self._complete_chat(session, llm, [
                {"role": "system", "content": "Update the task state. The latest user message is the goal. "
                 "Reply with four lines only: goal, entities, artifacts, blockers."},
                {"role": "user", "content": f"Latest user message:\n{user_text[:2000]}\n\nReply:\n{answer[:800]}"}],
                max_tokens=180)
        except Exception:
            log.warning("focus update failed", exc_info=True)
            return
        if session.focus_for != stamp:
            return
        parsed = parse_focus(raw)
        if parsed.get("goal"):
            session.model_goal = parsed["goal"]
        if parsed.get("entities"):
            session.entities = parsed["entities"]
        if parsed.get("artifacts"):
            session.artifacts = parsed["artifacts"]
        if parsed.get("blockers"):
            session.blockers = parsed["blockers"]

    async def _rewrite(self, session: Session, answer: str, llm: LLM) -> str:
        """One extra call when the reply used the wrong script. The check is on characters, not words."""
        try:
            text = await self._complete_chat(session, llm, [
                {"role": "system", "content": "Rewrite the reply. Hindi words in Devanagari. Common English words "
                 "may stay in Latin. Do not use Japanese or any unrelated script. Do not add facts."},
                {"role": "user", "content": answer[:4000]}], max_tokens=400)
        except Exception:
            log.warning("script rewrite failed", exc_info=True)
            return clean_reply(answer)
        cleaned = dedupe_sentences(clean_reply((text or "").strip()))
        return cleaned or clean_reply(answer)

    # ---------- async rolling summary (off the request path) ----------
    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    async def maybe_summarize(self, conversation_id: str, force: bool = False) -> bool:
        try:
            summary, upto = await self.convos.latest_summary(conversation_id)
            new = await self.convos.messages_after(conversation_id, upto)
            keep = self.s.last_n_turns * 2  # turns still sent verbatim are not summarized yet
            if len(new) - keep < (1 if force else self.s.summarize_every_n_messages):
                return False
            fold = new[: len(new) - keep]
            parent = turn_log_var.get()
            folded = "\n".join(f"{m['role']}: {m['content']}" for m in fold)
            ctx = TurnLog(source=parent.source if parent else "live", user_id=parent.user_id if parent else None,
                          session_id=conversation_id, turn_id=f"summary:{conversation_id}", model=self.llm.model,
                          provider=self.llm.provider, compass_version=parent.compass_version if parent else None,
                          tool_index=list(parent.tool_index) if parent and parent.tool_index else [],
                          compass_hint=parent.compass_hint if parent else None,
                          language=parent.language if parent else None,
                          transcript=parent.transcript if parent else None)
            token = turn_log_var.set(ctx)
            handler = CallLogHandler(self.call_log) if self.call_log else None
            config = {"callbacks": [handler], "metadata": {"source": ctx.source,
                                                           "conversation_id": conversation_id}} if handler else None
            try:
                text = await self.llm.complete([
                    {"role": "system", "content": "Update the running summary. First line is 'Current task: ' plus the "
                     "latest user message, not an older one. Then entities, files made, and open blockers. "
                     "Max 120 words. Drop finished tasks. Same language mix as the user."},
                    {"role": "user", "content": f"Previous summary:\n{summary or '(none)'}\n\nNew messages:\n{folded}"}],
                    config=config)
            finally:
                turn_log_var.reset(token)
            await self.convos.save_summary(conversation_id, text.strip(), fold[-1]["id"])
            return True
        except Exception:
            log.exception("summarization failed")
            return False

    async def _drop_thread(self, thread_id: str) -> None:
        """Finished turns do not need a checkpoint. Paused approvals keep theirs until the reply."""
        try:
            saver = self.graph().checkpointer
            if saver is not None and hasattr(saver, "adelete_thread"):
                await saver.adelete_thread(thread_id)
        except Exception:
            log.exception("dropping turn checkpoint failed")

    async def drain(self) -> None:
        if self._bg:
            await asyncio.gather(*self._bg, return_exceptions=True)


def client_events_for_tool(raw: str) -> list[dict]:
    """Phone events implied by a tool result. The model does not choose these; the result flags do."""
    opened = vm_open_event(raw)
    return [opened] if opened else []


def _attachment(raw: str) -> dict | None:
    try:
        data = json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        return None
    att = data.get("attachment") if isinstance(data, dict) else None
    if isinstance(att, dict) and att.get("url") and att.get("name"):
        return att
    return None


def compact_tool_result(raw: str, cap_tokens: int, store: dict) -> str:
    """Keep a short preview in the prompt. The full text stays in memory under a handle."""
    if count_text(raw) <= cap_tokens:
        return raw
    import secrets
    handle = "out_" + secrets.token_hex(4)
    store[handle] = raw
    preview = truncate_to(raw, max(80, cap_tokens // 3))
    return preview + f"\n[stored {handle}; call read_tool_result to read the rest]"


def tool_model_content(name: str, raw: str, compacted: str, files, user_id: str):
    """Tool message for the model. An image artifact is attached for vision; the text stays free of bytes."""
    if name == "artifact_read" and files is not None:
        part = files.vision_part(user_id, raw)
        if part:
            return [{"type": "text", "text": compacted}, part]
    return compacted


def _tool_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") != "image_url")
    return str(content or "")


def _flatten_tools(messages: list[dict]) -> list[dict]:
    """Same conversation with tool calls/results rendered as plain text, for a tool-less final answer."""
    out: list[dict] = []
    for m in messages:
        if m.get("role") == "tool":
            body = m.get("_text") or _tool_text(m.get("content"))
            out.append({"role": "user", "content": f"[tool result]\n{body[:1500]}"})
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            names = ", ".join(c["function"]["name"] for c in m["tool_calls"])
            out.append({"role": "assistant", "content": ((m.get("content") or "") + f" [called: {names}]").strip()})
        else:
            out.append(m)
    return out
