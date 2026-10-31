# Fix: `Session` has no attribute `live_state_block` (Reddit AI employee / WhatsApp)

## Symptom

Scheduled employee runs (e.g. “Run reddit ai employee work 2”) fail before any write tools run. LangSmith may show a successful `composio__REDDIT_SEARCH_ACROSS_SUBREDDITS` call in the VM deep agent, but WhatsApp gets:

> I couldn't finish … Nothing was retrieved with a verifiable source this run.

Server traceback (Lightsail `/app/app/agent_impl.py`):

```text
File "/app/app/agent_impl.py", line 876, in _structured_plan
    access_summary=session.live_state_block or "",
AttributeError: 'Session' object has no attribute 'live_state_block'
```

The crash happens in **`build` → `_build_v2` → `_structured_plan`** at the **start** of the turn, so the employee never reaches post/comment tools even when Reddit search already succeeded in a subgraph.

## Root cause

`_structured_plan` was updated to pass `session.live_state_block` into the route planner, but the `Session` type was not given that field (and nothing sets it in `_build_v2` yet). Any code path that uses `_build_v2` raises before tool execution.

## Fix (apply on **admeasy-ai-assistant** / production backend)

### 1. Add the field on `Session`

Where `Session` is defined (same module as `agent_impl` or `app/agent.py`):

```python
live_state_block: str = ""  # dataclass field, or instance attr default ""
```

Optional: populate before `_structured_plan` in `_build_v2`:

```python
try:
    from app.live import format_live_state_block  # name may differ in your tree
    session.live_state_block = await format_live_state_block(session.user_id)
except Exception:
    session.live_state_block = session.live_state_block or ""
```

An empty string is valid; the important part is that the attribute **exists**.

### 2. Harden `_structured_plan` (belt and suspenders)

```python
access_summary=getattr(session, "live_state_block", "") or "",
```

### 3. Deploy

Redeploy the FastAPI service on Lightsail (same image/process that serves `/employees`, triggers, and WhatsApp). Re-run the schedule or send “Run reddit ai employee work 2” again.

## Verify

1. No `live_state_block` in logs/tracebacks.
2. LangSmith turn continues past `_structured_plan` and shows `composio__REDDIT_CREATE_REDDIT_POST` or `composio__REDDIT_POST_REDDIT_COMMENT` when the employee instructions require it.
3. WhatsApp completion message reflects actual tool results, not the verifiable-source fallback.

## Reference in this repo

`backend/app/agent.py` `Session` includes `live_state_block: str = ""` so future merges from `admeasy-ai-assistant` do not drop the field again.
