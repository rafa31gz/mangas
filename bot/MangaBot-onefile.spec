# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

datas = []
binaries = []
hiddenimports = []

# Paquetes con recursos/hook
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('telegram')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Incluir navegadores de Playwright del perfil actual dentro del EXE
local_ms = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ms-playwright')
if local_ms and os.path.isdir(local_ms):
    datas.append((local_ms, 'ms-playwright'))

a = Analysis(
    ['telegram_bot.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['packaging.licenses', 'setuptools._vendor.packaging.licenses'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MangaBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
)
