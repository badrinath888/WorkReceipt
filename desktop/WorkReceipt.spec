# PyInstaller spec. Build with desktop/build_macos.sh (macOS). Version comes from app_core.VERSION: single source of truth.
import os, sys
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
import app_core

a = Analysis([os.path.join(ROOT, "desktop", "main.py")], pathex=[ROOT],
             datas=[(os.path.join(ROOT, "ui"), "ui"), (os.path.join(ROOT, "examples", "make_demo_workspace.py"), "examples")],
             hiddenimports=["webview.platforms.cocoa", "PyObjCTools.AppHelper"], excludes=["tkinter", "unittest", "test"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="WorkReceipt", console=False, argv_emulation=False,
          target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name="WorkReceipt")
app = BUNDLE(coll, name="WorkReceipt.app", icon=os.path.join(ROOT, "desktop", "icon", "WorkReceipt.icns"), bundle_identifier="app.workreceipt.desktop",
             version=app_core.VERSION,
             info_plist={"CFBundleName": "WorkReceipt", "CFBundleDisplayName": "WorkReceipt", "CFBundleShortVersionString": app_core.VERSION,
                         "CFBundleVersion": app_core.VERSION, "LSMinimumSystemVersion": "11.0", "NSHighResolutionCapable": True,
                         "LSApplicationCategoryType": "public.app-category.productivity",
                         "NSHumanReadableCopyright": "Local-first. Your data never leaves this computer.",
                         "NSDesktopFolderUsageDescription": "WorkReceipt reads the project folders you choose.",
                         "NSDocumentsFolderUsageDescription": "WorkReceipt reads project folders you choose and saves exported reports.",
                         "NSDownloadsFolderUsageDescription": "WorkReceipt reads project folders you choose."})
