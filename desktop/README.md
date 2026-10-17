# Admeasy desktop agent

Plain app for macOS and Windows: Google sign-in, device status, permission grants, and a live log tail. Chat and commands come from the phone only.

Full design: [`../docs/DESKTOP_AGENT.md`](../docs/DESKTOP_AGENT.md).

## Setup (Mac and Windows)

**macOS / Linux**

```bash
./scripts/setup-venv.sh
source .venv/bin/activate
```

**Windows (PowerShell)**

```powershell
.\scripts\setup-venv.ps1
.\.venv\Scripts\Activate.ps1
```

Optional: `playwright install chromium` if Google Chrome is not installed (browser jobs fall back to Chromium).

## Run against Lightsail

```bash
export ADMEASY_BACKEND=https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com
python -m admeasy_desktop doctor
python -m admeasy_desktop login
python -m admeasy_desktop run
```

Backend requirements (main repo):

- `DEVICES_ENABLED=true` on the Lightsail service
- Merged `docs/backend-changes.diff` (device tools, `/devices/tunnel`, desktop loopback on `/auth/google/start`)

## Commands

Same as `python -m admeasy_desktop …` or `admeasy-desktop …` after `pip install -e .`.

## Tests

```bash
python -m pytest -q tests
```

## Installers

- macOS: `packaging/build_macos.sh` (Developer ID + notarytool)
- Windows: `packaging/build_windows.ps1` (Inno Setup)
