# Desktop product: what a browser can do, and what we built

Written 28 Oct 2026 after reading this repo, the live Lightsail API (`image` `158b86a`), the public site at https://admeasy.ai, and the research brief on Clicky, Hermes, OpenClaw, Codex, and Claude. The private repo `Admeasy/admeasy-ai-assistant` was **not readable** with the GitHub token on this machine (`repository not found`). Theme values in `desktop/admeasy_desktop/ui/theme.css` are marked as captured from the deployed site stylesheet, not from that private source.

## Can a browser (or an installed PWA) do the OS work?

No. A page, installed or not, runs in the browser sandbox. It can ask the user for a few things. It cannot hold macOS Accessibility or Screen Recording, and it cannot inject input into other apps.

| Need | What the browser allows | What it cannot do |
|---|---|---|
| Playwright / driving Chrome | Nothing useful. There is no API that launches or attaches to the user's browser. | Start Playwright, reuse a profile, click a page the user already has open. |
| Accessibility (macOS AX, Windows UI Automation, Linux AT-SPI) | Nothing. | Read or press another app's controls. |
| Keyboard and mouse in other apps | The page only receives input aimed at itself. | `CGEvent` / `SendInput` / `uinput`. A page cannot type into Terminal, WhatsApp, or Cursor. |
| Screen capture | `getDisplayMedia()`: the user picks a screen or window **each time**, and the page receives a video stream while that tab is allowed to. | Silent or persistent capture. No pixel-to-click map the OS will honor. No ScreenCaptureKit. |
| Clipboard | Clipboard API read/write, usually only while the page is focused and after a user gesture or a permission prompt. | Background read/write while the helper is acting and the page is not focused. |
| Folders | File System Access API / `showDirectoryPicker()` in Chromium: a user-chosen directory handle, remembered for that **origin**. Firefox and Safari are much weaker. The handle is not an OS path a Python process can use. | Whole-disk access, or a path the helper can pass to `open`, `git`, or Playwright. |
| Shell / PTY | Nothing. | `cd` that sticks, `nano`, `git`, package managers. |
| Notifications | Notification API, and Web Push if a service worker has a VAPID subscription. Safari only for installed web apps, and it revokes permission if a push is not shown. | A toast after the browser is quit, unless the helper (a native process) shows one. |

Installing the site as a PWA does not add these powers. It is still the same sandbox, with its own window.

## How other products get those powers

Every product in the brief uses the same split: a **local process** holds the OS permissions, and the UI is a front end.

- **Hermes** desktop is an Electron shell. It talks to a local gateway over `/api/ws` with one-use tickets. The gateway is what has the terminal session (cwd survives), cron, and computer use. Computer use goes to the separate `cua-driver` process (AX on macOS, UI Automation on Windows, AT-SPI on Linux).
- **OpenClaw** is a menu-bar app. The dashboard is a web page. Pairing is a short-lived code. `system.run` still has to pass the node's own allow/deny rules. Notifications are native, not browser push.
- **Clicky** is a Swift menu-bar app. Screen capture is ScreenCaptureKit. The open-source build mostly points at the screen; API keys stay on a Cloudflare worker, not in the app. Rebuilding from a terminal invalidates the macOS permission grant, because the signed identity changed.
- **Codex** sandboxes shell commands (Seatbelt, bubblewrap, or a Windows sandbox) and still asks before it leaves the sandbox. That is a policy on a local process, not a browser feature.
- **Claude Desktop** runs local MCP servers. A folder the user picks is handed to that process as a path.

Admeasy already had the local process: `desktop/admeasy_desktop` opens an outbound WebSocket to `wss://<lightsail>/devices/tunnel`, so the phone and WhatsApp can drive this machine from behind NAT. Playwright, screenshots (`mss` plus the macOS screen APIs), and keyboard/mouse (`pyautogui`, and `CGEvent` / UI Automation in the platform modules) already live there. The gap was the product around it: a chat window, explicit folder grants, a real PTY, reminders, and an install path that does not need an Apple or Microsoft certificate.

We did **not** adopt `cua-driver` as a second binary. This repo already posts input and reads the accessibility tree on macOS and Windows. Shipping another native helper would mean another unsigned binary and another permission prompt. ScreenCaptureKit is the same story: it is macOS-only and wants a signed bundle. `mss` plus the existing Screen Recording check works on the three desktops we support.

## Unsigned install, compared

