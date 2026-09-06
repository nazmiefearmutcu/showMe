"""Regression tests for bot_service money-risk guards (campaign A3).

Covers, with fake collaborators (offline, no Binance, no threads):
- F1: SL/TP hit on a NON-ACTIVE position builds a CLOSE_* decision and calls
  execution_engine.execute (old code was warning-only).
- F2: cumulative auto-select refuses to switch symbols while the outgoing
  symbol still has an open position.
- F3: config hot-reload refuses mode/market_type changes while positions are
  open; accepted changes refresh ExecutionEngine mode/fee IN PLACE (paper
  balance preserved) and re-initialise BinanceClient; failed re-init reverts.
- F4: manual close command files are deleted only after a terminal outcome;
  a missing ticker price skips the cycle instead of pricing at entry_price.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.engine.services import bot_service as bs  # noqa: E402
from showme.engine.services.bot_service import BotService  # noqa: E402


class _Side:
    def __init__(self, value: str) -> None:
        self.value = value


class _Pos:
    def __init__(self, side: str = "LONG", qty: float = 2.0, entry: float = 100.0,
                 lev: int = 5) -> None:
        self.side = _Side(side)
        self.quantity = qty
        self.entry_price = entry
        self.leverage = lev
        self.warning: str | None = None


class _PM:
    def __init__(self, positions: dict[str, _Pos] | None = None) -> None:
        self.positions = positions or {}
        self.total_realized_pnl = 0.0
        self.trade_history: list = []
        self.config: dict = {}
        self.risk_config: dict = {}

    def get_position(self, sym):
        return self.positions.get(sym)

    def get_positions_dict(self):
        return {k: {"x": 1} for k in self.positions}


class _EE:
    def __init__(self, result=None) -> None:
        self.calls: list[dict] = []
        self.paper_balance = 4242.0
        self.mode = "paper"
        self.paper_config: dict = {}
        self.paper_fee_pct = 0.001
        self.config: dict = {}
        self.result = result or {"executed": True, "pnl": -50.0}

    def execute(self, decision):
        self.calls.append(decision)
        return self.result


class _Store:
    def __init__(self) -> None:
        self.state: dict = {"daily_pnl": 0.0}

    def get(self, key, default=None):
        return self.state.get(key, default)

    def update(self, **kw):
        self.state.update(kw)


class _Client:
    def __init__(self, prices: dict[str, float] | None = None) -> None:
        self.prices = prices or {}
        self.mode = "paper"
        self.market_type = "spot"
        self.init_calls = 0

    def get_ticker_price(self, sym):
        return self.prices.get(sym)

    def initialize(self):
        self.init_calls += 1


def _svc(tmp_path, monkeypatch) -> BotService:
    """A BotService skeleton without __init__ (only attributes under test)."""
    monkeypatch.chdir(tmp_path)
    svc = BotService.__new__(BotService)
    svc._auto_scan_interval = 600
    svc.market_cache = None
    svc.market_store = None
    return svc


# ── F1 ───────────────────────────────────────────────────────────────────
def test_f1_non_active_exit_reason_auto_closes(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch)
    pm = _PM({"XYZ": _Pos("LONG", qty=2.0, entry=100.0, lev=5)})
    ee = _EE()
    svc.position_manager = pm
    svc.execution_engine = ee
    svc.state_store = _Store()

    svc._auto_close_non_active("XYZ", pm.positions["XYZ"], 90.0, "stop_loss")

    assert len(ee.calls) == 1
    decision = ee.calls[0]
    assert decision["action"] == "CLOSE_LONG"
    assert decision["symbol"] == "XYZ"
    assert decision["price"] == 90.0
    assert decision["quantity"] == 2.0
    assert decision["leverage"] == 5
    assert "stop_loss" in decision["reason"]
    assert svc.state_store.state["daily_pnl"] == pytest.approx(-50.0)


def test_f1_non_active_short_closes_short_and_failure_is_logged(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch)
    pm = _PM({"XYZ": _Pos("SHORT")})
    ee = _EE(result={"executed": False, "reason": "Futures short not yet enabled"})
    svc.position_manager = pm
    svc.execution_engine = ee
    svc.state_store = _Store()

    svc._auto_close_non_active("XYZ", pm.positions["XYZ"], 90.0, "stop_loss")
    assert ee.calls[0]["action"] == "CLOSE_SHORT"
    assert svc.state_store.state["daily_pnl"] == pytest.approx(0.0)

    class _Boom:
        def execute(self, decision):
            raise RuntimeError("wire down")

    svc.execution_engine = _Boom()
    svc._auto_close_non_active("XYZ", pm.positions["XYZ"], 90.0, "stop_loss")  # must not raise


# ── F2 ───────────────────────────────────────────────────────────────────
class _SH:
    def append(self, *a, **k):
        pass

    def cumulative_ranking(self, top_n=None):
        return [{
            "symbol": "NEWSYM", "dominant_dir": "BUY", "total_score": 10.0,
            "appearances": 1, "max_appearances": 1, "avg_score": 10.0,
            "best_conf": 90,
        }]

    def saturation(self):
        return {"filled": 1, "max": 10}


class _SymbolCtrl:
    def __init__(self, sym):
        self.sym = sym

    def get_current_symbol(self):
        return self.sym


@pytest.fixture()
def scan_svc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    svc = BotService.__new__(BotService)
    svc._auto_scan_interval = 600
    svc.market_cache = None
    svc.market_store = None
    svc.symbol_controller = _SymbolCtrl("OLDSYM")
    svc._multi_tfs = ["1h"]
    svc._ZAK = {"1h": 50}
    svc._multi_scan_results = {}
    svc._multi_scan_full = {}
    svc.scan_history = _SH()
    svc.state_store = _Store()
    svc._last_scan_event_id = 0
    svc._last_scan_event_meta = {}
    svc.config = {"_config_path": str(tmp_path / "nope.yaml"),
                  "dashboard_status_path": str(tmp_path / "ds.json")}
    svc._last_auto_scan_time = 0.0
    svc._scanning_active = False

    written = {}

    class _FakeScanner:
        def __init__(self, *a, **k):
            pass

        def set_active_symbol(self, s):
            written["symbol"] = s
            return True

    monkeypatch.setattr(bs, "ScannerService", _FakeScanner)
    monkeypatch.setattr(bs, "runtime_path", lambda p: tmp_path / "no_such_flag")
    yield svc, written


def test_f2_auto_select_blocked_with_open_position(scan_svc, tmp_path):
    svc, written = scan_svc
    svc.position_manager = _PM({"OLDSYM": _Pos()})

    svc._process_multi_scan_results(tmp_path / "active_symbol.txt")

    assert "symbol" not in written, "switch must be blocked while position open"
    assert svc.symbol_controller.sym == "OLDSYM"


def test_f2_auto_select_proceeds_when_flat(scan_svc, tmp_path):
    svc, written = scan_svc
    svc.position_manager = _PM({})

    svc._process_multi_scan_results(tmp_path / "active_symbol.txt")

    assert written.get("symbol") == "NEWSYM"


# ── F3 ───────────────────────────────────────────────────────────────────
@pytest.fixture()
def reload_svc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("SignalService", "ConsensusEngine", "LeverageManager",
                 "DecisionEngine", "MarketDataProvider"):
        monkeypatch.setattr(
            bs, name,
            type("F" + name, (), {"__init__": lambda self, *a, **k: None}),
        )
    svc = BotService.__new__(BotService)
    svc._auto_scan_interval = 600
    svc.market_cache = None
    svc.market_store = None
    svc.config = {"mode": "paper", "market_type": "spot", "timeframe": "1h",
                  "polling_interval_seconds": 60, "risk": {},
                  "paper": {"fee_pct": 0.0005}}
    svc.binance_client = _Client()
    svc.position_manager = _PM()
    svc.execution_engine = _EE()
    return svc


def test_f3_accepted_mode_change_refreshes_engine_in_place(reload_svc):
    svc = reload_svc
    svc._apply_config({"mode": "live", "market_type": "spot", "timeframe": "1h",
                       "polling_interval_seconds": 60, "risk": {},
                       "paper": {"fee_pct": 0.0005}})
    assert svc.binance_client.mode == "live"
    assert svc.binance_client.init_calls == 1
    assert svc.execution_engine.mode == "live"
    assert svc.execution_engine.paper_fee_pct == pytest.approx(0.0005)
    assert svc.execution_engine.paper_balance == pytest.approx(4242.0)  # preserved
    assert svc.position_manager.config["mode"] == "live"


def test_f3_refuses_mode_change_with_open_positions(reload_svc):
    svc = reload_svc
    # Simulate the stale-engine state the fix guards against: the config file
    # (and svc.config) say paper/spot while engine + client actually run live.
    svc.position_manager = _PM({"BTCUSDT": _Pos()})
    svc.config["mode"] = "live"  # UI-facing config already live/spot
    svc.binance_client.mode = "live"
    svc.execution_engine.mode = "live"

    svc._apply_config({"mode": "paper", "market_type": "futures",
                       "timeframe": "1h", "polling_interval_seconds": 60,
                       "risk": {}, "paper": {"fee_pct": 0.0005}})

    assert svc.binance_client.mode == "live"
    assert svc.binance_client.market_type == "spot"
    assert svc.execution_engine.mode == "live"
    assert svc.config["mode"] == "live"
    assert svc.config["market_type"] == "spot"


def test_f3_failed_reinit_reverts_mode(reload_svc):
    svc = reload_svc

    class _Fail(_Client):
        def initialize(self):
            raise RuntimeError("keys missing")

    svc.binance_client = _Fail()

    svc._apply_config({"mode": "live", "market_type": "spot", "timeframe": "1h",
                       "polling_interval_seconds": 60, "risk": {},
                       "paper": {"fee_pct": 0.0005}})

    assert svc.binance_client.mode == "paper"
    assert svc.execution_engine.mode == "paper"
    assert svc.config["mode"] == "paper"


# ── F4 ───────────────────────────────────────────────────────────────────
def test_f4_close_command_deleted_only_after_success(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    cmd = runtime / "close_cmd_t.json"
    cmd.write_text(json.dumps({"symbol": "ABC"}))

    svc.position_manager = _PM({"ABC": _Pos(entry=999.0)})
    ee = _EE()
    svc.execution_engine = ee
    svc.state_store = _Store()
    svc.binance_client = _Client({"ABC": 90.0})

    svc._process_close_commands()

    assert not cmd.exists(), "successful close is terminal → delete"
    assert ee.calls[0]["price"] == 90.0


def test_f4_no_ticker_price_skips_and_keeps_command(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    cmd = runtime / "close_cmd_t.json"
    cmd.write_text(json.dumps({"symbol": "ABC"}))

    svc.position_manager = _PM({"ABC": _Pos(entry=999.0)})
    ee = _EE()
    svc.execution_engine = ee
    svc.state_store = _Store()
    svc.binance_client = _Client({})  # ticker unavailable

    svc._process_close_commands()

    assert cmd.exists(), "command must be kept for retry"
    assert ee.calls == [], "must not fabricate an entry-price close"


def test_f4_failed_execution_keeps_command(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    cmd = runtime / "close_cmd_t.json"
    cmd.write_text(json.dumps({"symbol": "ABC"}))

    svc.position_manager = _PM({"ABC": _Pos()})
    svc.execution_engine = _EE(result={"executed": False, "reason": "refused"})
    svc.state_store = _Store()
    svc.binance_client = _Client({"ABC": 90.0})

    svc._process_close_commands()
    assert cmd.exists()

    # position gone → terminal, file removed
    svc.position_manager = _PM({})
    svc.execution_engine = _EE()
    svc._process_close_commands()
    assert not cmd.exists()
