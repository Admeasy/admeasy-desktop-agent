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

The Connections screen shows this command again with a fresh **`POST /devices/pair-codes`** code when you are signed in.

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

The process prints `Admeasy is open at http://127.0.0.1:<port>/`. Sign in, grant the four permission rows, then the chat composer unlocks. `⋯` opens Profile, Connections, Workspace (employees, schedules, documents, vault, connectors), Automations, Plan, Activity, and Notifications.

API reference (derived from live OpenAPI): [`../docs/DESKTOP_API.md`](../docs/DESKTOP_API.md).

On a new config the helper will not click, type, or run a shell until that screen is finished. A computer that already had `~/.admeasy/config.json` keeps serving the phone.

Optional: `playwright install chromium` if Google Chrome is not installed.

## What to try

- **Chat.** History from `GET /conversations`. Send with `WSS /ws/session?token=<JWT>&client=desktop` (fragmented bubbles on `done` / `revision`).
- **Pairing.** Connections mints a code via `POST /devices/pair-codes`; install scripts redeem with `POST /devices/pair/redeem`.
- **Reminders.** `POST/GET/DELETE /reminders` plus tunnel `{type:"reminder"}` toasts. Web Push via `GET /push/vapid-public-key` and `POST /push/web` (client `desktop`).
- **Employees & automations.** Same REST as the phone (`/employees`, `/me/triggers`, `POST /triggers/{id}`). The **Workspace** hub also calls `/schedules`, `/kb/documents`, `/vault/overview`, and `/mcp/connectors/{slug}` when those routes are enabled on the backend.
- **QA sign-in (web).** When the server has Resend OTP enabled, accounts listed in `TEST_LOGIN_EMAILS` can use password login on the web app without email OTP if the server is configured with `TEST_LOGIN_PASSWORD` (or `TEST_ADMEASY_ACCOUNT`). The desktop app still uses Google OAuth only.
- **Permissions & folders.** Onboarding grants screen/accessibility/input/clipboard; Connections approves folder paths (not `/` or home).
- **Shell links.** Chat notes can open `admeasy://run?job=<id>` in your terminal app.
- **Phone.** Leave `python -m admeasy_desktop run` (or the service) running. The phone uses the same device tunnel as before.

## Tests

```bash
python -m pytest -q tests
```

## Unsigned bundles

The script above is the path that avoids Gatekeeper and SmartScreen. If you still want a `.dmg` or `.exe`, `packaging/build_macos_unsigned.sh` and `packaging/build_windows_unsigned.ps1` ad-hoc sign or leave the binary unsigned. macOS: right-click Open once. Windows: More info → Run anyway. Those builds ask for Screen Recording again after every rebuild, because the signature identity changes.

## Backend

Lightsail (main at `caeef71`) exposes the routes in [`../docs/DESKTOP_API.md`](../docs/DESKTOP_API.md). Set `ADMEASY_BACKEND` if you are not using the default hostname.

## Commands

`python -m admeasy_desktop` also has `doctor`, `login`, `pair`, `handle-url`, `register-handler`, and `install-service`.

Signed bundles, when a certificate exists: `packaging/build_macos.sh`, `packaging/build_windows.ps1`.
