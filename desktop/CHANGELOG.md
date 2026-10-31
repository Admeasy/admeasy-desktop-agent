# Changelog

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
