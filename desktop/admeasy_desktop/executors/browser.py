"""Browser: default_first (real browser + screen CUA) → Playwright for structured DOM ops. No Chrome extension."""
from __future__ import annotations

import asyncio
import base64
import os

import logging

from ..config import PROFILE_DIR, Settings
from ..failure_detect import analyze as detect_failure
from ..pacing import wait_if_needed
from .app_launch import open_url_default

log = logging.getLogger(__name__)

STRUCTURED_OPS = frozenset(
    {
        "list_tabs",
        "open_tab",
        "navigate",
        "read_page",
        "extract",
        "query_elements",
        "click_element",
        "type_element",
        "scroll",
        "wait_for",
        "screenshot_tab",
        "close_tab",
    }
)


def _automation_mode(p: dict) -> str:
    """Isolated Playwright only when the task explicitly requests it (or ADMEASY_PLAYWRIGHT=1)."""
    if p.get("force_playwright"):
        return "playwright_profile"
    if p.get("automation") == "playwright_profile" and os.environ.get("ADMEASY_PLAYWRIGHT"):
        return "playwright_profile"
    return "default_first"


async def _screen_snapshot(chars: int = 4000, skill_hints: list | None = None) -> dict:
    from . import screen

    from .. import a11y_tree

    shot = await asyncio.get_event_loop().run_in_executor(None, screen.screenshot)
    ax = a11y_tree.snapshot()
    fail = detect_failure(ax, skill_hints=skill_hints)
    body = {
        "url": "",
        "title": "",
        "text": "",
        "screenshot_b64": shot["screenshot_b64"],
        "size": shot["size"],
        "surface": "default_browser",
        "interaction": "use cua with element_id from elements[]",
        "elements": shot.get("elements") or [],
        "ax_tree": shot.get("ax_tree") or ax,
    }
    if fail:
        body["detected"] = fail
    return body, fail


_FOCUSED_TEXT_JS = """() => { const e = document.activeElement; if (!e) return null;
  if ('value' in e && typeof e.value === 'string') return e.value;
  return e.isContentEditable ? (e.innerText || e.textContent || '') : null; }"""


def typed_check(text: str, field: str | None) -> bool | None:
    """True: the field holds what was typed. False: readable but missing. None: can't read the field."""
    if field is None or not text:
        return None
    norm = lambda v: " ".join(str(v).split())
    probe = norm(text)[:60]
    return probe in norm(field)


async def page_typed_ok(page, text: str) -> bool | None:
    try:
        return typed_check(text, await page.evaluate(_FOCUSED_TEXT_JS))
    except Exception:
        return None


