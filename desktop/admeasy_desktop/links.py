"""admeasy:// links carry a server-issued or helper-issued job id, never a command string."""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse

from . import config
from .policy import judge

JOB_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_FORBIDDEN = {"command", "cmd", "c", "shell", "exec", "script", "args"}


def parse_run_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme != "admeasy":
        raise ValueError("not an admeasy link")
    action = (parsed.netloc or parsed.path or "").strip("/")
    if action not in ("run", "terminal"):
        raise ValueError("unsupported link")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    extra = set(query) - {"job"}
    if extra & _FORBIDDEN or extra:
        raise ValueError("the link must carry only a job id")
    job = (query.get("job") or [""])[0].strip()
    if not JOB_ID.match(job):
        raise ValueError("bad job id")
    return job


def _store_path():
    return config.HOME / "terminal-jobs.json"


def _read() -> dict:
    try:
        data = json.loads(_store_path().read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(data: dict) -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    _store_path().write_text(json.dumps(data))
    try:
        os.chmod(_store_path(), 0o600)
    except OSError:
        pass


def create_job(command: str, roots, mode: str = "autopilot", allowlist=None, blocklist=None) -> dict:
    command = (command or "").strip()
    if not command:
        raise ValueError("empty command")
    verdict = judge("shell", {"command": command}, mode, roots, allowlist=allowlist, blocklist=blocklist)
    if not verdict.allow:
        raise ValueError(verdict.reason or "blocked")
    if verdict.ask:
        raise ValueError("that command needs approval before it can be opened in a terminal")
    job_id = secrets.token_hex(8)
    rec = {"id": job_id, "command": command, "created": time.time(), "expires": time.time() + 600}
    data = _read()
    now = time.time()
    data = {k: v for k, v in data.items() if float(v.get("expires") or 0) > now}
    data[job_id] = rec
    _write(data)
    return {"id": job_id, "url": f"admeasy://run?job={job_id}", "ask": False}


def load_job(job_id: str) -> dict:
    if not JOB_ID.match(job_id or ""):
        raise ValueError("bad job id")
    rec = _read().get(job_id)
    if not rec:
        raise ValueError("unknown job")
    if float(rec.get("expires") or 0) < time.time():
        raise ValueError("that link has expired")
    return rec


def open_in_terminal(command: str, job_id: str) -> None:
    """Run a command that was already loaded by job id. The URL text is not used here."""
    folder = config.HOME / "terminal-runs"
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        script = folder / f"{job_id}.ps1"
        script.write_text(command + "\r\n", encoding="utf-8")
        wt = shutil.which("wt") or shutil.which("wt.exe")
        if wt:
            subprocess.Popen([wt, "new-tab", "--", "powershell", "-NoExit", "-File", str(script)])
        else:
            subprocess.Popen(["powershell", "-NoExit", "-File", str(script)])
        return
    script = folder / f"{job_id}.sh"
    script.write_text("#!/bin/bash\n" + command + "\n", encoding="utf-8")
    os.chmod(script, 0o700)
    quoted = str(script).replace('"', '\\"')
    if sys.platform == "darwin":
        prefer = os.environ.get("ADMEASY_TERMINAL", "Terminal")
        if prefer.lower() == "iterm":
            osa = f'tell application "iTerm" to create window with default profile command "bash \\"{quoted}\\""'
        else:
            osa = f'tell application "Terminal" to do script "bash \\"{quoted}\\""'
        subprocess.Popen(["osascript", "-e", osa])
        return
    term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("xterm")
    if not term:
        raise RuntimeError("no terminal emulator found")
    if os.path.basename(term) == "gnome-terminal":
        subprocess.Popen([term, "--", "bash", str(script)])
    else:
        subprocess.Popen([term, "-e", "bash", str(script)])


def register_url_handler(exe: list[str]) -> str:
    """Point admeasy:// at this helper. exe is an argv prefix, not a shell string."""
    if sys.platform == "darwin":
        return _register_mac(exe)
    if sys.platform == "win32":
        return _register_windows(exe)
    return _register_linux(exe)


def _register_mac(exe: list[str]) -> str:
    import plistlib
    app = config.HOME / "Admeasy Helper.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    # The bundle executable only forwards the URL. LaunchServices passes it as $1.
    quoted = " ".join(_sh_quote(part) for part in exe)
    (macos / "helper").write_text(f"#!/bin/bash\nexec {quoted} handle-url \"$1\"\n", encoding="utf-8")
    os.chmod(macos / "helper", 0o755)
    plist = {
        "CFBundleName": "Admeasy Helper",
        "CFBundleIdentifier": "ai.admeasy.helper",
        "CFBundleVersion": "1",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "helper",
        "CFBundleURLTypes": [{
            "CFBundleURLName": "Admeasy",
            "CFBundleURLSchemes": ["admeasy"],
        }],
    }
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    ls = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    if os.path.exists(ls):
        subprocess.run([ls, "-f", str(app)], check=False)
    return str(app)


def _register_linux(exe: list[str]) -> str:
    desktop = config.HOME / "applications"
    desktop.mkdir(parents=True, exist_ok=True)
    path = desktop / "admeasy-url.desktop"
    argv = " ".join(_sh_quote(part) for part in [*exe, "handle-url", "%u"])
    path.write_text(
        "[Desktop Entry]\n"
        "Name=Admeasy\n"
        f"Exec={argv}\n"
        "Type=Application\n"
        "Terminal=false\n"
        "MimeType=x-scheme-handler/admeasy;\n",
        encoding="utf-8",
    )
    local = os.path.expanduser("~/.local/share/applications")
    os.makedirs(local, exist_ok=True)
    target = os.path.join(local, "admeasy-url.desktop")
    shutil.copy(path, target)
    if shutil.which("xdg-mime"):
        subprocess.run(["xdg-mime", "default", "admeasy-url.desktop", "x-scheme-handler/admeasy"], check=False)
    return target


def _register_windows(exe: list[str]) -> str:
    command = " ".join(f'"{part}"' if " " in part else part for part in exe)
    command = f'{command} handle-url "%1"'
    ps = (
        "New-Item -Path 'HKCU:\\Software\\Classes\\admeasy' -Force | Out-Null; "
        "New-ItemProperty -Path 'HKCU:\\Software\\Classes\\admeasy' -Name 'URL Protocol' -Value '' -Force | Out-Null; "
        "Set-ItemProperty -Path 'HKCU:\\Software\\Classes\\admeasy' -Name '(default)' -Value 'URL:Admeasy'; "
        "New-Item -Path 'HKCU:\\Software\\Classes\\admeasy\\shell\\open\\command' -Force | Out-Null; "
        f"Set-ItemProperty -Path 'HKCU:\\Software\\Classes\\admeasy\\shell\\open\\command' -Name '(default)' -Value '{command}'"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
    return "HKCU\\Software\\Classes\\admeasy"


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
