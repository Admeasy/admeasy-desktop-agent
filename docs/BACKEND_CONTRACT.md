# Backend contract (desktop client)

Canonical server implementation: **admeasy-ai-assistant** `main` (device tools in `app/devices/tools.py`). The desktop app targets that API. If `GET /devices` returns **404**, the host has not been redeployed yet; **503** means `DEVICES_ENABLED=false`.

Desktop package version **0.3.0-beta** advertises **15 job kinds** (see below). Each backend `device_*` tool maps to one kind + `params.op` (and tool-specific fields).

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
| `step` | `job_id`, `text` (streamed progress, ≤300 chars) |
| `result` | `job_id`, `status`, `result?`, `error?` |

### Server → desktop

| type | fields |
|------|--------|
| `task` | `job_id`, `kind`, `params`, optional `timeout_s` |
| `approval_result` | `approval_id`, `allow` |
| `cancel_all` | — |

### Result `status`

`done`, `failed`, `denied`, `needs_login`, `needs_human`, `needs_permission`, `cancelled`

### Permissions (`hello.permissions`)

| key | macOS | Windows / Linux |
|-----|--------|-----------------|
| `screen` | Screen Recording | always `true` |
| `accessibility` | Accessibility | always `true` |
| `full_disk` | Full Disk Access (Messages, call history, notifications DB) | always `true` |

Kinds `screenshot` / `cua` require `screen` + `accessibility`. Kinds `messages` and `comms` (notifications/calls) require `full_disk` on macOS.

### Policy (desktop gate)

Independent of the cloud model: hard-block destructive shell patterns; **phone approval** for sends, calls, payments-ish text, installs, and risky shell unless `approval_mode=trusted`. Modes: `ask_risky` (default), `ask_always`, `trusted`.

---

## Job kinds & params

### `screenshot`

`{}` → `{screenshot_b64, size}`

### `cua`

`{action}` — pixel control: `screenshot`, `click`, `type`, `key`, `scroll`, `wait`, `move`, `done`, `needs_login`

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

### `browser`

Playwright on dedicated Chrome profile (`~/.admeasy/chrome-profile`).

| op | params |
|----|--------|
| `read`, `navigate`, `open` | `url` |
| `click` | `selector` or `text` or `x`,`y` |
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

| op | params |
|----|--------|
| `open_desktop` | — |
| `read`, `navigate`, `click`, `type`, … | same as `browser` (default `https://web.whatsapp.com/`) |

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

Includes `job_kinds` (sorted list), `tools` (group manifest), `cli_profiles`, `ide`, `browser`, `terminal`, `files` (shared folder paths), `approval_mode`, `keep_awake`.
