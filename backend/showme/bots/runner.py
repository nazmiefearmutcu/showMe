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
* Money-risk campaign 2026-09-05: F1 — live risk-based sizing REFUSES to
  submit on fallback equity; F3 — a zero-fill GTC limit entry is cancelled
  (or classified ``error`` when the cancel fails) instead of silently
  resting on the exchange; F4 — failed (skipped) exits keep ``in_pos`` and
  retry on the next tick; F5 — funding accrues on every in-position tick
  and the accumulator resets on any non-skipped exit; F2 — equity resolves
  in the bot symbol's quote currency via ``broker.account(symbol)``.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any

from showme.bots.ohlcv import BotRunnerError, bar_close_time, fetch_ohlcv
from showme.bots.record import BotRecord, ClosedTrade, SignalEntry
from showme.bots.store import BotStore, UnknownBot
from showme.strategies.sizing import (
    Side,
    SizingKind,
    compute_commission,
    compute_funding_delta,
    compute_pnl,
    resolve_quantity,
)

LOG = logging.getLogger("showme.bots.runner")


# C2 fix: fallback equity when ``broker.account()`` is unavailable / fails.
# A future iteration could pull this from a per-bot equity hint; for now
# this is the documented floor for ``risk_pct`` sizing.
_REFERENCE_EQUITY_USD = 10_000.0


async def _resolve_equity(
    broker: Any, fallback_usd: float = _REFERENCE_EQUITY_USD,
    symbol: str | None = None,
) -> float:
    """Try ``broker.account()['equity']``; fall back to ``fallback_usd``.

    Used by ``_resolve_quantity_async`` for ``risk_pct`` sizing so the
    runner doesn't multiply by a hardcoded $10k anymore. Brokers that
    don't expose ``account()`` (or that throw) fall back transparently.

    Q4 audit H13: fallback path now WARN-level (was DEBUG) so a silent
    $10k assumption can't hide in stdout. Use ``_resolve_equity_with_source``
    to also get a tag (``"broker"`` vs ``"fallback_10k"``).

    F2 fix: when ``symbol`` is given it is threaded into
    ``broker.account(symbol)`` (when the broker accepts it) so a ccxt
    broker resolves equity in the symbol's QUOTE currency instead of the
    numerically-largest balance across all currencies.
    """
    value, _source = await _resolve_equity_with_source(
        broker, fallback_usd, symbol=symbol,
    )
    return value


