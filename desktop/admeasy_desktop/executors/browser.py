"""Playwright on the user's REAL Chrome, with a dedicated persistent Admeasy profile (~/.admeasy/chrome-profile).

Why a dedicated profile: since Chrome 136, remote debugging is ignored on the default profile directory, so Playwright
cannot attach to the everyday profile. Instead the user signs in to their sites once in this window (on their own machine,
own IP, own device fingerprint) and the sessions stay on disk. That fixes the cloud-VM problem of sessions that are
missing or flagged. For the everyday Chrome window use pixel control (executors/screen.py)."""
from __future__ import annotations

import base64

from ..config import PROFILE_DIR

CAPTCHA = ["iframe[src*='challenges.cloudflare.com']", "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']",
           "text=Verify you are human", "#challenge-form"]
LOGIN_URL_PARTS = ("/login", "/signin", "/sign-in", "accounts.google.com", "/oauth")


class Browser:
    def __init__(self):
        self.pw = None
        self.ctx = None

    async def start(self):
        if self.ctx:
            return
        from playwright.async_api import async_playwright
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self.pw = await async_playwright().start()
        try:
            self.ctx = await self.pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), channel="chrome", headless=False, no_viewport=True,
                args=["--no-first-run", "--hide-crash-restore-bubble"], ignore_default_args=["--enable-automation"])
        except Exception:  # Chrome not installed: fall back to Playwright's Chromium (run `playwright install chromium`)
            self.ctx = await self.pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=False, no_viewport=True, args=["--no-first-run"])
        self.ctx.on("close", lambda *_: setattr(self, "ctx", None))

    async def page(self):
        await self.start()
        pages = [p for p in self.ctx.pages if not p.is_closed()]
        return pages[0] if pages else await self.ctx.new_page()

    async def snapshot(self, page, chars=4000):
        shot = await page.screenshot(type="jpeg", quality=55)
        txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
        return {"url": page.url, "title": await page.title(), "text": (txt or "")[:chars],
                "screenshot_b64": base64.b64encode(shot).decode()}

    async def status(self, page) -> str:
        for sel in CAPTCHA:
            try:
                if await page.locator(sel).first.is_visible(timeout=300):
                    return "needs_human"
            except Exception:
                pass
        if any(k in (page.url or "") for k in LOGIN_URL_PARTS):
            return "needs_login"
        try:
            if await page.locator("input[type='password']").first.is_visible(timeout=250):
                return "needs_login"
        except Exception:
            pass
        return "done"

    async def run(self, p: dict) -> dict:
        try:
            page = await self.page()
            op = p.get("op") or "read"
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
                await page.keyboard.insert_text(str(p.get("text") or ""))
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
                await loc.fill(str(p.get("text") or ""), timeout=8000)
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
                    return {"status": "done", "result": {"tabs": tabs}}
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

                return {"status": "done", "result": {"pdf_b64": b64.b64encode(data).decode() if data else ""}}
            elif op == "download":
                with page.expect_download(timeout=int(p.get("timeout_ms") or 60000)) as dl_info:
                    if p.get("selector"):
                        await page.locator(p["selector"]).first.click()
                dl = await dl_info.value
                path = await dl.path()
                return {"status": "done", "result": {"path": path, "suggested_filename": dl.suggested_filename}}
            await page.wait_for_timeout(400)
            st = await self.status(page)
            return {"status": st, "result": await self.snapshot(page, 8000 if op == "read" else 4000)}
        except Exception as e:
            return {"status": "failed", "error": f"{type(e).__name__}: {e}"}

    async def close(self):
        if self.ctx:
            await self.ctx.close()
        if self.pw:
            await self.pw.stop()
