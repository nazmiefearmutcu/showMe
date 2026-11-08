"""RV — Relative Valuation vs peer set."""

from __future__ import annotations

import asyncio
import statistics
from typing import Any


from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import finite, reference_profile


_METHODOLOGY = (
    "RV compares the target against a peer set from an explicit user list, Finnhub peers, "
    "or a labelled sector-reference peer map (see peer_source). Multiples are live yfinance "
    "fields when available; rank is computed within returned peers."
)

# yfinance info fields that carry a multiple or size. A refdata result with none of
# these is a failed or empty call (the adapter swallows info errors), not live data.
_MULTIPLE_KEYS = (
    "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
    "enterpriseToEbitda", "returnOnEquity", "returnOnAssets", "debtToEquity", "dividendYield",
)

_FIELD_DICTIONARY = {
    "pe": "Trailing price/earnings multiple.",
    "fwd_pe": "Forward price/earnings multiple.",
    "ev_ebitda": "Enterprise value / EBITDA.",
    "roe": "Return on equity as a fraction (0.25 = 25%).",
    "roa": "Return on assets as a fraction (0.05 = 5%).",
    "debt_equity": "Total debt / equity as a ratio (yfinance debtToEquity percent divided by 100).",
    "div_yield": "Dividend yield as a decimal fraction (0.0032 = 0.32%).",
    "rank_pe": "Ascending PE rank within peer set.",
    "percentile_pe": "Peer percentile for PE, lower is cheaper.",
    "peer_source": "Where the peer set came from: user_input, finnhub, or reference_sector_map.",
    "peer_count": "Number of peers (target excluded) that returned multiples. Under three draws a warning.",
    "peer_median": "Median of each metric across the peers (target excluded); P/E uses positive values only.",
    "peer_median_pe": "Peer median trailing P/E.",
    "pe_vs_peer_pct": "Target P/E premium (+) or discount (-) to the peer median P/E, in percent.",
    "own_pe": "Target trailing P/E (the issuer's own multiple), None when yfinance returned none.",
    "fcf_yield": "Free cash flow (TTM, yfinance freeCashflow) divided by market cap, as a decimal fraction. Negative when free cash flow is negative.",
    "pe_ttm": "Table alias of pe: trailing P/E.",
    "ps_ttm": "Table alias of ps: price/sales (trailing 12 months).",
    "dividend_yield": "Table alias of div_yield: decimal fraction.",
    "data_mode": "live_yfinance when multiples came back; provider_unavailable otherwise.",
}

# Ratio names offered by the seed's ``ratios`` input, mapped to the row key each
# is computed under. Every row also carries the seed name as a table alias.
_RATIO_ROW_KEYS = {
    "pe_ttm": "pe",
    "ev_ebitda": "ev_ebitda",
    "ps_ttm": "ps",
    "pb": "pb",
    "dividend_yield": "div_yield",
    "fcf_yield": "fcf_yield",
}
# Internal metric keys that a ratios filter removes from the rows.
_RATIO_INTERNAL_KEYS = ("pe", "fwd_pe", "ev_ebitda", "ps", "pb", "roe", "roa", "debt_equity", "div_yield", "fcf_yield")


