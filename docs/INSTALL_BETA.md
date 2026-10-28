# Admeasy desktop beta (v0.5.0-beta.6)

**You do not run curl.** Download the app, open it, sign in with Google.

Pair with the same Google account as the Admeasy phone app. The app talks to our Lightsail backend automatically.

Prefer **signed** release assets when listed on GitHub. Unsigned builds use `-unsigned` in the filename.

## macOS (normal users)

1. Download **`Admeasy-0.5.0-beta.6-macos-unsigned.dmg`** from [Releases](https://github.com/Admeasy/admeasy-desktop-agent/releases).
2. Open the DMG → drag **Admeasy** to **Applications**.
3. **First launch:** macOS may say the app “cannot be opened”. Open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** (or right-click the app → **Open** once).
4. Open Admeasy again. You should see the invite / sign-in screen (warm paper UI), **not** raw JavaScript text or a blank white window.
5. Enter an invite code if needed, then **Continue with Google**. Grant **Screen Recording** and **Accessibility** when asked.
6. Leave the app running (it registers a background helper for your phone).

**No Mac login password loops:** the app stores sign-in tokens in `~/.admeasy/secrets.json`, not repeated Keychain prompts.

## macOS (developers only)

Terminal install needs **Python 3.11+** (macOS’s built-in 3.9 is too old). Use the `.dmg` instead, or `brew install python@3.12` then the install script from Connections → advanced.

## Windows

1. Download **`Admeasy-0.5.0-beta.6-windows-unsigned.exe`** from Releases.
2. Run the installer (WebView2 installed if needed).
3. Enter an invite code, then sign in with Google. Grant Screen Recording + Accessibility.
4. Optional: `pip install uiautomation` is bundled in the installer build for UI Automation snapshots.

## What’s new in 0.5.0-beta.6

- Fix window showing raw `app.js` source: correct bundle paths, HTML-only `/`, pywebview loads `html` + base URL
- Packaged-build smoke test in CI (PyInstaller onedir + MIME checks)
- Startup checks UI bundle + Lightsail `/health` before opening the window

## What’s new in 0.5.0-beta.5

- Fix white window in the .dmg (UI assets were missing from the bundle)
- Admeasy icon in the .app (no Python floppy disk)
- Sign-in tokens in `~/.admeasy/secrets.json` (no repeated Keychain password prompts)
- Install docs and Connections screen lead with **download**, not curl
- `install.sh` detects Python 3.11+ and tells you to use the .dmg if macOS only has 3.9

## What’s new in 0.5.0-beta.4

- Full Lightsail wiring: chat (`client=desktop`), pair codes, reminders, web push, employees, triggers, connectors, activity
- Brand tokens vendored as `desktop/admeasy_desktop/ui/brand-tokens.json`
- Desktop API notes in `docs/DESKTOP_API.md`

## What’s new in 0.5.0-beta.3

- Chat window with web design tokens (warm paper, Gaegu/Nunito, marketing-style bubbles)
- Permissions, folder allowlist, reminders, install scripts, and `admeasy://` terminal links
- Same outbound phone tunnel; history from `GET /conversations` when signed in

## What’s new in 0.5.0-beta.2

- Invite code before Google sign-in, unless this account is already invited
- Computer-use actions check the weekly plan limit first
- The window shows your plan, actions left this week, and referral invites when the account has them

## What’s new in 0.4

- **Set-of-mark** clicks (`element_id`) on macOS and Windows
- **Browser** via the default browser + screen CUA (Playwright for structured DOM ops)
- **Long-run** helpers: idempotent jobs, reconnect resume, keep-awake during objectives
- **Artifacts:** append CSV/XLSX in `~/.admeasy` shared folders; upload via presigned URL from backend

## Phone

Approve sends, calls, installs, and destructive actions when prompted. The desktop has no chat UI — objectives show as step + row count in the window.

## Input self-test (macOS)

If clicks are reported but nothing happens, run from Terminal (Terminal needs Accessibility for this test):

```
cd admeasy-desktop-agent/desktop && python3 -m pip install --user pyobjc-framework-Quartz pyobjc-framework-ApplicationServices mss pyautogui && python3 scripts/selftest_input_mac.py
```

Send back every line starting with `SELFTEST` (no screenshots or text content are printed).
