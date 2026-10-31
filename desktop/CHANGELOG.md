# Changelog

## 0.5.0-beta.7 — 2026-10-31

- Workspace hub in the desktop window: AI employees, scheduled work, documents, vault, and MCP connectors (list/detail UX aligned with the web app).
- Hand-drawn hub icons bundled under `admeasy_desktop/ui/icons/hand/` (18 PNGs, 64×64).
- Backend proxy routes for `/schedules`, `/kb/documents`, `/vault/overview`, and `/mcp/connectors/{slug}`.
- Connectors screen shows health, MCP server URL, tool list, and reconnect when `needs_reauth`.

## 0.5.0-beta.6

- Fix packaged app serving raw JavaScript instead of the UI shell.
