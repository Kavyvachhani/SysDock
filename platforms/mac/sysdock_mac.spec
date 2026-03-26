# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# We assume this is run from the project root!
root_dir = os.path.abspath(os.getcwd())
gui_path = os.path.join(root_dir, 'platforms', 'mac', 'src', 'gui.py')
icon_path = os.path.join(root_dir, 'platforms', 'mac', 'SysDock.icns')

a = Analysis(
    [gui_path],
    pathex=[root_dir],
    binaries=[],
    datas=[],
    hiddenimports=['sysdock', 'bottle', 'webview', 'rich', 'psutil'],
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
    name='SysDock',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SysDock',
)

app = BUNDLE(
    coll,
    name='SysDock.app',
    icon=icon_path,
    bundle_identifier='io.sysdock.app',
    info_plist={
        'CFBundleName': 'SysDock',
        'CFBundleDisplayName': 'SysDock',
        'CFBundleGetInfoString': 'SysDock Monitoring Agent',
        'CFBundleIdentifier': 'io.sysdock.app',
        'CFBundleVersion': '1.4.6',
        'CFBundleShortVersionString': '1.4.6',
        'NSHighResolutionCapable': True,
        'LSUIElement': False,
    },
)
