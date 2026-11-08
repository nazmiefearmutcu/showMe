"""EMSX, AIM, TSOX, FXGO, BBGT, TCA — trade function suite."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.broker import (
    BrokerOrder, OrderSide, OrderType, TimeInForce
)
from showme.engine.core.instrument import AssetClass, Instrument

LOG = logging.getLogger("showme.engine.functions.trade")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fx_now_utc() -> datetime:
    """Current UTC time for FX quote-age checks (a seam tests can pin)."""
    return datetime.now(timezone.utc)


def _select_broker(deps: Any, asset_class: AssetClass) -> Any:
    """Map asset class → broker adapter from deps."""
    pref = {
        AssetClass.CRYPTO: "binance_broker",
        AssetClass.EQUITY: "alpaca_broker",
        AssetClass.ETF: "alpaca_broker",
        AssetClass.FX: "oanda_broker",
        AssetClass.BOND: "ibkr_broker",
        AssetClass.COMMODITY: "ibkr_broker",
        AssetClass.DERIVATIVE: "ibkr_broker",
    }
    return getattr(deps, pref.get(asset_class, "binance_broker"), None)


@FunctionRegistry.register
class EMSXFunction(BaseFunction):
    """EMSX — Execution Management."""
    code = "EMSX"
    name = "Execution Management"
    category = "trade"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_required",
                    "reason": f"{self.code} ticket requires a symbol before preview or submit.",
                    "broker": "paper",
                    "next_actions": [
                        "Pass ?symbol=... (e.g. ?symbol=EURUSD for FXGO).",
                        "Or set a symbol via the ticket controls in the workspace.",
                    ],
                },
                sources=["paper_ticket"],
                metadata={"preview_only": True},
            )
        quantity = _float_param(params.get("quantity"))
        side = str(params.get("side", "BUY")).upper()
        order_type = str(params.get("type", params.get("order_type", "MARKET"))).upper()
        tif = str(params.get("tif", params.get("time_in_force", "GTC"))).upper()
        submit = _truthy(params.get("submit"))
        # BBGT/C + EMSX guard (campaign 2026-09-11 F9): the manifests declare
        # ``paper_mode`` as a REQUIRED boolean defaulting True ("safe-by-default
        # rebuild contract"), but the engine never read the parameter — an API
        # or agent caller passing ``submit=true`` went straight to a live
        # broker order. Enforce it here at the single shared boundary:
        #   * paper_mode absent / True / any non-explicit-false value → paper;
        #   * only an explicit False arms the submit path, and even then a
        #     broker adapter must exist or we refuse (provider_unavailable).
        paper_mode = _paper_mode_enabled(params.get("paper_mode"))
        live_armed = submit and not paper_mode
        if quantity <= 0:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_required",
                    "reason": "Trade ticket needs a positive quantity before it can be previewed or submitted.",
                    "broker": "paper",
                    "symbol": instrument.symbol,
                    "asset_class": instrument.asset_class.value,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "time_in_force": tif,
                    "tif": tif,
                    "next_actions": [
                        "Enter a positive quantity in the ticket controls.",
                        "Keep submit=false for preview-only runs.",
                    ],
                },
                sources=["paper_ticket"],
                metadata={"preview_only": True},
            )
        broker = _select_broker(self.deps, instrument.asset_class)
        if broker is None and live_armed:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": (
                        f"No broker is configured for asset class "
                        f"{instrument.asset_class.value}; cannot submit."
                    ),
                    "broker": None,
                    "symbol": instrument.symbol,
                    "asset_class": instrument.asset_class.value,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "time_in_force": tif,
                    "tif": tif,
                    "next_actions": [
                        "Configure a broker for this asset class in Settings -> Secrets.",
                        "Re-run with submit=false to keep working in preview mode.",
                    ],
                },
                sources=["no_live_source"],
                metadata={
                    "fallback": True,
                    "provider_errors": [
                        f"no broker adapter wired for {instrument.asset_class.value}",
                    ],
                },
            )
        if broker is None or not live_armed:
            # Session-14 fix: preview used to drop the user-supplied limit
            # price and leverage entirely. The UI then showed an empty
            # "Price: —" row, hiding the fact that the value the user typed
            # was carried through. Echo both fields back so the preview is
            # actually a faithful round-trip of what the trader requested.
            price_param = _float_param(params.get("price"), default=0.0) if params.get("price") not in (None, "") else None
            leverage_param = params.get("leverage")
            preview = {
                "broker": "paper",
                "status": "preview",
                "submit": False,
                "paper_mode": paper_mode,
                "broker_available": broker is not None,
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class.value,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "time_in_force": tif,
                "tif": tif,
                "price": price_param,
                "leverage": leverage_param,
                "next_actions": [
                    "Review the ticket values.",
                    "Use the broker order endpoint or Advanced submit=true only after confirming the trade.",
                ],
            }
            if submit and not live_armed:
                # Honest signal: the caller asked for submit but the safe
                # paper_mode guard blocked it. Say so instead of silently
                # returning the normal preview.
                preview["reason"] = (
                    "paper_mode is on (safe default) — submit=true was ignored; "
                    "returning a paper preview."
                )
                preview["next_actions"] = [
                    "Review the ticket values.",
                    "To arm a live order set paper_mode=false in addition to submit=true (the UI does this only after the confirm gate).",
                ]
            return FunctionResult(code=self.code, instrument=instrument, data=preview,
                                  sources=["paper_ticket"], metadata={"preview_only": True})
        order = BrokerOrder(
            instrument=instrument,
            side=OrderSide(side),
            quantity=quantity,
            order_type=OrderType(order_type),
            price=params.get("price"),
            time_in_force=TimeInForce(tif),
            leverage=params.get("leverage"),
        )
        order_id = await broker.place_order(order)
        # Per PY-LINT-05 P0: do NOT silently swallow audit-write failures
        # after a real broker fill. The local audit row is the regulatory /
        # reconciliation trail; losing it after a successful place_order
        # is the data-loss-mask scenario the audit calls out.
        try:
            from showme.engine.services.order_history import record_order
            record_order(
                broker=broker.name, order_id=str(order_id),
                symbol=instrument.symbol,
                asset_class=instrument.asset_class.value,
                side=order.side.value, quantity=order.quantity,
                price=order.price, leverage=order.leverage,
                type=order.order_type.value, tif=order.time_in_force.value,
                metadata={"client_order_id": order.client_order_id},
            )
        except Exception:
            LOG.exception(
                "audit_event failed for order %s (broker=%s, symbol=%s)",
                order.client_order_id,
                broker.name,
                instrument.symbol,
            )
            raise
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                # F9 [H]: the old success payload was only {order_id, broker},
                # so the pane's "submitted/filled" branch was unreachable and a
                # real order rendered as a preview. Echo the ticket back with
                # an honest lifecycle status ("submitted" — the broker accepted
                # the order; ``place_order`` does not report fills).
                "status": "submitted",
                "broker": broker.name,
                "order_id": str(order_id),
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class.value,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "time_in_force": tif,
                "tif": tif,
                "price": params.get("price"),
                "leverage": params.get("leverage"),
                "next_actions": [
                    "Track the working order in AIM (broker + order_id).",
                    "A fill will appear in the AIM ledger once the broker reports it.",
                ],
            },
            sources=[broker.name],
            metadata={"preview_only": False, "submitted": True},
        )


@FunctionRegistry.register
class AIMFunction(BaseFunction):
    """AIM — Order Management (open + filled across brokers)."""
    code = "AIM"
    name = "Order Management"
    category = "trade"

    _BROKERS = ("binance_broker", "alpaca_broker", "ibkr_broker", "oanda_broker")

    # Lifecycle states that count as working when a live adapter lists the
    # order. "submitted" is included: a broker that reports it (IBKR "Submitted")
    # is working the order. History rows never reach this check; EMSX/BBGT write
    # "submitted" to history at placement and that row is never broker-confirmed.
    _OPEN_STATUSES = frozenset({
        "open", "new", "accepted", "pending", "pending_new", "working",
        "partially_filled", "submitted",
    })

    _FIELD_DICTIONARY = {
        "created_at": "Order creation timestamp.",
        "broker": "Adapter name (binance_broker, alpaca_broker, ...).",
        "order_id": "Broker-assigned order identifier.",
        "symbol": "Canonical instrument symbol.",
        "side": "BUY or SELL.",
        "quantity": "Order size in base units.",
        "price": "Limit price; null for market orders.",
        "type": "MARKET / LIMIT / ...",
        "tif": "Time-in-force directive.",
        "status": "open / filled / partially_filled / cancelled / rejected.",
        "filled_qty": "Quantity executed so far.",
        "avg_fill_px": "Volume-weighted average fill price.",
    }

    _METHODOLOGY = (
        "AIM iterates over every configured broker adapter (binance/alpaca/ibkr/oanda) one at a time "
        "(sequential, not parallel), calling get_open_orders() and collecting per-broker results. "
        "provider_mode=cached_snapshot skips live polling. Provider failures are recorded as "
        "warnings without dropping rows from working brokers. The persisted local order_history "
        "store contributes a configurable tail of recent orders so the user sees a cross-broker "
        "chronological ledger even when individual brokers are momentarily down. AIM never mutates "
        "state — it is the read-only counterpart to EMSX/BBGT/FXGO/TSOX."
    )

    @staticmethod
    def _broker_identities(key: str, broker: Any) -> set[str]:
        """Names one adapter's orders are stored under: its config key and its ``.name``."""
        ids = {key}
        nm = getattr(broker, "name", None)
        if isinstance(nm, str) and nm:
            ids.add(nm)
        return ids

    @staticmethod
    def _normalise_order(broker_name: str, raw: Any, *, from_history: bool = False) -> dict[str, Any]:
        """Coerce a broker open-order dict (or a stored history row) into the AIM table schema."""
        if not isinstance(raw, dict):
            raw = {"raw": raw}
        ts = raw.get("ts")
        created = raw.get("created_at") or raw.get("createdAt") or raw.get("time")
        if created is None and ts is not None:
            try:
                created = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                created = None
        status = raw.get("status")
        if status is None:
            status = "filled" if from_history else "open"
        return {
            "created_at": created,
            "broker": raw.get("broker") or broker_name,
            "order_id": raw.get("order_id") or raw.get("orderId") or raw.get("id"),
            "symbol": raw.get("symbol"),
            "side": (str(raw.get("side")).upper() if raw.get("side") is not None else None),
            "quantity": raw.get("quantity") if raw.get("quantity") is not None else raw.get("qty"),
            "price": raw.get("price"),
            "type": raw.get("type") or raw.get("order_type"),
            "tif": raw.get("tif") or raw.get("time_in_force"),
            "status": status,
            "filled_qty": raw.get("filled_qty") if raw.get("filled_qty") is not None else raw.get("filledQty"),
            "avg_fill_px": raw.get("avg_fill_px") if raw.get("avg_fill_px") is not None else raw.get("avgFillPx"),
        }

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        provider_errors: list[str] = []
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []
        brokers_online: list[str] = []
        # (broker identity, order_id) pairs that a live adapter currently lists.
        live_keys: set[tuple[str, str]] = set()

        broker_filter = params.get("broker_filter") or []
        if isinstance(broker_filter, str):
            broker_filter = [broker_filter]
        targets = [b for b in self._BROKERS if (not broker_filter or b in broker_filter)]

        # provider_mode=cached_snapshot skips live adapter polling entirely and
        # serves only the local history tail; any other value polls live.
        provider_mode = str(params.get("provider_mode") or "").strip().lower()
        skip_live = provider_mode == "cached_snapshot"
        if provider_mode and provider_mode not in {"live_exchange", "cached_snapshot"}:
            warnings.append(f"AIM: unsupported provider_mode={provider_mode!r}; live broker polling was used.")
        # brokers_checked: configured adapters AIM actually attempted a poll on
        # (failed polls included, unconfigured adapters and cached_snapshot excluded).
        polled: list[str] = []

        for name in ([] if skip_live else targets):
            broker = getattr(self.deps, name, None)
            if broker is None:
                continue
            polled.append(name)
            try:
                open_orders = await broker.get_open_orders()
            except Exception as exc:  # noqa: BLE001
                provider_errors.append(f"{name}.get_open_orders: {exc}")
                warnings.append(f"{name} unavailable: {exc}")
                continue
            brokers_online.append(name)
            for raw in (open_orders or []):
                live_row = self._normalise_order(name, raw, from_history=False)
                # Only a live broker listing proves an order is working now.
                live_row["confirmed_open"] = (
                    str(live_row.get("status") or "").lower() in self._OPEN_STATUSES
                )
                rows.append(live_row)
                if live_row.get("order_id") is not None:
                    for ident in self._broker_identities(name, broker):
                        live_keys.add((ident, str(live_row["order_id"])))

        # Persisted order history (cross-broker tail)
        raw_limit = params.get("limit", 200)
        try:
            limit_int = int(raw_limit) if raw_limit is not None else 200
        except (TypeError, ValueError):
            limit_int = 200
            provider_errors.append(f"AIM: ignoring non-integer limit={raw_limit!r}")
        limit_int = max(1, min(limit_int, 1000))
        history_rows: list[dict[str, Any]] = []
        try:
            from showme.engine.services.order_history import list_orders
            if broker_filter:
                # History rows are stored under the adapter's .name (not its
                # config key), so query every name the filtered adapters use.
                identities: set[str] = set()
                for name in targets:
                    identities |= self._broker_identities(name, getattr(self.deps, name, None))
                raw_history: list[dict[str, Any]] = []
                for ident in sorted(identities):
                    raw_history.extend(list_orders(broker=ident, limit=limit_int) or [])
                raw_history.sort(key=lambda r: r.get("ts") or 0, reverse=True)
                raw_history = raw_history[:limit_int]
            else:
                raw_history = list_orders(limit=limit_int) or []
            for raw in raw_history:
                history_rows.append(self._normalise_order("history", raw, from_history=True))
        except Exception as exc:  # noqa: BLE001
            provider_errors.append(f"order_history.list_orders: {exc}")
            warnings.append(f"order history unavailable: {exc}")
        # A history row that a live adapter already lists is the same order:
        # keep the live row only, so it is neither duplicated nor double counted.
        history_rows = [
            r for r in history_rows
            if (str(r.get("broker")), str(r.get("order_id"))) not in live_keys
        ]
        # The history store is written once at placement and never updated on
        # fills or closes, so no history row can prove a working order: it is
        # shown for the audit trail but never counted as open.
        for r in history_rows:
            r["confirmed_open"] = False
        # A 'submitted' row no live broker confirms may be stale (filled, closed).
        unconfirmed = [r for r in history_rows if str(r.get("status") or "").lower() == "submitted"]
        if unconfirmed:
            warnings.append(
                f"{len(unconfirmed)} order(s) recorded as 'submitted' in local history could not be "
                "confirmed open by a live broker; their current status may have changed since placement."
            )
        rows.extend(history_rows)

        # Optional status filter (manifest input).
        status_filter = params.get("status_filter") or []
        if isinstance(status_filter, str):
            status_filter = [status_filter]
        if status_filter:
            wanted = {str(s).lower() for s in status_filter}
            rows = [r for r in rows if str(r.get("status") or "").lower() in wanted]

        open_count = sum(1 for r in rows if r.get("confirmed_open") is True)
        filled_count = sum(
            1 for r in rows if str(r.get("status") or "").lower() in {"filled", "partially_filled"}
        )

        def _notional(r: dict[str, Any]) -> float | None:
            # None = not computable (market order with no price or fill price).
            try:
                qty = float(r.get("quantity") or 0.0)
                px_raw = r.get("price")
                if px_raw in (None, ""):
                    px_raw = r.get("avg_fill_px")
                if px_raw in (None, ""):
                    return None
                return qty * float(px_raw)
            except (TypeError, ValueError):
                return None

        notionals = [_notional(r) for r in rows]
        priced_count = sum(1 for n in notionals if n is not None)
        unpriced_count = len(rows) - priced_count
        # Quantities are base units and prices are quote units, and rows span
        # several symbols, so the total is an indicative sum, not a USD figure.
        total_notional = round(sum(n for n in notionals if n is not None), 2)
        if unpriced_count:
            warnings.append(
                f"{unpriced_count} unpriced order(s) (no price or fill price) are excluded from the indicative notional total."
            )

        data_mode = "live_exchange" if brokers_online else "not_configured"
        if (not brokers_online and history_rows) or skip_live:
            data_mode = "cached_snapshot"

        cards = {
            "open_count": open_count,
            "filled_today": filled_count,
            "brokers_online": len(brokers_online),
            "total_notional": total_notional,
            "notional_basis": "indicative_unconverted",
            "priced_count": priced_count,
            "unpriced_count": unpriced_count,
            "unconfirmed_submitted_count": len(unconfirmed),
            "data_mode": data_mode,
            "as_of": _utc_now_iso(),
        }

        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "reason": "No open or recent orders were found in configured brokers or local order history.",
                    "rows": [],
                    "orders": [],
                    "cards": cards,
                    "brokers_checked": list(polled),
                    "provider_mode": provider_mode or None,
                    "data_mode": data_mode,
                    "as_of": cards["as_of"],
                    "methodology": self._METHODOLOGY,
                    "field_dictionary": self._FIELD_DICTIONARY,
                    "next_actions": [
                        "Use BBGT/EMSX/FXGO/TSOX to preview a ticket.",
                        "Submitted broker orders will appear here after they are accepted or filled.",
                    ],
                },
                sources=["order_history"],
                warnings=warnings,
                metadata={"empty": True, "provider_errors": provider_errors, "row_count": 0},
            )

        metadata: dict[str, Any] = {"row_count": len(rows)}
        if provider_errors:
            metadata["provider_errors"] = provider_errors
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "rows": rows,
                "orders": rows,
                "cards": cards,
                "brokers_checked": list(polled),
                "brokers_online": brokers_online,
                "provider_mode": provider_mode or None,
                "data_mode": data_mode,
                "as_of": cards["as_of"],
                "methodology": self._METHODOLOGY,
                "field_dictionary": self._FIELD_DICTIONARY,
            },
            sources=["order_history"] + brokers_online,
            warnings=warnings,
            metadata=metadata,
        )


