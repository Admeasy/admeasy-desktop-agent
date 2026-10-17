# admeasy-desktop-agent

Desktop companion for [Admeasy](https://github.com/Admeasy/admeasy-ai-assistant): your phone (the command centre) drives actions on **your own** Mac or Windows PC through the same FastAPI backend, Supabase project, and Google account as the mobile app.

## Quick start

```bash
cd desktop
./scripts/setup-venv.sh          # Windows: powershell -File scripts/setup-venv.ps1
source .venv/bin/activate
python -m admeasy_desktop doctor
python -m admeasy_desktop login    # Google sign-in + device enrolment
python -m admeasy_desktop run      # local UI: status, permissions, live logs
```

Point at the Lightsail backend (default in code) or override:

```bash
export ADMEASY_BACKEND=https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com
```

The backend must have `DEVICES_ENABLED=true` and the device routes merged from `docs/backend-changes.diff` (applied in the main `admeasy-ai-assistant` repo).

## Repository layout

| Path | Purpose |
|------|---------|
| `desktop/` | Python app (`admeasy_desktop`), tests, packaging |
| `backend/app/devices/` | Reference copy of device service/routes/tools for this repo’s tests |
| `docs/DESKTOP_AGENT.md` | Full design (wire protocol, safety, permissions) |
| `docs/backend-changes.diff` | Required patches to `admeasy-ai-assistant` (`agent.py`, `main.py`, `auth.py`) |

## CLI

| Command | Description |
|---------|-------------|
| `python -m admeasy_desktop run` | Window + outbound tunnel (optional `--background` + tray) |
| `python -m admeasy_desktop login` | Browser Google sign-in, loopback token handoff, register device |
| `python -m admeasy_desktop doctor` | Backend health, sign-in, enrolment, permissions, screenshot |
| `python -m admeasy_desktop devices` | List computers on your account |
| `python -m admeasy_desktop logout` | Revoke this device and clear local secrets |

Config and secrets: `~/.admeasy/` (`ADMEASY_HOME` to override). Env vars only in docs — never commit secrets.

## Tests

```bash
cd desktop && source .venv/bin/activate && python -m pytest -q tests
```

## What needs a real Mac/Windows machine

macOS Screen Recording and Accessibility prompts, Playwright `channel="chrome"`, code signing/notarization, and tray/autostart are not fully exercised in Linux CI. See `docs/DESKTOP_AGENT.md` §10.
