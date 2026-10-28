"""Scoped folder grants. The helper refuses the whole disk and any path the user has not approved."""
from __future__ import annotations

import os
import subprocess
import sys

def _norm(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def _is_filesystem_root(path: str) -> bool:
    full = os.path.abspath(path)
    parent = os.path.dirname(full)
    if parent == full:
        return True
    # Windows drive root, e.g. C:\
    if len(full) <= 3 and full[1:2] == ":":
        return True
    return False


def reject_reason(path: str) -> str | None:
    """None when this path may be added to the allowlist."""
    if not path or not str(path).strip():
        return "choose a folder"
    full = _norm(path)
    if not os.path.isdir(full):
        return "that path is not a folder"
    if _is_filesystem_root(full):
        return "pick a specific folder, not the whole disk"
    home = _norm("~")
    broad = {home, _norm("/Users"), _norm("/home"), _norm("/Volumes")}
    if full in broad:
        return "pick a specific folder, not your whole home folder"
    return None


def grant(settings, path: str) -> str:
    reason = reject_reason(path)
    if reason:
        raise ValueError(reason)
    full = _norm(path)
    current = list(getattr(settings, "approved_folders", []) or [])
    if full not in current:
        current.append(full)
    settings.approved_folders = current
    settings.use_approved_folders_only = True
    settings.save()
    return full


def revoke(settings, path: str) -> None:
    full = _norm(path)
    settings.approved_folders = [p for p in (settings.approved_folders or []) if _norm(p) != full]
    settings.use_approved_folders_only = True
    settings.save()


def pick_folder() -> str | None:
    """Native folder dialog. Returns a path, or None if the user cancels."""
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "Allow Admeasy to use this folder")'
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip().rstrip("/") or None
    if sys.platform == "win32":
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
        )
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        path = proc.stdout.strip()
        return path or None
    for cmd in (["zenity", "--file-selection", "--directory", "--title=Allow Admeasy to use this folder"],):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askdirectory(title="Allow Admeasy to use this folder")
        root.destroy()
        return path or None
    except Exception:
        return None
