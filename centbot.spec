# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CENTBOT.exe — run via BUILD_EXE.bat on Windows

block_cipher = None

try:
    from PyInstaller.utils.hooks import collect_data_files

    certifi_datas = collect_data_files("certifi")
except Exception:
    certifi_datas = []

a = Analysis(
    ['centbot/windows/exe_entry.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('centbot/dashboard/panel.html', 'centbot/dashboard'),
        ('config/default.yaml', 'config'),
        ('config/local.yaml.example', 'config'),
        ('requirements.txt', '.'),
    ] + certifi_datas,
    hiddenimports=[
        'yaml',
        'flask',
        'requests',
        'certifi',
        'psutil',
        'nacl',
        'eth_account',
        'centbot',
        'centbot.__main__',
        'centbot.runtime_paths',
        'centbot.dashboard.app',
        'centbot.dashboard.portutil',
        'centbot.windows.launcher',
        'centbot.windows.setup',
        'centbot.windows.wizard',
        'centbot.core.engine',
        'centbot.core.config',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['centbot/windows/pyi_rth_centbot.py'],
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
