# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for showMe sidecar — onedir build (PERF-06 R3A).

After the structural refactor the engine is a regular Python subpackage
(``showme.engine``) so we no longer need a stand-alone ``src/`` data folder.
We bundle:

* the engine config sibling
* every ``showme.*`` submodule (collected dynamically)
* the trained ``showme_x_v1`` X Sentiment model (~491 MB) so the .app is
  fully self-contained
* the heavy ML wheels we depend on at runtime (torch, transformers,
  tokenizers) including their data files

Build layout (PERF-06 R3A migration):
* This spec emits a **onedir** bundle (``dist/showme-backend/``) rather
  than the legacy 656 MB onefile binary. The launcher executable is
  ``dist/showme-backend/showme-backend``; the rest of the directory
  contains the Python runtime, dependency wheels, and the
  ``showme_x_v1`` X-Sentiment model. The Tauri shell mounts the
  directory under ``tauri/binaries/showme-backend{,-aarch64-apple-darwin}``
  and resolves the executable inside it via ``externalBin``.
* Cold start drops from ≈7 s (onefile, ``/tmp/_MEI…`` re-extraction on
  every launch) to under 5 s because the runtime is already laid out
  on disk.
* ``upx=False`` per TEST-08 P3 — UPX-compressed Mach-O binaries trip
  Gatekeeper's hardened-runtime check.

Paths are resolved relative to this spec file so the build works from any
checkout location.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH).resolve()
PROJECT_ROOT = HERE.parent

datas = [
    (str(HERE / "config"), "config"),
    (str(HERE / "showme" / "engine"), "showme/engine"),
    # Sub-system A (multi-exchange portfolio foundation):
    # the catalog YAML is loaded at runtime via
    # ``Path(__file__).parent / "catalog" / "exchanges.yml"`` inside
    # ``showme.brokers.factory._default_catalog_path()``. PyInstaller bakes
    # Python source into the PYZ archive but raw data files must be added
    # to ``datas`` explicitly so they remain on disk next to the (extracted)
    # ``showme/brokers/catalog/`` directory.
    (
        str(HERE / "showme" / "brokers" / "catalog" / "exchanges.yml"),
        "showme/brokers/catalog",
    ),
    # Sub-system F (indicator depot):
    # Same pattern as exchanges.yml above — ``IndicatorCatalog.load`` reads
    # ``Path(__file__).parent / "catalog" / "indicators.yml"`` at runtime.
    # PyInstaller bakes Python source into the PYZ but raw YAML must be
    # added to ``datas`` explicitly.
    (
        str(HERE / "showme" / "indicators" / "catalog" / "indicators.yml"),
        "showme/indicators/catalog",
    ),
    # Sub-system G (template bot library):
    # Same pattern as indicators.yml above — ``TemplateCatalog.load`` reads
    # ``Path(__file__).parent / "catalog" / "templates.yml"`` at runtime.
    # PyInstaller bakes Python source into the PYZ but raw YAML must be
    # added to ``datas`` explicitly.
    (
        str(HERE / "showme" / "templates" / "catalog" / "templates.yml"),
        "showme/templates/catalog",
    ),
]

# X Sentiment AI model — embedded so the .app boots offline.
x_model_root = PROJECT_ROOT / "x_scraper_ai" / "model" / "showme_x_v1"
if x_model_root.is_dir():
    datas.append((str(x_model_root), "showme/data/x_model/showme_x_v1"))
else:
    print(f"warning: x_scraper_ai model not found at {x_model_root}; XAnalyzer will fail to load")

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
    "transformers",
    "transformers.models.roberta",
    "transformers.models.roberta.modeling_roberta",
    "transformers.models.roberta.tokenization_roberta_fast",
    "tokenizers",
    "safetensors",
    "safetensors.torch",
    "torch",
    "torch._C",
    "regex",
    "sentencepiece",
    # Sub-system A (multi-exchange portfolio foundation):
    "ccxt.async_support",
    "ccxt.base.exchange",
    "keyring.backends.macOS",
    "keyring.backends.fail",
    "keyring.backends.null",
]
datas += collect_data_files("yfinance")
datas += collect_data_files("transformers", include_py_files=False)
datas += collect_data_files("tokenizers")
hiddenimports += collect_submodules("showme")
hiddenimports += collect_submodules("yfinance")
hiddenimports += collect_submodules("lxml")
# Pull every transformers model family — AutoModel/AutoTokenizer touch the
# auto registry which imports each model package on lookup. Trimming this
# breaks at runtime even when the head model is RoBERTa-only.
hiddenimports += collect_submodules("transformers")
hiddenimports += collect_submodules("tokenizers")
# ccxt ships 386 vendored Python crypto libs (ecdsa, ethereum, msgpack, ...)
# under `ccxt/static_dependencies/` that are imported at runtime via
# `from ccxt.static_dependencies import X`. collect_submodules registers
# them as importable Python in the frozen PYZ; the datas.append below is
# belt-and-braces in case ccxt adds non-Python resources in a future
# release.
hiddenimports += collect_submodules("ccxt")

import importlib.util as _ilu  # noqa: E402

_ccxt_spec = _ilu.find_spec("ccxt")
if _ccxt_spec is not None and _ccxt_spec.origin:
    datas.append(
        (
            str(Path(_ccxt_spec.origin).resolve().parent / "static_dependencies"),
            "ccxt/static_dependencies",
        )
    )
del _ilu, _ccxt_spec


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

# PERF-06 R3A onedir migration:
# The EXE() block now only carries the bootstrap launcher (`a.scripts` +
# the empty argv shim). Binaries, zipfiles, and data files are emitted by
# the COLLECT() block below into ``dist/showme-backend/``. PyInstaller
# automatically wires the launcher to load everything from its parent
# directory, so cold start no longer pays for an unzip into ``/tmp``.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="showme-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="showme-backend",
)
