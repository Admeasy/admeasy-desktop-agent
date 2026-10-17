# Why computer-use workflows do not complete

This is a **system** diagnosis (desktop + backend + product), not a single bug.

## 1. The loop stops at the wrong boundary

| Layer | What runs today | Where it stops |
|--------|------------------|----------------|
| **Voice/chat turn** | LangGraph `voice-turn` graph with `InMemorySaver` | After `max_tool_iterations` model rounds → `final` node summarizes and **ends the turn** |
| **device_use_computer** | Inner loop in `backend/app/devices/cua.py` (≤40 CUA steps) | Step budget, `needs_login`, or one failed job |
| **Desktop** | One job at a time on the tunnel | Returns one `result`; no objective state |

There is **no durable checkpointed run** keyed by `objective_id` that spans: plan → parallel subtasks → verify → resume after crash. The model may call `device_browser` once, get `needs_login`, and the **chat turn** still closes with a polite summary — objective **not** achieved, user sees “done” tone anyway (`final` node).

**Fix (backend):** Supabase-backed LangGraph checkpointer + `device_objectives` table; graph node `verify_objective` before END; sheet append each batch (below). Desktop only echoes `objective_id` and rich `surface` payloads.

## 2. “Routing” drift (docs vs architecture)

`COMPUTER_USE.md` previously had an **intent → kind** table. That contradicts `backend/app/agent.py` (“NO intent routing”) and `devices/tools.py` (“model picks the tool”).

Stale **tool descriptions** also misled the model, e.g. `device_browser` claiming “real Chrome profile” while the desktop defaults to **`default_first`** (system browser + screen capture).

**Fix:** Tool descriptions + live **`surface`** state from the desktop (`hello`, `permissions`, optional `surface` push). Model chooses tools; Python does not map user phrases to kinds.

## 3. No skills → repeated mistakes

Each run rediscovers LinkedIn, Maps, WhatsApp flows. Hermes-style **skills** (versioned playbooks in repo or Supabase) are not loaded into context.

**Fix (backend):** `app/skills/` registry; inject relevant skill text when `device_*` or `device_use_computer` is bound (retrieval by goal embedding or tags), not hardcoded per app.

## 4. Output in chat, not in durable artifacts

Scrape/research rows live in the model transcript. A 3-hour run that crashes loses partial work.

**Fix (backend):** After each batch, append rows to Google Sheet / Supabase table (tool `sheet_append` or worker); chat only shows summary + link. Desktop can write CSV into shared folder via `device_files` as interim.

## 5. Pixel-only CUA is slow and brittle

`device_use_computer` plans **x,y** clicks on JPEG. No **set-of-mark (SOM)** numbers, no **accessibility tree** in the prompt → wrong targets, especially Retina and dense UIs.

**Fix (desktop, v0.3.2+):** Screenshot returns `elements[]` with numeric `id` + compact `ax_tree`; CUA accepts `element_id` / `click_mark`. Backend prompt updated to prefer marks over raw coordinates.

## 6. Serial desktop queue

`DeviceService._pump` runs **one** job per device. Bulk browser work cannot parallelize on one machine (by design), but the **orchestrator** should batch DOM reads via Playwright when isolated profile is explicitly requested, and use SOM CUA on the default browser for logged-in UIs — model decides via tools, not `if whatsapp then …` in Python.

---

## Minimal path to “workflow complete”

1. **Desktop:** surface + SOM + AX in every screenshot/CUA result; honest `browser` / `open` behavior (already `default_first`).
2. **Backend:** Fix tool copy; extend `ComputerUse` for `element_id`; add objective graph + Postgres checkpointer + verification node.
3. **Product:** Skills library; sheet append per batch; UI shows objective status ≠ last task status.
