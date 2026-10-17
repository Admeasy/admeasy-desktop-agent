# Admeasy desktop beta (v0.2.0-beta)

No terminal, Python, or env vars required. The app talks to the production Admeasy backend automatically.

## macOS

1. Download **`Admeasy-0.2.0-beta-macos-unsigned.dmg`** from [Releases](https://github.com/Admeasy/admeasy-desktop-agent/releases).
2. Open the DMG and drag **Admeasy** into **Applications**.
3. **First launch (unsigned):** Finder → Applications → **right-click Admeasy → Open** → **Open** in the dialog. (You only need this once.)
4. Sign in with the **same Google account** as the Admeasy phone app.
5. Grant **Screen Recording** and **Accessibility** when asked (System Settings → Privacy & Security).
6. Leave Admeasy running. It **starts again at login** in the background (menu-bar icon when paused/quit is available).

**Browser tasks:** install [Google Chrome](https://www.google.com/chrome/) if you want `device_browser` / web opens to use Chrome.

## Windows

1. Download **`Admeasy-0.2.0-beta-windows-unsigned.exe`** from Releases.
2. Run the installer. If SmartScreen warns: **More info → Run anyway**.
3. Open **Admeasy** from the Start menu, sign in with Google, allow permissions if prompted.
4. The installer registers Admeasy to **start at login** in the background (`run --background`).

Install [Google Chrome](https://www.google.com/chrome/) for best browser automation.

## Phone

Use the same Google account. Ask Admeasy to use **your computer** (e.g. “open Instagram on my MacBook”). Approve risky actions on the phone when prompted.

## Data location

Settings, tokens, and logs: `~/.admeasy/` (macOS/Linux) or `%USERPROFILE%\.admeasy\` (Windows).
