import pytest

from admeasy_desktop import job_store


@pytest.fixture(autouse=True)
def _isolated_job_store(tmp_path, monkeypatch):
    # Every job is cached by key now; tests reuse job ids like "j1", so never share the user's real store.
    monkeypatch.setattr(job_store, "STORE", tmp_path / "job_store.json")
