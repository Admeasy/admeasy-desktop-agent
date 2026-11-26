# Agent-driven desktop audit

Audit of places where Python decided instead of the model (pre-change locations). **Changed** summarizes what we did in `0.5.0-beta.11`.

| Location | What Python did | Change |
|----------|-----------------|--------|
| `desktop/admeasy_desktop/agent.py:46` | `APPROVAL_WAIT_S = 300` — no answer treated as deny | **Removed.** Approvals wait until `approval_result`; tunnel gets `needs_approval` + notification. |
| `desktop/admeasy_desktop/agent.py:199-201` | `asyncio.wait_for(fut, APPROVAL_WAIT_S+5)` → `False` | **Removed.** `await fut` without wall clock. |
| `desktop/admeasy_desktop/agent.py:274-275` | User deny → vague `blocked` / "did not approve" | **`failed`** with `code: denied` via outcome contract. |
| `desktop/admeasy_desktop/agent.py:290` | Global `asyncio.wait_for(dispatch, job_timeout_s(...))` per job | **Removed job-level cap.** Per-tool `tool_timeout_s` + heartbeats only (`_dispatch_tool`). |
| `desktop/admeasy_desktop/policy.py:199-200` | `autonomous and verdict.ask` → hard deny | **Removed.** Scheduled jobs park on `needs_approval` like interactive jobs. |
| `desktop/admeasy_desktop/policy.py:5` (doc) | Documented "300 s = no" | **Updated** to resumable `needs_approval`. |
| `desktop/admeasy_desktop/job_limits.py:8-26` | Short per-kind job caps (screenshot 20s, open 30s, …) | **Per-tool defaults** (shell/browser 600s, max 1800s). No global step limit. |
| `desktop/admeasy_desktop/executors/terminal_exec.py:155` | Default command timeout 120s, max 900s | **Default 600s**, max `MAX_TOOL_TIMEOUT_S` (1800). |
| `desktop/admeasy_desktop/results.py` | Legacy status only on wire | **`finalize()`** adds `{ok, status, code, detail, job_id}` outcome fields. |
| `desktop/admeasy_desktop/agent.py:dispatch` | Fixed per-workflow handlers only | **General tools:** `screen`, `notify`; **legacy** kinds gated behind `ADMEASY_LEGACY_HANDLERS=1`. |
| `desktop/admeasy_desktop/failure_detect.py` | Heuristic login/captcha from AX text | **Kept** as factual signals (`needs_auth`), not answer rewriting. |
| `desktop/admeasy_desktop/agent.py:cua` | `detect_failure` may set captcha/needs_human | **Unchanged** — returns typed status; model/backend decides next step. |

## Intentionally kept (safety)

| Location | Purpose |
|----------|---------|
| `policy.py` `HARD_BLOCK` | Catastrophic commands never run |
| `policy.py` / `judge` | Approval prompts for destructive shell, delete, send, pay, install |
| `safety.gate_job` | Capability toggles and onboarding gate |
| `entitlements` | Plan limits → `rate_limited` / `blocked` with real messages |

## Backend pairing

- Resume approvals: existing `approval_result` on `/devices/tunnel` (`allow` bool).
- New non-terminal message: `type: needs_approval` (same fields as outcome `needs_approval`).
- Progress: `type: heartbeat` every ~15s during tool execution.
- Contract version in `hello`: **`0.5.1`**.