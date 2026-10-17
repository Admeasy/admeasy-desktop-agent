# Admeasy Desktop Agent: control your own computer from your phone

Status: v0.1 scaffold. Backend, agent, tests and packaging scripts are in this repo. Sections 9 and 10 list what is verified and what is not.

## 1. The idea

You talk to Admeasy on your phone. The cloud assistant decides what to do. When the task is "use my MacBook", it calls `device_*` tools, the backend relays them over a connection your computer opened, and a small desktop app executes them on the real machine: real Chrome, real logins, real files, real terminal. The desktop app has no chat. It is hands and eyes only.

```
 Phone (Android / iOS)                 Admeasy backend (FastAPI)                 Your Mac / PC
 ┌──────────────────┐   WSS    ┌────────────────────────────────────┐   WSS     ┌────────────────────────┐
 │ chat + voice     │ ───────► │ agent loop (LLM picks tools)       │ ◄──────── │ desktop agent          │
 │ approve / deny   │ ◄─────── │ device_* tools -> DeviceService    │  outbound │  screen + mouse + keys │
 │ device list      │  push    │ user_devices, device_jobs (Postgres)│  only     │  Playwright (Chrome)   │
 └──────────────────┘          │ vision model (Bedrock computer-use)│           │  shell, files, clipboard│
                               └────────────────────────────────────┘           │  policy gate + approvals│
                                                                                └────────────────────────┘
```

Why this fixes the cloud-VM problem: on the VM the user logs in on a machine that is not theirs (different IP, fresh browser fingerprint), and your own `workers/signin.py` notes that copied cookies are weaker because sites bind them to the browser that minted them. On the user's own computer the login happens in place, once, and stays on disk.

## 2. What already exists in your repo and is reused

Your cloud VM agent (`backend/app/workers/vm/agent.py`) is about 70% of this design already:

