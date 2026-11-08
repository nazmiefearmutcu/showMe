"""LOC-3-RQ — bot_service reads its YAML config as UTF-8 (with BOM tolerance).

The dashboard writes the config as UTF-8, sometimes with a BOM and Turkish
characters (Ş, Ğ, İ, ı). A read that uses the locale codec mis-decodes the BOM
(``ï»¿``) so the first key is no longer ``auto_scan_enabled`` and the dashboard
toggle is silently ignored.

Two read sites must honour the file:
  * ``_auto_scan_market`` (bot_service ~903): ``auto_scan_enabled``;
  * ``_process_multi_scan_results`` (bot_service ~1283): ``auto_select_enabled``.

The pytest host locale is not guaranteed to be UTF-8 (this Windows host is
cp1254), so every test here replaces ``Path.read_text`` with a reader whose
default codec is latin-1: a single-byte codec that decodes every byte, so the
BOM is mis-decoded to ``ï»¿`` the same way on any host. A read site that passes
``encoding`` explicitly is unaffected; one that relies on the locale codec
mis-decodes the BOM and fails.
Offline: no threads, no exchange, no scan is started.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.services import bot_service as bot_module  # noqa: E402
from showme.engine.services.bot_service import BotService  # noqa: E402

_REAL_READ_TEXT = Path.read_text

_YAML_TEXT = (
    "# Şişli Ğ İ ı ö ü — Turkish comment\n"
    "display_name: \"Ş Ğ İ ı\"\n"
    "auto_scan_enabled: false\n"
    "auto_select_enabled: false\n"
)


@pytest.fixture
def locale_cp1254(monkeypatch):
    """Simulate a non-UTF-8 locale: a read with no explicit encoding uses latin-1."""

    def _read_text(self, encoding=None, errors=None):
        return _REAL_READ_TEXT(self, encoding=encoding or "latin-1", errors=errors)

    monkeypatch.setattr(Path, "read_text", _read_text)


def _service_for(config_path: Path, **overrides: Any) -> BotService:
    svc = BotService.__new__(BotService)  # skip __init__: no exchange clients
    svc.config = {"_config_path": str(config_path), "auto_scan_enabled": True,
                  "auto_select_enabled": True, **overrides}
    return svc


def _bom_file(tmp_path: Path, text: str = _YAML_TEXT) -> Path:
    cfg = tmp_path / "default.yaml"
    cfg.write_bytes(text.encode("utf-8-sig"))  # BOM-prefixed UTF-8
    return cfg


def test_locale_simulation_really_mojibakes_the_bom(tmp_path, locale_cp1254) -> None:
    """Control: without utf-8-sig the first key is no longer auto_scan_enabled."""
    cfg = _bom_file(tmp_path)
    assert cfg.read_text().startswith("ï»¿"), "the simulated locale read must mis-decode the BOM"


def test_auto_scan_reads_bom_utf8_config_and_honours_disable(tmp_path, monkeypatch, locale_cp1254) -> None:
    monkeypatch.chdir(tmp_path)  # no runtime/auto_scan_disabled flag here
    svc = _service_for(_bom_file(tmp_path))
    # auto_scan_enabled is false in the file: the method must return before
    # touching any scan state. A mis-decoded read falls back to the in-memory
    # True and proceeds, which raises here because the scan state is absent.
    assert svc._auto_scan_market() is None


def test_auto_scan_turkish_only_file_is_read_as_utf8(tmp_path, monkeypatch, locale_cp1254) -> None:
    """A Turkish file without a BOM is read as UTF-8 and its disable is honoured."""
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "default.yaml"
    cfg.write_bytes(_YAML_TEXT.encode("utf-8"))
    svc = _service_for(cfg)
    assert svc._auto_scan_market() is None


class _Recorder:
    """Stands in for the symbol controller: records that auto-select reached it."""

    def __init__(self, current: str) -> None:
        self.calls: list[str] = []
        self._current = current

    def get_current_symbol(self) -> str:
        self.calls.append("get_current_symbol")
        return self._current


class _NoPositions:
    def get_position(self, symbol: str) -> None:
        return None


class _ScanHistory:
    def append(self, results: Any, timestamp: str | None = None) -> None:
        return None

    def cumulative_ranking(self, top_n: int = 10) -> list[dict[str, Any]]:
        return [{"symbol": "ETHUSDT", "dominant_dir": "BUY", "total_score": 10.0,
                 "appearances": 1, "max_appearances": 1, "avg_score": 5.0, "best_conf": 60}]

    def saturation(self) -> dict[str, int]:
        return {"filled": 1, "max": 10}


class _StateStore:
    def update(self, **kwargs: Any) -> None:
        return None


def _multi_scan_service(tmp_path: Path, config_path: Path, recorder: _Recorder) -> BotService:
    """A bare instance with exactly the attributes _process_multi_scan_results reads."""
    svc = _service_for(config_path, dashboard_status_path=str(tmp_path / "dashboard_status.json"))
    row = {"symbol": "ETHUSDT", "confidence": 70, "signal": "BUY", "price": 1.0}
    svc._multi_tfs = ["15m"]
    svc._ZAK = {"15m": 50}
    svc._multi_scan_results = {"15m": [row]}
    svc._multi_scan_full = {"15m": [row]}
    svc._last_scan_event_id = 0
    svc._last_scan_event_meta = {}
    svc._last_auto_scan_time = 0.0
    svc._scanning_active = True
    svc._scan_started_monotonic = None
    svc.scan_history = _ScanHistory()
    svc.state_store = _StateStore()
    svc.symbol_controller = recorder
    svc.position_manager = _NoPositions()
    return svc


def test_multi_scan_auto_select_honours_bom_disable(tmp_path, monkeypatch, locale_cp1254) -> None:
    """Second read site: auto_select_enabled false in a BOM file must skip auto-select."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bot_module, "runtime_path", lambda name: tmp_path / "runtime" / name)
    recorder = _Recorder(current="BTCUSDT")
    svc = _multi_scan_service(tmp_path, _bom_file(tmp_path), recorder)
    svc._process_multi_scan_results(tmp_path / "symbols.txt")
    assert recorder.calls == [], "auto-select ran although the YAML disables it"


def test_multi_scan_auto_select_runs_when_yaml_enables_it(tmp_path, monkeypatch, locale_cp1254) -> None:
    """Positive control: the same path reaches the controller when the file enables it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bot_module, "runtime_path", lambda name: tmp_path / "runtime" / name)
    enabled = _YAML_TEXT.replace("auto_select_enabled: false", "auto_select_enabled: true")
    recorder = _Recorder(current="BTCUSDT")
    svc = _multi_scan_service(tmp_path, _bom_file(tmp_path, enabled), recorder)
    svc._process_multi_scan_results(tmp_path / "symbols.txt")
    assert recorder.calls == ["get_current_symbol"]
