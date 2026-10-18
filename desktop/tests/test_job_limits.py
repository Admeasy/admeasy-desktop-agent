import asyncio

from admeasy_desktop.job_limits import DEFAULT_TIMEOUT_S, job_idempotency_key, job_timeout_s
from admeasy_desktop.job_store import MAX_IDEMPOTENT, JobStore


def test_every_job_gets_a_unique_key():
    assert job_idempotency_key("j1", {}) == "job:j1"
    assert job_idempotency_key("j2", {"idempotency_key": ""}) == "job:j2"
    assert job_idempotency_key("j3", {"idempotency_key": "k"}) == "k"
    assert job_idempotency_key("a", {}) != job_idempotency_key("b", {})


def test_interactive_steps_get_short_defaults():
    assert job_timeout_s("screenshot", {}, {}) == DEFAULT_TIMEOUT_S["screenshot"] < 60
    assert job_timeout_s("open", {}, {}) <= 30 and job_timeout_s("cua", {}, {}) <= 60
    assert job_timeout_s("open", {}, {"timeout_s": 90}) == 90
    assert job_timeout_s("open", {"timeout_s": 12}, {"timeout_s": 90}) == 12
    assert job_timeout_s("open", {}, {"timeout_s": "bad"}) == DEFAULT_TIMEOUT_S["open"]
    assert job_timeout_s("unknown_kind", {}, {}) == 120


def test_store_is_bounded_and_drops_screenshots(tmp_path):
    st = JobStore(tmp_path / "s.json")
    for i in range(MAX_IDEMPOTENT + 20):
        st.put_idempotent(f"job:{i}", {"status": "ok", "result": {"screenshot_b64": "x" * 100, "w": 1}})
    assert st.get_idempotent("job:0") is None
    last = st.get_idempotent(f"job:{MAX_IDEMPOTENT + 19}")
    assert last == {"status": "ok", "result": {"w": 1}}


class _Agent:
    pass


def test_redelivered_job_does_not_run_twice(tmp_path, monkeypatch):
    from admeasy_desktop import agent as agent_mod

    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a.store = JobStore(tmp_path / "s.json")
    sent, runs = [], []

    async def send(m):
        sent.append(m)

    async def fake_run(job, jid, kind, p, idem):
        runs.append(jid)
        await asyncio.sleep(0.05)
        a.store.put_idempotent(idem, {"status": "ok"})
        await send({"type": "result", "job_id": jid, "status": "ok"})

    a.send, a._run_job = send, fake_run
    job = {"job_id": "j1", "kind": "cua", "params": {}}

    async def go():
        await asyncio.gather(a.run_job(job), a.run_job(job))  # duplicate delivery while running
        await a.run_job(job)  # re-delivered after it finished
    asyncio.run(go())
    assert runs == ["j1"]
    assert [m["job_id"] for m in sent] == ["j1", "j1"]
