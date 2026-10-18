# Backend contract (desktop client)

Canonical server implementation: **admeasy-ai-assistant** `main` (device tools in `app/devices/tools.py`). The desktop app targets that API. If `GET /devices` returns **404**, the host has not been redeployed yet; **503** means `DEVICES_ENABLED=false`.

**Contract version `0.4.0`** — desktop package **0.4.0-beta.1** advertises **17 job kinds**. Mirror copy: **admeasy-ai-assistant** `docs/DESKTOP_BACKEND_CONTRACT.md`.

The LLM picks `device_*` tools (no intent routing). See [COMPUTER_USE.md](COMPUTER_USE.md) and [WORKFLOW_DIAGNOSIS.md](WORKFLOW_DIAGNOSIS.md).

**v0.4 highlights:** typed result `status`, `status`/`signin` job kinds, SOM + AX (macOS + Windows UIA), session probe (boolean only), idempotency + reconnect buffer, artifact append/upload, `skill_hints` on jobs for failure detection (no hardcoded site lists in desktop code).

**Browser policy (v0.4.0-beta.3+):** Desktop enforces **`default_first`** unless `task.params.force_playwright=true` or env `ADMEASY_PLAYWRIGHT=1`. Backend must not rely on isolated `~/.admeasy/chrome-profile` for user sessions. `hello.capabilities.playwright_requires` documents this.

## Enablement

- `DEVICES_ENABLED=true` on the backend (Postgres + migration `user_devices` / `device_jobs`).
- Device REST returns **503** when disabled; the desktop treats that as a hard configuration error.

## Sign-in

1. Bind loopback port `P` ∈ **1024–65535** and random `nonce` (≤ **64** chars).
2. `GET {PUBLIC_BASE_URL}/auth/google/start?desktop_port=P&nonce={nonce}`
3. Redirect: `http://127.0.0.1:P/callback?access_token=…&refresh_token=…&email=…&nonce=…`
4. `POST /auth/refresh` body `{"refresh_token": "…"}`

## Register device

`POST /devices/register` with user `Authorization: Bearer <access JWT>`:

```json
{"name": "…", "platform": "macos|windows|linux", "os_version": "…", "capabilities": {}}
```

Response: `{"device_id": "uuid", "device_token": "secret-once"}`

## User REST (Bearer access JWT)

| Method | Path | Notes |
|--------|------|--------|
| GET | `/devices` | `{"devices": [...]}` |
| PATCH | `/devices/{id}` | `{"name": "…"}` |
| DELETE | `/devices/{id}` | Revoke |
| POST | `/devices/{id}/cancel` | Kill switch |
| GET | `/devices/approvals` | `{"pending": [{id, device_id, action, summary, risk}]}` |
| POST | `/devices/approvals/{id}` | `{"allow": true\|false}` |

## WebSocket tunnel

- URL: `wss://{host}/devices/tunnel`
- Headers: `Authorization: Bearer <device_token>`, `X-Device-Id: <device_id>`
- Auth failure: close **4401** before accept

### Desktop → server

| type | fields |
|------|--------|
| `hello` | `version`, `os_version`, `capabilities`, `permissions` |
| `permissions` | `permissions` |
| `approval_request` | `approval_id`, `job_id`, `action`, `summary`, `risk` |
| `step` | `job_id`, `text` (≤300 chars), optional `objective_id` |
| `result` | `job_id`, `status`, `result?`, `error?` — `result.reason`, `result.evidence.screenshot_ref` |

### Server → desktop

| type | fields |
|------|--------|
| `task` | `job_id`, `kind`, `params`, optional `timeout_s`, optional `objective_id` (also inside `params`) |
| `approval_result` | `approval_id`, `allow` |
| `cancel_all` | — |

### Result `status` (v0.4)

`ok`, `needs_login`, `needs_human`, `offline`, `blocked`, `rate_limited`, `permission_missing`, `timeout`, `captcha`, `error`, `cancelled`

Legacy `done`/`failed`/`denied` are normalized to `ok`/`error`/`blocked` on the wire. Every non-`ok` result should include `error` and `result.reason`; screenshot-bearing results include `result.evidence.screenshot_ref` = `job_id`.

### Task params (all kinds)

| field | purpose |
|-------|---------|
| `objective_id` | echoed in `result`; drives `step.objective_id` and keep-awake while jobs run |
| `idempotency_key` | duplicate task after backend restart returns cached result (no double-act) |
| `skill_hints` | strings from backend skills — used for captcha/login heuristics only |
| `rate_limit_hints` | `{requests_per_minute, jitter_ms, daily_cap}` — desktop pacing |

### Permissions (`hello.permissions`)

| key | macOS | Windows / Linux |
|-----|--------|-----------------|
| `screen` | Screen Recording | always `true` |
| `accessibility` | Accessibility | always `true` |
| `full_disk` | Full Disk Access (Messages, call history, notifications DB) | always `true` |

Kinds `screenshot` / `cua` require `screen` + `accessibility`. Kinds `messages` and `comms` (notifications/calls) require `full_disk` on macOS.

### Policy (desktop gate)

Independent of the cloud model: hard-block destructive shell patterns; **phone approval** for sends, calls, payments-ish text, installs, and risky shell unless `approval_mode=trusted`. Modes: `autopilot` (default: open/click/type/navigate never ask; destructive shell/file steps, installs and final sends/calls ask), `ask_risky`, `ask_always`, `trusted`.

---

## Job kinds & params

### `screenshot`

`{}` → `{screenshot_b64, size}`

### `status`

Surface facts for `surfaces_status` (no recommendations):

```json
{"domains": ["example.com"]}
```