class Browser:
    def __init__(self):
        self.pw = None
        self.ctx = None
        self._tab_sem = asyncio.Semaphore(3)

    async def start_playwright(self):
        if self.ctx:
            return
        from playwright.async_api import async_playwright

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self.pw = await async_playwright().start()
        s = Settings.load()
        if s.playwright_real_profile:
            from ..default_browser import default_browser
            from ..real_profile import hint_for, resolve

            db = default_browser()
            name = str(db.get("name") or "").lower()
            hint = hint_for(name)
            rp = resolve(hint, s)
            if rp:
                try:
                    self.ctx = await self.pw.chromium.launch_persistent_context(
                        rp["user_data_dir"], executable_path=rp["executable"], headless=False, no_viewport=True,
                        args=["--no-first-run", "--hide-crash-restore-bubble"],
                        ignore_default_args=["--enable-automation"])
                    log.info("playwright real profile browser=%s source=%s", hint or "custom", rp["source"])
                    self.ctx.on("close", lambda *_: setattr(self, "ctx", None))
                    return
                except Exception as e:  # usually: the browser is open and holds the profile lock
                    log.warning("playwright real profile unavailable (%s: %s); using the isolated profile",
                                type(e).__name__, str(e)[:160])
            else:
                log.info("playwright real profile: no Chromium profile for default browser %r; isolated", name)
        try:
            self.ctx = await self.pw.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                no_viewport=True,
                args=["--no-first-run", "--hide-crash-restore-bubble"],
                ignore_default_args=["--enable-automation"],
            )
        except Exception:
            self.ctx = await self.pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, no_viewport=True, args=["--no-first-run"]
            )
        self.ctx.on("close", lambda *_: setattr(self, "ctx", None))

    async def page(self):
        await self.start_playwright()
        pages = [p for p in self.ctx.pages if not p.is_closed()]
        return pages[0] if pages else await self.ctx.new_page()

    async def snapshot(self, page, chars=4000, skill_hints=None):
        shot = await page.screenshot(type="jpeg", quality=55)
        txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
        from .. import a11y_tree

        ax = a11y_tree.snapshot()
        fail = detect_failure(ax, skill_hints=skill_hints)
        body = {
            "url": page.url,
            "title": await page.title(),
            "text": (txt or "")[:chars],
            "screenshot_b64": base64.b64encode(shot).decode(),
            "surface": "playwright_profile",
            "ax_tree": ax,
        }
        if fail:
            body["detected"] = fail
        return body, fail

    async def run_structured(self, p: dict) -> dict:
        """Structured DOM ops run in the Playwright profile (the Chrome extension bridge was removed)."""
        domain = str(p.get("domain") or "")
        wait_if_needed(domain, p.get("rate_limit_hints"))
        async with self._tab_sem:
            return await self.run_playwright(p)

    async def run_default_first(self, p: dict) -> dict:
        op = p.get("op") or "read"
        url = p.get("url") or ""
        hints = p.get("skill_hints") or []

        if op in STRUCTURED_OPS:
            return await self.run_structured(p)

        if op in ("open", "navigate") and url:
            opened = open_url_default(url if url.startswith("http") else f"https://{url}",
                                      reuse_tab=not p.get("new_tab"))
            await asyncio.sleep(0.8 if opened.get("reused") else float(p.get("settle_s") or 2.0))
            snap, fail = await _screen_snapshot(skill_hints=hints)
            snap["url"] = url
            snap["reused_tab"] = bool(opened.get("reused"))
            if fail and fail.get("status") == "captcha":
                return {"status": "captcha", "error": fail.get("reason"), "result": snap}
            if fail:
                return {"status": fail.get("status", "needs_human"), "error": fail.get("reason"), "result": snap}
            return {"status": "ok", "result": snap}

        if op == "read":
            if url:
                open_url_default(url if url.startswith("http") else f"https://{url}")
                await asyncio.sleep(float(p.get("settle_s") or 2.0))
            snap, fail = await _screen_snapshot(8000, hints)
            if url:
                snap["url"] = url
            if fail and fail.get("status") == "captcha":
                return {"status": "captcha", "error": fail.get("reason"), "result": snap}
            if fail:
                return {"status": fail.get("status", "needs_login"), "error": fail.get("reason"), "result": snap}
            return {"status": "ok", "result": snap}

        if op in ("click", "type", "press", "fill", "hover", "scroll", "select", "search"):
            snap, fail = await _screen_snapshot(skill_hints=hints)
            if fail and fail.get("status") == "captcha":
                return {"status": "captcha", "error": fail.get("reason"), "result": snap}
            return {
                "status": "needs_human",
                "error": "use_cua",
                "result": snap,
            }

        snap, _ = await _screen_snapshot(skill_hints=hints)
        return {"status": "ok", "result": snap}

    async def run_playwright(self, p: dict) -> dict:
        hints = p.get("skill_hints") or []
        try:
            page = await self.page()
            op = p.get("op") or "read"
            typed = None
            if op in STRUCTURED_OPS:
                return await self.run_structured(p)
            if op in ("open", "navigate") and p.get("url"):
                await page.goto(p["url"], wait_until="domcontentloaded", timeout=45000)
            elif op == "navigate" and p.get("direction") == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=15000)
            elif op == "navigate" and p.get("direction") == "forward":
                await page.go_forward(wait_until="domcontentloaded", timeout=15000)
            elif op == "click":
                if p.get("selector"):
                    await page.locator(p["selector"]).first.click(timeout=8000)
                elif p.get("text"):
                    await page.get_by_text(p["text"], exact=False).first.click(timeout=8000)
                else:
                    await page.mouse.click(float(p["x"]), float(p["y"]))
            elif op == "type":
                if p.get("selector"):
                    await page.locator(p["selector"]).first.click(timeout=8000)
                text = str(p.get("text") or "")
                await page.keyboard.insert_text(text)
                typed = await page_typed_ok(page, text)
            elif op == "press":
                await page.keyboard.press(str(p.get("key") or "Enter"))
            elif op == "scroll":
                await page.mouse.wheel(0, float(p.get("dy") or 600))
            elif op == "search":
                q = str(p.get("query") or "")
                try:
                    await page.get_by_text(q, exact=False).first.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
            elif op == "fill":
                loc = page.locator(p["selector"]).first if p.get("selector") else page.locator("input,textarea").first
                text = str(p.get("text") or "")
                await loc.fill(text, timeout=8000)
                try:
                    typed = typed_check(text, await loc.input_value(timeout=2000))
                except Exception:
                    typed = await page_typed_ok(page, text)
            elif op == "hover":
                if p.get("selector"):
                    await page.locator(p["selector"]).first.hover(timeout=8000)
                else:
                    await page.mouse.move(float(p.get("x", 0)), float(p.get("y", 0)))
            elif op == "select":
                await page.locator(p["selector"]).first.select_option(str(p.get("value") or ""), timeout=8000)
            elif op == "wait_for":
                sel = str(p.get("selector") or "")
                state = str(p.get("state") or "visible")
                await page.locator(sel).first.wait_for(state=state, timeout=int(p.get("timeout_ms") or 15000))
            elif op == "tabs":
                sub = p.get("subop") or "list"
                if sub == "list":
                    tabs = [{"index": i, "url": pg.url, "title": await pg.title()} for i, pg in enumerate(self.ctx.pages)]
                    return {"status": "ok", "result": {"tabs": tabs}}
                if sub == "new":
                    await self.ctx.new_page()
                elif sub == "close" and self.ctx.pages:
                    await self.ctx.pages[-1].close()
                elif sub == "switch":
                    idx = int(p.get("index") or 0)
                    if idx < len(self.ctx.pages):
                        await self.ctx.pages[idx].bring_to_front()
            elif op == "pdf":
                data = await page.pdf() if hasattr(page, "pdf") else b""
                import base64 as b64

                return {"status": "ok", "result": {"pdf_b64": b64.b64encode(data).decode() if data else ""}}
            elif op == "download":
                with page.expect_download(timeout=int(p.get("timeout_ms") or 60000)) as dl_info:
                    if p.get("selector"):
                        await page.locator(p["selector"]).first.click()
                dl = await dl_info.value
                path = await dl.path()
                return {"status": "ok", "result": {"path": path, "suggested_filename": dl.suggested_filename}}
            if typed is False:
                return {"status": "error", "error": "typed text did not appear in the field",
                        "result": {"typed_ok": False}}
            await page.wait_for_timeout(400)
            snap, fail = await self.snapshot(page, 8000 if op == "read" else 4000, hints)
            if typed is not None and isinstance(snap, dict):
                snap["typed_ok"] = typed
            if fail and fail.get("status") == "captcha":
                return {"status": "captcha", "error": fail.get("reason"), "result": snap}
            if fail:
                return {"status": fail.get("status", "needs_login"), "error": fail.get("reason"), "result": snap}
            return {"status": "ok", "result": snap}
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    async def run(self, p: dict) -> dict:
        pool = int(p.get("tab_pool_size") or 0)
        if pool > 0:
            self._tab_sem = asyncio.Semaphore(max(1, min(pool, 12)))
        mode = _automation_mode(p)
        if mode == "default_first":
            return await self.run_default_first(p)
        return await self.run_playwright(p)

    async def close(self):
        if self.ctx:
            await self.ctx.close()
        if self.pw:
            await self.pw.stop()
