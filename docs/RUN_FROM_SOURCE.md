# Run the Admeasy desktop agent from source

Everything runs from the `desktop/` folder of this repo. Python 3.11+ is required (3.12 recommended).

## New install — Mac (Terminal)

```bash
# 1) Python 3.12 + git (pick one way for Python)
brew install python@3.12 git          # Homebrew: https://brew.sh
#   or: python.org installer https://www.python.org/downloads/macos/  and  xcode-select --install  (for git)

# 2) Get the agent and install it in a virtual env
git clone https://github.com/Admeasy/admeasy-desktop-agent.git
cd admeasy-desktop-agent/desktop
PY=python3.12 ./scripts/setup-venv.sh
source .venv/bin/activate

# 3) Sign in, check, run
python -m admeasy_desktop login
python -m admeasy_desktop doctor --click-test
python -m admeasy_desktop run
```

Permissions (macOS checks the app you launch from — **Terminal**, not Admeasy.app):
1. System Settings → Privacy & Security → **Accessibility** → add **Terminal**, switch it on.
2. Privacy & Security → **Screen Recording** → add **Terminal**, switch it on.
3. When asked "Terminal wants to control Comet / System Events", click **OK** (Automation; used to reuse open tabs).
4. Terminal menu → make sure **Secure Keyboard Entry** is OFF (it blocks typing).
5. Quit Terminal fully (Cmd+Q) and reopen it, then `cd admeasy-desktop-agent/desktop && source .venv/bin/activate && python -m admeasy_desktop run`.
6. If the old Admeasy.app (v0.4) is running, quit it (menu-bar icon → Quit).

`doctor --click-test` must end with every line `[ok]`; it prints the exact fix if clicks or typing are dropped.

## New install — Windows (PowerShell)

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
# close and reopen PowerShell so python/git are on PATH
git clone https://github.com/Admeasy/admeasy-desktop-agent.git
cd admeasy-desktop-agent\desktop
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -U pip wheel
python -m pip install -r requirements.txt
python -m pip install -e .
python -m admeasy_desktop login
python -m admeasy_desktop doctor --click-test
python -m admeasy_desktop run
```

## Update an existing clone

Mac:
```bash
cd admeasy-desktop-agent && git pull origin main && cd desktop
[ -d .venv ] || PY=python3.12 ./scripts/setup-venv.sh
source .venv/bin/activate
python -m pip install -r requirements.txt && python -m pip install -e .
# stop the running agent (Ctrl+C in its Terminal window), then:
python -m admeasy_desktop doctor --click-test
python -m admeasy_desktop run
```

Windows:
```powershell
cd admeasy-desktop-agent; git pull origin main; cd desktop
if (!(Test-Path .venv)) { py -3.12 -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt; python -m pip install -e .
# stop the running agent (Ctrl+C), then:
python -m admeasy_desktop run
```
