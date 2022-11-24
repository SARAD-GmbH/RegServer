# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ("*.bat", "."),
    ("network.ico", "."),
    ("eula.txt", "."),
    ("*.toml", "."),
    ("*.ps1", "."),
]
binaries = []
hiddenimports = [
    "thespian.system.multiprocTCPBase",
    "thespian.system.multiprocUDPBase",
    "thespian.system.multiprocQueueBase",
    "win32timezone",
]
tmp_ret = collect_all("sarad")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]


block_cipher = None


a = Analysis(
    ["regserver-service.py"],
    pathex=["D:\\Projekte\\RegServer\\src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="regserver-service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="regserver-service",
)
