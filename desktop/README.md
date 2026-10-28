# Admeasy on your computer

A chat window (WhatsApp-style bubbles) plus a helper that can actually type, click, capture the screen, run a shell, and drive Playwright. The phone can still drive this computer through the same outbound tunnel.

Why the browser is not enough, and how install works without a signing certificate: [`../docs/ARCHITECTURE_WEB_APP.md`](../docs/ARCHITECTURE_WEB_APP.md).

## Install without a certificate

The script uses `curl` / `irm`, which do not mark the download as quarantined, so Gatekeeper and SmartScreen do not prompt. You still grant Accessibility and Screen Recording yourself on a Mac. Read the script before you run it.

**macOS or Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/Admeasy/admeasy-desktop-agent/main/desktop/packaging/install.sh | bash -s -- --backend "$ADMEASY_BACKEND"
```

Until that file is on `main`, run it from a checkout:

```bash
desktop/packaging/install.sh --source "$(pwd)" --backend "${ADMEASY_BACKEND:-https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com}"
```

**Windows (PowerShell)**

```powershell
$env:ADMEASY_BACKEND = "https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com"
irm https://raw.githubusercontent.com/Admeasy/admeasy-desktop-agent/main/desktop/packaging/install.ps1 | iex
```

From a checkout, before the script is on `main`:

```powershell
$env:ADMEASY_SOURCE = (Get-Location).Path
$env:ADMEASY_BACKEND = "https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com"
powershell -File .\desktop\packaging\install.ps1
```

The script installs into `~/.admeasy/venv`, registers a per-user background service, and registers the `admeasy://` link handler. Then open the window and sign in with the same Google account as your phone.

The Connections screen shows this command again. If the backend has issued a pairing code, the command includes it. Today the live API does not, so the script falls back to Google sign-in (exit code 2 from `pair`).

## Run from a checkout

**macOS / Linux**

```bash
./scripts/setup-venv.sh
source .venv/bin/activate
export ADMEASY_BACKEND=https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com
python -m admeasy_desktop run
```

**Windows (PowerShell)**

```powershell
.\scripts\setup-venv.ps1
.\.venv\Scripts\Activate.ps1
$env:ADMEASY_BACKEND = "https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com"
python -m admeasy_desktop run
```

The process prints `Admeasy is open at http://127.0.0.1:<port>/`. Sign in, grant the four permission rows, then the chat composer unlocks. `⋯` opens Profile, Connections, Plan, and Notifications.

On a new config the helper will not click, type, or run a shell until that screen is finished. A computer that already had `~/.admeasy/config.json` keeps serving the phone.

Optional: `playwright install chromium` if Google Chrome is not installed.

## What to try

- **Chat.** After sign-in, history loads from `GET /conversations`. Sending uses `WSS /ws/session`. The live Lightsail image we probed does not mount that socket yet; the window says so, and the phone tunnel still runs. See the PR for the backend change.
- **Permissions.** The first screen shows screen, accessibility, keyboard/mouse, and clipboard. Grant opens System Settings on macOS.
- **Folders.** Connections → approve a folder. `/` and your home directory are rejected. Revoke removes it. File jobs cannot leave the list once you have approved one.
- **Shell.** A shell note in the chat has "open in terminal". That navigates to `admeasy://run?job=<id>` (a job id only). The helper opens Terminal, iTerm (`ADMEASY_TERMINAL=iterm`), Windows Terminal, or `x-terminal-emulator`.
- **Reminders.** Notifications → pick a time. This computer toasts when it is due. WhatsApp delivery waits on `POST /reminders` in the backend.
- **Phone.** Leave `python -m admeasy_desktop run` (or the service) running. The phone uses the same device tunnel as before.

## Tests

```bash
python -m pytest -q tests
```

## Unsigned bundles

The script above is the path that avoids Gatekeeper and SmartScreen. If you still want a `.dmg` or `.exe`, `packaging/build_macos_unsigned.sh` and `packaging/build_windows_unsigned.ps1` ad-hoc sign or leave the binary unsigned. macOS: right-click Open once. Windows: More info → Run anyway. Those builds ask for Screen Recording again after every rebuild, because the signature identity changes.

## Backend

The Lightsail service needs `DEVICES_ENABLED=true`, the entitlements routes, and the device tunnel from `docs/backend-changes.diff`. Chat history is `GET /conversations`. Sending a turn needs `WSS /ws/session`, which the live image does not mount yet.

## Commands

`python -m admeasy_desktop` also has `doctor`, `login`, `pair`, `handle-url`, `register-handler`, and `install-service`.

Signed bundles, when a certificate exists: `packaging/build_macos.sh`, `packaging/build_windows.ps1`.
