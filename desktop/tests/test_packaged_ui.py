"""Packaged-build HTTP checks (simulates PyInstaller layout)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from admeasy_desktop.__main__ import _html_ui_ready
from admeasy_desktop.config import Settings
from admeasy_desktop.ui.server import UiState, serve


@pytest.fixture(scope="module")
def pyinstaller_dist(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    packaging = root / "packaging"
    dist = tmp_path_factory.mktemp("dist")
    build = tmp_path_factory.mktemp("build")
    venv = tmp_path_factory.mktemp("venv")
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    if sys.platform == "win32":
        py = venv / "Scripts" / "python.exe"
    else:
        py = venv / "bin" / "python"
    subprocess.run([str(py), "-m", "pip", "install", "-q", "-U", "pip", "pyinstaller"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "-e", str(root)], check=True)
    env = {"ADMEASY_RELEASE_VERSION": "0.0.0-smoke"}
    subprocess.run(
        [str(py), "-m", "PyInstaller", "admeasy.spec", "--noconfirm",
         "--distpath", str(dist), "--workpath", str(build)],
        cwd=str(packaging),
        env={**os.environ, **env},
        check=True,
        timeout=300,
    )
    internal = dist / "Admeasy" / "_internal"
    assert (internal / "admeasy_desktop" / "ui" / "index.html").is_file()
    assert (internal / "admeasy_desktop" / "ui" / "icons" / "hand" / "01-computer.png").is_file()
    return internal


def test_frozen_http_serves_html_not_js(pyinstaller_dist, monkeypatch):
    monkeypatch.setenv("ADMEASY_HOME", str(pyinstaller_dist / "home"))
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(pyinstaller_dist), raising=False)
    ui = UiState(Settings())
    srv, port = serve(ui)
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/") as res:
            html = res.read().decode()
            assert res.headers.get_content_type() == "text/html"
            assert _html_ui_ready(html, res.status)
        with urllib.request.urlopen(base + "/icons/hand/01-computer.png") as res:
            assert res.headers.get_content_type() == "image/png"
            assert len(res.read()) > 100
        with urllib.request.urlopen(base + "/app.js") as res:
            assert res.headers.get_content_type() == "application/javascript"
            head = res.read(40).decode()
            assert head.startswith("const token")
        with urllib.request.urlopen(base + "/api/state") as res:
            snap = json.load(res)
            assert "backend" in snap or "settings" in snap
        try:
            urllib.request.urlopen(base + "/nope")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        srv.shutdown()
