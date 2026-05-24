"""Bot runner — asyncio scheduler per enabled bot.

Each enabled bot gets a long-running task that ticks every
``tick_interval_seconds``. On each tick: pull OHLCV, run
``evaluate_last_bar`` (state-aware, single-bar) and route the event.

Shadow mode logs to signal_log only. Live mode also calls
broker.submit_order(). The adapter-level _require("trade") gate
from A's CcxtBroker remains the final defense.

Fix highlights (FIX_CONTRACT 2026-05-23):
* C-RUNTIME-1: ``BotRecord`` rejects extreme (TF, tick_interval) pairs.
* C-RUNTIME-2 / H-RT-4: replaced the per-tick 200-bar replay with a
  state-aware ``evaluate_last_bar`` call.
* C-RUNTIME-3: ``factory.get_broker`` now caches; runner doesn't leak.
* C-RUNTIME-4 / H-RT-1: ``_dispatch_live_order`` consults ``close_position``
  first and falls back to a sizing-derived opposite-side order with a
  partial-fill audit.
* C-RUNTIME-5: ``start_all`` holds an asyncio.Lock so two concurrent
  invocations cannot double-spawn.
* H-RT-2: ``disable()`` cancels the running task *before* releasing the lock.
* H-RT-5: every tick re-checks the credential's ``trade`` permission.
* H-RT-6: bot.timeframe vs strategy.timeframe drift logs a ``skipped`` entry.
* C2 sizing: every entry/exit consults the new ``strategies.sizing`` module
  and ``_resolve_equity()`` (broker.account() with a fallback constant).
* C4 signal-log split: every paired exit appends a ``ClosedTrade`` to
  ``closed_trades_log`` (append-only, no cap) in addition to the existing
  ``signal_log`` debug entry.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from showme.bots.ohlcv import BotRunnerError, fetch_ohlcv
from showme.bots.record import BotRecord, ClosedTrade, SignalEntry
from showme.bots.store import BotStore, UnknownBot
from showme.strategies.sizing import (
    Side,
    SizingKind,
    compute_pnl,
    resolve_quantity,
)

LOG = logging.getLogger("showme.bots.runner")


# C2 fix: fallback equity when ``broker.account()`` is unavailable / fails.
# A future iteration could pull this from a per-bot equity hint; for now
# this is the documented floor for ``risk_pct`` sizing.
_REFERENCE_EQUITY_USD = 10_000.0


async def _resolve_equity(broker: Any, fallback_usd: float = _REFERENCE_EQUITY_USD) -> float:
    """Try ``broker.account()['equity']``; fall back to ``fallback_usd``.

    Used by ``_resolve_quantity_async`` for ``risk_pct`` sizing so the
    runner doesn't multiply by a hardcoded $10k anymore. Brokers that
    don't expose ``account()`` (or that throw) fall back transparently.
    """
    fn = getattr(broker, "account", None)
    if fn is None:
        return float(fallback_usd)
    try:
        acct = await fn()
    except Exception as exc:  # noqa: BLE001
        LOG.debug("broker.account() failed; using fallback equity: %s", exc)
        return float(fallback_usd)
    try:
        for k in ("equity", "cash", "buying_power"):
            v = acct.get(k) if isinstance(acct, dict) else None
            if v and float(v) > 0:
                return float(v)
    except Exception as exc:  # noqa: BLE001
        LOG.debug("account() payload unexpected: %s", exc)
    return float(fallback_usd)


def _resolve_quantity(spec: Any, df: Any) -> float:
    """Legacy synchronous sizing resolver kept for backward compatibility.

    Pre-2026-05-23 callers (notably ``tests/test_runner_fixes.py``) imported
    this function directly. New code should use
    :func:`_resolve_quantity_async` which validates inputs and consults
    live broker equity for ``risk_pct`` sizing. This shim preserves the old
    behaviour: a hardcoded ``_REFERENCE_EQUITY_USD`` for ``risk_pct`` and
    no broker.account() round-trip.
    """
    sizing_kind: SizingKind = spec.position.sizing_kind
    sizing_value = float(spec.position.sizing_value)
    try:
        price = float(df.iloc[-1]["close"])
    except Exception as exc:  # noqa: BLE001
        raise BotRunnerError(
            f"cannot resolve quantity: last-close lookup failed ({exc})",
        ) from exc
    try:
        return resolve_quantity(
            sizing_kind=sizing_kind,
            sizing_value=sizing_value,
            price=price,
            equity=_REFERENCE_EQUITY_USD,
        )
    except ValueError as exc:
        raise BotRunnerError(f"sizing rejected: {exc}") from exc


async def _resolve_quantity_async(spec: Any, df: Any, broker: Any) -> float:
    """Translate spec.position sizing into a broker-ready qty.

    Delegates to ``strategies.sizing.resolve_quantity`` which validates
    inputs (negative / zero / NaN / out-of-range ``risk_pct`` all raise).
    ``risk_pct`` uses live broker equity via ``_resolve_equity``.
    """
    sizing_kind: SizingKind = spec.position.sizing_kind
    sizing_value = float(spec.position.sizing_value)
    try:
        price = float(df.iloc[-1]["close"])
    except Exception as exc:  # noqa: BLE001
        raise BotRunnerError(
            f"cannot resolve quantity: last-close lookup failed ({exc})",
        ) from exc
    if sizing_kind == "risk_pct":
        equity = await _resolve_equity(broker)
    else:
        equity = _REFERENCE_EQUITY_USD  # unused by fixed_* but pass through
    try:
        return resolve_quantity(
            sizing_kind=sizing_kind,
            sizing_value=sizing_value,
            price=price,
            equity=equity,
        )
    except ValueError as exc:
        # Map sizing validation errors to BotRunnerError so the tick
        # logger reports a clear "skipped" entry instead of a 500.
        raise BotRunnerError(f"sizing rejected: {exc}") from exc


def _has_trade_perm(credential_id: str) -> bool:
    """Return True if the credential exists AND has the ``trade`` perm.

    Lookup order:

    1. ``CredentialStore`` (production path — the vault is the canonical
       source of permissions). Hit + missing-trade → False; hit + trade → True.
    2. ``UnknownCredential`` (no record) → True. The credential might be
       a test fixture or a synthetic broker registered directly via
       ``factory._REGISTRY``; the broker's own ``_require("trade")``
       gate is still the final defense at order-submit time.

    Other unexpected exceptions still fail closed (False) so a brittle
    vault path doesn't silently green-light live trades.

    S4 fix: ``start_all`` consults this helper before respawning a live-mode
    bot so a sidecar restart cannot resurrect a revoked-trade credential.
    H-RT-5: tick path also consults this each iteration so a permission
    revoked while the bot is running converts to a clean ``skipped`` entry
    on the next tick instead of a broker rejection at order-submit time.
    """
    try:
        from showme.brokers import CredentialStore, UnknownCredential
    except Exception as exc:  # noqa: BLE001
        LOG.debug("credential store unavailable: %s", exc)
        return False
    try:
        rec, _ = CredentialStore.fresh().get(credential_id)
    except UnknownCredential:
        # No record in the vault — most often because the broker was
        # registered directly via ``factory.register_broker`` (test
        # fixtures, synthetic adapters). Defer to the broker's own
        # permission check at order-submit time.
        return True
    except Exception as exc:  # noqa: BLE001
        LOG.debug("trade perm lookup for %s failed: %s", credential_id, exc)
        return False
    return "trade" in rec.permissions


class BotRunner:
    """Owns one asyncio.Task per enabled bot."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        # S8 fix: per-bot async lock guards the tick read-modify-write
        # against concurrent CRUD writes from route handlers (PUT/DELETE).
        self._locks: dict[str, asyncio.Lock] = {}
        # C-RUNTIME-5 fix: a single global lock serialises ``start_all``
        # against concurrent invocations so two parallel callers can't
        # both observe ``is_running == False`` and spawn duplicate loops.
        self._start_all_lock: asyncio.Lock = asyncio.Lock()
        self._stopped = False

    def _get_lock(self, bot_id: str) -> asyncio.Lock:
        """Return the per-bot async lock, creating it on first access."""
        lock = self._locks.get(bot_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[bot_id] = lock
        return lock

    def _drop_lock(self, bot_id: str) -> None:
        """H-API-2 fix: evict the per-bot lock after disable/delete so a
        stream of create→delete bots doesn't leak entries forever."""
        self._locks.pop(bot_id, None)

    def is_running(self, bot_id: str) -> bool:
        t = self._tasks.get(bot_id)
        return t is not None and not t.done()

    async def start_all(self, store: BotStore) -> None:
        """Spawn a task for every enabled bot in the store.

        S4 fix: live-mode bots whose credential no longer has ``trade``
        permission are auto-disabled here (with a WARNING).
        C-RUNTIME-5 fix: serialised against concurrent invocations.
        """
        async with self._start_all_lock:
            for meta in store.list():
                if not meta.enabled:
                    continue
                if meta.mode == "live":
                    has_trade = _has_trade_perm(meta.credential_id)
                    if not has_trade:
                        LOG.warning(
                            "bot %s: credential %s no longer has trade perm; auto-disabling",
                            meta.id, meta.credential_id,
                        )
                        async with self._get_lock(meta.id):
                            try:
                                rec = store.get(meta.id)
                                store.save(rec.model_copy(update={"enabled": False}))
                            except UnknownBot:
                                LOG.debug("bot %s disappeared during start_all", meta.id)
                        continue
                if not self.is_running(meta.id):
                    self._spawn(meta.id, store)

    def _spawn(self, bot_id: str, store: BotStore) -> None:
        if self._stopped:
            return
        task = asyncio.create_task(self._run_loop(bot_id, store), name=f"bot:{bot_id}")
        self._tasks[bot_id] = task

    async def enable(self, bot_id: str, store: BotStore) -> BotRecord:
        # Hold the per-bot lock around the read-modify-write so concurrent
        # tick / PUT cannot clobber the enabled flag.
        async with self._get_lock(bot_id):
            rec = store.get(bot_id)
            if not rec.enabled:
                rec = rec.model_copy(update={"enabled": True})
                rec = store.save(rec)
        if not self.is_running(bot_id):
            self._spawn(bot_id, store)
        return rec

    async def disable(self, bot_id: str, store: BotStore) -> BotRecord:
        """Disable a bot and cancel its loop.

        H-RT-2 fix: cancel the asyncio task BEFORE acquiring the per-bot
        lock so a tick that's mid-flight (and holding the lock) doesn't
        force the DELETE UX to wait 5-30s for the tick to release.
        """
        task = self._tasks.pop(bot_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        async with self._get_lock(bot_id):
            try:
                rec = store.get(bot_id)
            except UnknownBot:
                # Bot was deleted concurrently — nothing to disable.
                raise
            if rec.enabled:
                rec = rec.model_copy(update={"enabled": False})
                rec = store.save(rec)
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
        * On a paired exit, appends to closed_trades_log (C4)
        * In live mode, calls broker.submit_order() or close_position()
        """
        async with self._get_lock(bot_id):
            rec = store.get(bot_id)
            if not rec.enabled:
                return None

            # H-RT-5 fix: re-check trade perm every live tick so a runtime
            # revoke converts to a clean ``skipped`` entry on the next tick
            # without ever attempting an order submit.
            if rec.mode == "live" and not _has_trade_perm(rec.credential_id):
                entry = SignalEntry(
                    bar_index=-1, bar_time="", kind="entry",
                    price=0.0, action="skipped",
                    error="credential trade permission missing or revoked",
                )
                try:
                    fresh = store.get(bot_id)
                except UnknownBot:
                    return None
                store.save(fresh.append_signal(entry))
                return entry

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

            # H-RT-6 fix: bot vs strategy timeframe drift produces a clean
            # ``skipped`` entry instead of silently fetching the bot's TF
            # against rules that were authored at a different cadence.
            if spec.timeframe != rec.timeframe:
                entry = SignalEntry(
                    bar_index=-1, bar_time="", kind="entry",
                    price=0.0, action="skipped",
                    error=(
                        f"bot.timeframe={rec.timeframe} ≠ strategy.timeframe={spec.timeframe}; "
                        f"fix one side"
                    ),
                )
                try:
                    fresh = store.get(bot_id)
                except UnknownBot:
                    return None
                store.save(fresh.append_signal(entry))
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

            # C-RUNTIME-2 / H-RT-4 fix: state-aware single-bar evaluator.
            # The runner is the source of truth for ``in_position``; the
            # last entry/exit in signal_log determines current state.
            from showme.strategies.evaluate import evaluate_last_bar
            in_pos = bool(
                rec.last_processed_event is not None
                and rec.last_processed_event.kind == "entry"
                and rec.last_processed_event.action != "skipped"
            )
            last_event = evaluate_last_bar(spec, df, in_position=in_pos)
            if last_event is None:
                return None

            # Deduplicate against the last processed event so a bot that
            # ticks faster than the bar produces one signal per bar at
            # most (idempotency against the same bar_time + kind).
            if (rec.last_processed_event is not None
                    and rec.last_processed_event.bar_time == last_event.bar_time
                    and rec.last_processed_event.kind == last_event.kind):
                return None

            # Route.
            action = "shadow"
            order_id: str | None = None
            error: str | None = None
            filled_qty: float | None = None
            avg_fill_price: float | None = None
            if rec.mode == "live":
                try:
                    order = await self._dispatch_live_order(
                        bot_id=bot_id,
                        broker=broker,
                        spec=spec,
                        rec=rec,
                        event=last_event,
                        df=df,
                    )
                    order_id = order.id if hasattr(order, "id") else str(order)
                    # H-RT-1 partial-fill audit. If the broker came back
                    # with ``filled_quantity`` strictly smaller than the
                    # requested ``quantity``, report the signal as
                    # ``placed`` (the order DID go through) but stash the
                    # diagnostic in the ``error`` field so PERF / UI can
                    # surface it. A fully-rejected IOC (``filled=0``)
                    # downgrades to ``skipped``.
                    fq = getattr(order, "filled_quantity", None)
                    rq = getattr(order, "quantity", None)
                    if fq is not None:
                        filled_qty = float(fq)
                    if avg := getattr(order, "avg_fill_price", None):
                        avg_fill_price = float(avg)
                    if filled_qty is not None and rq is not None:
                        if float(filled_qty) <= 0:
                            action = "skipped"
                            error = f"IOC unfilled (filled=0 of {float(rq)})"
                        elif float(filled_qty) + 1e-9 < float(rq):
                            action = "placed"
                            error = (
                                f"partial fill: {float(filled_qty)} of {float(rq)}"
                            )
                        else:
                            action = "placed"
                    else:
                        action = "placed"
                except Exception as exc:  # noqa: BLE001
                    action = "skipped"
                    error = f"submit failed: {exc}"

            # Resolve quote price for closed-trade pairing. In shadow mode
            # the qty is the strategy's spec qty (so PnL reads end-to-end);
            # in live mode use the actual filled qty when available.
            entry = SignalEntry(
                bar_index=last_event.bar_index,
                bar_time=last_event.bar_time,
                kind=last_event.kind,
                price=last_event.price,
                action=action,
                order_id=order_id,
                error=error,
            )

            try:
                fresh = store.get(bot_id)
            except UnknownBot:
                return None
            new_rec = fresh.append_signal(entry)

            # C4 fix: on a paired exit (in_pos was True at start of tick
            # and event is "exit"), construct a ClosedTrade. The matching
            # entry is the last non-skipped entry on the existing log.
            if (
                entry.kind == "exit"
                and in_pos
                and entry.action != "skipped"
            ):
                matching_entry = _last_non_skipped_entry(fresh.signal_log)
                if matching_entry is not None and matching_entry.price > 0:
                    side: Side = spec.position.side  # type: ignore[assignment]
                    # Choose qty: filled_qty if available, else recomputed
                    # from spec sizing math on the entry price.
                    if filled_qty is not None and filled_qty > 0:
                        qty = float(filled_qty)
                    else:
                        try:
                            equity_hint = (
                                await _resolve_equity(broker)
                                if rec.mode == "live"
                                else _REFERENCE_EQUITY_USD
                            )
                            qty = resolve_quantity(
                                sizing_kind=spec.position.sizing_kind,
                                sizing_value=float(spec.position.sizing_value),
                                price=matching_entry.price,
                                equity=equity_hint,
                            )
                        except (ValueError, Exception):  # noqa: BLE001
                            qty = 0.0
                    pnl = compute_pnl(
                        entry_price=matching_entry.price,
                        exit_price=entry.price,
                        side=side,
                        entry_qty=qty,
                    )
                    closed = ClosedTrade(
                        entry_timestamp=matching_entry.bar_time or matching_entry.timestamp,
                        exit_timestamp=entry.bar_time or entry.timestamp,
                        entry_price=float(matching_entry.price),
                        exit_price=float(entry.price),
                        qty=float(qty),
                        side=side,
                        pnl=float(pnl),
                        bar_index_entry=int(matching_entry.bar_index),
                        bar_index_exit=int(entry.bar_index),
                    )
                    new_rec = new_rec.append_closed_trade(closed)

            store.save(new_rec)
            return entry

    async def _dispatch_live_order(
        self,
        *,
        bot_id: str,
        broker: Any,
        spec: Any,
        rec: BotRecord,
        event: Any,
        df: Any,
    ) -> Any:
        """Submit the live-mode order for ``event`` against ``broker``.

        Returns the broker's :class:`Order` so the caller can audit the
        actual ``filled_quantity`` for partial-fill detection.

        Exit path (C-RUNTIME-4): prefer the broker's ``close_position``
        contract — it knows the position's real qty and won't reverse
        exposure. Fallback for paper / custom adapters that don't expose
        ``close_position`` uses the strategy's sizing math.

        Entry path: open in the strategy's declared direction; qty comes
        from the shared sizing module so a negative / out-of-range value
        raises ``BotRunnerError`` *before* touching the wire.
        """
        from showme.brokers import OrderSide, OrderType, TimeInForce
        # Strategy-declared direction. Prefer the event's side (carries
        # the strategy intent at evaluate-time) then spec.position.side.
        strategy_side = getattr(event, "side", None) or spec.position.side

        if event.kind == "exit":
            close_fn = getattr(broker, "close_position", None)
            if close_fn is not None:
                try:
                    return await close_fn(rec.symbol)
                except Exception as exc:  # noqa: BLE001
                    # Surface as a runner error so the tick records a
                    # ``skipped`` entry with a clear reason — better than
                    # silently falling through to an exposure-flip below.
                    raise BotRunnerError(
                        f"close_position({rec.symbol}) failed: {exc}",
                    ) from exc
            # Fallback: brokers without close_position get the legacy
            # opposite-side market order. C-RUNTIME-4 partial-fix: log a
            # warning and use the same sizing math as entry, NOT raw
            # sizing_value (which conflated qty units across sizing kinds).
            LOG.warning(
                "broker %r has no close_position; falling back to opposite-side "
                "order using strategy sizing for bot %s on %s",
                getattr(broker, "name", "?"), bot_id, rec.symbol,
            )
            opposite_side = (
                OrderSide.SELL if strategy_side == "long" else OrderSide.BUY
            )
            qty = await _resolve_quantity_async(spec, df, broker)
            return await broker.submit_order(
                symbol=rec.symbol,
                side=opposite_side,
                quantity=qty,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.IOC,
                notes=f"bot:{bot_id}:close_fallback",
            )

        # Entry: open a new position in the strategy's declared direction.
        side = OrderSide.BUY if strategy_side == "long" else OrderSide.SELL
        qty = await _resolve_quantity_async(spec, df, broker)
        return await broker.submit_order(
            symbol=rec.symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.IOC,
            notes=f"bot:{bot_id}",
        )


def _last_non_skipped_entry(signal_log: list[SignalEntry]) -> SignalEntry | None:
    """C4 helper: walk the signal log backwards for the most recent
    non-skipped ``kind=='entry'`` event. Used by the tick path to pair
    exits with the matching entry when minting a ``ClosedTrade``.

    The capped FIFO of ``signal_log`` means a very-old entry that paired
    with a very-recent exit could fall off the log; in that pathological
    case we return ``None`` and skip emitting a closed-trade for that
    pairing. The PERF route still has the prior closed-trade history.
    """
    for s in reversed(signal_log):
        if s.kind == "entry" and s.action != "skipped":
            return s
    return None