@FunctionRegistry.register
class TSOXFunction(EMSXFunction):
    """TSOX — Treasury / Bond order ticket."""
    code = "TSOX"
    name = "Treasury Order Entry"
    # Cash Treasuries (BOND) and CME Treasury futures (DERIVATIVE, e.g. ZN=F).
    asset_classes = (AssetClass.BOND, AssetClass.DERIVATIVE)


@FunctionRegistry.register
class FXGOFunction(EMSXFunction):
    """FXGO — FX trading desk with a live keyless spot dealing board."""
    code = "FXGO"
    name = "FX Trading"
    asset_classes = (AssetClass.FX,)

    # Default dealing-board grid (majors + key crosses). yfinance FX pairs use
    # the ``EURUSD=X`` style ticker.
    _BOARD_PAIRS = (
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "USDCAD", "NZDUSD", "EURGBP",
        "EURJPY", "GBPJPY",
    )

    # A spot quote older than this is shown as a stale reference, never as a
    # live price (e.g. a Friday-close quote read on the weekend).
    _QUOTE_STALE_AFTER_SECONDS = 3600

    _BOARD_FIELD_DICTIONARY = {
        "pair": "FX pair (base/quote).",
        "bid": "Indicative bid (quote per base) — mid minus half a synthetic spread; not a quoted venue bid.",
        "ask": "Indicative ask (quote per base) — mid plus half a synthetic spread; not a quoted venue ask.",
        "bid_ask_basis": "synthetic_indicative — bid/ask are derived from the spot mid, never a broker or venue quote.",
        "mid": "Mid price (last traded spot).",
        "spread": "Ask minus bid, in quote units.",
        "spread_pips": "Spread expressed in pips.",
        "change": "Absolute change vs the prior daily session close (one-day bar).",
        "change_pct": "Percent change vs the prior daily session close (one-day bar).",
        "previous_close": "Prior daily session close (the bar before the latest one), not the start of the 5-day window.",
        "previous_close_date": "UTC date of the prior daily session bar that previous_close comes from.",
        "quote_time": "UTC time the provider printed the mid (regularMarketTime). Unknown when the provider omits it.",
        "quote_age_seconds": "Seconds between the quote time and the request. Above the stale threshold the board is reference, not live.",
        "as_of": "Quote time of the oldest quote on the board (null when the provider gave no quote time).",
        "fetched_at": "When ShowMe fetched the board (not a market time).",
    }

    _BOARD_METHODOLOGY = (
        "FXGO surfaces a live keyless FX dealing board: spot mid for each major/cross is pulled "
        "from yfinance (EURUSD=X style tickers); a synthetic dealing spread (1 pip JPY-quoted, "
        "0.0001 otherwise, scaled to liquidity) is applied around the mid to derive indicative "
        "bid/ask so the board reads like a venue ladder without any keyed broker feed. When a "
        "ticket (quantity/side/submit) is supplied, FXGO falls back to the EMSX two-mode "
        "safe-by-default trade-ticket contract (paper preview unless explicitly armed)."
    )

    @staticmethod
    def _to_yf_fx(pair: str) -> str:
        # FX tickers are alphabetic; strip anything else so user-supplied
        # ``pairs`` cannot smuggle path segments / query chars into the Yahoo
        # chart URL. Returns "" when nothing alphabetic survives so the caller
        # can skip the pair rather than request a malformed ``=X`` symbol.
        # The Yahoo ``=X`` suffix must be removed BEFORE the non-letter strip:
        # the strip deletes "=" first, so ``GBPUSD=X`` used to become
        # ``GBPUSDX`` and requested the non-existent ``GBPUSDX=X`` (404).
        text = str(pair or "").strip().upper()
        if text.endswith("=X"):
            text = text[:-2]
        base = re.sub(r"[^A-Z]", "", text)
        if not base:
            return ""
        return f"{base}=X"

    @staticmethod
    def _pip_size(pair: str) -> float:
        return 0.01 if pair.upper().endswith("JPY") else 0.0001

    def _fetch_fx_spot(self, pair: str) -> tuple[float | None, float | None]:
        """Return (mid, previous_close) for an FX pair from a keyless source.

        Uses Yahoo's public chart endpoint with the FX ``EURUSD=X`` ticker.
        Tests monkeypatch this method to inject a deterministic spot without
        network. Raises on a real network outage so the caller can degrade to
        ``provider_unavailable``.
        """
        import requests

        yf_symbol = self._to_yf_fx(pair)
        if not yf_symbol:
            # Nothing alphabetic in the pair → no resolvable Yahoo ticker.
            # Degrade to "no spot" so the caller skips this row instead of
            # requesting a malformed symbol.
            return (None, None)
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}",
            params={"range": "5d", "interval": "1d", "includePrePost": "false"},
            headers={"User-Agent": "showMe/1.0", "Accept": "application/json"},
            timeout=4.0,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        result = (((payload.get("chart") or {}).get("result") or [None])[0]) or {}
        meta = result.get("meta") or {}
        quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
        # Pair each daily bar's close with its timestamp; bars without a close
        # (e.g. an unfinished bar) are skipped.
        raw_closes = list(quote.get("close") or [])
        raw_ts = list(result.get("timestamp") or [])
        bars = [
            (raw_ts[i] if i < len(raw_ts) else None, c)
            for i, c in enumerate(raw_closes)
            if c is not None
        ]
        closes = [c for _, c in bars]
        last_close = closes[-1] if closes else None
        mid = meta.get("regularMarketPrice") or last_close
        # Prior session = the daily bar before the latest one. Yahoo's
        # chartPreviousClose / previousClose for range=5d is the close BEFORE
        # the whole 5-session window, so it must never stand in for the
        # one-day previous close.
        prev = closes[-2] if len(closes) >= 2 else None
        prev_date = None
        if len(bars) >= 2 and bars[-2][0] is not None:
            prev_date = datetime.fromtimestamp(int(bars[-2][0]), tz=timezone.utc).date().isoformat()
        # regularMarketTime is when the quoted price printed; it is the honest
        # as-of for the mid, not the moment we fetched it.
        quote_time = None
        try:
            if meta.get("regularMarketTime") is not None:
                quote_time = datetime.fromtimestamp(int(meta["regularMarketTime"]), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            quote_time = None
        return (
            float(mid) if mid is not None else None,
            float(prev) if prev is not None else None,
            {"previous_close_date": prev_date, "quote_time": quote_time},
        )

    def _board_row(self, pair: str) -> dict[str, Any] | None:
        spot = self._fetch_fx_spot(pair)
        mid, prev = spot[0], spot[1]
        spot_meta = spot[2] if len(spot) > 2 and isinstance(spot[2], dict) else {}
        if mid is None or mid <= 0:
            return None
        pip = self._pip_size(pair)
        # Indicative dealing spread: ~1 pip for majors, widen for JPY/cross.
        spread = pip * 1.0
        bid = round(mid - spread / 2.0, 6)
        ask = round(mid + spread / 2.0, 6)
        change = None
        change_pct = None
        try:
            if prev is not None and float(prev) != 0:
                change = round(mid - float(prev), 6)
                change_pct = round((mid - float(prev)) / float(prev) * 100.0, 4)
        except (TypeError, ValueError):
            change = None
            change_pct = None
        quote_time = spot_meta.get("quote_time")
        quote_age = None
        if isinstance(quote_time, datetime):
            quote_age = max(0, int((_fx_now_utc() - quote_time).total_seconds()))
        return {
            "pair": pair.upper(),
            "symbol": pair.upper(),
            "bid": bid,
            "ask": ask,
            "bid_ask_basis": "synthetic_indicative",
            "mid": round(mid, 6),
            "spread": round(ask - bid, 6),
            "spread_pips": round((ask - bid) / pip, 2),
            "change": change,
            "change_pct": change_pct,
            "previous_close": (round(float(prev), 6) if prev is not None else None),
            "previous_close_date": spot_meta.get("previous_close_date"),
            "quote_time": quote_time.isoformat() if isinstance(quote_time, datetime) else None,
            "quote_age_seconds": quote_age,
        }

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # When the caller is composing an actual order (any ticket intent), defer
        # to the inherited EMSX two-mode safe-by-default trade-ticket contract.
        ticket_intent = (
            _float_param(params.get("quantity")) > 0
            or _truthy(params.get("submit"))
            or params.get("side") is not None
        )
        if ticket_intent:
            return await super().execute(instrument=instrument, **params)

        # Default path: live FX dealing board (keyless spot grid w/ bid/ask/spread).
        # ``pairs`` is the board's own input. ``symbols`` is deliberately NOT
        # read here: the router injects the FX agent peer group
        # (EURUSD/GBPUSD/USDJPY) into ``symbols`` for every FX route, which
        # would silently shrink the default 10-pair board to three rows.
        pairs = params.get("pairs")
        board_source = "explicit_pairs"
        if isinstance(pairs, str):
            pairs = [p.strip() for p in pairs.split(",") if p.strip()]
        if not pairs:
            # A symbol is only a board request when the caller supplied it;
            # the router sets __explicit_symbol=False when it injected one.
            explicit_symbol = params.get("__explicit_symbol", True) is not False
            single = None
            if explicit_symbol:
                single = params.get("symbol") or (instrument.symbol if instrument else None)
            if single:
                pairs = [single]
                board_source = "explicit_symbol"
            else:
                pairs = list(self._BOARD_PAIRS)
                board_source = "default"

        # ``pairs`` is user-supplied — cap it to a sane board size so a caller
        # cannot fan out hundreds of blocking ``requests.get`` threads at once.
        board_warnings: list[str] = []
        _MAX_BOARD_PAIRS = 25
        if len(pairs) > _MAX_BOARD_PAIRS:
            board_warnings.append(
                f"Requested {len(pairs)} pairs; board capped to first "
                f"{_MAX_BOARD_PAIRS}."
            )
            pairs = pairs[:_MAX_BOARD_PAIRS]

        # ``_board_row`` does a blocking ``requests.get`` per pair. Running the
        # default 10-pair board sequentially in this ``async`` method would
        # freeze the whole sidecar event loop for up to 10×4s. Offload each
        # fetch to a worker thread and gather them concurrently so the loop
        # stays responsive and the board refresh is ~one timeout, not ten.
        rows: list[dict[str, Any]] = []
        provider_errors: list[str] = []
        results = await asyncio.gather(
            *(asyncio.to_thread(self._board_row, str(pair)) for pair in pairs),
            return_exceptions=True,
        )
        for pair, result in zip(pairs, results, strict=False):
            if isinstance(result, Exception):
                provider_errors.append(f"{pair}: {result}")
                continue
            if result is not None:
                rows.append(result)

        fetched_at = _utc_now_iso()
        # as_of is the OLDEST quote on the board (the honest freshness bound);
        # None when the provider gave no quote time.
        aged_rows = [r for r in rows if r.get("quote_age_seconds") is not None]
        oldest = max(aged_rows, key=lambda r: r["quote_age_seconds"]) if aged_rows else None
        as_of = oldest["quote_time"] if oldest else None
        stale_rows = [
            r for r in aged_rows
            if r["quote_age_seconds"] > self._QUOTE_STALE_AFTER_SECONDS
        ]
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "broker": "paper",
                    "symbol": (instrument.symbol if instrument else (pairs[0] if pairs else "EURUSD")),
                    "side": "BUY",
                    "quantity": 0,
                    "order_type": "MARKET",
                    "tif": "GTC",
                    "rows": [],
                    "cards": {"data_mode": "provider_unavailable", "as_of": None},
                    "data_mode": "provider_unavailable",
                    "as_of": None,
                    "fetched_at": fetched_at,
                    "methodology": self._BOARD_METHODOLOGY,
                    "field_dictionary": self._BOARD_FIELD_DICTIONARY,
                    "warning": "FX spot board unavailable from yfinance.",
                    "next_actions": [
                        "Retry shortly — the keyless FX feed may be rate-limited.",
                        "Pass ?symbol=EURUSD&quantity=... to compose an order ticket instead.",
                    ],
                },
                sources=["yfinance"],
                warnings=["FX spot board unavailable from yfinance."]
                + board_warnings
                + ([f"errors: {provider_errors}"] if provider_errors else []),
                metadata={"fallback": True, "provider_errors": provider_errors},
            )

        # Honesty: the board's data_mode reflects how much of the requested
        # board actually survived the provider calls. Claiming live_exchange
        # while most pairs 404'd is exactly the false-labelling defect the
        # FN-WAVE survey caught.
        total_requested = len(rows) + len(provider_errors)
        if provider_errors and len(rows) < total_requested:
            board_mode = "delayed_reference"
            board_warnings.append(
                f"Board degraded: {len(rows)}/{total_requested} pairs returned "
                "quotes; the rest failed upstream and are NOT shown."
            )
        elif stale_rows:
            # The feed answered, but the newest quote is old (e.g. the FX
            # market is closed): this is a reference price, not a live one.
            board_mode = "delayed_reference"
            board_warnings.append(
                f"Stale quotes: {len(stale_rows)}/{len(rows)} pair(s) were last "
                f"quoted more than {self._QUOTE_STALE_AFTER_SECONDS // 60} minutes "
                f"before the request (oldest quote {as_of}). Shown as reference, "
                "not a live price."
            )
        else:
            # Yahoo spot quotes with an indicative spread - not a venue's
            # two-way board, so never "live_exchange".
            board_mode = "live_yfinance_quote"
        unknown_time = [r["pair"] for r in rows if r.get("quote_time") is None]
        if unknown_time:
            board_warnings.append(
                "Quote time not reported by the provider for: "
                + ", ".join(unknown_time)
                + "; freshness of these rows is unknown."
            )

        # Card summary mirrors the EMSX/manifest card slots while reflecting the
        # live board: show the top pair's indicative two-way quote.
        top = rows[0]
        cards = {
            "status": "stale" if stale_rows else "ok",
            "broker": "indicative",
            "symbol": top["pair"],
            "side": "TWO_WAY",
            "quantity": len(rows),
            "order_type": "BOARD",
            "tif": "RT",
            "price": top["mid"],
            "as_of": as_of,
            "data_mode": board_mode,
        }
        warnings = board_warnings + (
            [f"errors: {provider_errors}"] if provider_errors else []
        )
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "broker": "indicative",
                "symbol": top["pair"],
                "side": "TWO_WAY",
                "quantity": len(rows),
                "order_type": "BOARD",
                "tif": "RT",
                "rows": rows,
                "cards": cards,
                "data_mode": board_mode,
                "requested_pairs": [str(p).upper() for p in pairs],
                "board_source": board_source,
                "bid_ask_basis": "synthetic_indicative",
                "as_of": as_of,
                "fetched_at": fetched_at,
                "methodology": self._BOARD_METHODOLOGY,
                "field_dictionary": self._BOARD_FIELD_DICTIONARY,
                "next_actions": [
                    "Click a pair then pass ?symbol=...&quantity=... to compose an order ticket.",
                ],
            },
            sources=["yfinance"],
            warnings=warnings,
            metadata={
                "row_count": len(rows),
                "requested_count": total_requested,
                "provider_errors": provider_errors,
            },
        )


@FunctionRegistry.register
class BBGTFunction(EMSXFunction):
    """BBGT — Bloomberg Trade (multi-asset)."""
    code = "BBGT"
    name = "Multi-Asset Trade Ticket"


# TCA is canonically registered via showme.engine.functions.trade.tca (TCAFunction).
# The legacy stub here was deleted to avoid the duplicate-code drift flagged in
# ARCH-10/PY-LINT-08.


def _float_param(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _paper_mode_enabled(value: Any) -> bool:
    """Safe-default parser for the ticket ``paper_mode`` guard (F9/C).

    Fail CLOSED: only an explicit falsy literal (``False`` / ``"false"`` /
    ``"0"`` / ``"no"`` / ``"off"``) disarms paper mode. Absent, ``None`` and
    any unrecognised value keep the ticket in paper mode, so a malformed API
    or agent call can never reach a live broker by accident.
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in {"0", "false", "no", "off"}
