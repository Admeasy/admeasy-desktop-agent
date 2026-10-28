# Desktop API (Lightsail contract)

Canonical spec lives in **admeasy-ai-assistant** (`docs/DESKTOP_API.md` at commit `caeef71`). This copy is derived from the live OpenAPI at `ADMEASY_BACKEND/openapi.json` so the desktop repo stays testable without cloning the private assistant repo.

Default backend: `https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com`

## Auth

| Flow | Endpoint | Notes |
|------|----------|--------|
| Google (desktop) | `GET /auth/google/start?desktop_port=&nonce=&invite=` | Redirects to loopback with JWTs |
| Refresh | `POST /auth/refresh` | `{refresh_token}` |
| Profile | `GET /auth/me` | Bearer JWT |

Production rejects bare `user_id` query params; send **Bearer** JWT (or `token` query only where documented for legacy web).

## Chat

| Action | Endpoint |
|--------|----------|
| List threads | `GET /conversations?limit=` |
| History | `GET /conversations/{id}/messages?limit=` |
| Send + stream | `WSS /ws/session?token=<JWT>&client=desktop&conversation_id=` (optional) |

WebSocket client messages: `{"type":"text","text":"..."}`.

Server events handled by the desktop UI: `session`, `token`, `done`, `revision`, `tool_call`, `error`, `approval_required`, `attachment`.

## Devices (phone → your computer)

| Action | Endpoint |
|--------|----------|
| Register (signed-in) | `POST /devices/register` |
| Pair code (JWT) | `POST /devices/pair-codes` |
| Redeem (installer) | `POST /devices/pair/redeem` `{code,name,platform,os_version}` |
| Tunnel | `WSS /devices/tunnel` headers `Authorization: Bearer <device_token>`, `X-Device-Id` |
| Tunnel push | `{type:"reminder", text:...}` → native toast |

## Reminders & push

| Action | Endpoint |
|--------|----------|
| Create | `POST /reminders` `{text, at, client:"desktop"}` |
| List | `GET /reminders?limit=` |
| Cancel | `DELETE /reminders/{id}` |
| VAPID | `GET /push/vapid-public-key` |
| Register subscription | `POST /push/web` `{endpoint, keys, client:"desktop"}` |

## Parity screens (3-dot menu)

| Screen | Backend |
|--------|---------|
| Plan | `GET /entitlements/me`, `GET /billing/status` |
| Employees | `GET/POST /employees`, `GET /employees/{id}`, pause/resume |
| Automations | `POST /me/triggers`, `POST /triggers/{id}` (invoke) |
| Connectors | `GET /oauth/connections`, MCP routes under `/mcp/*` |
| Activity | `GET /activity?limit=` |

## Gaps (desktop-side notes)

- **admeasy-ai-assistant** repo was not readable from the cloud agent GitHub token; `brand-tokens.json` is vendored from the live **admeasy.ai** web bundle and should be replaced with the assistant repo file when available.
- Employee **run** is via **trigger invoke** (`POST /triggers/{id}`), not a dedicated “run employee” POST.
- MCP connect flows still open in the system browser from the phone/web; the desktop lists catalog/installed only.
