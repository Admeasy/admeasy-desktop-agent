# Prompt for backend agent (admeasy-ai-assistant)

Copy everything below the line into your backend coding agent.

---

You are fixing **Computer Use (CUA)** and **voice/chat tool orchestration** for Admeasy. The desktop agent (`admeasy-desktop-agent` v0.4.0-beta.5+) is working per-job: each `cua` job runs one action, returns `status: "ok"` and a fresh `screenshot_b64` + `elements[]`. Users still see **only one screenshot**, **no clicks**, and the message *"I did several steps but couldn't finish this in one go"*.

## Symptoms (production)

1. Backend opens URLs/apps via `open` / `browser` tools, but **CUA loop stops after the first desktop screenshot** or never submits click/type jobs.
2. Phone UI shows **"Looking into that" / "Working..."** while the Mac is idle.
3. User device reports **Agent 0.4.0-beta.3** — browser work uses screen CUA (the Chrome extension was removed).
4. Retrying with a follow-up prompt **reloads the same URL** instead of continuing from the last screenshot/history.

## Root causes to verify and fix

### A. CUA job success status (critical)

Desktop returns **`status: "ok"`** (not `"done"`) for successful CUA steps with a screenshot in `result`.

In `backend/app/devices/cua.py` (or equivalent):

- Replace any `if status != "done":` with `if not job_succeeded(status):` where `job_succeeded` accepts **`ok` and `done`**.
- In `DeviceService` activity log / normalization, treat **`ok` like success** for device jobs.

Add/keep test: `test_job_succeeded_accepts_desktop_ok_status`.

**Deploy**: rebuild Docker image from `main`, deploy to Lightsail (`admeasy-backend`), remove any startup `sed` hotfix on the container once the image includes the fix. Confirm with a manual CUA run: **≥3** `cua` jobs in logs for one user goal.

### B. CUA loop must run until `done` or step budget

In `ComputerUse.run()`:

- Loop: `submit(cua, action)` → `wait` → read `screenshot_b64` → `plan` next action.
- Do **not** exit the loop on first screenshot unless the model returns `done`.
- Default `max_steps` ≥ **15**; for long objectives allow **25–40** when the user asks for multi-step workflows (Instagram search, WhatsApp DM, Claude prompt).
- If `wait` returns `permission_missing`, surface that to the user (Accessibility on Mac).

### C. Voice/chat agent must not pretend work finished

In `backend/app/agent.py` (or LangGraph turn):

- The fallback string *"I did several steps but couldn't finish..."* is emitted when **`final` summary is empty** after tool rounds — often because tools returned errors or the model never got tool results.
- Increase tool rounds for `device__cua` / `computer_use` objectives.
- Pass **last screenshot URL or step count** into the final summary user message.
- If `device__cua` returns `failed` / `permission_missing` / missing screenshot, the model must say that explicitly — **never** claim success.
- Support **continue** intents: when the user says "continue", pass `history` / last `steps` from the previous CUA run into the next `ComputerUse.run()` call (persist in session or conversation metadata).

### D. Tool routing

- Prefer **`device__cua`** (or your device computer tool) for **native apps** (WhatsApp, Instagram desktop, Claude in Arc/Chrome).
- Do not only call `browser` `navigate` to `instagram.com` and stop — chain into CUA with goal text that references **element_id** from `elements[]` when SOM marks are present.
- For WhatsApp desktop: goal should include "use search field" and **type** actions, not only `open`.

### E. Model / Bedrock computer tool

- `display_width_px` / `display_height_px` must match desktop `result.size` from the **last** screenshot.
- Include `elements` (set-of-mark) in the planner prompt; prefer `element_id` clicks over raw coordinates when marks exist.
- If the model returns only `screenshot` repeatedly, add planner prompt: *after navigate/open, you must click or type within 2 steps*.

### F. Observability

- Log each CUA iteration: `job_id`, `action.type`, `status`, `has_screenshot`, `len(elements)`.
- Alert if a `ComputerUse.run` completes with `steps` length 1 and goal not `done`.

## Acceptance tests

1. Goal: "Open Instagram and click Search" — backend logs **≥4** CUA jobs; last result has different screenshot hash than first.
2. Goal: "Open WhatsApp, search Nitish, send hello" — at least one `type` action in steps.
3. Desktop without Accessibility → `permission_missing` returned to phone, not silent idle.
4. Production `GET /health` unchanged; deploy revision documented.

## Files likely touched

- `backend/app/devices/cua.py`
- `backend/app/devices/service.py`
- `backend/app/devices/tools.py`
- `backend/app/agent.py` (turn graph, final node, device tool wiring)
- `backend/tests/test_cua_job_status.py`, `backend/tests/test_devices.py`

## Do not

- Treat desktop `status: "ok"` as failure.
