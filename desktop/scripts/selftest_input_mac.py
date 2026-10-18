#!/usr/bin/env python3
"""Standalone macOS input self-test for the Admeasy desktop agent.

Run it with the SAME python/executable the agent uses (TCC permissions are per
executable). It opens a fresh TextEdit document (a safe target), then for each
injection method (Quartz kCGHIDEventTap, Quartz kCGSessionEventTap, pyautogui):
  1. moves the pointer to the document and reads the pointer position back
  2. clicks, checks which app is frontmost
  3. types a marker and reads the document text back via AppleScript
Prints one SELFTEST line per step. No screenshots, no network, nothing leaves the Mac.
"""
import os
import subprocess
import sys
import time


def log(msg):
    print(f"SELFTEST {msg}", flush=True)


def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    return r.stdout.strip(), r.stderr.strip()


def identity():
    log(f"executable={sys.executable} python={sys.version.split()[0]} pid={os.getpid()} ppid={os.getppid()}")
    try:
        from ApplicationServices import AXIsProcessTrusted
        log(f"ax_trusted={bool(AXIsProcessTrusted())}")
    except Exception as e:
        log(f"ax_trusted=ERROR {type(e).__name__}: {e}")
    try:
        import Quartz
        log(f"screen_capture={bool(Quartz.CGPreflightScreenCaptureAccess())}")
        log(f"post_event_access={bool(Quartz.CGPreflightPostEventAccess())}")
        log(f"listen_event_access={bool(Quartz.CGPreflightListenEventAccess())}")
    except Exception as e:
        log(f"quartz_preflight=ERROR {type(e).__name__}: {e}")
    try:
        from AppKit import NSBundle
        b = NSBundle.mainBundle()
        log(f"bundle_id={b.bundleIdentifier()} bundle_path={b.bundlePath()}")
    except Exception as e:
        log(f"bundle=ERROR {type(e).__name__}: {e}")


def frontmost():
    out, _ = osa('tell application "System Events" to get name of first application process whose frontmost is true')
    return out


def doc_text():
    out, err = osa('tell application "TextEdit" to get text of document 1')
    return out if not err else f"ERR:{err[:80]}"


def prepare_textedit():
    osa('tell application "TextEdit" to activate')
    osa('tell application "TextEdit" to make new document')
    time.sleep(1.0)
    osa('tell application "TextEdit" to set bounds of window 1 to {200, 200, 900, 700}')
    time.sleep(0.5)
    # deactivate TextEdit so the click itself must bring it forward
    osa('tell application "Finder" to activate')
    time.sleep(0.8)
    return (550, 450)  # centre of the document body, global logical points


def pointer_pos():
    import Quartz
    p = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return round(p.x), round(p.y)


def quartz_click_type(x, y, tap_name, marker):
    import Quartz
    tap = Quartz.kCGHIDEventTap if tap_name == "hid" else Quartz.kCGSessionEventTap
    pt = (x, y)
    mv = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, pt, Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(tap, mv)
    time.sleep(0.2)
    log(f"method=quartz_{tap_name} move_target={pt} pointer_after_move={pointer_pos()}")
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        ev = Quartz.CGEventCreateMouseEvent(None, kind, pt, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, 1)
        Quartz.CGEventPost(tap, ev)
        time.sleep(0.05)
    time.sleep(0.6)
    log(f"method=quartz_{tap_name} frontmost_after_click={frontmost()}")
    for ch in marker:
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(ev, 1, ch)
            Quartz.CGEventPost(tap, ev)
        time.sleep(0.02)


def pyautogui_click_type(x, y, marker):
    import pyautogui
    pyautogui.moveTo(x, y, duration=0.1)
    log(f"method=pyautogui move_target={(x, y)} pointer_after_move={pointer_pos()} pyautogui_size={tuple(pyautogui.size())}")
    pyautogui.click(x, y)
    time.sleep(0.6)
    log(f"method=pyautogui frontmost_after_click={frontmost()}")
    pyautogui.typewrite(marker, interval=0.02)


def main():
    if sys.platform != "darwin":
        print("macOS only"); return 2
    identity()
    try:
        import mss
        with mss.mss() as s:
            for i, m in enumerate(s.monitors):
                log(f"monitor[{i}] left={m['left']} top={m['top']} width={m['width']} height={m['height']}")
            raw = s.grab(s.monitors[1])
            log(f"monitor[1] raw_pixels={raw.size.width}x{raw.size.height}")
    except Exception as e:
        log(f"mss=ERROR {type(e).__name__}: {e}")
    results = {}
    for method in ("hid", "session", "pyautogui"):
        x, y = prepare_textedit()
        marker = f"adm{method}ok"
        try:
            if method == "pyautogui":
                pyautogui_click_type(x, y, marker)
            else:
                quartz_click_type(x, y, method, marker)
            time.sleep(0.6)
            text = doc_text()
            ok = marker in text
            results[method] = ok
            log(f"method={method} typed_readback_ok={ok} doc_len={len(text)}")
        except Exception as e:
            results[method] = False
            log(f"method={method} ERROR {type(e).__name__}: {e}")
    log("RESULT " + " ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in results.items()))
    log("Close the test TextEdit documents without saving.")
    return 0 if any(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
