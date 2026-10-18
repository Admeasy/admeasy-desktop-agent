# PyInstaller spec. macOS -> Admeasy.app, Windows -> Admeasy.exe (windowed, no console).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ver = os.environ.get("ADMEASY_RELEASE_VERSION", "0.2.0-beta")
root = os.path.abspath(os.path.join(SPECPATH, ".."))
hidden = collect_submodules("admeasy_desktop") + [
    "keyring.backends",
    "pystray._darwin",
    "pystray._win32",
    "webview",
    "webview.platforms",
    "httpx",
    "websockets",
    "playwright",
    "playwright.async_api",
    "mss",
    "PIL",
    "pyautogui",
    "pyperclip",
]
if sys.platform == "win32":
    hidden += collect_submodules("uiautomation") + ["uiautomation", "comtypes", "comtypes.client", "comtypes.gen"]
    hidden += ["tkinter", "_tkinter"]
if sys.platform == "linux":
    hidden += ["tkinter", "_tkinter"]
if sys.platform == "darwin":
    hidden += [
        "AppKit",
        "Foundation",
        "objc",
        "Quartz",
        "ApplicationServices",
        "admeasy_desktop.input_darwin",
        "admeasy_desktop.cursor_overlay_mac",
        "admeasy_desktop.screen_coords_mac",
    ]
if sys.platform == "win32":
    hidden += ["admeasy_desktop.cursor_overlay_win"]

datas = [(os.path.join(root, "admeasy_desktop", "ui", "index.html"), os.path.join("admeasy_desktop", "ui")),
         (os.path.join(root, "admeasy_desktop", "chromium_browsers.json"), "admeasy_desktop")]

a = Analysis(
    [os.path.join(root, "admeasy_desktop", "__main__.py")],
    pathex=[root],
    hiddenimports=hidden,
    datas=datas,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Admeasy",
    console=False,
    entitlements_file="entitlements.plist" if sys.platform == "darwin" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Admeasy")
if sys.platform == "darwin":
    icon = "icon.icns" if os.path.exists(os.path.join(SPECPATH, "icon.icns")) else None
    app = BUNDLE(
        coll,
        name="Admeasy.app",
        icon=icon,
        bundle_identifier="ai.admeasy.desktop",
        info_plist={
            "CFBundleName": "Admeasy",
            "CFBundleDisplayName": "Admeasy",
            "CFBundleShortVersionString": ver,
            "CFBundleVersion": ver.replace("-", "."),
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSAppleEventsUsageDescription": "Admeasy opens and controls apps on your Mac when you ask it from your phone.",
            "NSDesktopFolderUsageDescription": "Admeasy reads and saves files in your Desktop folder when you ask.",
            "NSDocumentsFolderUsageDescription": "Admeasy reads and saves files in your Documents folder when you ask.",
            "NSDownloadsFolderUsageDescription": "Admeasy reads and saves files in your Downloads folder when you ask.",
            "NSAccessibilityUsageDescription": "Admeasy moves the mouse and types on your Mac when you control it from your phone.",
            "NSScreenCaptureUsageDescription": "Admeasy captures the screen so the assistant can see apps and websites.",
        },
    )
