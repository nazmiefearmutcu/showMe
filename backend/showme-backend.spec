# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for showMe sidecar (post-unification).

After the structural refactor the engine is a regular Python subpackage
(``showme.engine``) so we no longer need a stand-alone ``src/`` data folder.
We just bundle the engine config sibling and let PyInstaller collect every
``showme.*`` submodule via ``collect_submodules``.

Paths are resolved relative to this spec file so the build works from any
checkout location.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH).resolve()
PROJECT_ROOT = HERE.parent

datas = [
    (str(HERE / "config"), "config"),
    # showme.engine ships a sibling YAML config we ship verbatim
    (str(HERE / "showme" / "engine"), "showme/engine"),
]

# Optional veryfinder integration (only if checked out as a sibling project)
veryfinder_root = PROJECT_ROOT.parent / "veryfinder"
if (veryfinder_root / "veryfinder").is_dir():
    datas.append((str(veryfinder_root / "veryfinder"), "integrations/veryfinder/veryfinder"))
if (veryfinder_root / "data").is_dir():
    datas.append((str(veryfinder_root / "data"), "integrations/veryfinder/data"))

hiddenimports = [
    "feedparser",
    "lxml",
    "sgmllib",
    "uvicorn.logging",
    "uvicorn.protocols",
    "uvicorn.lifespan.on",
]
datas += collect_data_files("yfinance")
hiddenimports += collect_submodules("showme")
hiddenimports += collect_submodules("yfinance")
hiddenimports += collect_submodules("lxml")


a = Analysis(
    ["showme/server.py"],
    pathex=[str(HERE)],
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
    name="showme-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
