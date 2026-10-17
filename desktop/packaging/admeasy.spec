# PyInstaller spec. macOS -> Admeasy.app (menu-bar style, stable bundle id), Windows -> Admeasy.exe (windowed).
import sys
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("admeasy_desktop") + ["keyring.backends", "pystray._darwin", "pystray._win32"]
a = Analysis(["../admeasy_desktop/__main__.py"], pathex=[".."], hiddenimports=hidden,
             datas=[("../admeasy_desktop/ui/index.html", "admeasy_desktop/ui")])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Admeasy", console=False,
          entitlements_file="entitlements.plist" if sys.platform == "darwin" else None)
coll = COLLECT(exe, a.binaries, a.datas, name="Admeasy")
if sys.platform == "darwin":
    import os
    app = BUNDLE(coll, name="Admeasy.app", icon="icon.icns" if os.path.exists("icon.icns") else None, bundle_identifier="ai.admeasy.desktop",
                 info_plist={
                     "CFBundleName": "Admeasy", "CFBundleShortVersionString": "0.1.0", "LSMinimumSystemVersion": "12.0",
                     "NSHighResolutionCapable": True,
                     # no Info.plist key exists for Screen Recording / Accessibility: macOS prompts by API call (permissions.py)
                     "NSAppleEventsUsageDescription": "Admeasy opens and controls apps on your Mac when you ask it from your phone.",
                     "NSDesktopFolderUsageDescription": "Admeasy reads and saves files in your Desktop folder when you ask.",
                     "NSDocumentsFolderUsageDescription": "Admeasy reads and saves files in your Documents folder when you ask.",
                     "NSDownloadsFolderUsageDescription": "Admeasy reads and saves files in your Downloads folder when you ask.",
                 })
