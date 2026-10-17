# Signing releases (required for smooth install on macOS and Windows)

Unsigned builds are blocked by **Gatekeeper** (macOS) and **SmartScreen** (Windows). CI produces **signed** installers when these GitHub Actions **repository secrets** are set:

## macOS (Developer ID + notarization)

| Secret | Example |
|--------|---------|
| `MAC_CERT_P12` | Base64 of `.p12` export (Developer ID Application) |
| `MAC_CERT_PASSWORD` | P12 export password |
| `MAC_SIGN_ID` | `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID` | Apple ID email |
| `APPLE_TEAM_ID` | 10-char team id |
| `APPLE_APP_PASSWORD` | App-specific password for notarytool |

Artifacts: `Admeasy-<version>-macos.dmg` (notarized).

## Windows (Authenticode)

| Secret | Example |
|--------|---------|
| `WIN_SIGN_PFX` | Base64 of code-signing `.pfx` |
| `WIN_SIGN_PFX_PASSWORD` | PFX password |

Artifacts: `Admeasy-<version>-windows.exe`.

If secrets are missing, CI still publishes **ad-hoc** macOS DMG (`*-macos-unsigned.dmg`) and unsigned Windows installer (`*-windows-unsigned.exe`). macOS: **Right-click → Open** once. Windows: **More info → Run anyway**, and ensure WebView2 installs (the setup runs `install-webview2.ps1` automatically).
