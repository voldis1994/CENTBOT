# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CENTBOT.exe — run via BUILD_EXE.bat on Windows

block_cipher = None

a = Analysis(
    ['centbot/windows/exe_entry.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('centbot/dashboard/panel.html', 'centbot/dashboard'),
        ('config/default.yaml', 'config'),
        ('config/local.yaml.example', 'config'),
        ('requirements.txt', '.'),
    ],
    hiddenimports=[
        'yaml',
        'flask',
        'requests',
        'psutil',
        'nacl',
        'eth_account',
        'centbot',
        'centbot.__main__',
        'centbot.dashboard.app',
        'centbot.dashboard.portutil',
        'centbot.windows.launcher',
        'centbot.windows.setup',
        'centbot.windows.wizard',
        'centbot.core.engine',
    ],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CENTBOT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
