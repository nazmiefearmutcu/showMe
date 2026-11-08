"""YAML config readers must decode UTF-8, not the platform locale (XCUT-LOCALE, LOC-3).

On Windows with a Turkish locale, ``open()`` and ``Path.read_text()`` default to
cp1254. A Turkish value saved as UTF-8 (``Ş`` = C5 9E) then either raises
UnicodeDecodeError or decodes to mojibake. The readers must pass an explicit
encoding. ``utf-8-sig`` also accepts a BOM that Notepad may write.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from showme.engine.control import config_watcher
from showme.engine.services import function_factory as function_factory_module

LABEL = "Şirket Ğ ş İ"


def _minimal_config_text(extra: str) -> str:
    return (
        "mode: paper\n"
        "timeframe: 1h\n"
        "active_symbol_path: data/symbols.yaml\n"
        "risk:\n"
        "  risk_per_trade: 0.01\n"
        "  stop_loss_pct: 2.0\n"
        "  take_profit_pct: 4.0\n"
        "  confidence_threshold: 60\n"
        f"label: \"{extra}\"\n"
    )


def _write_utf8(path: Path, text: str, *, bom: bool = False) -> Path:
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return path


def test_load_config_decodes_utf8_turkish_values(tmp_path: Path) -> None:
    path = _write_utf8(tmp_path / "default.yaml", _minimal_config_text(LABEL))
    config: dict[str, Any] = config_watcher.load_config(str(path))
    assert config["label"] == LABEL


def test_load_config_accepts_a_utf8_bom_written_by_notepad(tmp_path: Path) -> None:
    path = _write_utf8(tmp_path / "default.yaml", _minimal_config_text(LABEL), bom=True)
    config: dict[str, Any] = config_watcher.load_config(str(path))
    assert config["mode"] == "paper"
    assert config["label"] == LABEL


def test_config_watcher_reload_decodes_utf8(tmp_path: Path) -> None:
    path = _write_utf8(tmp_path / "default.yaml", _minimal_config_text(LABEL))
    watcher = config_watcher.ConfigWatcher(str(path))
    watcher.load()
    assert watcher.config["label"] == LABEL


def test_function_factory_reads_utf8_data_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Adapter construction is network-free but heavy; only the config read is under test.
    monkeypatch.setattr(function_factory_module.FunctionFactory, "_build", lambda self: None)
    path = tmp_path / "data_sources.yaml"
    path.write_bytes(f"label: \"{LABEL}\"\n".encode("utf-8"))
    factory = function_factory_module.FunctionFactory(config_path=path)
    assert factory.config["label"] == LABEL