def _account_accepts_symbol(fn: Any) -> bool:
    """F2 fix: True when ``fn`` accepts a positional symbol argument.

    Signature inspection keeps production ``CcxtBroker.account(symbol)``
    on the quote-currency path while legacy test fakes
    (``async def account()``) and AsyncMocks keep their no-arg contract.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        return False
    for p in sig.parameters.values():
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


async def _resolve_equity_with_source(
    broker: Any, fallback_usd: float = _REFERENCE_EQUITY_USD,
    symbol: str | None = None,
) -> tuple[float, str]:
    """Q4 audit H13: equity + provenance.

    ``source`` ∈ ``{"broker", "fallback_10k"}``. Callers thread this into
    response payloads so UIs can flag a fallback (e.g. yellow badge on
    the dashboard "Sizing using fallback equity").

    F2 fix: ``symbol`` is passed to ``broker.account(symbol)`` when the
    broker's signature accepts it, so the equity comes back in the bot
    symbol's quote currency (CcxtBroker._normalise_account) instead of
    max-across-all-currencies.
    """
    fn = getattr(broker, "account", None)
    if fn is None:
        LOG.warning(
            "broker %r exposes no account(); risk_pct sizing using fallback %s USD",
            getattr(broker, "name", "?"), fallback_usd,
        )
        return float(fallback_usd), "fallback_10k"
    try:
        if symbol is not None and _account_accepts_symbol(fn):
            acct = await fn(symbol)
        else:
            acct = await fn()
    except Exception as exc:  # noqa: BLE001
        LOG.warning(
            "broker.account() failed (%s); using fallback equity %s USD", exc, fallback_usd,
        )
        return float(fallback_usd), "fallback_10k"
    try:
        for k in ("equity", "cash", "buying_power"):
            v = acct.get(k) if isinstance(acct, dict) else None
            if v and float(v) > 0:
                return float(v), "broker"
    except Exception as exc:  # noqa: BLE001
        LOG.debug("account() payload unexpected: %s", exc)
    LOG.warning(
        "broker.account() returned no usable equity; falling back to %s USD",
        fallback_usd,
    )
    return float(fallback_usd), "fallback_10k"


# Q4 audit C4: funding-rate cache (per symbol). 60s TTL.
_FUNDING_CACHE: dict[str, tuple[float, float]] = {}
_FUNDING_TTL_S = 60.0


async def _fetch_funding_rate(broker: Any, symbol: str) -> float:
    """Q4 audit C4: ccxt fetch_funding_rate with 60s cache.

    Returns 0.0 if the broker doesn't expose the function (spot adapters)
    or on any error — funding is a perp/futures concept and a silent
    skip is the right behaviour for spot bots.
    """
    now = time.time()
    cached = _FUNDING_CACHE.get(symbol)
    if cached is not None:
        rate, expires = cached
        if expires > now:
            return rate
    ex = getattr(broker, "_ex", None)
    fn = getattr(ex, "fetch_funding_rate", None) if ex is not None else None
    if fn is None:
        return 0.0
    try:
        result = await fn(symbol)
        rate = float(result.get("fundingRate") or 0.0) if isinstance(result, dict) else 0.0
    except Exception as exc:  # noqa: BLE001
        LOG.debug("fetch_funding_rate(%s) failed: %s", symbol, exc)
        return 0.0
    _FUNDING_CACHE[symbol] = (rate, now + _FUNDING_TTL_S)
    return rate


def _is_real_precision_fn(fn: Any) -> bool:
    """Q4 audit H12: tell a real ccxt precision helper from a MagicMock auto-attr.

    MagicMock auto-creates attributes on access (and ``MagicMock().__float__``
    coerces to 1.0!), so the legacy test brokers that set ``broker._ex =
    MagicMock()`` without an explicit ``amount_to_precision`` mock would
    silently get every qty rounded to 1.0. We accept either:

    1. an attribute explicitly configured on the mock
       (``configure_mock(amount_to_precision=Mock(...))``), or
    2. a callable that's NOT a MagicMock instance (real ccxt).

    Bare MagicMock children get rejected → fall back to 8dp rounding.
    """
    if fn is None or not callable(fn):
        return False
    try:
        from unittest.mock import Mock
        if isinstance(fn, Mock):
            # Mock with no return_value configured (auto-magic): reject.
            try:
                rv = fn._mock_return_value  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                return False
            from unittest.mock import DEFAULT
            return rv is not DEFAULT
    except ImportError:  # pragma: no cover
        pass
    return True


async def _round_qty_to_precision(broker: Any, symbol: str, qty: float) -> float:
    """Q4 audit H12: route qty through ccxt.amount_to_precision when available.

    Falls back to 8-decimal rounding for non-ccxt brokers / unknown
    symbols. The runner calls this BEFORE submit_order so a hostile
    decimal can't pass through unchanged.
    """
    ex = getattr(broker, "_ex", None)
    if ex is None:
        return round(float(qty), 8)
    fn = getattr(ex, "amount_to_precision", None)
    if not _is_real_precision_fn(fn):
        return round(float(qty), 8)
    try:
        return float(fn(symbol, float(qty)))
    except Exception as exc:  # noqa: BLE001
        LOG.debug("amount_to_precision(%s, %s) failed: %s", symbol, qty, exc)
        return round(float(qty), 8)


async def _round_price_to_precision(broker: Any, symbol: str, price: float) -> float:
    """H12: ccxt.price_to_precision wrapper (same pattern as qty)."""
    ex = getattr(broker, "_ex", None)
    if ex is None:
        return round(float(price), 8)
    fn = getattr(ex, "price_to_precision", None)
    if not _is_real_precision_fn(fn):
        return round(float(price), 8)
    try:
        return float(fn(symbol, float(price)))
    except Exception as exc:  # noqa: BLE001
        LOG.debug("price_to_precision(%s, %s) failed: %s", symbol, price, exc)
        return round(float(price), 8)


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
            stop_loss_pct=spec.position.stop_loss_pct,
        )
    except ValueError as exc:
        raise BotRunnerError(f"sizing rejected: {exc}") from exc


async def _resolve_quantity_async(
    spec: Any, df: Any, broker: Any, leverage: float = 1.0,
    equity_override: float | None = None, symbol: str | None = None,
) -> float:
    """Translate spec.position sizing into a broker-ready qty.

    Delegates to ``strategies.sizing.resolve_quantity`` which validates
    inputs (negative / zero / NaN / out-of-range ``risk_pct`` all raise).
    ``risk_pct`` uses live broker equity via ``_resolve_equity``.

    Q4 audit C5: ``leverage`` threaded through so risk_pct and
    risk_per_trade sizing get correct effective notional.

    P1 honesty fix: when ``equity_override`` is provided the internal
    ``_resolve_equity`` call is skipped and the supplied value is used.
    This lets the caller resolve ``broker.account()`` ONCE per tick (via
    ``_resolve_equity_with_source`` for the honesty tag) and thread the
    SAME equity value down here, so the ``equity_source`` tag on the
    SignalEntry always matches the equity actually used to size the order.

    F2 fix: ``symbol`` threads into the internal ``_resolve_equity`` fall-
    back so quote-currency equity is used when no override was supplied.
    """
    sizing_kind: SizingKind = spec.position.sizing_kind
    sizing_value = float(spec.position.sizing_value)
    try:
        price = float(df.iloc[-1]["close"])
    except Exception as exc:  # noqa: BLE001
        raise BotRunnerError(
            f"cannot resolve quantity: last-close lookup failed ({exc})",
        ) from exc
    if sizing_kind in ("risk_pct", "risk_per_trade"):
        equity = (
            float(equity_override)
            if equity_override is not None
            else await _resolve_equity(broker, symbol=symbol)
        )
    else:
        equity = _REFERENCE_EQUITY_USD  # unused by fixed_* but pass through
    try:
        return resolve_quantity(
            sizing_kind=sizing_kind,
            sizing_value=sizing_value,
            price=price,
            equity=equity,
            leverage=leverage,
            stop_loss_pct=spec.position.stop_loss_pct,
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
        # KAOS multibot (2026-09-09): per-bot lane status rows keyed by
        # bot id — {updated_at, rows: [{venue_id, market, bars_age,
        # last_eval, decisions, lane_status}]}. Surfaced by the bot status
        # route via ``kaos_lane_rows``; only ever written by ``_tick_kaos``.
        self._kaos_lanes: dict[str, dict[str, Any]] = {}

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
        self._kaos_lanes.pop(bot_id, None)
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

            # KAOS multibot delegate (2026-09-09): records persisted before
            # the ``engine`` field default to "spec" and keep the EXACT
            # spec-rule path below, untouched. KAOS bots evaluate every
            # configured venue's universe per tick and route each decision
            # through the same dispatch/guards as spec events.
            if (getattr(rec, "engine", "spec") or "spec") == "kaos":
                return await self._tick_kaos(bot_id=bot_id, store=store, rec=rec)

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

            # Validate the strategy spec indicators against the catalog.
            # Ensures manual json tampering / indicator catalog drift doesn't
            # cause silent NaN-bots at runtime.
            try:
                from pathlib import Path
                from showme.indicators.catalog.loader import load_indicator_catalog
                cat_path = Path(__file__).resolve().parents[1] / "indicators" / "catalog" / "indicators.yml"
                cat = load_indicator_catalog(cat_path)
                cat_ids = {e.id for e in cat.entries}
                spec.validate_against_catalog(cat_ids)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("bot %s strategy validation failed: %s", bot_id, exc)
                entry = SignalEntry(
                    bar_index=-1, bar_time="", kind="entry",
                    price=0.0, action="skipped",
                    error=f"strategy validation failed: {exc}",
                )
                try:
                    fresh = store.get(bot_id)
                except UnknownBot:
                    return None
                store.save(fresh.append_signal(entry))
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
            # F4/M1 companion: a SKIPPED exit means the close submit
            # failed — the position is still OPEN. Keep ``in_pos`` True
            # (and recover the original entry for price/qty math) instead
            # of dropping the bot to flat state, which would make the
            # failed exit un-retryable. ``in_pos_entry`` is the entry
            # event that opened the position we (still) hold.
            in_pos_entry: SignalEntry | None = None
            last_ev = rec.last_processed_event
            if (last_ev is not None and last_ev.kind == "entry"
                    and last_ev.action != "skipped"):
                in_pos_entry = last_ev
            elif (last_ev is not None and last_ev.kind == "exit"
                    and last_ev.action == "skipped"):
                in_pos_entry = _last_non_skipped_entry(rec.signal_log)
            in_pos = in_pos_entry is not None
            # Q4 audit C9: pass open-position entry price so evaluate_last_bar
            # can run an intrabar SL/TP check before the rule-based exit.
            entry_price_for_eval: float | None = None
            if in_pos_entry is not None:
                # Prefer broker-confirmed fill price; fall back to signal price.
                entry_price_for_eval = float(
                    in_pos_entry.fill_price or in_pos_entry.price
                )
            last_event = evaluate_last_bar(
                spec, df, in_position=in_pos,
                entry_price=entry_price_for_eval,
            )

            # Q4 audit C4 / F5 fix: accrue funding on ANY tick while in
            # position — including ticks that produce a signal — so the
            # bars around trades don't systematically undercount. Spot
            # symbols and non-perp brokers return 0.0 (no-op).
            if in_pos and in_pos_entry is not None:
                funding_rate = await _fetch_funding_rate(broker, rec.symbol)
                if funding_rate != 0.0 and in_pos_entry.qty:
                    entry_px_funding = float(
                        in_pos_entry.fill_price or in_pos_entry.price
                    )
                    notional = entry_px_funding * float(in_pos_entry.qty)
                    delta = compute_funding_delta(
                        position_notional=notional,
                        funding_rate=funding_rate,
                        dt_seconds=float(rec.tick_interval_seconds),
                        side=spec.position.side,
                    )
                    if delta != 0.0:
                        try:
                            fresh_f = store.get(bot_id)
                        except UnknownBot:
                            return None
                        new_cum = float(fresh_f.cumulative_funding_pnl) + delta
                        store.save(fresh_f.model_copy(update={
                            "cumulative_funding_pnl": new_cum,
                        }))

            if last_event is None:
                return None

            # Deduplicate against the last processed event so a bot that
            # ticks faster than the bar produces one signal per bar at
            # most (idempotency against the same bar_time + kind).
            # F4/M1 fix: the short-circuit only applies when the last
            # event was NOT skipped — or the kind is an entry. Failed
            # (skipped) EXITS retry on the next tick while the exit
            # condition persists; failed ENTRIES stay deduped
            # (resubmit-storm protection).
            if (rec.last_processed_event is not None
                    and rec.last_processed_event.bar_time == last_event.bar_time
                    and rec.last_processed_event.kind == last_event.kind
                    and (rec.last_processed_event.action != "skipped"
                         or last_event.kind == "entry")):
                return None

            # Route.
            action = "shadow"
            order_id: str | None = None
            error: str | None = None
            filled_qty: float | None = None
            avg_fill_price: float | None = None
            # H13 honesty: provenance of the equity used to size a LIVE
            # order. Threaded onto the SignalEntry so the UI can flag a
            # fallback-equity-sized order. Shadow entries leave this None.
            equity_source: str | None = None
            # P1 honesty fix: resolve broker equity ONCE per tick (for
            # risk-based sizing) and thread the resolved VALUE into the
            # dispatch path so ``broker.account()`` is hit a single time and
            # the ``equity_source`` tag matches the equity used to size.
            equity_for_sizing: float | None = None
            if rec.mode == "live":
                # Resolve the equity source for sizing-aware honesty tagging.
                # Only risk-based sizing consults broker equity; fixed_* sizing
                # ignores it, so leave the tag None for those kinds.
                if spec.position.sizing_kind in ("risk_pct", "risk_per_trade"):
                    try:
                        equity_for_sizing, equity_source = (
                            await _resolve_equity_with_source(
                                broker, symbol=rec.symbol,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        LOG.debug("equity source resolve failed: %s", exc)
                        equity_source = None
                        equity_for_sizing = None
                    # F1/H5 fix: fail CLOSED on fallback equity. A transient
                    # broker outage must not silently substitute $10k for
                    # real equity on the input that determines live position
                    # size — refuse the order instead. (Exits are NOT gated
                    # here: blocking a close on an equity blip would strand
                    # the position; close_position sizes from the live
                    # position, not from equity.)
                    if equity_source != "broker" and last_event.kind == "entry":
                        entry = SignalEntry(
                            bar_index=last_event.bar_index,
                            bar_time=last_event.bar_time,
                            kind=last_event.kind,
                            price=last_event.price,
                            action="skipped",
                            error=(
                                "live sizing refused: broker equity unavailable "
                                f"(equity_source={equity_source})"
                            ),
                            bar_close_time=bar_close_time(
                                last_event.bar_time, rec.timeframe,
                            ),
                            reason=getattr(last_event, "reason", None),
                            equity_source=equity_source,
                        )
                        try:
                            fresh = store.get(bot_id)
                        except UnknownBot:
                            return None
                        store.save(fresh.append_signal(entry))
                        return entry
                action, order_id, error, filled_qty, avg_fill_price = (
                    await self._submit_live_and_audit(
                        bot_id=bot_id, broker=broker, spec=spec, rec=rec,
                        event=last_event, df=df,
                        equity_for_sizing=equity_for_sizing,
                    )
                )

            # Resolve quote price for closed-trade pairing. In shadow mode
            # the qty is the strategy's spec qty (so PnL reads end-to-end);
            # in live mode use the actual filled qty when available.
            # Q4 audit H17: persist qty on every entry so exit pairing
            # uses the entry-time qty (not a recompute on current equity).
            persisted_qty: float | None = None
            if last_event.kind == "entry":
                if filled_qty is not None and filled_qty > 0:
                    persisted_qty = float(filled_qty)
                else:
                    # Pre-compute qty so PnL reads correctly downstream. In
                    # live mode, reuse the equity resolved once above so this
                    # does NOT trigger a second ``broker.account()`` round-trip
                    # (P1) — the persisted qty is then sized on the very same
                    # equity that was tagged onto the entry.
                    try:
                        persisted_qty = await _resolve_quantity_async(
                            spec, df, broker, leverage=float(rec.leverage),
                            equity_override=equity_for_sizing,
                            symbol=rec.symbol,
                        )
                    except (BotRunnerError, Exception):  # noqa: BLE001
                        persisted_qty = None
            entry = SignalEntry(
                bar_index=last_event.bar_index,
                bar_time=last_event.bar_time,
                kind=last_event.kind,
                price=last_event.price,
                action=action,
                order_id=order_id,
                error=error,
                fill_price=avg_fill_price,
                qty=persisted_qty,
                bar_close_time=bar_close_time(last_event.bar_time, rec.timeframe),
                reason=getattr(last_event, "reason", None),
                equity_source=equity_source,
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
                # F5/M2 fix: the position is gone as of ANY non-skipped
                # exit. Reset the funding accumulator HERE — not inside
                # the successful-pairing branch — so a failed pairing
                # (entry fell off the 100-cap FIFO / price<=0) can no
                # longer leak this position's funding into the next
                # round-trip's net_pnl/funding_paid.
                new_rec = new_rec.model_copy(update={"cumulative_funding_pnl": 0.0})
                matching_entry = _last_non_skipped_entry(fresh.signal_log)
                if matching_entry is not None and matching_entry.price > 0:
                    side: Side = spec.position.side  # type: ignore[assignment]
                    # Q4 audit H17: prefer the persisted entry qty (set at
                    # entry-time on running equity); only recompute if the
                    # entry was minted before this fix landed.
                    if filled_qty is not None and filled_qty > 0:
                        qty = float(filled_qty)
                    elif matching_entry.qty is not None and matching_entry.qty > 0:
                        qty = float(matching_entry.qty)
                    else:
                        try:
                            # P1: reuse the equity resolved once this tick when
                            # available so an exit tick doesn't fire a second
                            # broker.account() round-trip for the PnL-qty
                            # recompute. Falls back only for legacy/fixed paths.
                            if rec.mode == "live":
                                equity_hint = (
                                    float(equity_for_sizing)
                                    if equity_for_sizing is not None
                                    else await _resolve_equity(
                                        broker, symbol=rec.symbol,
                                    )
                                )
                            else:
                                equity_hint = _REFERENCE_EQUITY_USD
                            qty = resolve_quantity(
                                sizing_kind=spec.position.sizing_kind,
                                sizing_value=float(spec.position.sizing_value),
                                price=matching_entry.price,
                                equity=equity_hint,
                                leverage=float(rec.leverage),
                                stop_loss_pct=spec.position.stop_loss_pct,
                            )
                        except (ValueError, Exception):  # noqa: BLE001
                            qty = 0.0
                    # Prefer broker-confirmed fill price for both legs.
                    entry_px_pnl = float(matching_entry.fill_price or matching_entry.price)
                    exit_px_pnl = float(entry.fill_price or entry.price)
                    pnl = compute_pnl(
                        entry_price=entry_px_pnl,
                        exit_price=exit_px_pnl,
                        side=side,
                        entry_qty=qty,
                    )
                    # Q4 audit C3: commission deduction.
                    commission = compute_commission(
                        entry_price=entry_px_pnl, exit_price=exit_px_pnl,
                        qty=qty, commission_rate=float(rec.commission_rate),
                    )
                    # Q4 audit C4: pull accumulated funding from BotRecord.
                    funding = float(fresh.cumulative_funding_pnl)
                    net = float(pnl) - commission - funding
                    closed = ClosedTrade(
                        entry_timestamp=matching_entry.bar_time or matching_entry.timestamp,
                        exit_timestamp=entry.bar_time or entry.timestamp,
                        entry_price=entry_px_pnl,
                        exit_price=exit_px_pnl,
                        qty=float(qty),
                        side=side,
                        pnl=float(pnl),
                        bar_index_entry=int(matching_entry.bar_index),
                        bar_index_exit=int(entry.bar_index),
                        commission_paid=float(commission),
                        funding_paid=float(funding),
                        net_pnl=float(net),
                        exit_reason=getattr(entry, "reason", None) or "rule",
                    )
                    new_rec = new_rec.append_closed_trade(closed)
                    # (F5 fix: the funding-accumulator reset moved above —
                    # it now fires on ANY non-skipped exit, paired or not.)

            store.save(new_rec)
            return entry

    async def _submit_live_and_audit(
        self,
        *,
        bot_id: str,
        broker: Any,
        spec: Any,
        rec: BotRecord,
        event: Any,
        df: Any,
        equity_for_sizing: float | None = None,
    ) -> tuple[str, str | None, str | None, float | None, float | None]:
        """Submit the live-mode order for ``event`` and audit the fill.

        Shared by the spec path (``tick``) and the KAOS delegate
        (``_tick_kaos``) so BOTH engines flow through the SAME dispatch and
        the same H-RT-1 partial-fill / F3 GTC zero-fill-cancel guards.

        Returns ``(action, order_id, error, filled_qty, avg_fill_price)``.
        """
        action = "placed"
        order_id: str | None = None
        error: str | None = None
        filled_qty: float | None = None
        avg_fill_price: float | None = None
        try:
            order = await self._dispatch_live_order(
                bot_id=bot_id,
                broker=broker,
                spec=spec,
                rec=rec,
                event=event,
                df=df,
                equity_override=equity_for_sizing,
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
                    from showme.brokers import OrderType, TimeInForce
                    otype = getattr(order, "order_type", None)
                    tif = getattr(order, "time_in_force", None)
                    if otype == OrderType.LIMIT and tif == TimeInForce.GTC:
                        # F3/H4 fix: the limit path submits GTC — a
                        # zero-fill leaves a REAL resting order on
                        # the exchange. Attempt a cancel; if the
                        # cancel fails or the broker can't cancel,
                        # the possibly-resting order must stay
                        # VISIBLE: classify ``error`` (not
                        # ``skipped``). Downstream state checks
                        # treat the non-skipped entry as position-
                        # affecting, so no new entry resubmits on
                        # top of the unknown order.
                        cancel_fn = getattr(broker, "cancel_order", None)
                        cancelled = False
                        if cancel_fn is not None and order_id:
                            try:
                                cancelled = bool(
                                    await cancel_fn(str(order_id)),
                                )
                            except Exception as canc_exc:  # noqa: BLE001
                                LOG.warning(
                                    "bot %s: cancel of unfilled GTC "
                                    "limit %s failed: %s",
                                    bot_id, order_id, canc_exc,
                                )
                        if cancelled:
                            action = "skipped"
                            error = "GTC unfilled — cancelled"
                        else:
                            action = "error"
                            error = (
                                "GTC limit zero-fill; cancel failed or "
                                "unavailable — order may rest on "
                                f"exchange (id={order_id})"
                            )
                    else:
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
        return action, order_id, error, filled_qty, avg_fill_price

    # ---- KAOS multibot delegate (2026-09-09 campaign) -------------------

    def kaos_lane_rows(self, bot_id: str, venues: Any) -> list[dict[str, Any]]:
        """Per-venue status rows for a KAOS bot's status payload.

        Merges the latest tick's lane state with the record's configured
        venues; a venue never evaluated yet reports ``lane_status="idle"``
        (honest: the runner has nothing measured for it).
        """
        state = self._kaos_lanes.get(bot_id) or {}
        latest = {r.get("venue_id"): dict(r) for r in state.get("rows", [])}
        out: list[dict[str, Any]] = []
        for v in venues or []:
            vid = v.get("id") if isinstance(v, dict) else getattr(v, "id", "?")
            market = (
                v.get("market") if isinstance(v, dict)
                else getattr(v, "market", "")
            )
            row = latest.get(vid)
            if row is None:
                row = {
                    "venue_id": vid, "market": market, "bars_age": None,
                    "last_eval": None, "decisions": 0, "lane_status": "idle",
                }
            out.append(row)
        return out

    @staticmethod
    def _kaos_position_state(rec: BotRecord) -> dict[str, dict[str, Any]]:
        """Per-symbol open-position state from the signal log (KAOS bots).

        Mirrors the spec path convention: the last non-skipped event per
        symbol decides state — an ``entry`` opens a position (remembering
        its side/price/qty), an ``exit`` (or a SKIPPED exit being retried,
        F4) keeps it until a non-skipped exit lands.
        """
        out: dict[str, dict[str, Any]] = {}
        for s in rec.signal_log:
            if s.action == "skipped" or not s.symbol:
                continue
            if s.kind == "entry":
                out[s.symbol] = {
                    "entry": s,
                    "side": s.side or "long",
                }
            elif s.kind == "exit":
                out.pop(s.symbol, None)
        return out

    async def _tick_kaos(
        self, *, bot_id: str, store: BotStore, rec: BotRecord,
    ) -> SignalEntry | None:
        """Single KAOS iteration: evaluate every venue's universe, route
        each decision through the EXISTING dispatch.

        Per-venue isolation: one venue failing (broker missing, bar fetch
        error, evaluation error) can never block the other venue — each
        stage is guarded and the lane status row records the honest state.
        """
        from showme.bots.kaos.adapter import evaluate as kaos_evaluate
        from showme.bots.kaos.config import default_config as kaos_default_config

        # Sizing source: the bound strategy spec (same sizing semantics as
        # spec bots — fixed_quote etc. through the shared sizing module).
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
        except ValueError as exc:
            entry = SignalEntry(bar_index=-1, bar_time="", kind="entry",
                                price=0.0, action="skipped",
                                error=f"strategy unavailable: {exc}")
            store.save(rec.append_signal(entry))
            return entry

        venues = list(rec.venues or [])
        if not venues:
            entry = SignalEntry(bar_index=-1, bar_time="", kind="entry",
                                price=0.0, action="skipped",
                                error="kaos bot has no venues configured")
            store.save(rec.append_signal(entry))
            return entry

        from datetime import datetime, timezone
        from showme.brokers import factory as factory_mod

        cfg = kaos_default_config()
        pos_state = self._kaos_position_state(rec)
        lane_rows: list[dict[str, Any]] = []
        last_entry: SignalEntry | None = None

        # F5 parity: funding accrues on ANY in-position tick for perp
        # symbols (spot / Alpaca brokers return 0.0 — honest no-op). The
        # side comes from the held entry so shorts accrue sign-correct.
        for sym, st in list(pos_state.items()):
            held_entry: SignalEntry | None = st.get("entry")
            venue_id = getattr(held_entry, "venue_id", None)
            held_venue = next(
                (v for v in venues if getattr(v, "id", None) == venue_id),
                None,
            )
            if held_venue is None or held_entry is None:
                continue
            if not held_entry.qty or held_entry.qty <= 0:
                continue
            try:
                held_broker = factory_mod.get_broker(
                    f"{held_venue.exchange_id}:{rec.credential_id}",
                )
            except KeyError:
                continue
            funding_rate = await _fetch_funding_rate(held_broker, sym)
            if funding_rate == 0.0:
                continue
            notional = float(held_entry.fill_price or held_entry.price) * float(held_entry.qty)
            delta = compute_funding_delta(
                position_notional=notional,
                funding_rate=funding_rate,
                dt_seconds=float(rec.tick_interval_seconds),
                side=st.get("side") or "long",
            )
            if delta != 0.0:
                try:
                    fresh_f = store.get(bot_id)
                except UnknownBot:
                    return None
                store.save(fresh_f.model_copy(update={
                    "cumulative_funding_pnl":
                        float(fresh_f.cumulative_funding_pnl) + delta,
                }))

        for venue in venues:
            row: dict[str, Any] = {
                "venue_id": venue.id, "market": venue.market,
                "bars_age": None, "last_eval": None, "decisions": 0,
                "lane_status": rec.mode,
            }
            broker_name = f"{venue.exchange_id}:{rec.credential_id}"
            try:
                broker = factory_mod.get_broker(broker_name)
            except KeyError as exc:
                LOG.debug("bot %s: venue %s broker %s missing: %s",
                          bot_id, venue.id, broker_name, exc)
                row["lane_status"] = (
                    "PAPER (no Alpaca keys)" if venue.market == "us-equities"
                    else "broker unavailable"
                )
                lane_rows.append(row)
                continue

            bars_by_symbol: dict[str, Any] = {}
            newest_bar_ms = 0
            held_symbols = set(pos_state or ())
            for sym in venue.symbols:
                try:
                    # R2 M-1 fix: 512 bars (vs 200) so a held symbol's entry
                    # bar stays inside the evaluation window across a multi-
                    # hour outage; the honest "held-unresolved" note below
                    # covers anything that still falls outside it.
                    df = await fetch_ohlcv(broker, sym, rec.timeframe, limit=512)
                except BotRunnerError as exc:
                    LOG.debug("bot %s: venue %s bar fetch failed for %s: %s",
                              bot_id, venue.id, sym, exc)
                    continue
                if df.empty:
                    continue
                bars_by_symbol[sym] = df
                try:
                    bar_ms = int(df.index[-1].value // 1_000_000)
                except Exception:  # noqa: BLE001
                    bar_ms = 0
                newest_bar_ms = max(newest_bar_ms, bar_ms)

            if not bars_by_symbol:
                row["lane_status"] = (
                    "PAPER (no Alpaca keys) — bars unavailable"
                    if venue.market == "us-equities" else "bars unavailable"
                )
                lane_rows.append(row)
                continue

            # R2 M-1 fix (honesty): a HELD symbol whose bars never arrived
            # cannot be exited by the evaluator this tick — say so instead
            # of silently skipping it.
            unresolved = sorted(held_symbols - set(bars_by_symbol))
            held_note = ""
            if unresolved:
                held_note = (
                    f" — held-unresolved ({', '.join(unresolved[:5])}"
                    + ("…" if len(unresolved) > 5 else "") + ")"
                )
                row["lane_status"] = held_note.strip(" —")

            try:
                decisions = kaos_evaluate(
                    bars_by_symbol, venue, cfg,
                    in_position_by_symbol=pos_state,
                )
            except Exception as exc:  # noqa: BLE001
                LOG.warning("bot %s: venue %s evaluation failed: %s",
                            bot_id, venue.id, exc)
                row["lane_status"] = "evaluation error"
                lane_rows.append(row)
                continue

            now = time.time()
            row["decisions"] = len(decisions)
            row["last_eval"] = datetime.now(tz=timezone.utc).isoformat()
            if newest_bar_ms:
                row["bars_age"] = max(0.0, now * 1000.0 - newest_bar_ms) / 1000.0
            if venue.market == "us-equities" and rec.mode != "live":
                # Keys ARE attached (a broker resolved), but the bot has
                # never been user-flipped to live: the equity lane is a
                # shadow evaluation on real bars, never a real order.
                row["lane_status"] = "shadow (paper fills)" + held_note
            elif held_note:
                row["lane_status"] = row["lane_status"] + held_note
            lane_rows.append(row)

            for dec in decisions:
                dec_df = bars_by_symbol.get(dec.symbol)
                if dec_df is None:
                    # Defensive: an evaluation returning a decision for a
                    # symbol it was given no bars for is a contract
                    # violation — skip it, never route blind.
                    LOG.warning(
                        "bot %s: venue %s decision for %s has no bars; skipped",
                        bot_id, venue.id, dec.symbol,
                    )
                    continue
                last_entry = await self._route_kaos_decision(
                    bot_id=bot_id, store=store, rec=rec, spec=spec,
                    broker=broker, dec=dec, df=dec_df,
                    pos_state=pos_state,
                )
                if last_entry is not None:
                    try:
                        rec = store.get(bot_id)
                    except UnknownBot:
                        return last_entry

        self._kaos_lanes[bot_id] = {"updated_at": datetime.now(
            tz=timezone.utc).isoformat(), "rows": lane_rows}
        return last_entry

    async def _route_kaos_decision(
        self,
        *,
        bot_id: str,
        store: BotStore,
        rec: BotRecord,
        spec: Any,
        broker: Any,
        dec: Any,
        df: Any,
        pos_state: dict[str, dict[str, Any]],
    ) -> SignalEntry | None:
        """Route ONE KAOS decision through the existing dispatch.

        Same guards as the spec path: same-bar dedup against the last
        processed event, F1 live fail-closed sizing, the shared
        ``_submit_live_and_audit`` dispatch, per-entry qty persistence and
        closed-trade pairing. Symbol provenance (``symbol`` / ``venue_id`` /
        ``side``) rides on the SignalEntry so feed/PERF stay honest.
        """
        held = pos_state.get(dec.symbol)
        if dec.kind == "entry" and held is not None:
            return None
        if dec.kind == "exit" and held is None:
            return None

        # Same-bar dedup: the same decision (bar_time + kind + symbol) is
        # never double-processed, matching the spec path's idempotency rule
        # (failed exits retry; failed entries stay deduped).
        lpe = rec.last_processed_event
        if (lpe is not None and lpe.symbol == dec.symbol
                and lpe.bar_time == dec.bar_time and lpe.kind == dec.kind
                and (lpe.action != "skipped" or dec.kind == "entry")):
            return None

        action = "shadow"
        order_id: str | None = None
        error: str | None = None
        filled_qty: float | None = None
        avg_fill_price: float | None = None
        equity_source: str | None = None
        equity_for_sizing: float | None = None

        # Per-symbol record view so the SHARED dispatch submits the
        # decision's symbol (the record's own symbol is only a placeholder
        # for multibot records). model_copy skips validators on purpose:
        # ccxt perp symbols ("BTC/USDT:USDT") carry a colon.
        # R2 M-2 fix: RegT equity venues are NEVER levered — force
        # leverage=1.0 on the copy so BOTH the live order sizing and the
        # qty persistence below read 1.0 for "equity" risk profiles.
        _dec_venue = next(
            (v for v in (rec.venues or [])
             if getattr(v, "id", None) == getattr(dec, "venue_id", None)),
            None,
        )
        _kaos_updates: dict[str, Any] = {"symbol": dec.symbol}
        if getattr(_dec_venue, "risk_profile", "") == "equity":
            _kaos_updates["leverage"] = 1.0
        rec_for_symbol = rec.model_copy(update=_kaos_updates)
        event = _KaosEventView(dec)

        if rec.mode == "live":
            if spec.position.sizing_kind in ("risk_pct", "risk_per_trade"):
                try:
                    equity_for_sizing, equity_source = (
                        await _resolve_equity_with_source(
                            broker, symbol=dec.symbol,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    LOG.debug("equity source resolve failed: %s", exc)
                    equity_source = None
                    equity_for_sizing = None
                # F1 (fail-closed): no real equity — no live entry. Exits
                # are not gated (a close must never strand a position).
                if equity_source != "broker" and dec.kind == "entry":
                    entry = SignalEntry(
                        bar_index=dec.bar_index, bar_time=dec.bar_time,
                        kind=dec.kind, price=dec.price, action="skipped",
                        error=(
                            "live sizing refused: broker equity unavailable "
                            f"(equity_source={equity_source})"
                        ),
                        bar_close_time=bar_close_time(dec.bar_time, rec.timeframe),
                        reason=dec.reason,
                        equity_source=equity_source,
                        symbol=dec.symbol, venue_id=dec.venue_id, side=dec.side,
                    )
                    try:
                        fresh = store.get(bot_id)
                    except UnknownBot:
                        return None
                    store.save(fresh.append_signal(entry))
                    return entry
            action, order_id, error, filled_qty, avg_fill_price = (
                await self._submit_live_and_audit(
                    bot_id=bot_id, broker=broker, spec=spec,
                    rec=rec_for_symbol, event=event, df=df,
                    equity_for_sizing=equity_for_sizing,
                )
            )

        # Persist entry qty (shadow: spec sizing; live: actual fill when
        # available) so exit pairing reads the entry-time qty (H17).
        persisted_qty: float | None = None
        if dec.kind == "entry":
            if filled_qty is not None and filled_qty > 0:
                persisted_qty = float(filled_qty)
            else:
                try:
                    # R2 M-2 fix: size on the per-symbol view (equity venues
                    # carry leverage=1.0 there — never the record's default).
                    persisted_qty = await _resolve_quantity_async(
                        spec, df, broker,
                        leverage=float(rec_for_symbol.leverage),
                        equity_override=equity_for_sizing,
                        symbol=dec.symbol,
                    )
                except (BotRunnerError, Exception):  # noqa: BLE001
                    persisted_qty = None

        entry = SignalEntry(
            bar_index=dec.bar_index,
            bar_time=dec.bar_time,
            kind=dec.kind,
            price=dec.price,
            action=action,
            order_id=order_id,
            error=error,
            fill_price=avg_fill_price,
            qty=persisted_qty,
            bar_close_time=bar_close_time(dec.bar_time, rec.timeframe),
            reason=dec.reason,
            equity_source=equity_source,
            symbol=dec.symbol,
            venue_id=dec.venue_id,
            side=dec.side,
        )

        try:
            fresh = store.get(bot_id)
        except UnknownBot:
            return None
        new_rec = fresh.append_signal(entry)

        # Closed-trade pairing on a non-skipped exit (same-symbol entry).
        if dec.kind == "exit" and held is not None and entry.action != "skipped":
            new_rec = new_rec.model_copy(
                update={"cumulative_funding_pnl": 0.0},
            )
            matching_entry = None
            for s in reversed(fresh.signal_log):
                if (s.kind == "entry" and s.action != "skipped"
                        and s.symbol == dec.symbol):
                    matching_entry = s
                    break
            if matching_entry is not None and matching_entry.price > 0:
                side: Side = dec.side  # decision truth: the held side
                if filled_qty is not None and filled_qty > 0:
                    qty = float(filled_qty)
                elif matching_entry.qty is not None and matching_entry.qty > 0:
                    qty = float(matching_entry.qty)
                else:
                    qty = 0.0
                entry_px_pnl = float(matching_entry.fill_price or matching_entry.price)
                exit_px_pnl = float(entry.fill_price or entry.price)
                pnl = compute_pnl(
                    entry_price=entry_px_pnl, exit_price=exit_px_pnl,
                    side=side, entry_qty=qty,
                )
                commission = compute_commission(
                    entry_price=entry_px_pnl, exit_price=exit_px_pnl,
                    qty=qty, commission_rate=float(rec.commission_rate),
                )
                funding = float(fresh.cumulative_funding_pnl)
                net = float(pnl) - commission - funding
                closed = ClosedTrade(
                    entry_timestamp=matching_entry.bar_time or matching_entry.timestamp,
                    exit_timestamp=entry.bar_time or entry.timestamp,
                    entry_price=entry_px_pnl,
                    exit_price=exit_px_pnl,
                    qty=float(qty),
                    side=side,
                    pnl=float(pnl),
                    bar_index_entry=int(matching_entry.bar_index),
                    bar_index_exit=int(entry.bar_index),
                    commission_paid=float(commission),
                    funding_paid=float(funding),
                    net_pnl=float(net),
                    exit_reason=dec.reason or "kaos_exit",
                )
                new_rec = new_rec.append_closed_trade(closed)

        store.save(new_rec)

        # Keep the per-symbol position book coherent for the rest of tick.
        if dec.kind == "entry":
            pos_state[dec.symbol] = {"entry": entry, "side": dec.side}
        else:
            pos_state.pop(dec.symbol, None)
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
        equity_override: float | None = None,
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

        P1 honesty fix: ``equity_override`` is threaded into the sizing
        calls so risk-based sizing reuses the equity the caller already
        resolved (and tagged) this tick — ``broker.account()`` is called
        exactly once, so the ``equity_source`` tag matches the sized qty.
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
            matching_entry = _last_non_skipped_entry(rec.signal_log)
            if matching_entry is not None and matching_entry.qty is not None and matching_entry.qty > 0:
                qty = matching_entry.qty
            else:
                qty = await _resolve_quantity_async(
                    spec, df, broker, leverage=float(rec.leverage),
                    equity_override=equity_override, symbol=rec.symbol,
                )
            qty = await _round_qty_to_precision(broker, rec.symbol, qty)
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
        qty = await _resolve_quantity_async(
            spec, df, broker, leverage=float(rec.leverage),
            equity_override=equity_override, symbol=rec.symbol,
        )
        # Q4 audit H12: ccxt lot/tick precision rounding before submit.
        qty = await _round_qty_to_precision(broker, rec.symbol, qty)
        # Q4 audit H10: honour entry_order_type. Limit / stop_limit fall back
        # to MARKET when limit_price_offset_pct is missing or non-positive.
        entry_order_type_str = getattr(spec.position, "entry_order_type", "market")
        offset_pct = float(getattr(spec.position, "limit_price_offset_pct", 0.0) or 0.0)
        last_close = float(df.iloc[-1]["close"])
        if entry_order_type_str == "limit" and offset_pct > 0:
            # Long limit goes BELOW close (buy lower); short above.
            if strategy_side == "long":
                limit_px = last_close * (1.0 - offset_pct / 100.0)
            else:
                limit_px = last_close * (1.0 + offset_pct / 100.0)
            limit_px = await _round_price_to_precision(broker, rec.symbol, limit_px)
            return await broker.submit_order(
                symbol=rec.symbol,
                side=side,
                quantity=qty,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.GTC,
                limit_price=limit_px,
                notes=f"bot:{bot_id}",
            )
        return await broker.submit_order(
            symbol=rec.symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.IOC,
            notes=f"bot:{bot_id}",
        )


class _KaosEventView:
    """Minimal Event-like view over a KAOS decision for the shared dispatch.

    Exposes exactly the attributes ``_dispatch_live_order`` reads (``kind``,
    ``side``; plus ``price`` / ``bar_time`` for diagnostics). KAOS decisions
    therefore flow through the EXISTING dispatch unchanged.
    """

    __slots__ = ("kind", "side", "price", "bar_index", "bar_time", "reason")

    def __init__(self, dec: Any) -> None:
        self.kind = dec.kind
        self.side = dec.side
        self.price = dec.price
        self.bar_index = dec.bar_index
        self.bar_time = dec.bar_time
        self.reason = dec.reason


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
