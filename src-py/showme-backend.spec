# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('/Users/nazmi/Desktop/Projeler/proje/showMe/engine/src', 'src'), ('/Users/nazmi/Desktop/Projeler/proje/showMe/engine/config', 'config')]
hiddenimports = ['feedparser', 'lxml', 'sgmllib', 'uvicorn.logging', 'uvicorn.protocols', 'uvicorn.lifespan.on']
datas += collect_data_files('yfinance')
hiddenimports += collect_submodules('src')
hiddenimports += collect_submodules('yfinance')
hiddenimports += collect_submodules('lxml')


a = Analysis(
    ['showme/server.py'],
    pathex=['/Users/nazmi/Desktop/Projeler/proje/showMe/engine'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='showme-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)
