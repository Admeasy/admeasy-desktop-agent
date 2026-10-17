# Backend contract (desktop client)

Canonical server implementation: merged to **admeasy-ai-assistant** `main` ([PR #42](https://github.com/Admeasy/admeasy-ai-assistant/pull/42)). The desktop app targets that API. If `GET /devices` returns **404**, the Lightsail (or other) host has not been redeployed yet; **503** means `DEVICES_ENABLED=false`.

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
| `step` | `job_id`, `text` |
| `result` | `job_id`, `status`, `result?`, `error?` |

### Server → desktop

| type | fields |
|------|--------|
| `task` | `job_id`, `kind`, `params` |
| `approval_result` | `approval_id`, `allow` |
| `cancel_all` | — |

### Job kinds

`screenshot`, `open`, `browser`, `shell`, `files`, `clipboard`, `cua` (`params.action` for computer-use steps, including `done` and `needs_login`).