@FunctionRegistry.register
class RVFunction(BaseFunction):
    code = "RV"
    name = "Relative Valuation"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        target = instrument.symbol
        peers, peer_source = await self._resolve_peers(target, params)
        by_symbol = await self._refdata_rows([target] + peers, params) if self.deps.yfinance else {}

        metadata: dict[str, Any] = {"peers": peers, "peer_source": peer_source}
        ranked = [by_symbol[s] for s in [target] + peers if s in by_symbol]
        reason: str | None = None
        warnings: list[str] = []
        # ``ratios`` restricts the table (and the peer medians) to a subset.
        # Unknown names are reported, never silently guessed.
        selected, unknown_ratios = _selected_ratios(params.get("ratios"))
        if unknown_ratios:
            warnings.append(
                "Unknown ratio(s) ignored: " + ", ".join(unknown_ratios)
                + ". Valid names: " + ", ".join(_RATIO_ROW_KEYS) + "."
            )
        peer_count: int | None = None
        peer_median: dict[str, float] = {}
        peer_median_pe: float | None = None
        pe_vs_peer_pct: float | None = None
        if target in by_symbol and len(ranked) > 1:
            status = "ok"
            rows = _rank_rows(ranked, target)
            sources = _sources(peer_source, live=True)
            peer_rows = [r for r in rows if not r.get("is_target")]
            peer_count = len(peer_rows)
            peer_median = _peer_medians(peer_rows)
            peer_median_pe = peer_median.get("pe")
            target_pe = finite(by_symbol[target].get("pe"))
            if target_pe is not None and target_pe > 0 and peer_median_pe:
                pe_vs_peer_pct = (target_pe / peer_median_pe - 1.0) * 100.0
            if peer_count < 3:
                warnings.append(
                    f"Only {peer_count} peer(s) returned multiples; the peer median is "
                    "unreliable with fewer than three peers."
                )
        else:
            status = "provider_unavailable"
            if not self.deps.yfinance:
                reason = "The yfinance refdata adapter is not configured, so no peer multiples can be fetched."
            elif target not in by_symbol:
                reason = f"yfinance refdata returned no multiples for {target}; peer multiples are not shown without the target."
            else:
                reason = "yfinance refdata returned the target only; no peer multiples were available for the median."
            rows = _rank_rows(ranked, target) if target in by_symbol else []
            if not rows:
                rows = [{
                    "symbol": target,
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
            # Failure semantics: the status is a provider failure. Only yfinance
            # is listed, and only when the target's own live multiples came back;
            # with no target row no source produced values, so none is listed.
            sources = ["yfinance"] if target in by_symbol else []
            metadata.update({
                "fallback": True,
                "data_mode": "provider_unavailable",
                "provider_errors": [reason],
            })
        own_row = by_symbol.get(target) or {}
        data: dict[str, Any] = {
            "status": status,
            "rows": [_table_row(row, selected) for row in rows],
            "peers": peers,
            "peer_source": peer_source,
            # Peer statistics exclude the target. They are None (not zero or a
            # guess) when no peer set could be priced.
            "peer_count": peer_count,
            "peer_median": _restrict_medians(peer_median, selected) or None,
            "peer_median_pe": peer_median_pe,
            "pe_vs_peer_pct": pe_vs_peer_pct,
            "own_pe": finite(own_row.get("pe")),
            "data_mode": "live_yfinance" if status == "ok" else "provider_unavailable",
            "ratios": sorted(selected) if selected is not None else None,
            "methodology": _METHODOLOGY,
            "field_dictionary": dict(_FIELD_DICTIONARY),
        }
        if reason is not None:
            data["reason"] = reason
            data["next_actions"] = [
                "Retry when the yfinance refdata provider recovers.",
                "Pass an explicit peer list to compare against a different peer set.",
            ]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources,
            warnings=warnings,
            metadata=metadata,
        )

    async def _resolve_peers(self, target: str, params: dict[str, Any]) -> tuple[list[str], str]:
        raw_peers = params.get("peers")
        peers: list[str] = (
            [str(p).strip().upper() for p in raw_peers if str(p).strip()]
            if isinstance(raw_peers, (list, tuple, set)) else []
        )
        source = "user_input" if peers else ""
        if not peers and self.deps.finnhub:
            try:
                fetched = await asyncio.wait_for(
                    self.deps.finnhub.peers(target),
                    timeout=float(params.get("finnhub_timeout", 8)),
                )
            except Exception:
                fetched = None
            if isinstance(fetched, (list, tuple)):
                peers = [str(p).strip().upper() for p in fetched if str(p).strip()]
                source = "finnhub" if peers else ""
        peers = list(dict.fromkeys(p for p in peers if p != target))[:8]
        if not peers:
            ref = [p for p in reference_profile(target).get("peers", []) if p != target][:6]
            if ref:
                peers = ref
                source = "reference_sector_map"
        return peers, (source or "none")

    async def _refdata_rows(self, symbols: list[str], params: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Rows for the symbols whose refdata actually carries multiples.

        A failed or empty refdata call is dropped rather than turned into an
        all-None row labelled live.
        """
        from showme.engine.core.base_data_source import DataKind, DataRequest
        from showme.engine.core.instrument import Instrument as I

        tasks = [asyncio.wait_for(
            self.deps.yfinance.fetch(DataRequest(
                kind=DataKind.REFDATA,
                instrument=I(symbol=s, asset_class=AssetClass.EQUITY, exchange="NASDAQ"),
            )),
            timeout=float(params.get("yfinance_timeout", 8)),
        ) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, dict[str, Any]] = {}
        for sym, r in zip(symbols, results):
            if isinstance(r, Exception) or r is None:
                continue
            raw = (r.extras or {}).get("raw", {}) if hasattr(r, "extras") else {}
            if not isinstance(raw, dict):
                raw = {}
            market_cap = r.market_cap or raw.get("marketCap")
            if finite(market_cap) is None and all(finite(raw.get(k)) is None for k in _MULTIPLE_KEYS):
                continue
            div_yield, div_yield_status = _dividend_yield(raw.get("dividendYield"), raw)
            de_pct = finite(raw.get("debtToEquity"))
            # FCF yield: yfinance freeCashflow (the same info payload DCF reads
            # through this adapter) over market cap. Missing input means None.
            free_cash_flow = finite(raw.get("freeCashflow"))
            mcap = finite(market_cap)
            fcf_yield = (
                free_cash_flow / mcap
                if free_cash_flow is not None and mcap is not None and mcap > 0
                else None
            )
            out[sym] = {
                "symbol": sym,
                "marketCap": market_cap,
                "pe": raw.get("trailingPE"),
                "fwd_pe": raw.get("forwardPE"),
                "pb": raw.get("priceToBook"),
                "ps": raw.get("priceToSalesTrailing12Months"),
                "ev_ebitda": raw.get("enterpriseToEbitda"),
                "roe": raw.get("returnOnEquity"),
                "roa": raw.get("returnOnAssets"),
                # yfinance debtToEquity is percent (84.286 = 0.84x); deliver a ratio.
                "debt_equity": None if de_pct is None else de_pct / 100.0,
                "div_yield": div_yield,
                "div_yield_status": div_yield_status,
                "fcf_yield": fcf_yield,
                "source_mode": "live_yfinance",
            }
        return out


def _sources(peer_source: str, *, live: bool) -> list[str]:
    """Providers that contributed: the peer-set origin plus yfinance when rows are live."""
    out: list[str] = []
    if peer_source == "finnhub":
        out.append("finnhub")
    if live:
        out.append("yfinance")
    if peer_source == "reference_sector_map":
        out.append("reference_sector_map")
    return out


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


_PEER_MEDIAN_KEYS = (
    "pe", "fwd_pe", "pb", "ps", "ev_ebitda", "roe", "roa", "debt_equity", "div_yield", "fcf_yield", "marketCap",
)


def _selected_ratios(raw: Any) -> tuple[set[str] | None, list[str]]:
    """The internal row keys selected by ``ratios`` plus the unknown names.

    ``None`` means no filter (every ratio is shown). A list or a comma-separated
    string is accepted; an empty value is no filter.
    """
    if isinstance(raw, str):
        names = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        names = [str(part).strip() for part in raw]
    else:
        return None, []
    names = [name for name in names if name]
    if not names:
        return None, []
    known = [name for name in names if name in _RATIO_ROW_KEYS]
    unknown = [name for name in names if name not in _RATIO_ROW_KEYS]
    if not known:
        return None, unknown
    return {_RATIO_ROW_KEYS[name] for name in known}, unknown


def _table_row(row: dict[str, Any], selected: set[str] | None) -> dict[str, Any]:
    """A row with the seed's table keys (pe_ttm, ps_ttm, dividend_yield, fcf_yield...).

    With a ratios filter only the selected ratios stay in the row; the symbol,
    rank and provenance fields always stay.
    """
    out = dict(row)
    for name, internal in _RATIO_ROW_KEYS.items():
        out[name] = row.get(internal)
    if selected is not None:
        for key in _RATIO_INTERNAL_KEYS:
            if key not in selected:
                out.pop(key, None)
        for name, internal in _RATIO_ROW_KEYS.items():
            if internal not in selected:
                out.pop(name, None)
    return out


def _restrict_medians(medians: dict[str, float], selected: set[str] | None) -> dict[str, float]:
    """Peer medians limited to the selected ratios. ``pe`` always stays (the P/E premium uses it)."""
    if selected is None:
        return dict(medians)
    keep = selected | {"pe"}
    return {key: value for key, value in medians.items() if key in keep}


def _peer_medians(peer_rows: list[dict[str, Any]]) -> dict[str, float]:
    """Median per metric across the peer rows (target excluded).

    Only finite values take part. P/E uses positive values only, matching the
    ranking: a negative P/E means loss-making, not cheap. A metric no peer
    supplies gets no key rather than a zero.
    """
    out: dict[str, float] = {}
    for key in _PEER_MEDIAN_KEYS:
        values = [finite(r.get(key)) for r in peer_rows]
        usable = [v for v in values if v is not None and (v > 0 if key == "pe" else True)]
        if usable:
            out[key] = float(statistics.median(usable))
    return out