| Existing piece | Reused as |
|---|---|
| Outbound WSS tunnel, `hello / task / step / result`, reconnect with backoff | Same wire protocol in `desktop/admeasy_desktop/agent.py` (no inbound ports on the user's machine) |
| `vm_jobs` queue + `_pump` + `FOR UPDATE SKIP LOCKED` | `device_jobs`, one job at a time per device (one screen, one mouse) |
| `token_hash` auth for VMs | `user_devices.token_hash`; the device token is shown once and only its hash is stored |
| `browser` job ops (open, click, type, read...) | `executors/browser.py`, same ops, pointed at real Chrome |
| `cua` job + `bedrock_cua.py` + `vm_vision.py` | `devices/cua.py` (adds right click, double click, drag, move; same Bedrock / vision fallback) |
| Google sign-in, JWT, `users.id` | Same account on phone and computer (section 4) |
| `AdmeasyNotificationListener` + `notifications_search` | Already reads Android notifications (section 6) |
| Activity log | Every device job writes to `activity_log` as `device__<kind>` |

New backend code: `backend/app/devices/{service,routes,tools,cua}.py`, small hooks in `agent.py`, `main.py`, `auth.py`. New app: `desktop/`.

## 3. About "Hermes"

The link in the brief, `facebook/hermes`, is Meta's JavaScript engine. Your React Native app already runs on it, so it has nothing to teach the agent design. The project that matches the description is Nous Research's Hermes Agent (`NousResearch/hermes-agent`): a terminal agent with a messaging gateway (Telegram, Slack, WhatsApp...), swappable terminal backends (local, Docker, SSH, cloud), a `~/.hermes` home folder, `hermes doctor`, and install-as-a-background-service. If you meant a different Hermes, tell me.

What was borrowed:

- **Gateway pattern.** Hermes lets you message an agent that runs on another machine. Admeasy's phone is the gateway; the desktop app is the always-on executor.
- **Execution backends.** Hermes picks where commands run (local, Docker, SSH). Admeasy now has two: cloud VM (`vm_*` tools) and your own computer (`device_*` tools). The model picks per task.
- **`~/.admeasy` home folder** for config, Chrome profile, logs.
- **`doctor` command:** `python -m admeasy_desktop doctor` checks backend, sign-in, enrolment, permissions, Chrome, screenshot.
- **Runs as a background service:** auto-start at login (LaunchAgent on Mac, Run key on Windows).

## 4. Same Gmail means same computer: how identity works

1. Desktop app opens the system browser at `/auth/google/start?desktop_port=P&nonce=N` (same Google OAuth client and redirect URI as the phone, no new Google Cloud setup).
2. Backend finishes OAuth, and instead of the `admeasy://` deep link it redirects to `http://127.0.0.1:P/callback?...`. The desktop's loopback listener checks the nonce (a test proves a wrong nonce is rejected) and stores tokens in the Keychain / Credential Locker.
3. App calls `POST /devices/register` with the user's JWT and gets `device_id` + `device_token`.
4. Phone calls `GET /devices` and sees the computer, with online/offline and permission state.

Risk to check: your `users` row is keyed by `google_sub`, which for password sign-in holds the Supabase user id. If someone signs in with Google on the phone and with email+password on the computer (or the reverse), they may get two different `user_id`s even with the same address. Pick one method for the desktop (Google, as built) and confirm both paths resolve to one row.

Which computer does "my MacBook" mean? `device_list` returns names; `DeviceService.pick` matches an exact id, then a name or platform ("macbook", "windows"). One device: used automatically. Several online and no name: the tool returns the list and the assistant asks. Rename in the app or via `PATCH /devices/{id}`.

## 5. Tools the model gets

| Tool | Does | Notes |
|---|---|---|
| `device_list` | Computers, online state, permissions | First call for "my computer" |
| `device_use_computer(goal)` | Screenshot, decide, act loop (up to 40 steps) | Open any app, click, type. Uses Claude computer-use on Bedrock, JSON-vision fallback |
| `device_screenshot` | Current screen | Frame also pushed to the phone via `on_screenshot` hook (not wired yet) |
| `device_open(target)` | App name, file path, or URL | `open -a` on Mac, `Start-Process` on Windows |
| `device_browser(op, ...)` | Playwright on real Chrome | Cheaper and more reliable than pixels for web pages |
| `device_shell(command)` | zsh / PowerShell | Always asks approval unless "trusted" mode |
| `device_files(op, path)` | list, read, write, mkdir, delete | Only inside shared folders (Downloads, Desktop, Documents by default) |
| `device_clipboard` | get / set | Also how non-ASCII text is typed reliably |
| `device_cancel` | Stop current job, clear queue | Also `POST /devices/{id}/cancel` |

These follow your architecture rules: no intent routing, the model chooses; tools are pinned like `vm_*` so there is no `load_tools` round trip; there is no canned prose in `app/`.

Examples that now work in principle: "open chatgpt.com on my MacBook and ask X" (browser or computer use), "open Cursor and fix this bug" (`device_use_computer` or `device_shell` with `cursor` / `claude -p`), "open Terminal and run git pull" (`device_shell`), "open Slack and read the last DM" (`device_use_computer`), "put report.pdf from Downloads into chat" (`device_files`).

## 6. Python dependencies

Desktop agent (`desktop/requirements.txt`):

| Package | Why |
|---|---|
| `websockets` | Outbound tunnel (same lib as the VM agent) |
| `httpx` | Backend REST: refresh, register, device list |
| `playwright` | Drives real Chrome with `channel="chrome"` (no browser download if Chrome is installed) |
| `mss` | Fast, multi-monitor screenshots |
| `pyautogui` | Mouse and keyboard on Mac / Windows. `FAILSAFE` on: slam the mouse into a screen corner to abort |
| `pillow` | Downscale and JPEG-encode screenshots |
| `pyperclip` | Clipboard, and typing any language via paste |
| `keyring` | Tokens in Keychain / Credential Locker (0600 file fallback) |
| `pywebview` | The plain login + devices window |
| `pystray`, `psutil` | Tray icon and process info (tray is wired as optional; see section 10) |
| `pyobjc-framework-Quartz`, `-ApplicationServices` (macOS) | Check and request Screen Recording and Accessibility |
| `pyinstaller` | Build `.app` and `.exe` |

Backend: no new packages. It uses `boto3`, `websockets` and `asyncpg`, already in `requirements.txt`.

Model: reuse `BEDROCK_VM_MODEL_ID` (Sonnet 4.5 profile) for computer use. Keep screenshots at or under 1280px on the long edge (the Scaler does this and maps clicks back to real points; skipping that mapping misclicks on Retina displays). Groq vision stays a fallback via `VM_VISION_PROVIDER`.

## 7. Permissions

**Mac (the strict one).** Granted per app bundle in System Settings, Privacy & Security:

| Permission | Needed for | How requested |
|---|---|---|
| Screen Recording | Screenshots | `CGRequestScreenCaptureAccess()` on first run |
| Accessibility | Mouse, keyboard, key presses | `AXIsProcessTrustedWithOptions(prompt)` on first run |
| Automation (Apple Events) | Controlling other apps by script | Prompts on first use; Info.plist text included |
| Files and Folders (Desktop, Documents, Downloads) | `device_files` | Prompts on first access; Info.plist text included |
| Full Disk Access | Only if you want folders beyond those | Manual, off by default |

There is no Info.plist key for Screen Recording or Accessibility; the app calls the APIs. **Sign every release with the same Developer ID**, or macOS asks again after each update. Without notarization Gatekeeper blocks the download.

**Windows.** No per-app grant for screen or input. Limit: a normal-privilege agent cannot click into windows running as Administrator. Run the agent elevated only if you need that. Sign the `.exe` or SmartScreen warns.

**Android phone** (this is already in your manifest and app): `BIND_NOTIFICATION_LISTENER_SERVICE` (user enables Notification access in Settings, plus an in-app switch; `AdmeasyNotificationListener.kt` posts to `/notifications` and the assistant searches with `notifications_search`), `POST_NOTIFICATIONS` for approval prompts, `RECORD_AUDIO` and foreground service for wake word, `SYSTEM_ALERT_WINDOW`, battery-optimization exemption so the socket survives.

**iPhone.** iOS has no API to read other apps' notifications. The iPhone can send commands, receive approvals and see screenshots, but cannot feed notifications to the assistant.

## 8. Safety: this machine can now be driven remotely

The policy gate runs on the computer, so it holds even if a web page prompt-injects the cloud model.

1. **Hard block (any mode):** disk wipes, `rm -rf` on root or home, shutdown / reboot, piping curl to a shell, reading the Keychain, or Admeasy's own secrets and config.
2. **Approval:** shell commands, file writes and deletes, and quit/close/delete shortcuts ask first. The request goes to the phone (`GET /devices/approvals`, `POST /devices/approvals/{id}`); no answer in 120 s counts as no. Modes: `ask_risky` (default), `ask_always`, `trusted`.
3. **Scoped files:** only the shared folders, symlink-safe; shared roots cannot be deleted.
4. **Kill switches:** phone `device_cancel` or `POST /devices/{id}/cancel`; mouse into a screen corner; "Pause Admeasy" in the app; sign out removes the device and revokes its token.
5. **No inbound ports.** Tokens are hashed server-side; the user's JWT never goes to the tunnel.
6. **Audit:** every job lands in `activity_log`.

Not solved yet: captchas and password fields. The agent reports `needs_human` / `needs_login` instead of fighting them. Because the user is away, the phone needs a live view to help (section 11).

## 9. Caveats to plan around

- **Sleep.** The app holds idle-sleep off (`caffeinate` on Mac, `SetThreadExecutionState` on Windows). A closed laptop lid still sleeps the machine unless it is on power with an external display. The phone gets "offline" and the tool says why. No software can change this; Wake-on-LAN does not work across the internet.
- **Locked screen.** Mouse and keyboard control does not work behind the macOS lock screen. Use "Lock after N minutes" with care, or leave the screen unlocked on an at-home machine.
- **Chrome 136+** ignores `--remote-debugging-port` on the default profile, so Playwright cannot attach to the everyday profile. The agent uses a dedicated persistent Admeasy Chrome profile (`~/.admeasy/chrome-profile`); the user signs in to their sites once there. For the everyday Chrome window use `device_use_computer`.
- **One job at a time per computer.** There is one mouse.
- **Computer-use accuracy** is good, not perfect. Prefer `device_browser`, `device_shell` and `device_files` when they fit.

## 10. What is verified and what is not

Verified here (Linux sandbox): 14 desktop tests pass, including a real WebSocket round trip against a stub backend with the real Agent (task, approval request, approval result, shell output, hard-block denial, out-of-folder denial), Retina click mapping, loopback nonce check, file traversal and root-protection, key parsing. 6 backend tests for tool schemas, device picking, action mapping and screenshot stripping pass. The existing guard tests pass for my code. One failure remains in a file I did not touch: `bedrock_cua.py` lines 51 and 53 trip `test_no_intent_routing_in_app_code`; add a `# noroute:` reason or restructure.

Not verified, needs a real machine or service:

- `DeviceService` against Postgres (DB tests skip without Postgres; schema is idempotent `CREATE TABLE IF NOT EXISTS`).
- The real Google redirect to the loopback port.
- macOS permission prompts, `pywebview` window, tray (`pystray` and `pywebview` both want the main thread on macOS; the window is the main path, the tray is not wired).
- PyInstaller builds, signing, notarization, the Windows installer (scripts and CI are written, never run).
- Playwright on real Chrome; the Bedrock computer-use call (it falls back to JSON vision on failure).

## 11. Next steps, in order

1. Run `DEVICES_ENABLED=true`, start the backend with Postgres, `python -m admeasy_desktop login` on a Mac, then `python -m admeasy_desktop doctor`.
2. Phone UI: a Devices screen (`GET /devices`), approval sheet (`GET /devices/approvals`), and wire `on_approval` to your existing FCM `PushSender` so a "Run `git push`?" notification arrives while you are away. `DeviceService.on_approval` is the hook.
3. Live view: wire `on_screenshot` to push frames to the phone (JPEG over your existing WebSocket first, WebRTC later). This is what lets you solve a captcha remotely.
4. Mac menu-bar item and Windows tray (pause, status, quit).
5. Signed `.dmg` and `.exe` through the CI workflow (`.github/workflows/desktop.yml`; needs Apple Developer ID, notarytool credentials, and a Windows code-signing cert).
6. Per-site "allowed apps" list and a daily action cap, once real usage shows what people do.
7. Auto-update (Sparkle on Mac, Squirrel or WinSparkle on Windows).
