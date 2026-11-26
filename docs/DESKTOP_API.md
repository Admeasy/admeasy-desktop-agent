# Desktop API (tunnel + tools)

Default backend: `https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com`

Contract version in `hello.capabilities.contract_version`: **`0.5.1`**

## Handshake (`hello`)

Desktop → server on WSS connect:

```json
{
  "type": "hello",
  "version": "0.5.0-beta.11",
  "contract_version": "0.5.1",
  "capabilities": {
    "job_kinds": ["..."],
    "tools": ["..."],
    "tool_schemas": ["terminal", "files", "screen", "browser", "notify", "clipboard"],
    "legacy_handlers": false,
    "tool_schemas": [ { "name": "terminal", "kind": "terminal", "parameters": { ... } }, ... ]
  }
}
```

Set `ADMEASY_LEGACY_HANDLERS=1` to re-enable per-app handlers (`whatsapp`, `mail`, `cli`, `app`, `ide`, …).

## Task → outcome (every job)

Server → desktop:

```json
{ "type": "task", "job_id": "uuid", "kind": "terminal", "params": { "op": "run", "command": "pwd" } }
```

Desktop → server (terminal, always includes outcome fields):

```json
{
  "type": "result",
  "job_id": "uuid",
  "ok": true,
  "status": "done",
  "code": "ok",
  "detail": "",
  "result": { "exit_code": 0, "output": "/Users/you\n" }
}
```

### `status` enum

| status | ok | Meaning |
|--------|-----|---------|
| `done` | true | Tool finished successfully |
| `failed` | false | Error, timeout, cancel, deny |
| `needs_auth` | false | Login/captcha (`code`: `needs_login`, `captcha`, …) |
| `needs_approval` | false | Parked until user approves (see below) |
| `rate_limited` | false | Plan usage cap |
| `blocked` | false | Policy/hard block/onboarding |

Optional: `connect_url`, `artifacts`, `approval_id`, `pending_action`.

Exceptions in the agent map to `failed` with `detail` = exception text (no canned replacement).

## Approvals (resumable)

1. Desktop sends `approval_request` (unchanged).
2. Desktop sends **`needs_approval`** (non-terminal progress):

```json
{
  "type": "needs_approval",
  "job_id": "uuid",
  "approval_id": "uuid",
  "ok": false,
  "status": "needs_approval",
  "code": "needs_approval",
  "detail": "run: rm …",
  "pending_action": { "action": "shell", "summary": "...", "risk": "high" }
}
```

3. Server/user replies on tunnel:

```json
{ "type": "approval_result", "approval_id": "uuid", "allow": true }
```

4. Job continues; final `type: result` uses the outcome contract.

There is **no** approval wall-clock auto-deny on the desktop.

## Heartbeats

During long tool calls (~15s interval):

```json
{ "type": "heartbeat", "job_id": "uuid", "elapsed_s": 45.2 }
```

Backend should extend server-side wait while heartbeats arrive (mirror LangGraph long runs).

## Tool manifest (general tools)

| Tool | `kind` | Notes |
|------|--------|--------|
| `terminal` | `terminal` | Persistent PTY per `session_id`; default `timeout_s` 600 |
| `files` | `files` | User-shared folders only |
| `screen` | `screen` | `screenshot` / `act` (CUA); also `screenshot` + `cua` kinds |
| `browser` | `browser` | CDP attach when `--remote-debugging-port` present; else Playwright profile; browser call up to 1800s |
| `notify` | `notify` | Native toast |
| `clipboard` | `clipboard` | get/set |

JSON Schema definitions: `hello.capabilities.tool_schemas` (see `admeasy_desktop/tool_schemas.py`).

## Browser CDP

- Detect: `127.0.0.1:9222` (or `ADMEASY_CDP_PORT`).
- Login wall: `status: needs_auth`, `result.connect_url` or `cdp_hint` for relaunch with `--remote-debugging-port=9222`.
- Never export cookies/passwords.

## Backend agent checklist

1. Bind tools from `tool_schemas`; send `kind` + `params` on `task`.
2. Handle `heartbeat` to avoid tunnel timeouts.
3. On `needs_approval`, surface UI and later send `approval_result` (same as LangGraph `interrupt` + `Command(resume=...)`).
4. Parse `ok` + `status` + `code` + `detail` on every `result`.
5. Use `contract_version` `0.5.1` feature detection (outcome fields required).

## Auth, chat, devices

See prior sections in this repo (`/devices/tunnel`, pair/redeem, chat WSS) — unchanged for beta.11 except outcome shape on device results.