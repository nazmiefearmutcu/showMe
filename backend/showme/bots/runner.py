"""Bot runner — asyncio scheduler per enabled bot.

Each enabled bot gets a long-running task that ticks every
``tick_interval_seconds``. On each tick: pull OHLCV, run evaluate,
detect NEW event vs last_processed_event, route it.

Shadow mode logs to signal_log only. Live mode also calls
broker.submit_order(). The adapter-level _require("trade") gate
from A's CcxtBroker remains the final defense.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from showme.bots.ohlcv import BotRunnerError, fetch_ohlcv
from showme.bots.record import BotRecord, SignalEntry
from showme.bots.store import BotStore, UnknownBot

LOG = logging.getLogger("showme.bots.runner")


class BotRunner:
    """Owns one asyncio.Task per enabled bot."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._stopped = False

    def is_running(self, bot_id: str) -> bool:
        t = self._tasks.get(bot_id)
        return t is not None and not t.done()

    async def start_all(self, store: BotStore) -> None:
        """Spawn a task for every enabled bot in the store."""
        for meta in store.list():
            if meta.enabled and not self.is_running(meta.id):
                self._spawn(meta.id, store)

    def _spawn(self, bot_id: str, store: BotStore) -> None:
        if self._stopped:
            return
        task = asyncio.create_task(self._run_loop(bot_id, store), name=f"bot:{bot_id}")
        self._tasks[bot_id] = task

    async def enable(self, bot_id: str, store: BotStore) -> BotRecord:
        rec = store.get(bot_id)
        if not rec.enabled:
            rec = rec.model_copy(update={"enabled": True})
            rec = store.save(rec)
        if not self.is_running(bot_id):
            self._spawn(bot_id, store)
        return rec

    async def disable(self, bot_id: str, store: BotStore) -> BotRecord:
        rec = store.get(bot_id)
        if rec.enabled:
            rec = rec.model_copy(update={"enabled": False})
            rec = store.save(rec)
        task = self._tasks.pop(bot_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        return rec

    async def aclose(self) -> None:
        self._stopped = True
        for bot_id, task in list(self._tasks.items()):
            task.cancel()
        for bot_id, task in list(self._tasks.items()):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()

    async def _run_loop(self, bot_id: str, store: BotStore) -> None:
        """Per-bot loop. Catches per-tick exceptions so one failure
        doesn't kill the bot — the next tick retries."""
        LOG.info("bot %s loop started", bot_id)
        try:
            while True:
                try:
                    rec = store.get(bot_id)
                except UnknownBot:
                    LOG.warning("bot %s gone; stopping loop", bot_id)
                    return
                if not rec.enabled:
                    LOG.info("bot %s disabled; stopping loop", bot_id)
                    return
                try:
                    await self.tick(bot_id, store, _now=None)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("bot %s tick failed: %s", bot_id, exc)
                await asyncio.sleep(rec.tick_interval_seconds)
        except asyncio.CancelledError:
            LOG.info("bot %s loop cancelled", bot_id)
            raise

    async def tick(self, bot_id: str, store: BotStore, _now: Any = None) -> SignalEntry | None:
        """Single iteration: fetch OHLCV, evaluate, route. Returns the
        signal entry (if any) it appended, or None.

        Side effects:
        * Appends to signal_log
        * Updates last_processed_event
        * In live mode, calls broker.submit_order()
        """
        rec = store.get(bot_id)
        if not rec.enabled:
            return None

        # Resolve broker.
        from showme.brokers import factory as factory_mod
        broker_name = f"{rec.exchange_id}:{rec.credential_id}"
        try:
            broker = factory_mod.get_broker(broker_name)
        except KeyError as exc:
            LOG.warning("bot %s: broker %s missing: %s", bot_id, broker_name, exc)
            entry = SignalEntry(bar_index=-1, bar_time="", kind="entry",
                               price=0.0, action="skipped",
                               error=f"broker unavailable: {exc}")
            store.save(rec.append_signal(entry))
            return entry

        # Resolve strategy + fetch ohlcv.
        from showme.strategies.store import StrategyStore, UnknownStrategy
        try:
            spec = StrategyStore.fresh().get(rec.strategy_id)
        except UnknownStrategy as exc:
            LOG.warning("bot %s: strategy %s missing", bot_id, rec.strategy_id)
            entry = SignalEntry(bar_index=-1, bar_time="", kind="entry",
                               price=0.0, action="skipped",
                               error=f"strategy unavailable: {exc}")
            store.save(rec.append_signal(entry))
            return entry

        try:
            df = await fetch_ohlcv(broker, rec.symbol, rec.timeframe, limit=200)
        except BotRunnerError as exc:
            entry = SignalEntry(bar_index=-1, bar_time="", kind="entry",
                               price=0.0, action="skipped", error=str(exc))
            store.save(rec.append_signal(entry))
            return entry

        if df.empty:
            return None

        from showme.strategies.evaluate import evaluate
        events = evaluate(spec, df)
        if not events:
            return None

        # Take the most recent event on the most recent bar:
        last_event = events[-1]
        last_bar_index_in_df = len(df) - 1
        # Only fire if it's truly the latest bar (event happened on this tick's last bar)
        if last_event.bar_index != last_bar_index_in_df:
            return None

        # Deduplicate vs last_processed_event:
        if (rec.last_processed_event is not None
                and rec.last_processed_event.bar_time == last_event.bar_time
                and rec.last_processed_event.kind == last_event.kind):
            return None

        # Route.
        action = "shadow"
        order_id: str | None = None
        error: str | None = None
        if rec.mode == "live":
            try:
                from showme.brokers import OrderSide, OrderType, TimeInForce
                side = OrderSide.BUY if last_event.kind == "entry" else OrderSide.SELL
                # Position-side reversal for exit: this is a market close.
                qty_signal_to_qty = float(spec.position.sizing_value)
                order = await broker.submit_order(
                    symbol=rec.symbol,
                    side=side,
                    quantity=qty_signal_to_qty,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.IOC,
                    notes=f"bot:{bot_id}",
                )
                action = "placed"
                order_id = order.id
            except Exception as exc:  # noqa: BLE001
                action = "skipped"
                error = f"submit failed: {exc}"

        entry = SignalEntry(
            bar_index=last_event.bar_index,
            bar_time=last_event.bar_time,
            kind=last_event.kind,
            price=last_event.price,
            action=action,
            order_id=order_id,
            error=error,
        )
        store.save(rec.append_signal(entry))
        return entry
