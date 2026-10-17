from admeasy_desktop.job_store import JobStore


def test_idempotency_and_pending(tmp_path):
    store = JobStore(tmp_path / "store.json")
    payload = {"status": "ok", "result": {"x": 1}}
    store.put_idempotent("k1", payload)
    assert store.get_idempotent("k1") == payload
    store.buffer_result({"type": "result", "job_id": "j", "status": "ok"})
    pending = store.pop_pending()
    assert len(pending) == 1
