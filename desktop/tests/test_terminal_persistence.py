import pytest


@pytest.mark.asyncio
async def test_terminal_spawn_persists_session_id():
    from admeasy_desktop.executors import terminal_exec

    a = await terminal_exec.run({"op": "spawn", "cwd": "."})
    assert a["status"] == "done"
    sid = a["result"]["session_id"]
    b = await terminal_exec.run({"op": "list"})
    ids = [s["session_id"] for s in b["result"]["sessions"]]
    assert sid in ids
    await terminal_exec.run({"op": "close", "session_id": sid})