Returns `online`, `os`, `agent_version`, `permissions`, `permissions_missing`, `default_browser`, `sessions` (per domain: `session_present`, `browser`, `last_seen_at` — **no cookie values**), `active_app`, `idle_seconds`, `extension_installed` (always false; extension removed), `speed_tier`, `timestamp`.

### `signin`

Handoff when backend `interrupt` + `needs_login`:

`{domain, url?, label?, timeout_s?, poll_s?}` → polls session probe → `{session_verified, probe}`.

### `cua`

`{action, skill_hints?}` — prefer `element_id` / `click_mark` / `ax_press` / `ax_type`; fallback `x`,`y`. Returns SOM `elements[]`, `frame_id`, `stable_id`, `ax_tree`. Stops with `captcha` / `needs_human` when detected (never bypass captcha).

### `open`

`{target}` — URL, file path, or app name

### `shell`

`{command, cwd?, timeout_s?}` → `{exit_code, output}`

### `terminal`

PTY sessions and one-shot runs with streamed `step` output.

| op | params |
|----|--------|
| `run` | `command`, `cwd?`, `timeout_s?` |
| `spawn` | `cwd?`, `session_id?` |
| `write` | `session_id`, `data` |
| `read` | `session_id` |
| `close` | `session_id` |
| `list` | — |

### `cli`

Managed CLIs: **claude**, **gemini**, **cursor** (`cursor-agent`), **git**.

| op | params |
|----|--------|
| `profiles` | — |
| `run` | `profile`, `prompt` or `command`, `cwd?`, `timeout_s?` |
| `spawn` / `write` / `read` / `close` / `list` | same as `terminal` + `profile`, `init?` |

### Objectives (backend orchestration)

The **desktop does not run the objective loop**; it executes tasks and echoes `objective_id` in `result`. The **assistant backend** should:

1. Create an objective record (e.g. Supabase `device_objectives`: id, user_id, description, success_criteria, status).
2. Plan steps; send each `task` with `params.objective_id`.
3. After each result, evaluate whether the **objective** is achieved (not only whether the last task succeeded).
4. If not achieved, continue with more tasks or return `objective_status: incomplete` with a clear reason.

Desktop capabilities include `objectives.echo_objective_id: true`.

### `browser`

**Order:** **`default_first`** (real browser + screen/SOM CUA) → Playwright profile for structured DOM ops. The Chrome extension bridge was removed (Oct 2026).

Structured ops (`read_page`, `extract`, `query_elements`, `click_element`, `type_element`, …) run in the Playwright profile.


`default_first`: `read`/`open`/`navigate` open the **default browser** and return screen capture + SOM. Ops Playwright cannot serve return `use_cua` so the backend drives the screen.

| op | params |
|----|--------|
| `read`, `navigate`, `open` | `url`, `settle_s?`, `domain?`, `rate_limit_hints?`, `tab_pool_size?` |
| `click` | `selector` or `text` or `x`,`y` (playwright profile only) |
| `type`, `fill` | `text`, `selector?` |
| `press` | `key` |
| `scroll` | `dy` |
| `hover` | `selector` or `x`,`y` |
| `select` | `selector`, `value` |
| `wait_for` | `selector`, `state?`, `timeout_ms?` |
| `search` | `query` |
| `tabs` | `subop`: `list`, `new`, `close`, `switch` + `index?` |
| `pdf` | — |
| `download` | `selector?`, `timeout_ms?` |

### `files`

Paths must stay under `capabilities.files` (shared folders).

| op | params |
|----|--------|
| `list`, `read`, `write`, `mkdir`, `delete`, `stat`, `copy`, `move`, `search` | `path`, … |
| `append_rows` | `path`, `rows[]`, `format`: `csv` \| `xlsx` |
| `upload_artifact` | `path`, `upload_url` (presigned PUT from backend) |

### `clipboard`

| op | params |
|----|--------|
| `get`, `set`, `clear`, `append` | `text` for set/append |

### `app`

| op | params |
|----|--------|
| `open` | `name` |
| `install` / `uninstall` | `name` (brew / winget / choco) |
| `list`, `which` | `name?` |

### `ide`

| op | params |
|----|--------|
| `open` | `ide`: `cursor` \| `vscode`, `path`, `line?`, `column?` |
| `command` | `command` |
| `diff` | `left`, `right` |
| `extensions` | `subop`: `list` \| `install`, `id?` |

### `whatsapp`

**Default:** opens **WhatsApp desktop** and returns a screen screenshot. Web only when `fallback_web: true`.

| op | params |
|----|--------|
| `open`, `read`, `status` | `settle_s?`, `fallback_web?` |
| `open_desktop` | — |

### `messages` (macOS)

| op | params |
|----|--------|
| `recent` | `handle?`, `limit?` |
| `send` | `to`, `text` — **requires approval** |

### `comms`

| op | params |
|----|--------|
| `notifications` | `limit?` |
| `calls` | `limit?` |
| `continuity_call` | `number` — **requires approval** |

### `mail`

| op | params |
|----|--------|
| `unread`, `search`, `compose`, `open` | `query?`, `to?`, `subject?`, `body?` — compose **requires approval** |

---

## Capabilities (`hello.capabilities`)

Includes `contract_version`, `job_kinds` (17), `tools`, `browser`, `browser_modes`, `set_of_mark`, `ax_tree`, `native_apps`, `agent_cursor_overlay`, `objectives`, `cli_profiles`, `ide`, `terminal`, `files`, `approval_mode`, `keep_awake`.

## Reconnect

On tunnel drop, undelivered `result` messages are buffered under `~/.admeasy/job_store.json` and replayed on the next `hello`. Backend should reuse `idempotency_key` when resubmitting after restart.
