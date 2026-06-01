# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


def data_path(*parts):
    return os.path.join(*parts)


datas = [
    ("logo.png", "."),
    (data_path("backend", "*.py"), "backend"),
    (data_path("backend", "routers", "*.py"), data_path("backend", "routers")),
    (data_path("frontend", "dist"), data_path("frontend", "dist")),
]
binaries = []
hiddenimports = ["main", "tgcrypto"]

for package_name in (
    "fastapi",
    "uvicorn",
    "pyrogram",
    "sqlalchemy",
    "apscheduler",
    "pydantic",
    "qrcode",
    "webview",
    "pystray",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

datas += copy_metadata("apscheduler")
hiddenimports += collect_submodules("pystray")


a = Analysis(
    ["desktop_app.py"],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyinstaller_runtime_hook.py"],
    excludes=["winotify"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SchoolManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SchoolManager",
)

app = BUNDLE(
    coll,
    name="SchoolManager.app",
    icon=None,
    bundle_identifier="com.schoolmanager.app",
    info_plist={
        "CFBundleName": "School Manager",
        "CFBundleDisplayName": "School Manager",
        "CFBundleShortVersionString": "2.1",
        "CFBundleVersion": "2.1.0",
        "NSHighResolutionCapable": "True",
    },
)