| Shape | What the user hits without a certificate | Least-friction path |
|---|---|---|
| **pip / the install script (chosen)** | `curl` does not set the macOS quarantine bit, and `irm` does not set the Windows Mark of the Web, so Gatekeeper and SmartScreen stay quiet. The user still gets the normal Accessibility and Screen Recording prompts. | `desktop/packaging/install.sh` and `install.ps1`. They create `~/.admeasy/venv`, install this package, register a per-user service (LaunchAgent, systemd `--user`, or HKCU Run), and register `admeasy://`. |
| **PWA by itself** | No Gatekeeper dialog, because nothing native was downloaded. Also no OS control. | Not sufficient. |
| **PWA plus this helper** | The page can be installed from the helper's localhost origin (Chrome treats localhost as a secure context). The helper is still the thing that was installed by the script. | This is the UI we ship. A page hosted on `https://admeasy.ai` that called `127.0.0.1` would also face Chrome's Local Network Access prompt. We avoid that by serving the UI from the helper. |
| **pywebview window** | Same process as the helper. No extra signature. If the webview cannot start, the UI opens in the browser. | `python -m admeasy_desktop run` already did this. It still does. |
| **Tauri or Electron** | An unsigned `.app` downloaded in a browser gets `com.apple.quarantine`. The user must right-click Open once (or clear the flag). An unsigned `.exe` gets SmartScreen ("More info" → "Run anyway") until a certificate builds reputation. Ad-hoc `codesign -s -` changes every build, so macOS asks for Accessibility and Screen Recording again after each update. That is the same failure Clicky documents for `xcodebuild`. | Not worth a rewrite while we have no Developer ID. The existing unsigned DMG/EXE scripts stay for people who want a bundle. A $99/year Developer ID plus notarization is the only way those prompts stick across updates. |
| **Homebrew / winget** | A cask or winget manifest can avoid the browser's quarantine, but the formula has to be published in those registries. We did not publish one. | Later. The script is the path that works from this repo today. |

A custom URL scheme cannot be registered by a bare shell script on macOS. The helper writes a small `Admeasy Helper.app` (or a `.desktop` file, or an HKCU `URL Protocol` key) whose only job is to forward `admeasy://…` to `handle-url`. The link is allowed to contain a job id and nothing else. Query keys such as `command` are rejected. The helper loads the command it stored earlier, checks the blocklist again, writes a script file, and opens Terminal, iTerm (`ADMEASY_TERMINAL=iterm`), Windows Terminal (`wt`), or `x-terminal-emulator`. The URL text is never pasted into a shell.

No product can open a terminal from a web page **before** something native is installed. The window therefore shows a copy-paste command. After the helper is in place, `admeasy://run?job=<id>` opens the terminal.

## Chosen architecture

```
Phone / WhatsApp / this window
        │  HTTPS + WSS, user JWT or device token
        ▼
Lightsail backend (existing)
        ▲
        │  outbound WSS /devices/tunnel  (already implemented; works behind NAT)
        │
Admeasy helper  (this Python package, per-user service)
        │  http://127.0.0.1:<port>  with a per-launch token
        ▼
Chat window (the files in desktop/admeasy_desktop/ui)
```

The helper keeps the phone-control tunnel. A computer that already has `~/.admeasy/config.json` is not locked: `gate_until_onboarding` stays false, so the phone can keep sending jobs. A **new** config refuses shell, screen, input, browser, and files until the window's permission steps are finished.

The window is one chat column. The ⋯ menu opens Profile, Connections, Plan, and Notifications. Assistant replies are split into short bubbles in `fragments.py`. The backend still stores one assistant message per turn; splitting in the client is what the desktop shows. WhatsApp will not match that until the backend splits too (see the PR).

### Chat and the same account

Sign-in is unchanged: system browser → `GET /auth/google/start?desktop_port&nonce&invite` → loopback `http://127.0.0.1/callback` → `POST /devices/register`. Tokens stay in the keychain (or `~/.admeasy/secrets.json` when the keychain is missing). The window never sees them.

History uses the live routes, confirmed on the Lightsail host:

- `GET /conversations?limit=`
- `GET /conversations/{id}/messages?limit=`

Both require the user JWT. The newest conversation is the one the window opens, which is the same thread WhatsApp and the phone write.

Sending is `WSS /ws/session?token=&conversation_id=` with `{"type":"text","text":"…"}`, which is what `backend/app/main.py` in **this** repo implements. Events we render: `token`, `done`, `revision`, `tool_call`, `error`, `approval_required`, `attachment`. On 28 Oct 2026 the **live** host returned **404** for `/ws/session` and for the other chat paths we probed. `GET /conversations` is there (401 without a token). So history works against production as soon as you are signed in. Sending works against a backend that still mounts `/ws/session`, and the window says so when production answers 404. That route has to be deployed from `admeasy-ai-assistant`. We did not change that repo and we did not deploy.

### Permissions

