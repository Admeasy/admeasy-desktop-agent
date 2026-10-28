# Admeasy desktop beta (v0.5.0-beta.3)

No terminal required. Pair with the same Google account as the Admeasy phone app.

Prefer **signed** release assets when listed on GitHub. Unsigned builds use `-unsigned` in the filename.

## macOS

1. Download **`Admeasy-0.5.0-beta.3-macos.dmg`** (or `*-unsigned.dmg`) from [Releases](https://github.com/Admeasy/admeasy-desktop-agent/releases).
2. Open the DMG → drag **Admeasy** to **Applications**.
3. **Unsigned:** right-click **Open** once to bypass Gatekeeper.
4. Enter an invite code, then sign in with Google (an account that is already invited can sign in directly). Grant **Screen Recording**, **Accessibility**, and **Full Disk** if you use Messages/comms jobs.
5. Grant **Screen Recording** and **Accessibility** to Admeasy.app (no browser extension is needed).
6. Leave the app running (auto-starts at login).

## Windows

1. Download **`Admeasy-0.5.0-beta.3-windows.exe`** (or unsigned) from Releases.
2. Run the installer (WebView2 installed if needed).
3. Enter an invite code, then sign in with Google. Grant Screen Recording + Accessibility.
4. Optional: `pip install uiautomation` is bundled in the installer build for UI Automation snapshots.

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
