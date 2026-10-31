# Changelog

## 0.5.0-beta.10 — 2026-10-31

- CI: exclude `live_network` tests from default pytest (founder invite expiry on production); fix Windows PyInstaller test venv paths.
- Windows overlays: import `wintypes` in cursor overlay; resolve `GetModuleHandleW` via `kernel32` (not `user32`).
- Frozen smoke: detect second-instance handoff via `agent.log` (windowed `.exe` has no stdout).
- Frozen smoke: wait for `ui-server.json` before second launch; do not inherit `ADMEASY_HEADLESS_HOLD` on the handoff process.
- macOS CI: mock Accessibility in CUA contract tests (headless runners lack ApplicationServices).

## 0.5.0-beta.9 — 2026-10-31

- Fix Windows UI hang: serve sign-in and static assets before API routes; preload HTML/JS; run backend proxy and chat history off-thread with 5s caps; stop blocking `/api/state` on Lightsail (cached devices/entitlements/install snippet).
- Single-instance handoff when Admeasy is already running (mutex + ui-server.json); `/api/ping` and `/signin` aliases.
- Windows overlay: define `HCURSOR`/`HBRUSH` via `HANDLE` when missing from `ctypes.wintypes`.
- CI frozen smoke adds stress load + second-instance test; UI probe logs timing to agent.log.

## 0.5.0-beta.8 — 2026-10-31

- Fix packaged app startup: the sign-in probe now reads enough HTML (Google Fonts in `<head>` pushed `id="app"` past the old 512-byte limit).
- Start the device tunnel only after the loopback UI is verified; improve UI probe logging and HTTP handler error isolation.
- CI: frozen-binary headless smoke (`ADMEASY_HEADLESS_SMOKE`) on Linux, macOS, and Windows.

## 0.5.0-beta.7 — 2026-10-31

- Workspace hub in the desktop window: AI employees, scheduled work, documents, vault, and MCP connectors (list/detail UX aligned with the web app).
- Hand-drawn hub icons bundled under `admeasy_desktop/ui/icons/hand/` (18 PNGs, 64×64).
- Backend proxy routes for `/schedules`, `/kb/documents`, `/vault/overview`, and `/mcp/connectors/{slug}`.
- Connectors screen shows health, MCP server URL, tool list, and reconnect when `needs_reauth`.

## 0.5.0-beta.6

- Fix packaged app serving raw JavaScript instead of the UI shell.
