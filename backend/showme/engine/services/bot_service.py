"""Bot service - main orchestration loop tying all components together."""

import asyncio
import time
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from showme.engine.api.binance_client import BinanceClient
from showme.engine.data.market_data import MarketDataProvider
from showme.engine.services.signal_service import SignalService
from showme.engine.services.scanner_service import ScannerService
from showme.engine.consensus.engine import ConsensusEngine
from showme.engine.trading.decision_engine import DecisionEngine
from showme.engine.trading.execution_engine import ExecutionEngine
from showme.engine.trading.leverage_manager import LeverageManager
from showme.engine.trading.order_models import TradeAction
from showme.engine.trading.position_manager import PositionManager
from showme.engine.control.symbol_controller import SymbolController
from showme.engine.control.config_watcher import ConfigWatcher
from showme.engine.persistence.state_store import StateStore
from showme.engine.persistence.scan_history import ScanHistoryStore
from showme.engine.monitoring.status_exporter import StatusExporter
from showme.engine.utils.logger import get_logger
from showme.engine.utils.helpers import iso_now

logger = get_logger("services.bot_service")


class BotService:
    """Main bot orchestrator - runs the continuous trading loop."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.running = False

        # Initialize components
        self.binance_client = BinanceClient(config)

        # ── Data pipeline (optional — feature-flagged) ──
        self.market_cache: Optional[Any] = None
        self.market_store: Optional[Any] = None
        self.ws_manager: Optional[Any] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        dp_cfg = config.get("data_pipeline", {}) or {}
        if dp_cfg.get("use_ws_cache", False):
            try:
                from showme.engine.data.market_cache import MarketCache
                from showme.engine.data.market_store import MarketStore
                self.market_cache = MarketCache(max_candles=1000, max_trades=10_000)
                self.market_store = MarketStore(
                    db_path=dp_cfg.get("store_path", "runtime/market.db")
                )
                logger.info("Data pipeline (WS cache) enabled")
            except Exception as e:
                logger.error(f"Data pipeline init failed, falling back to REST-only: {e}")
                self.market_cache = None
                self.market_store = None

        self.market_data = MarketDataProvider(
            self.binance_client, config,
            cache=self.market_cache, store=self.market_store,
        )
        self.signal_service = SignalService(
            config, binance_client=self.binance_client,
            cache=self.market_cache, store=self.market_store,
        )
        self.consensus_engine = ConsensusEngine(config)
        self.position_manager = PositionManager(config)
        self.leverage_manager = LeverageManager(config, self.binance_client)
        self.decision_engine = DecisionEngine(config, self.position_manager, self.leverage_manager)
        self.execution_engine = ExecutionEngine(config, self.binance_client, self.position_manager)
        self.symbol_controller = SymbolController(config.get("active_symbol_path", "runtime/active_symbol.txt"))
        self.state_store = StateStore(config.get("state_path", "runtime/state.json"))
        self.scan_history = ScanHistoryStore(
            config.get("scan_history_path", "runtime/scan_history.json")
        )

        # Event counters for dashboard notifications (popup + sound)
        # Bumped on (a) trade execution, (b) auto-scan completion
        self._last_trade_event_id: int = 0
        self._last_scan_event_id: int = 0
        self._last_trade_event_meta: dict[str, Any] = {}
        self._last_scan_event_meta: dict[str, Any] = {}
        self.status_exporter = StatusExporter(config.get("dashboard_status_path", "runtime/dashboard_status.json"))
        config_path = config.get("_config_path", "config/default.yaml")
        self.config_watcher = ConfigWatcher(config_path)
        self.config_watcher.config = config
        # Set mtime to current so we don't reload on first cycle
        try:
            self.config_watcher._last_mtime = Path(config_path).stat().st_mtime
        except Exception:
            self.config_watcher._last_mtime = 0.0

        self.polling_interval = config.get("polling_interval_seconds", 60)
        self._cycle_count = 0

        # Same-candle detection: don't open new positions on unchanged data
        self._last_candle_time: str | None = None
        self._candle_changed = False

        # Per-cycle state for status export
        self._last_indicator_results: list[Any] | None = None
        self._last_consensus: dict[str, Any] | None = None
        self._last_decision: dict[str, Any] | None = None
        self._last_execution: dict[str, Any] | None = None
        self._last_price: float | None = None

        # Auto-scan: multi-TF scan every 10 minutes in background
        self._auto_scan_interval = config.get("auto_scan_interval_seconds", 600)  # 10 min
        self._scanning_active = False  # True while any scan is in progress
        # Restore last scan time from progress file to avoid immediate re-scan on restart
        self._last_auto_scan_time: float = 0.0
        try:
            _prog_path = Path(config.get("dashboard_status_path", "runtime/dashboard_status.json")).parent / "auto_scan_progress.json"
            if _prog_path.exists():
                _prog = json.loads(_prog_path.read_text())
                _last_ts = _prog.get("last_auto_scan") or _prog.get("completed_at") or _prog.get("started_at")
                if _last_ts:
                    from datetime import datetime as _dt, timezone as _tz
                    _parsed = _dt.fromisoformat(_last_ts)
                    _age_secs = (_dt.now(_tz.utc) - _parsed).total_seconds()
                    if _age_secs < self._auto_scan_interval:
                        # Recent scan exists — set timer so we wait the remaining interval
                        self._last_auto_scan_time = time.time() - _age_secs
                        logger.info(f"Restored last scan time: {_last_ts} ({_age_secs:.0f}s ago)")
        except Exception:
            pass
        self._scan_threads: list[threading.Thread] = []
        self._scan_lock = threading.Lock()
        self._multi_scan_done_count = 0
        self._multi_scan_results: dict[str, list] = {}  # tf → top15 results
        self._multi_scan_full: dict[str, list] = {}    # tf → ALL results

        # All 12 timeframes sorted by duration
        _TF_MINUTES = {"m": 1, "h": 60, "d": 1440}
        self._multi_tfs = sorted(
            ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"],
            key=lambda t: int(t[:-1]) * _TF_MINUTES.get(t[-1], 1),
        )

        # ZAK — Zaman Dilimi Ağırlık Katsayısı
        self._ZAK = {
            "1d": 95, "12h": 90, "8h": 85, "6h": 80, "4h": 75,
            "2h": 65, "1h": 58, "30m": 48, "15m": 38, "5m": 25,
            "3m": 15, "1m": 8,
        }

    def initialize(self) -> None:
        """Initialize all components and restore state."""
        # Clean stale manual scan lock from previous runs
        # (auto_scan_progress.json is kept — it has last_auto_scan timestamp)
        try:
            p = Path("runtime/manual_scan_active.json")
            if p.exists():
                p.unlink()
                logger.info("Cleaned stale manual scan lock file")
        except Exception:
            pass
        # Mark any in-progress auto-scan as not-scanning (stale from previous run)
        try:
            p = Path("runtime/auto_scan_progress.json")
            if p.exists():
                _d = json.loads(p.read_text())
                if _d.get("scanning"):
                    _d["scanning"] = False
                    p.write_text(json.dumps(_d, default=str))
                    logger.info("Reset stale auto-scan scanning flag")
        except Exception:
            pass
        logger.info("=" * 60)
        logger.info("Trading Bot Initializing...")
        logger.info(f"Mode: {self.config.get('mode', 'paper')}")
        logger.info(f"Market: {self.config.get('market_type', 'spot')}")
        logger.info(f"Timeframe: {self.config.get('timeframe', '1h')}")
        logger.info("=" * 60)

        # Initialize Binance client
        self.binance_client.initialize()

        # Restore state
        state = self.state_store.load()
        self._restore_state(state)

        # Load initial symbol
        symbol = self.symbol_controller.get_current_symbol()
        if symbol:
            logger.info(f"Active symbol: {symbol}")
        else:
            logger.warning("No valid symbol found, defaulting to BTCUSDT")
            self.symbol_controller.set_symbol("BTCUSDT")

        self.state_store.update(bot_start_time=iso_now())

        # Start WS manager in background thread (if enabled and components exist)
        if self.market_cache is not None and self.market_store is not None:
            self._start_ws_thread()

        logger.info("Bot initialization complete")

    def _start_ws_thread(self) -> None:
        """Spawn an asyncio loop in a daemon thread that runs WSManager.run()."""
        try:
            from showme.engine.data.ws_manager import WSManager
        except Exception as e:
            logger.error(f"Cannot import WSManager: {e}")
            return

        # Determine which symbols to subscribe to
        active = self.symbol_controller.get_current_symbol() or "BTCUSDT"
        dp_cfg = self.config.get("data_pipeline", {}) or {}
        ws_symbols_limit = int(dp_cfg.get("ws_symbols_limit", 200))

        # Start with the active symbol; expand later if scanner identifies hot symbols
        symbols = [active]
        try:
            top = self.binance_client.get_futures_symbols()[:ws_symbols_limit]
            if top:
                symbols = top
        except Exception:
            pass

        self.ws_manager = WSManager(
            symbols=symbols,
            timeframes=self._multi_tfs,
            cache=self.market_cache,
            store=self.market_store,
            rest_client=self.binance_client,
        )

        def _run():
            try:
                self._ws_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._ws_loop)
                self._ws_loop.run_until_complete(self.ws_manager.run())
            except Exception as e:
                logger.error(f"WS thread crashed: {e}")

        self._ws_thread = threading.Thread(target=_run, daemon=True, name="ws-manager")
        self._ws_thread.start()
        logger.info(f"WS manager started ({len(symbols)} symbols × {len(self._multi_tfs)} TFs)")

    def _restore_state(self, state: dict[str, Any]) -> None:
        """Restore bot state from persisted data."""
        # Restore positions
        positions_data = state.get("positions", {})
        if positions_data:
            self.position_manager.load_positions(positions_data)

        # Restore trade history
        history = state.get("trade_history", [])
        if history:
            self.position_manager.load_trade_history(history)

        # Restore paper balance
        paper_balance = state.get("paper_balance", self.config.get("paper", {}).get("starting_balance", 10000.0))
        self.execution_engine.set_paper_balance(paper_balance)

        # Restore PnL tracking
        self.position_manager.total_realized_pnl = state.get("total_realized_pnl", 0.0)

        # Check daily reset
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        saved_date = state.get("daily_date")
        if saved_date != today:
            self.state_store.update(
                daily_pnl=0.0,
                daily_start_balance=paper_balance,
                daily_date=today,
            )
            logger.info(f"New trading day: {today}. Daily PnL reset.")

        logger.info(
            f"State restored | balance={paper_balance:.2f} | "
            f"positions={len(positions_data)} | "
            f"total_pnl={self.position_manager.total_realized_pnl:.4f}"
        )

    def run(self) -> None:
        """Run the main bot loop."""
        self.running = True
        logger.info("Bot loop started")

        while self.running:
            try:
                self._cycle()
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, shutting down...")
                self.running = False
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(5)
                continue

            time.sleep(self.polling_interval)

        self._shutdown()

    def _apply_config(self, new_config: dict[str, Any]) -> None:
        """Apply a new config to all components at runtime."""
        old_tf = self.config.get("timeframe")
        old_interval = self.config.get("polling_interval_seconds")
        self.config = new_config

        # Update polling interval
        self.polling_interval = new_config.get("polling_interval_seconds", 60)
        self._auto_scan_interval = new_config.get("auto_scan_interval_seconds", self._auto_scan_interval)

        # Re-initialize components that depend on config
        self.signal_service = SignalService(
            new_config, binance_client=self.binance_client,
            cache=self.market_cache, store=self.market_store,
        )
        self.consensus_engine = ConsensusEngine(new_config)
        self.leverage_manager = LeverageManager(new_config, self.binance_client)
        # Update position manager's risk config so max_open_positions etc. take effect
        self.position_manager.risk_config = new_config.get("risk", {})
        self.decision_engine = DecisionEngine(new_config, self.position_manager, self.leverage_manager)
        self.market_data = MarketDataProvider(
            self.binance_client, new_config,
            cache=self.market_cache, store=self.market_store,
        )

        changes = []
        if old_tf != new_config.get("timeframe"):
            changes.append(f"timeframe: {old_tf} -> {new_config.get('timeframe')}")
        if old_interval != new_config.get("polling_interval_seconds"):
            changes.append(f"interval: {old_interval}s -> {new_config.get('polling_interval_seconds')}s")
        if changes:
            logger.info(f"Config reloaded: {', '.join(changes)}")
        else:
            logger.info("Config reloaded (no critical changes)")

    def _cycle(self) -> None:
        """Execute one full trading cycle."""
        self._cycle_count += 1
        logger.info(f"--- Cycle #{self._cycle_count} ---")

        # 0. Check for config changes
        changed, new_config = self.config_watcher.check_for_changes()
        if changed:
            self._apply_config(new_config)

        # 1. Check for symbol change
        changed, symbol = self.symbol_controller.check_for_change()
        if not symbol:
            logger.warning("No valid symbol. Skipping cycle.")
            return

        if changed:
            logger.info(f"Symbol switched to {symbol}. Adapting...")
            self.state_store.update(active_symbol=symbol)

        # 2. Fetch market data
        df = self.market_data.get_ohlcv(symbol)
        if df is None or df.empty:
            logger.warning(f"No market data for {symbol}. Skipping cycle.")
            return

        current_price = float(df["close"].iloc[-1])
        latest_candle_time = str(df.index[-1]) if hasattr(df.index[-1], 'isoformat') else str(df.index[-1])

        # Same-candle detection
        if latest_candle_time != self._last_candle_time:
            self._candle_changed = True
            self._last_candle_time = latest_candle_time
        else:
            self._candle_changed = False

        logger.info(f"Current price: {symbol} = {current_price} | candle_changed={self._candle_changed}")

        # 3. Calculate all indicators
        indicator_results = self.signal_service.calculate_all(df)

        # 4. Run consensus engine
        consensus = self.consensus_engine.evaluate(indicator_results)

        # 5. Get balance and PnL info
        balance = self.execution_engine.get_balance()
        daily_pnl = self.state_store.get("daily_pnl", 0.0)
        daily_start_balance = self.state_store.get("daily_start_balance", balance)

        # 6. Decision engine
        decision = self.decision_engine.decide(
            symbol=symbol,
            consensus=consensus,
            current_price=current_price,
            balance=balance,
            daily_pnl=daily_pnl,
            daily_start_balance=daily_start_balance,
        )

        # 7. Execute
        execution_result = self.execution_engine.execute(decision)

        # 8. Update state
        self._update_state_after_cycle(
            symbol, decision, execution_result, consensus, current_price, balance
        )

        # 9. Log decision summary
        self._log_cycle_summary(symbol, consensus, decision, execution_result, balance)

        # 10. Process manual close commands from dashboard
        self._process_close_commands()

        # 11. Check SL/TP for ALL non-active positions
        self._check_other_positions(symbol, balance)

        # 11. Auto-scan market every 10 minutes — switch to best coin
        self._auto_scan_market()

        # 12. Update live multi-TF signals for active coin (background, non-blocking)
        self._update_active_coin_signals(symbol)

        # 13. Export dashboard status snapshot
        self._last_indicator_results = indicator_results
        self._last_consensus = consensus
        self._last_decision = decision
        self._last_execution = execution_result
        self._last_price = current_price
        self._export_dashboard_status(balance)

    def _update_state_after_cycle(
        self,
        symbol: str,
        decision: dict[str, Any],
        execution_result: dict[str, Any],
        consensus: dict[str, Any],
        current_price: float,
        balance: float,
    ) -> None:
        """Persist state after each cycle."""
        daily_pnl = self.state_store.get("daily_pnl", 0.0)

        if execution_result.get("executed") and "pnl" in execution_result:
            daily_pnl += execution_result["pnl"]

        # Bump trade event id only on OPEN — popup announces "trade entered"
        action = execution_result.get("action", "")
        executed = bool(execution_result.get("executed"))
        if executed and action in ("OPEN_LONG", "OPEN_SHORT"):
            self._last_trade_event_id += 1
            self._last_trade_event_meta = {
                "id": self._last_trade_event_id,
                "timestamp": iso_now(),
                "symbol": execution_result.get("symbol", symbol),
                "action": action,
                "side": execution_result.get("side"),
                "quantity": execution_result.get("quantity"),
                "price": execution_result.get("price"),
                "leverage": execution_result.get("leverage"),
            }

        self.state_store.update(
            active_symbol=symbol,
            positions=self.position_manager.get_positions_dict(),
            last_decision={
                "action": decision["action"],
                "signal": consensus["final_signal"],
                "confidence": consensus["confidence"],
                "risk_level": consensus["risk_level"],
                "price": current_price,
                "timestamp": iso_now(),
            },
            last_trade_time=iso_now() if executed else self.state_store.get("last_trade_time"),
            daily_pnl=round(daily_pnl, 4),
            total_realized_pnl=round(self.position_manager.total_realized_pnl, 4),
            trade_history=[t.to_dict() for t in self.position_manager.trade_history[-100:]],
            paper_balance=round(self.execution_engine.paper_balance, 4),
            last_trade_event_id=self._last_trade_event_id,
            last_trade_event_meta=self._last_trade_event_meta,
        )

    def _log_cycle_summary(
        self,
        symbol: str,
        consensus: dict[str, Any],
        decision: dict[str, Any],
        execution_result: dict[str, Any],
        balance: float,
    ) -> None:
        """Log a summary of the cycle."""
        pos = self.position_manager.get_position(symbol)
        pos_info = f"{pos.side.value} qty={pos.quantity} entry={pos.entry_price} lev={pos.leverage}x" if pos else "FLAT"

        logger.info(
            f"Summary | {symbol} | signal={consensus['final_signal']} "
            f"conf={consensus['confidence']}% | risk={consensus['risk_level']} | "
            f"action={decision['action']} | pos={pos_info} | "
            f"balance={balance:.2f} | daily_pnl={self.state_store.get('daily_pnl', 0):.4f}"
        )

        if execution_result.get("executed"):
            logger.info(f"Execution: {json.dumps(execution_result, default=str)}")

    def _process_close_commands(self) -> None:
        """Check for manual close commands written by dashboard and execute them."""
        runtime_dir = Path("runtime")
        try:
            cmd_files = list(runtime_dir.glob("close_cmd_*.json"))
        except Exception:
            return
        for cmd_file in cmd_files:
            try:
                data = json.loads(cmd_file.read_text())
                sym = data.get("symbol", "")
                cmd_file.unlink(missing_ok=True)  # remove command file immediately
                if not sym:
                    continue
                pos = self.position_manager.get_position(sym)
                if not pos:
                    logger.info(f"Close command for {sym} but no position found (already closed)")
                    continue
                price = self.binance_client.get_ticker_price(sym)
                if not price:
                    price = pos.entry_price
                close_action = (
                    TradeAction.CLOSE_LONG if pos.side.value == "LONG"
                    else TradeAction.CLOSE_SHORT
                )
                decision = {
                    "action": close_action.value,
                    "symbol": sym,
                    "quantity": pos.quantity,
                    "price": price,
                    "reason": "Manuel kapatma (dashboard)",
                    "timestamp": iso_now(),
                    "consensus_signal": "NEUTRAL",
                    "confidence": 0,
                    "risk_level": "LOW",
                    "leverage": pos.leverage,
                }
                exec_result = self.execution_engine.execute(decision)
                if exec_result.get("executed"):
                    pnl = exec_result.get("pnl", 0)
                    daily_pnl = self.state_store.get("daily_pnl", 0.0) + pnl
                    self.state_store.update(
                        daily_pnl=round(daily_pnl, 4),
                        total_realized_pnl=round(self.position_manager.total_realized_pnl, 4),
                        positions=self.position_manager.get_positions_dict(),
                        trade_history=[t.to_dict() for t in self.position_manager.trade_history[-100:]],
                        paper_balance=round(self.execution_engine.paper_balance, 4),
                    )
                    logger.info(f"✅ {sym} manually closed via dashboard | PnL: {pnl:.4f}")
            except Exception as e:
                logger.warning(f"Failed to process close command {cmd_file}: {e}")
                try:
                    cmd_file.unlink(missing_ok=True)
                except Exception:
                    pass

    def _check_other_positions(self, active_symbol: str, balance: float) -> None:
        """Fast SL/TP/trailing/break-even check on ALL non-active positions.

        Optimization (2026-04-29): one bulk ticker call instead of N sequential
        calls; per-position indicator/consensus calc removed because signal-reversal
        auto-close is disabled. Cycle phase reduced from ~10 s to <300 ms for 40+
        positions.
        """
        positions = dict(self.position_manager.positions)
        if not positions:
            return

        # 1 HTTP call → all symbol prices
        all_prices = self.binance_client.get_all_prices()
        if not all_prices:
            logger.warning("Bulk price fetch failed — skipping non-active position checks")
            return

        for sym, pos in positions.items():
            if sym == active_symbol:
                continue
            price = all_prices.get(sym)
            if not price:
                continue
            try:
                exit_reason = self.position_manager.update_position(sym, price)
                if exit_reason:
                    pos.warning = exit_reason
                    logger.warning(
                        f"Position {sym} hit {exit_reason} — NOT auto-closing. "
                        f"Manual close required."
                    )
            except Exception as e:
                logger.warning(f"Failed to update position {sym}: {e}")

    # ── Live multi-TF signals for active coin ──────────────────────

    def _update_active_coin_signals(self, symbol: str) -> None:
        """Calculate signals for the active coin across all 12 TFs in a background thread.

        Writes result to runtime/active_coin_signals.json every cycle.
        Non-blocking: launches a daemon thread.
        """
        # Don't launch if a previous one is still running
        if hasattr(self, "_active_signals_thread") and self._active_signals_thread.is_alive():
            return

        def _worker():
            try:
                results = {}
                for tf in self._multi_tfs:
                    try:
                        md = MarketDataProvider(
                            self.binance_client, {**self.config, "timeframe": tf},
                            cache=self.market_cache, store=self.market_store,
                        )
                        df = md.get_ohlcv(symbol)
                        if df is None or df.empty:
                            results[tf] = {"signal": "N/A", "confidence": 0, "risk_level": "N/A"}
                            continue
                        svc = SignalService(
                            {**self.config, "timeframe": tf},
                            binance_client=self.binance_client,
                            cache=self.market_cache, store=self.market_store,
                        )
                        indicators = svc.calculate_all(df)
                        consensus = ConsensusEngine(self.config).evaluate(indicators)
                        conf = consensus["confidence"]
                        zak = self._ZAK.get(tf, 50)
                        results[tf] = {
                            "signal": consensus["final_signal"],
                            "confidence": conf,
                            "risk_level": consensus["risk_level"],
                            "zak": zak,
                            "nihai_skor": round((conf ** 2) * (zak / 100), 2),
                        }
                    except Exception as e:
                        logger.debug(f"Active coin signal calc failed for {tf}: {e}")
                        results[tf] = {"signal": "N/A", "confidence": 0, "risk_level": "N/A"}

                # Write to file
                data = {
                    "symbol": symbol,
                    "timeframes": results,
                    "updated_at": iso_now(),
                }
                runtime_dir = Path(self.config.get("dashboard_status_path", "runtime/dashboard_status.json")).parent
                out = runtime_dir / "active_coin_signals.json"
                tmp = out.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, default=str))
                tmp.replace(out)
            except Exception as e:
                logger.warning(f"Active coin signals update failed: {e}")

        self._active_signals_thread = threading.Thread(target=_worker, daemon=True)
        self._active_signals_thread.start()

    def _is_manual_scan_active(self) -> bool:
        """Check if a dashboard-triggered manual scan is currently running.
        Auto-clears stale locks older than 30 minutes.
        """
        try:
            runtime_dir = Path(self.config.get("dashboard_status_path", "runtime/dashboard_status.json")).parent
            lock_file = runtime_dir / "manual_scan_active.json"
            if lock_file.exists():
                d = json.loads(lock_file.read_text())
                if d.get("active", False):
                    # Check if lock is stale (>30 min old)
                    ts = d.get("ts", "")
                    if ts:
                        from datetime import datetime, timezone
                        lock_time = datetime.fromisoformat(ts)
                        age_minutes = (datetime.now(timezone.utc) - lock_time).total_seconds() / 60
                        if age_minutes > 30:
                            logger.warning(f"Stale manual scan lock ({age_minutes:.0f} min old) — auto-clearing")
                            lock_file.unlink(missing_ok=True)
                            return False
                    return True
        except Exception:
            pass
        return False

    def _auto_scan_market(self) -> None:
        """Launch multi-TF auto-scan in background threads (non-blocking).

        Scans all 12 timeframes (1m–1d) in parallel.
        Uses a threading.Lock to guarantee only one batch runs at a time.
        Timer counts 10 min from scan COMPLETION.
        Skips if a manual scan is running (from dashboard).
        Skips if auto-scan is disabled via dashboard toggle.
        """
        # Check if auto-scan is disabled
        flag_file = Path("runtime") / "auto_scan_disabled"
        if flag_file.exists():
            return
        # Dashboard toggle'ını yakalamak için taze config oku (watcher gecikmesini atla)
        try:
            import yaml as _yaml
            _cfg_path = Path(self.config.get("_config_path", "config/default.yaml"))
            config = _yaml.safe_load(_cfg_path.read_text()) or {}
        except Exception:
            config = self.config
        if not config.get("auto_scan_enabled", True):
            return

        # Fast check: is a scan already in progress?
        if self._scanning_active:
            if any(t.is_alive() for t in self._scan_threads):
                return
            # Threads finished but flag wasn't cleared (shouldn't happen, safety net)
            self._scanning_active = False

        # Block if manual scan is active — don't consume the timer
        if self._is_manual_scan_active():
            logger.debug("Manual scan active — skipping auto-scan this cycle")
            return

        # Timer check
        now = time.time()
        if now - self._last_auto_scan_time < self._auto_scan_interval:
            return

        # Try to acquire lock (non-blocking) — only for initial checks
        if not self._scan_lock.acquire(blocking=False):
            return

        try:
            if self._scanning_active or any(t.is_alive() for t in self._scan_threads):
                return

            # Double-check manual scan right before committing
            if self._is_manual_scan_active():
                logger.debug("Manual scan active (double-check) — aborting auto-scan")
                return

            # Mark scan as active IMMEDIATELY to prevent re-entry
            self._scanning_active = True
            self._last_auto_scan_time = now  # prevent re-trigger while scanning
        finally:
            # Release lock early — _scanning_active flag prevents re-entry
            # Lock must be free for scan threads + progress writer to use it
            self._scan_lock.release()

        # Off-load all phase coordination to a top-level thread so the
        # main bot cycle returns immediately and never waits on Binance.
        coord = threading.Thread(
            target=self._scan_coordinator, daemon=True, name="scan-coordinator",
        )
        coord.start()

    def _scan_coordinator(self) -> None:
        """Run phase-1 + phase-2 scans without blocking the main cycle."""
        try:
            symbol_path = Path(self.config.get("active_symbol_path", "runtime/active_symbol.txt"))
            total_tfs = len(self._multi_tfs)
            self._multi_scan_done_count = 0
            self._multi_scan_results = {}
            self._multi_scan_full = {}
            self._scan_threads = []

            # Pre-fetch symbol list ONCE
            _prefetch_scanner = ScannerService(self.config, shared_client=self.binance_client)
            shared_symbols = _prefetch_scanner._get_top_symbols_by_volume()

            # ── 2-PHASE SCAN ──
            # Phase 1: Scan ALL coins on top 3 ZAK TFs (1d, 12h, 8h) → find promising coins
            # Phase 2: Deep-scan top 50 coins on remaining 9 TFs
            # This reduces API calls from ~7900 to ~2400 (~3x faster)
            _phase1_tfs = ["1d", "12h", "8h"]
            _phase2_tfs = [tf for tf in self._multi_tfs if tf not in _phase1_tfs]
            _PHASE2_TOP_N = 50  # How many coins survive Phase 1

            logger.info(f"🔍 2-Phase auto-scan: Phase1={_phase1_tfs} (all {len(shared_symbols)} coins) → Phase2={_phase2_tfs} (top {_PHASE2_TOP_N})")

            # Limit concurrent threads to avoid Binance rate limits
            _scan_semaphore = threading.Semaphore(3)
            req_delay = 0.15

            # Write initial progress file — preserve last completed scan data
            self._auto_scan_start_time = iso_now()
            self._auto_scan_scanners: dict[str, ScannerService] = {}
            prev_progress = {}
            try:
                runtime_dir = Path(self.config.get("dashboard_status_path", "runtime/dashboard_status.json")).parent
                prev_file = runtime_dir / "auto_scan_progress.json"
                if prev_file.exists():
                    prev_progress = json.loads(prev_file.read_text())
                # Fallback: if no last_auto_scan, try dashboard_status.json
                if not prev_progress.get("last_auto_scan"):
                    ds_path = Path(self.config.get("dashboard_status_path", "runtime/dashboard_status.json"))
                    if ds_path.exists():
                        ds = json.loads(ds_path.read_text())
                        if ds.get("last_auto_scan"):
                            prev_progress["last_auto_scan"] = ds["last_auto_scan"]
                        if ds.get("last_scan_results"):
                            prev_progress["last_scan_results"] = ds["last_scan_results"]
                        if ds.get("last_scan_total"):
                            prev_progress["last_scan_total"] = ds["last_scan_total"]
                        if ds.get("last_scan_hot_count") is not None:
                            prev_progress["last_scan_hot_count"] = ds["last_scan_hot_count"]
            except Exception:
                pass
            self._write_auto_scan_progress({
                "scanning": True,
                "total": total_tfs,
                "done": 0,
                "pct": 0,
                "done_tfs": [],
                "all_tfs": self._multi_tfs,
                "started_at": self._auto_scan_start_time,
                # Preserve last completed scan data for display
                "last_auto_scan": prev_progress.get("last_auto_scan"),
                "last_scan_results": prev_progress.get("last_scan_results"),
                "last_scan_hot_count": prev_progress.get("last_scan_hot_count"),
                "last_scan_total": prev_progress.get("last_scan_total"),
            })

            # Background thread to update progress based on per-coin scanning
            def _progress_writer():
                import time as _t
                while True:
                    _t.sleep(3)
                    with self._scan_lock:
                        done_count = self._multi_scan_done_count
                        done_tfs = list(self._multi_scan_results.keys())
                    if done_count >= total_tfs:
                        break  # final progress written by _process_multi_scan_results
                    # Calculate TF-weighted progress:
                    # done TFs = 100%, running TFs = their coin%, pending = 0%
                    tf_pct_sum = done_count * 100  # completed TFs
                    total_coins = 0
                    scanned_coins = 0
                    for tf, scanner in list(self._auto_scan_scanners.items()):
                        try:
                            prog = scanner._scan_progress
                            t = prog.get("total", 0)
                            c = prog.get("current", 0)
                            total_coins += t
                            scanned_coins += c
                            if tf not in done_tfs and t > 0:
                                tf_pct_sum += int(c * 100 / t)
                        except Exception:
                            pass
                    if total_tfs > 0:
                        pct = int(tf_pct_sum / total_tfs)
                    else:
                        pct = 0
                    self._write_auto_scan_progress({
                        "scanning": True,
                        "total": total_tfs,
                        "done": done_count,
                        "pct": pct,
                        "done_tfs": done_tfs,
                        "all_tfs": self._multi_tfs,
                        "started_at": self._auto_scan_start_time,
                        "coins_scanned": scanned_coins,
                        "coins_total": total_coins,
                        # Preserve last completed scan data
                        "last_auto_scan": prev_progress.get("last_auto_scan"),
                        "last_scan_results": prev_progress.get("last_scan_results"),
                        "last_scan_hot_count": prev_progress.get("last_scan_hot_count"),
                        "last_scan_total": prev_progress.get("last_scan_total"),
                    })

            pw = threading.Thread(target=_progress_writer, daemon=True)
            pw.start()

            def _scan_single_tf(tf: str, symbols_override: list[str] | None = None):
                _scan_semaphore.acquire()
                try:
                    syms = symbols_override if symbols_override else shared_symbols
                    scanner = ScannerService(
                        self.config, symbol_file=symbol_path, timeframe=tf,
                        shared_symbols=syms,
                    )
                    scanner._request_delay = req_delay
                    self._auto_scan_scanners[tf] = scanner
                    scanner.scan(min_confidence=0)
                    results = scanner.results
                    # Nihai sinyal skoru = (güven²) × (ZAK / 100)
                    zak = self._ZAK.get(tf, 50)
                    for r in results:
                        r["zak"] = zak
                        r["nihai_skor"] = round((r["confidence"] ** 2) * (zak / 100), 2)
                    top15 = sorted(results, key=lambda r: r["nihai_skor"], reverse=True)[:15]

                    with self._scan_lock:
                        self._multi_scan_results[tf] = top15
                        self._multi_scan_full[tf] = results
                        self._multi_scan_done_count += 1
                        done = self._multi_scan_done_count

                    logger.info(f"  ✅ {tf} scan done: {len(syms)}→{len(results)} coins ({done}/{total_tfs})")

                    # When ALL timeframes are done, process combined results
                    if done == total_tfs:
                        self._process_multi_scan_results(symbol_path)
                except Exception as e:
                    logger.error(f"Auto-scan {tf} failed: {e}", exc_info=True)
                    with self._scan_lock:
                        if tf not in self._multi_scan_results:
                            self._multi_scan_results[tf] = []
                            self._multi_scan_full[tf] = []
                        self._multi_scan_done_count += 1
                        done = self._multi_scan_done_count
                    if done == total_tfs:
                        self._process_multi_scan_results(symbol_path)
                finally:
                    _scan_semaphore.release()

            # ── PHASE 1: High-ZAK TFs scan ALL coins ──
            phase1_threads = []
            for i, tf in enumerate(_phase1_tfs):
                t = threading.Thread(target=_scan_single_tf, args=(tf, None), daemon=True, name=f"scan-{tf}")
                self._scan_threads.append(t)
                phase1_threads.append(t)
                t.start()
                if i < len(_phase1_tfs) - 1:
                    time.sleep(1)

            # Wait for Phase 1 to complete
            for t in phase1_threads:
                t.join()

            # ── Determine Phase 2 survivors ──
            # Phase 1 threads are done (join completed), safe to read without lock
            _p1_scores: dict[str, float] = {}
            for tf in _phase1_tfs:
                for r in self._multi_scan_full.get(tf, []):
                    sym = r["symbol"]
                    _p1_scores[sym] = _p1_scores.get(sym, 0) + r.get("nihai_skor", 0)

            # Top N coins by Phase 1 aggregate NSS
            _survivors = sorted(_p1_scores.items(), key=lambda x: -x[1])[:_PHASE2_TOP_N]
            _phase2_symbols = [s[0] for s in _survivors]
            logger.info(f"🏅 Phase 1 complete. Top {len(_phase2_symbols)} coins for Phase 2: {', '.join(_phase2_symbols[:10])}...")

            # ── PHASE 2: Remaining TFs scan only survivors ──
            for i, tf in enumerate(_phase2_tfs):
                t = threading.Thread(target=_scan_single_tf, args=(tf, _phase2_symbols), daemon=True, name=f"scan-{tf}")
                self._scan_threads.append(t)
                t.start()
                if i < len(_phase2_tfs) - 1:
                    time.sleep(1)
        except Exception as e:
            logger.error(f"Auto-scan failed: {e}", exc_info=True)
            self._scanning_active = False

    def _process_multi_scan_results(self, symbol_path: Path) -> None:
        """Process combined multi-TF scan results: cross-ranking, auto-select, save."""
        try:
            tf_data = self._multi_scan_results
            total_tfs = len(self._multi_tfs)

            # Build cross-ranking with net NSS (opposing signals subtracted)
            symbol_stats: dict[str, dict] = {}
            for tf in self._multi_tfs:
                zak = self._ZAK.get(tf, 50)
                top15 = tf_data.get(tf, [])
                for r in top15:
                    sym = r["symbol"]
                    conf = r["confidence"]
                    sig = r["signal"].upper()
                    nss = round((conf ** 2) * (zak / 100), 2)
                    if sym not in symbol_stats:
                        symbol_stats[sym] = {
                            "symbol": sym, "count": 0, "total_conf": 0,
                            "buy_nss": 0, "sell_nss": 0,
                            "best_conf": 0, "price": r.get("price", 0),
                            "signals": {}, "all_signals": {},
                        }
                    symbol_stats[sym]["count"] += 1
                    symbol_stats[sym]["total_conf"] += conf
                    if sig in ("BUY", "STRONG_BUY"):
                        symbol_stats[sym]["buy_nss"] += nss
                    elif sig in ("SELL", "STRONG_SELL"):
                        symbol_stats[sym]["sell_nss"] += nss
                    # NEUTRAL contributes nothing
                    if conf > symbol_stats[sym]["best_conf"]:
                        symbol_stats[sym]["best_conf"] = conf
                        symbol_stats[sym]["price"] = r.get("price", 0)
                    symbol_stats[sym]["signals"][tf] = {
                        "signal": r["signal"], "confidence": conf, "zak": zak, "nihai_skor": nss,
                    }
                    symbol_stats[sym]["all_signals"][tf] = {
                        "signal": r["signal"], "confidence": conf, "zak": zak, "nihai_skor": nss, "in_top15": True,
                    }

            # Calculate net_nss: dominant direction NSS minus opposing direction NSS
            for sym, s in symbol_stats.items():
                if s["buy_nss"] >= s["sell_nss"]:
                    s["dominant_dir"] = "BUY"
                    s["net_nss"] = round(s["buy_nss"] - s["sell_nss"], 2)
                else:
                    s["dominant_dir"] = "SELL"
                    s["net_nss"] = round(s["sell_nss"] - s["buy_nss"], 2)
                s["total_nss"] = s["net_nss"]  # for backward compat

            # Sıralama: net NSS'e göre (karşı yön çıkarılmış)
            cross_ranked = sorted(
                symbol_stats.values(),
                key=lambda x: -x["net_nss"],
            )

            # Fill non-top15 TF confidences from full results for top 10
            ranked_symbols = {c["symbol"] for c in cross_ranked[:10]}
            full_data = self._multi_scan_full
            for tf in self._multi_tfs:
                zak = self._ZAK.get(tf, 50)
                all_results = full_data.get(tf, [])
                for r in all_results:
                    sym = r["symbol"]
                    if sym in ranked_symbols:
                        for c in cross_ranked[:10]:
                            if c["symbol"] == sym and tf not in c["all_signals"]:
                                conf = r["confidence"]
                                nss = round((conf ** 2) * (zak / 100), 2)
                                c["all_signals"][tf] = {
                                    "signal": r["signal"], "confidence": conf,
                                    "zak": zak, "nihai_skor": nss, "in_top15": False,
                                }
                                break

            # Log cross-ranking top 10
            logger.info("🏆 Multi-TF cross-ranking (top 10 — net NSS):")
            for i, c in enumerate(cross_ranked[:10]):
                tfs_str = ", ".join(f"{tf}={c['signals'][tf]['nihai_skor']:.0f}" for tf in self._multi_tfs if tf in c['signals'])
                logger.info(f"  #{i+1} {c['symbol']:12s} | {c['dominant_dir']} net={c['net_nss']:.0f} | {c['count']}/{total_tfs} TF | {tfs_str}")

            # ── New cumulative auto-select (replaces old unanimous-direction logic) ──
            # 1) Append this scan to rolling history (≤24 h, last 10)
            # 2) Build cumulative ranking from history
            # 3) If 10/10 saturated: top cumulative coin → set as active symbol directly
            scan_time_iso = iso_now()
            self.scan_history.append(cross_ranked[:50], timestamp=scan_time_iso)
            cumulative = self.scan_history.cumulative_ranking(top_n=10)
            saturation = self.scan_history.saturation()

            # Resolve auto_select_on (re-read fresh YAML for hot-reload safety)
            auto_select_on = None
            try:
                _cfg_path = Path(self.config.get("_config_path", "config/default.yaml"))
                import yaml as _yaml
                _fresh_cfg = _yaml.safe_load(_cfg_path.read_text()) or {}
                auto_select_on = _fresh_cfg.get("auto_select_enabled", True)
            except Exception:
                pass
            if Path("runtime/auto_select_disabled").exists():
                auto_select_on = False
            if auto_select_on is None:
                auto_select_on = self.config.get("auto_select_enabled", True)

            logger.info(
                f"📊 Cumulative table: {saturation['filled']}/{saturation['max']} scans, "
                f"top-1 {cumulative[0]['symbol'] if cumulative else 'N/A'}"
            )
            for i, c in enumerate(cumulative[:10]):
                logger.info(
                    f"  C#{i+1} {c['symbol']:14s} | {c['dominant_dir']:5s} | "
                    f"total={c['total_score']:>9.0f} | "
                    f"appearances={c['appearances']}/{c['max_appearances']} | "
                    f"avg={c['avg_score']:.0f} | best_conf={c['best_conf']}%"
                )

            # No saturation gate — top-1 of cumulative table is always taken
            if auto_select_on and cumulative:
                top = cumulative[0]
                current_symbol = self.symbol_controller.get_current_symbol()
                if top["symbol"] != current_symbol:
                    logger.info(
                        f"⚡ Cumulative auto-select: "
                        f"{current_symbol} → {top['symbol']} "
                        f"(total={top['total_score']:.0f}, "
                        f"{top['appearances']}/{top['max_appearances']} apps, "
                        f"history={saturation['filled']}/{saturation['max']})"
                    )
                    scanner = ScannerService(self.config, symbol_file=symbol_path)
                    scanner.set_active_symbol(top["symbol"])
                else:
                    logger.info(
                        f"✅ Active symbol {current_symbol} still cumulative #1 "
                        f"(total={top['total_score']:.0f})"
                    )
            elif not auto_select_on:
                logger.info("Auto-select disabled — keeping current symbol")

            # Bump scan event id for dashboard popup/sound notification
            self._last_scan_event_id += 1
            self._last_scan_event_meta = {
                "id": self._last_scan_event_id,
                "timestamp": scan_time_iso,
                "saturation": saturation,
                "top_cumulative_symbol": cumulative[0]["symbol"] if cumulative else None,
                "scan_size": len(symbol_stats),
            }

            # Save results to state store + multi_scan_results.json
            self.state_store.update(
                last_auto_scan=scan_time_iso,
                last_scan_results=cross_ranked[:10],
                last_scan_hot_count=sum(1 for c in cross_ranked if c["count"] == total_tfs),
                last_scan_total=len(symbol_stats),
                cumulative_results=cumulative,
                cumulative_saturation=saturation,
                last_scan_event_id=self._last_scan_event_id,
                last_scan_event_meta=self._last_scan_event_meta,
            )

            # Save full multi-scan data for dashboard
            multi_result = {
                "any_scanning": False,
                "timeframes": {},
                "common_symbols": [c["symbol"] for c in cross_ranked if c["count"] == total_tfs],
                "cross_ranking": cross_ranked[:10],
                "scan_time": iso_now(),
            }
            for tf in self._multi_tfs:
                top15 = tf_data.get(tf, [])
                multi_result["timeframes"][tf] = {
                    "scanning": False,
                    "progress": {"current": 0, "total": 0, "status": "complete"},
                    "top15": top15,
                    "total_scanned": len(top15),
                }
            try:
                runtime_dir = Path(self.config.get("dashboard_status_path", "runtime/dashboard_status.json")).parent
                scan_file = runtime_dir / "multi_scan_results.json"
                tmp = scan_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(multi_result, default=str))
                tmp.replace(scan_file)
                logger.info(f"Multi-TF results saved to {scan_file}")
            except Exception as e:
                logger.warning(f"Failed to save multi-scan results: {e}")

            # Mark progress as complete with full scan data + cumulative table
            self._write_auto_scan_progress({
                "scanning": False,
                "total": total_tfs,
                "done": total_tfs,
                "pct": 100,
                "done_tfs": self._multi_tfs,
                "all_tfs": self._multi_tfs,
                "completed_at": scan_time_iso,
                "last_auto_scan": scan_time_iso,
                "last_scan_results": cross_ranked[:10],
                "last_scan_hot_count": sum(1 for c in cross_ranked if c["count"] == total_tfs),
                "last_scan_total": len(symbol_stats),
                "cumulative_results": cumulative,
                "cumulative_saturation": saturation,
                "last_scan_event_id": self._last_scan_event_id,
                "last_scan_event_meta": self._last_scan_event_meta,
            })

        except Exception as e:
            logger.error(f"Multi-scan processing failed: {e}", exc_info=True)
        finally:
            self._last_auto_scan_time = time.time()
            self._scanning_active = False

    def _write_auto_scan_progress(self, data: dict) -> None:
        """Write auto-scan progress to a JSON file for the dashboard to read."""
        try:
            runtime_dir = Path(self.config.get("dashboard_status_path", "runtime/dashboard_status.json")).parent
            progress_file = runtime_dir / "auto_scan_progress.json"
            tmp = progress_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, default=str))
            tmp.replace(progress_file)
        except Exception:
            pass  # Non-critical

    def _patch_dashboard_status(self, updates: dict) -> None:
        """Directly patch dashboard_status.json with given key-value pairs."""
        try:
            status_path = Path(self.config.get("dashboard_status_path", "runtime/dashboard_status.json"))
            if status_path.exists():
                ds = json.loads(status_path.read_text())
            else:
                ds = {}
            ds.update(updates)
            tmp = status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(ds, indent=2, default=str))
            tmp.replace(status_path)
        except Exception as e:
            logger.warning(f"Failed to patch dashboard_status.json: {e}")

    def _fetch_all_position_prices(self) -> dict[str, float]:
        """Fetch current prices for all symbols with open positions.

        Uses BinanceClient.get_all_prices() — single bulk call, ~100 ms
        regardless of position count.
        """
        positions = self.position_manager.get_positions_dict()
        if not positions:
            return {}
        all_prices = self.binance_client.get_all_prices()
        result = {sym: all_prices[sym] for sym in positions if sym in all_prices}
        active_symbol = self.symbol_controller.get_current_symbol()
        if active_symbol and self._last_price:
            result[active_symbol] = self._last_price
        return result

    def _export_dashboard_status(self, balance: float) -> None:
        """Export dashboard snapshot after each cycle."""
        try:
            all_prices = self._fetch_all_position_prices()
            self.status_exporter.export(
                config=self.config,
                state=self.state_store.state,
                consensus=self._last_consensus,
                indicator_results=self._last_indicator_results,
                decision=self._last_decision,
                execution_result=self._last_execution,
                balance=balance,
                current_price=self._last_price,
                cycle_count=self._cycle_count,
                running=self.running,
                all_prices=all_prices,
                data_pipeline_health=self._collect_pipeline_health(),
            )
        except Exception as e:
            logger.error(f"Failed to export dashboard status: {e}")

    def _collect_pipeline_health(self) -> dict[str, Any]:
        """Collect WS/cache/store metrics for the dashboard."""
        h: dict[str, Any] = {
            "use_ws_cache": bool(
                self.market_cache is not None and self.market_store is not None
            ),
        }
        if self.ws_manager is not None:
            try:
                h["ws"] = self.ws_manager.get_health()
            except Exception:
                pass
        if self.market_cache is not None:
            try:
                h["cache"] = self.market_cache.get_health()
            except Exception:
                pass
        if self.market_store is not None:
            try:
                h["store"] = self.market_store.get_stats()
            except Exception:
                pass
        return h

    def _shutdown(self) -> None:
        """Graceful shutdown - save state and export stopped status."""
        logger.info("Shutting down bot...")
        self.state_store.save()
        try:
            self.status_exporter.export_stopped(self.config, self.state_store.state)
        except Exception as e:
            logger.error(f"Failed to export shutdown status: {e}")
        logger.info("State saved. Bot stopped.")

    def stop(self) -> None:
        """Signal the bot to stop."""
        self.running = False