The first screen after sign-in shows Screen Recording, Accessibility, keyboard/mouse (the same Accessibility grant), and clipboard. Grant opens the System Settings URL on macOS (`permissions.open_settings`). Windows and Linux have no per-app screen or input grant; those rows show as granted, which matches `permissions.check`. Clipboard is probed with a read, never a write. If the machine has no clipboard (a headless Linux box), the user can mark that and continue. The composer stays disabled until those checks pass. New installs also refuse device jobs until then.

### Folders

Connections lists approved folders. Add opens a native picker (`osascript` / the Windows folder dialog / zenity) or accepts a typed path. The helper rejects filesystem roots and the home directory itself. `use_approved_folders_only` is set on the first approve or revoke, and file jobs then use only that list (`safety.folder_roots`). Older configs keep the previous Downloads/Desktop/Documents behavior until the user touches the list, so an existing phone setup does not lose its folders by surprise.

### Terminal

`terminal` jobs spawn a POSIX PTY (`pty.openpty`) so `cd` sticks and programs like `nano` have a tty. Output is streamed on the existing `step` channel and into the window's activity feed. Windows uses `pywinpty` when it is installed, otherwise a PowerShell pipe (cwd will not stick in that fallback). A button on a shell note calls `POST /api/terminal-jobs`, which stores the command only after `policy.judge` allows it, and returns `admeasy://run?job=<id>`.

### Safety

Copied from the Hermes / Codex pattern, enforced in the helper so a prompt-injected model cannot skip it:

- The hard block (`rm -rf /`, disk erase, shutdown, piping curl into a shell, reading `~/.admeasy` secrets) still cannot be turned off.
- `command_blocklist` in Connections is the same: it wins over trusted mode and over the allowlist.
- `command_allowlist` skips the approval prompt for an exact command or a glob.
- Anything that would have asked is **denied** when the job is marked `autonomous`, `scheduled`, or `reminder_id`. No prompt, no timeout window.
- Other risky commands still ask. The wait is 300 seconds, then deny. The phone answers as before. The window can answer too (`POST /api/approvals`).
- Every job appends a line to `~/.admeasy/audit.jsonl` (kind, status, a short summary). Connections shows the tail.
- Capability toggles: shell, files, screen, input, browser (Playwright), notifications. Off means the helper returns `blocked` and does not act. Default is on, so a computer that was already paired keeps working.

### Reminders and notifications

The window's Notifications screen saves a reminder locally and tries `POST /reminders` on the backend. That route is not on the live API (it 404s). Until it exists, the helper's scheduler fires the reminder: a native toast (`osascript` / a Windows toast / `notify-send`) and, if the window is open and permission was granted, a Notification plus the service worker. Web Push from Lightsail needs a VAPID key we cannot add from this repo. WhatsApp delivery is the same backend scheduler fanning out. The helper also shows a toast if the tunnel sends `{"type":"reminder","text":"…"}`.

### Pairing code

`POST /devices/pair-codes` is attempted when the window builds the install command. If the backend returns a code, the command includes `--pair`. `admeasy-desktop pair CODE` posts it to `POST /devices/pair/redeem`. If that route 404s, the command exits 2 and the install script tells the user to finish with the existing Google sign-in. That Google path is what actually pairs the machine with the phone and WhatsApp account today.

## What still has to change in admeasy-ai-assistant

Not done here. Not deployed.

1. Mount `WSS /ws/session` again on the Lightsail image (this repo's `backend/app/main.py` already has it; image `158b86a` returns 404). Client text frame: `{"type":"text","text":"…"}`. Optional query `conversation_id`. Optional field `client: "desktop"` if you want to tell channels apart.
2. `POST /devices/pair-codes` (Bearer user JWT) → `{code, expires_in}` single-use, about 10 minutes. `POST /devices/pair/redeem` `{code, name, platform, os_version}` → the same `access_token`, `refresh_token`, `email` as the Google loopback, plus `device_id` and `device_token`.
3. `POST /reminders`, `GET /reminders`, `DELETE /reminders/{id}` on the existing scheduler. Fan-out to the device tunnel as `{"type":"reminder","id","text"}`, to WhatsApp, and to mobile push. One id, so the helper can drop duplicates.
4. `GET /push/vapid-public-key` and `POST /push/web` so the service worker can subscribe. The helper already calls `showNotification` when a reminder fires locally.
5. Optional: emit assistant text as several bubbles (`{"type":"bubbles","texts":[…]}`) if WhatsApp should match the desktop. The desktop splits on its own until then.
6. Optional: `GET /devices/terminal-jobs/{id}` if a phone should mint an `admeasy://` link. The helper already mints ids locally.

LLM keys stay on Lightsail. The helper stores only the user refresh token and the device token.
