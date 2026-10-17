# Computer use on the local desktop (v0.3+)

## Intended workflow

1. **Native apps first** — `open` / `app` / `whatsapp` launch **WhatsApp, Cursor, VS Code**, etc. via the OS (Dock / Launchpad / Start). The result includes `surface: native_app` and `hint: use cua screenshot`.
2. **Your real browser** — Default mode `browser_automation=default_first` opens URLs with **Safari/Chrome/Edge default profile** (your saved logins), then returns a **full-screen screenshot** (`surface: screen`). It does **not** open an isolated Chrome guest profile.
3. **Interact with CUA** — Clicks, typing, and sign-in flows use kind **`cua`** (screen + accessibility). A **pink on-screen cursor** shows where the agent moves when `show_agent_cursor` is true in `~/.admeasy/config.json`.
4. **Playwright profile (optional)** — Backend may set `params.force_playwright=true` or user sets `browser_automation` to `playwright_profile` for isolated `~/.admeasy/chrome-profile` automation only.

## Backend routing (important)

| User intent | Send kind | Notes |
|-------------|-----------|--------|
| Open Cursor / WhatsApp / Mail | `open` or `app` | Not `browser` with a URL |
| Read a logged-in website | `browser` `read` + default_first | Screenshot of real browser |
| Click Sign in / type password | `cua` | Not `browser` click in default_first |
| WhatsApp messages on Mac | `whatsapp` `read` (desktop) or `messages` | Web only if `fallback_web: true` |

## Objectives (backend loop)

The desktop **echoes** `objective_id` from `task.params` in `result`. The **orchestration loop** (plan → act → verify objective achieved) lives in **admeasy-ai-assistant** with Supabase — see `BACKEND_CONTRACT.md` § Objectives.
