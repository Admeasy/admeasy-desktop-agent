# Admeasy desktop beta (v0.4.0-beta.1)

No terminal required. Pair with the same Google account as the Admeasy phone app.

Prefer **signed** release assets when listed on GitHub. Unsigned builds use `-unsigned` in the filename.

## macOS

1. Download **`Admeasy-0.4.0-beta.1-macos.dmg`** (or `*-unsigned.dmg`) from [Releases](https://github.com/Admeasy/admeasy-desktop-agent/releases).
2. Open the DMG → drag **Admeasy** to **Applications**.
3. **Unsigned:** right-click **Open** once to bypass Gatekeeper.
4. Sign in with Google; grant **Screen Recording**, **Accessibility**, and **Full Disk** if you use Messages/comms jobs.
5. On the permissions page, use **One-click setup** to register the **browser extension** + native messaging host (Chrome / Edge / Brave).
6. Leave the app running (auto-starts at login).

## Windows

1. Download **`Admeasy-0.4.0-beta.1-windows.exe`** (or unsigned) from Releases.
2. Run the installer (WebView2 installed if needed).
3. Sign in, grant permissions, run extension setup from the app UI.
4. Optional: `pip install uiautomation` is bundled in the installer build for UI Automation snapshots.

## What’s new in 0.4

- **Set-of-mark** clicks (`element_id`) on macOS and Windows
- **Structured browser** via extension when installed; otherwise default browser + CUA
- **Long-run** helpers: idempotent jobs, reconnect resume, keep-awake during objectives
- **Artifacts:** append CSV/XLSX in `~/.admeasy` shared folders; upload via presigned URL from backend

## Phone

Approve sends, calls, installs, and destructive actions when prompted. The desktop has no chat UI — objectives show as step + row count in the window.
