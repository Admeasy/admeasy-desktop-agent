# Desktop ↔ backend contract (v0.5.0)

Handshake: desktop `hello` includes top-level `contract_version` (must match `capabilities.contract_version`).

## CUA job result (each step)

```json
{
  "status": "ok",
  "result": {
    "screenshot_b64": "...",
    "size": [1280, 800],
    "elements": [],
    "last_action": {"input": "quartz", "pointer_ok": true, "ax_ok": false}
  }
}
```

Coordinates in `action.x` / `action.y` are in **screenshot pixel space** (`size`); desktop scales to logical points (Retina + `monitor_origin` when used).

Shared fixtures: `docs/contract-fixtures/instagram_flow.json`

Conformance test: `python scripts/run_cua_conformance.py`
