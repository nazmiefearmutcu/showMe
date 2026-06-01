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
        if broker is None and submit:
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
        if broker is None or not submit:
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
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"order_id": order_id, "broker": broker.name})


@FunctionRegistry.register
class AIMFunction(BaseFunction):
    """AIM — Order Management (open + filled across brokers)."""
    code = "AIM"
    name = "Order Management"
    category = "trade"

    _BROKERS = ("binance_broker", "alpaca_broker", "ibkr_broker", "oanda_broker")

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
        "AIM iterates over every configured broker adapter (binance/alpaca/ibkr/oanda), calling "
        "get_open_orders() and collecting per-broker results. Provider failures are recorded as "
        "warnings without dropping rows from working brokers. The persisted local order_history "
        "store contributes a configurable tail of recent orders so the user sees a cross-broker "
        "chronological ledger even when individual brokers are momentarily down. AIM never mutates "
        "state — it is the read-only counterpart to EMSX/BBGT/FXGO/TSOX."
    )

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

        broker_filter = params.get("broker_filter") or []
        if isinstance(broker_filter, str):
            broker_filter = [broker_filter]
        targets = [b for b in self._BROKERS if (not broker_filter or b in broker_filter)]

        for name in targets:
            broker = getattr(self.deps, name, None)
            if broker is None:
                continue
            try:
                open_orders = await broker.get_open_orders()
            except Exception as exc:  # noqa: BLE001
                provider_errors.append(f"{name}.get_open_orders: {exc}")
                warnings.append(f"{name} unavailable: {exc}")
                continue
            brokers_online.append(name)
            for raw in (open_orders or []):
                rows.append(self._normalise_order(name, raw, from_history=False))

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
            for raw in (list_orders(limit=limit_int) or []):
                history_rows.append(self._normalise_order("history", raw, from_history=True))
        except Exception as exc:  # noqa: BLE001
            provider_errors.append(f"order_history.list_orders: {exc}")
            warnings.append(f"order history unavailable: {exc}")
        rows.extend(history_rows)

        # Optional status filter (manifest input).
        status_filter = params.get("status_filter") or []
        if isinstance(status_filter, str):
            status_filter = [status_filter]
        if status_filter:
            wanted = {str(s).lower() for s in status_filter}
            rows = [r for r in rows if str(r.get("status") or "").lower() in wanted]

        open_count = sum(1 for r in rows if str(r.get("status") or "").lower() == "open")
        filled_count = sum(
            1 for r in rows if str(r.get("status") or "").lower() in {"filled", "partially_filled"}
        )

        def _notional(r: dict[str, Any]) -> float:
            try:
                qty = float(r.get("quantity") or 0.0)
                px = float(r.get("price") or r.get("avg_fill_px") or 0.0)
                return qty * px
            except (TypeError, ValueError):
                return 0.0

        total_notional = round(sum(_notional(r) for r in rows), 2)

        data_mode = "live_exchange" if brokers_online else "not_configured"
        if not brokers_online and history_rows:
            data_mode = "cached_snapshot"

        cards = {
            "open_count": open_count,
            "filled_today": filled_count,
            "brokers_online": len(brokers_online),
            "total_notional": total_notional,
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
                    "brokers_checked": list(targets),
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
                "brokers_checked": list(targets),
                "brokers_online": brokers_online,
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
    asset_classes = (AssetClass.BOND,)


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

    _BOARD_FIELD_DICTIONARY = {
        "pair": "FX pair (base/quote).",
        "bid": "Best bid (quote per base) — last minus half synthetic spread.",
        "ask": "Best ask (quote per base) — last plus half synthetic spread.",
        "mid": "Mid price (last traded spot).",
        "spread": "Ask minus bid, in quote units.",
        "spread_pips": "Spread expressed in pips.",
        "change": "Absolute change vs previous close.",
        "change_pct": "Percent change vs previous close.",
        "previous_close": "Prior session close.",
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
        base = re.sub(r"[^A-Za-z]", "", pair).upper().replace("=X", "")
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
        closes = [c for c in (quote.get("close") or []) if c is not None]
        last_close = closes[-1] if closes else None
        mid = meta.get("regularMarketPrice") or last_close
        prev = (
            meta.get("previousClose")
            or meta.get("chartPreviousClose")
            or (closes[-2] if len(closes) >= 2 else None)
        )
        return (
            float(mid) if mid is not None else None,
            float(prev) if prev is not None else None,
        )

    def _board_row(self, pair: str) -> dict[str, Any] | None:
        mid, prev = self._fetch_fx_spot(pair)
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
        return {
            "pair": pair.upper(),
            "symbol": pair.upper(),
            "bid": bid,
            "ask": ask,
            "mid": round(mid, 6),
            "spread": round(ask - bid, 6),
            "spread_pips": round((ask - bid) / pip, 2),
            "change": change,
            "change_pct": change_pct,
            "previous_close": (round(float(prev), 6) if prev is not None else None),
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
        pairs = params.get("pairs") or params.get("symbols")
        if isinstance(pairs, str):
            pairs = [p.strip() for p in pairs.split(",") if p.strip()]
        if not pairs:
            single = params.get("symbol") or (instrument.symbol if instrument else None)
            pairs = [single] if single else list(self._BOARD_PAIRS)

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

        as_of = _utc_now_iso()
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
                    "cards": {"data_mode": "provider_unavailable", "as_of": as_of},
                    "data_mode": "provider_unavailable",
                    "as_of": as_of,
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

        # Card summary mirrors the EMSX/manifest card slots while reflecting the
        # live board: show the top pair's indicative two-way quote.
        top = rows[0]
        cards = {
            "status": "live",
            "broker": "indicative",
            "symbol": top["pair"],
            "side": "TWO_WAY",
            "quantity": len(rows),
            "order_type": "BOARD",
            "tif": "RT",
            "price": top["mid"],
            "as_of": as_of,
            "data_mode": "live_exchange",
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
                "data_mode": "live_exchange",
                "as_of": as_of,
                "methodology": self._BOARD_METHODOLOGY,
                "field_dictionary": self._BOARD_FIELD_DICTIONARY,
                "next_actions": [
                    "Click a pair then pass ?symbol=...&quantity=... to compose an order ticket.",
                ],
            },
            sources=["yfinance"],
            warnings=warnings,
            metadata={"row_count": len(rows), "provider_errors": provider_errors},
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
