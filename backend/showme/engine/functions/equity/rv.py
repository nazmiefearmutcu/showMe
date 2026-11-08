"""RV — Relative Valuation vs peer set."""

from __future__ import annotations

import asyncio
from typing import Any


from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import finite, reference_profile


@FunctionRegistry.register
class RVFunction(BaseFunction):
    code = "RV"
    name = "Relative Valuation"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        raw_peers = params.get("peers")
        peers: list[str] = [str(p).strip().upper() for p in raw_peers if str(p).strip()] if isinstance(raw_peers, (list, tuple, set)) else []
        if self.deps.finnhub:
            try:
                if not peers:
                    peers = await asyncio.wait_for(
                        self.deps.finnhub.peers(instrument.symbol),
                        timeout=float(params.get("finnhub_timeout", 8)),
                    )
            except Exception:
                peers = peers or []
        peers = [p for p in peers if p != instrument.symbol][:8]
        if not peers:
            peers = [p for p in reference_profile(instrument.symbol).get("peers", []) if p != instrument.symbol][:6]
        full = [instrument.symbol] + peers
        rows: list[dict[str, Any]] = []
        if self.deps.yfinance:
            from showme.engine.core.base_data_source import DataKind, DataRequest
            from showme.engine.core.instrument import Instrument as I
            tasks = [asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA,
                    instrument=I(symbol=s, asset_class=AssetClass.EQUITY, exchange="NASDAQ"),
                )),
                timeout=float(params.get("yfinance_timeout", 8)),
            ) for s in full]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, r in zip(full, results):
                if isinstance(r, Exception) or r is None:
                    continue
                raw = (r.extras or {}).get("raw", {}) if hasattr(r, "extras") else {}
                div_yield, div_yield_status = _dividend_yield(raw.get("dividendYield"), raw)
                rows.append({
                    "symbol": sym,
                    "marketCap": r.market_cap or raw.get("marketCap"),
                    "pe": raw.get("trailingPE"),
                    "fwd_pe": raw.get("forwardPE"),
                    "pb": raw.get("priceToBook"),
                    "ps": raw.get("priceToSalesTrailing12Months"),
                    "ev_ebitda": raw.get("enterpriseToEbitda"),
                    "roe": raw.get("returnOnEquity"),
                    "roa": raw.get("returnOnAssets"),
                    "debt_equity": raw.get("debtToEquity"),
                    "div_yield": div_yield,
                    "div_yield_status": div_yield_status,
                    "source_mode": "live_yfinance",
                })
        if not rows:
            rows = [{
                "symbol": instrument.symbol,
                "marketCap": None,
                "pe": None,
                "fwd_pe": None,
                "pb": None,
                "ps": None,
                "ev_ebitda": None,
                "roe": None,
                "roa": None,
                "debt_equity": None,
                "div_yield": None,
                "status": "provider_unavailable",
                "source_mode": "provider_unavailable",
            }]
        rows = _rank_rows(rows, instrument.symbol)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok" if len(rows) > 1 else "provider_unavailable",
                "rows": rows,
                "peers": peers,
                "methodology": "RV compares the target against a peer set from Finnhub or a labelled sector-reference peer map. Multiples are live yfinance fields when available; rank is computed within returned peers.",
                "field_dictionary": {
                    "pe": "Trailing price/earnings multiple.",
                    "fwd_pe": "Forward price/earnings multiple.",
                    "ev_ebitda": "Enterprise value / EBITDA.",
                    "rank_pe": "Ascending PE rank within peer set.",
                    "percentile_pe": "Peer percentile for PE, lower is cheaper.",
                },
            },
            sources=["finnhub", "yfinance"] if self.deps.yfinance else ["relative_value_model"],
            metadata={"peers": peers},
        )


def _dividend_yield(value: Any, raw: dict[str, Any] | None = None) -> tuple[float | None, str]:
    """Dividend yield as a decimal fraction (0.0032 = 0.32%) plus its status.

    yfinance ``dividendYield`` is percent units in current releases (AAPL 0.32),
    but older releases shipped a decimal. The unit is settled only by evidence:

    * a zero yield is unit-free and resolved (0.0);
    * otherwise both readings (percent and decimal) are checked against
      ``dividendRate / price``. The closer reading wins only when it is within a
      factor of two of that implied yield;
    * with no rate or price, or when neither reading is consistent with it, the
      unit is unresolved and the yield is None. A magnitude guess is never used.

    Status is one of ``ok``, ``missing`` (absent or negative) or ``unit_unresolved``.
    """
    v = finite(value)
    if v is None or v < 0:
        return None, "missing"
    if v == 0:
        return 0.0, "ok"
    implied = _implied_yield_fraction(raw or {})
    if implied is None:
        return None, "unit_unresolved"
    as_percent, as_decimal = v / 100.0, v
    chosen = as_percent if abs(as_percent - implied) <= abs(as_decimal - implied) else as_decimal
    if not (0.5 * implied <= chosen <= 2.0 * implied):
        return None, "unit_unresolved"
    return chosen, "ok"


def _implied_yield_fraction(raw: dict[str, Any]) -> float | None:
    """``dividendRate / price`` as a fraction, or None when either is missing."""
    rate = finite(raw.get("dividendRate"))
    price = None
    for key in ("currentPrice", "regularMarketPrice", "previousClose"):
        price = finite(raw.get(key))
        if price is not None and price > 0:
            break
    if rate is None or rate <= 0 or price is None or price <= 0:
        return None
    return rate / price


def _rank_rows(rows: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    # HNT-11 fix: a negative trailing P/E (loss-making company) means N/A,
    # not "cheapest" — it used to sort first and earn percentile 0. Only
    # positive finite PEs participate in the ranking; the raw value still
    # shows in the row.
    valid = sorted(
        [r for r in rows if (finite(r.get("pe")) or 0) > 0],
        key=lambda r: finite(r.get("pe")) or 0,
    )
    n = max(1, len(valid) - 1)
    ranks = {r["symbol"]: (idx + 1, idx / n if n else 0) for idx, r in enumerate(valid)}
    for row in rows:
        rank = ranks.get(row.get("symbol"))
        if rank:
            row["rank_pe"] = rank[0]
            row["percentile_pe"] = round(rank[1] * 100, 2)
        row["is_target"] = row.get("symbol") == target
    return rows
