# Computer use — model-driven (no intent routing)

Python **does not** map user phrases to job kinds. The LLM reads **tool descriptions** and **live surface state**, then chooses `device_*` tools.

## Live surface (desktop → backend)

On `hello` and when permissions change, the desktop sends:

- `capabilities` — `job_kinds`, `browser` mode (`default_first` | `playwright_profile`), `native_apps`, etc.
- `permissions` — `screen`, `accessibility`, `full_disk`

After jobs that change the UI, results include:

- `surface` — e.g. `native_app`, `default_browser`, `screen`, `whatsapp_desktop`, `playwright_profile`
- `interaction` — hint for the model (e.g. “use cua with element_id from last screenshot”)
- `elements` / `ax_tree` — set-of-mark targets (when accessibility is granted)

The model should call **`device_list`** to refresh device capabilities before ambiguous computer tasks.

## Tool choice (descriptions, not routing tables)

| Tool | When the model should prefer it |
|------|----------------------------------|
| `device_open` | Launch a **native app** or open a URL in the **default browser** (user sessions) |
| `device_use_computer` | Interact with **whatever is on screen** (apps, default browser, dialogs) using **element_id** from the last screenshot |
| `device_browser` | DOM automation only when params request `force_playwright` / isolated profile; not for “use my logged-in Chrome” |
| `device_shell` / `device_files` | Commands and shared-folder files |
| `device_screenshot` | One frame + SOM/AX without acting |

There is **no** fixed rule like “WhatsApp → whatsapp kind”. Use `device_open("WhatsApp")` then `device_use_computer` with marks.

## Objectives

Long-running work uses **`objective_id`** on the backend orchestrator (Supabase + checkpointed LangGraph). The desktop echoes `objective_id` in results; it does not run the verify loop. See `WORKFLOW_DIAGNOSIS.md` and `BACKEND_CONTRACT.md`.
