"""ESG — Environment / Social / Governance scoring (real keyless data).

Primary source: Yahoo Finance sustainability frame (Sustainalytics-derived ESG
risk scores) via the wired yfinance adapter / yfinance package. When Yahoo does
not publish a sustainability frame for a ticker (common for smaller or non-US
names), fall back to a SEC EDGAR full-text-mined E/S/G *proxy*: term-frequency
counts of environmental / social / governance language across the company's
10-K filings from the last three years, fetched keyless from the EDGAR full-text search index. The
proxy is clearly labelled as a derived signal, never presented as a vendor
(Sustainalytics) score.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_YF_METHODOLOGY = (
    "ESG risk scores sourced from Yahoo Finance sustainability data "
    "(Sustainalytics-derived). Lower scores indicate lower unmanaged ESG risk. "
    "Pillar scores (E/S/G) decompose the total ESG risk score; controversy "
    "level is the highest active controversy (1-5)."
)

_PROXY_WINDOW_YEARS = 3

_PROXY_METHODOLOGY = (
    "DERIVED PROXY (no Yahoo/Sustainalytics ESG score published for this "
    "ticker). Each count is the number of SEC EDGAR 10-K filings filed in the "
    f"last {_PROXY_WINDOW_YEARS} years whose text contains at least one E, S or G "
    "term (keyless full-text search index). These are filing counts, not term "
    "frequency. The total counts filings matching any term, so it is not the sum "
    "of the pillars. Counts are a relative emphasis signal, NOT risk scores, and "
    "are not comparable to vendor ratings."
)

_FIELD_DICTIONARY = {
    "pillar": "ESG component (total / environment / social / governance / controversy).",
    "score": "Row score: vendor ESG risk score (yfinance path, lower = lower unmanaged risk) or a 10-K filing count (SEC proxy path, not a risk score).",
    "scale": "Scale / unit semantics for the displayed score.",
    "source_mode": "Provider state for the displayed row.",
    "totalEsg": "Vendor composite ESG risk score (yfinance path). On the SEC proxy path it is the count of unique 10-K filings in the window matching any E/S/G term, not a risk score.",
    "environmentScore": "E pillar score.",
    "socialScore": "S pillar score.",
    "governanceScore": "G pillar score.",
    "controversyLevel": "Highest active controversy level (1-5) when available.",
}

# Term buckets used for the SEC EDGAR full-text proxy.
_PROXY_TERMS: dict[str, str] = {
    "environment": (
        '"climate change" OR "greenhouse gas" OR "carbon emissions" OR '
        '"renewable energy" OR "environmental"'
    ),
    "social": (
        '"human capital" OR "diversity" OR "employee safety" OR '
        '"community" OR "labor practices"'
    ),
    "governance": (
        '"board independence" OR "executive compensation" OR '
        '"shareholder rights" OR "audit committee" OR "corporate governance"'
    ),
}

_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_SEC_UA = {"User-Agent": "showMe research contact@example.com"}


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _flatten_sustainability(scores: Any) -> dict[str, Any]:
    """Normalise a yfinance sustainability table to a flat key->value dict."""
    if not isinstance(scores, dict):
        return {}
    flat = scores
    if "Value" in scores and isinstance(scores.get("Value"), dict):
        flat = scores["Value"]
    return flat if isinstance(flat, dict) else {}


def _build_rows_from_sustainability(flat: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Build pillar rows; return None when no real pillar value is present."""
    spec = [
        ("totalEsg", "total"),
        ("environmentScore", "environment"),
        ("socialScore", "social"),
        ("governanceScore", "governance"),
        ("highestControversy", "controversy"),
    ]
    rows: list[dict[str, Any]] = []
    has_value = False
    for key, label in spec:
        value = _coerce_float(flat.get(key))
        if value is not None and label != "controversy":
            has_value = True
        rows.append(
            {
                "pillar": label,
                "score": value,
                "scale": "vendor risk scale (lower=better)"
                if label != "controversy"
                else "level 1-5",
                "source_mode": "delayed_reference",
            }
        )
    return rows if has_value else None


def proxy_window(today: date | None = None) -> dict[str, str]:
    """Filing-date window the proxy counts cover: the last few years, inclusive."""
    end = today or date.today()
    start = end - timedelta(days=365 * _PROXY_WINDOW_YEARS)
    return {"startdt": start.isoformat(), "enddt": end.isoformat(), "form": "10-K"}


async def _efts_total(client: Any, query: str, symbol: str, window: dict[str, str]) -> int:
    resp = await client.get(
        _EFTS_URL,
        params={"q": query, "entityName": symbol, "forms": "10-K",
                "startdt": window["startdt"], "enddt": window["enddt"]},
        headers=_SEC_UA,
        timeout=10.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    hits = payload.get("hits", {}) if isinstance(payload, dict) else {}
    total = hits.get("total", {}) if isinstance(hits, dict) else {}
    value = total.get("value") if isinstance(total, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        # No count in the payload is not a zero count: surface it as a provider error.
        raise ValueError("EFTS response has no hits.total.value")
    return int(value)


async def _fetch_proxy_counts(symbol: str) -> dict[str, int]:
    """Count the 10-K filings in the proxy window that match each E/S/G bucket.

    ``any`` is the number of filings matching at least one term across all
    buckets. It is queried directly, because summing the pillars would count a
    filing once per pillar it mentions.
    """
    from showme.providers._http import get_client

    client = await get_client()
    window = proxy_window()
    counts: dict[str, int] = {}
    for pillar, query in _PROXY_TERMS.items():
        counts[pillar] = await _efts_total(client, query, symbol, window)
    any_query = " OR ".join(_PROXY_TERMS.values())
    counts["any"] = await _efts_total(client, any_query, symbol, window)
    return counts


@FunctionRegistry.register
class ESGFunction(BaseFunction):
    code = "ESG"
    name = "ESG Scores"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError

        symbol = instrument.symbol
        warnings: list[str] = []

        # ---- Primary: Yahoo Finance sustainability (Sustainalytics) ----
        scores: dict[str, Any] = {}
        yahoo_note: str | None = None  # why the Yahoo primary gave no pillar values
        try:
            if self.deps.yfinance:
                import yfinance as yf

                timeout = float(params.get("timeout", 8))
                t = await asyncio.wait_for(
                    asyncio.to_thread(yf.Ticker, symbol), timeout=timeout
                )
                sus = await asyncio.wait_for(
                    asyncio.to_thread(getattr, t, "sustainability", None),
                    timeout=timeout,
                )
                if sus is not None:
                    scores = sus.to_dict() if hasattr(sus, "to_dict") else dict(sus)
            else:
                yahoo_note = "yahoo sustainability: yfinance adapter not configured"
        except Exception as exc:  # network / parse failure -> try proxy next
            yahoo_note = f"yfinance esg: {str(exc) or type(exc).__name__}"

        flat = _flatten_sustainability(scores)
        rows = _build_rows_from_sustainability(flat) if flat else None
        if rows is None:
            # Record why the primary gave nothing, so provenance shows why the proxy answered.
            warnings.append(
                yahoo_note or "yahoo sustainability: Yahoo published no pillar values for this ticker"
            )
        if rows is not None:
            data = {
                "symbol": symbol,
                "status": "ok",
                "totalEsg": _coerce_float(flat.get("totalEsg")),
                "environmentScore": _coerce_float(flat.get("environmentScore")),
                "socialScore": _coerce_float(flat.get("socialScore")),
                "governanceScore": _coerce_float(flat.get("governanceScore")),
                "controversyLevel": _coerce_float(flat.get("highestControversy")),
                "data_mode": "delayed_reference",
                "rows": rows,
                "methodology": _YF_METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
            }
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=data,
                sources=["yfinance"],
                metadata={"source_kind": "sustainalytics"},
            )

        # ---- Fallback: SEC EDGAR text-mined E/S/G proxy (keyless) ----
        try:
            counts = await _fetch_proxy_counts(symbol)
        except Exception as exc:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "symbol": symbol,
                    "status": "provider_unavailable",
                    "data_mode": "not_configured",
                    "totalEsg": None,
                    "environmentScore": None,
                    "socialScore": None,
                    "governanceScore": None,
                    "controversyLevel": None,
                    "rows": [],
                    "next_actions": [
                        "Retry later",
                        "Verify the ticker is a US SEC filer",
                    ],
                    "methodology": (
                        "No Yahoo Finance sustainability data and SEC EDGAR "
                        "full-text search is unavailable."
                    ),
                    "field_dictionary": _FIELD_DICTIONARY,
                },
                sources=["yfinance", "sec_edgar"],
                metadata={"provider_errors": warnings + [f"sec_edgar: {str(exc) or type(exc).__name__}"]},
            )

        # Total = filings matching any E/S/G term (never the sum of the pillars,
        # which would count one filing once per pillar it mentions).
        total_mentions = counts.get("any")
        if not any(counts.get(pillar, 0) for pillar in _PROXY_TERMS):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "symbol": symbol,
                    "status": "empty",
                    "data_mode": "not_configured",
                    "rows": [],
                    "next_actions": [
                        "No vendor ESG score and no E/S/G filing language found",
                        "Verify the ticker is a US SEC filer",
                    ],
                    "methodology": _PROXY_METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                },
                sources=["yfinance", "sec_edgar"],
                metadata={"provider_errors": warnings} if warnings else {},
            )

        proxy_rows = [
            {
                "pillar": "total",
                "score": total_mentions,
                "scale": "filing mentions (proxy)",
                "source_mode": "sec_text_proxy",
            },
            {
                "pillar": "environment",
                "score": counts["environment"],
                "scale": "filing mentions (proxy)",
                "source_mode": "sec_text_proxy",
            },
            {
                "pillar": "social",
                "score": counts["social"],
                "scale": "filing mentions (proxy)",
                "source_mode": "sec_text_proxy",
            },
            {
                "pillar": "governance",
                "score": counts["governance"],
                "scale": "filing mentions (proxy)",
                "source_mode": "sec_text_proxy",
            },
        ]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "symbol": symbol,
                "status": "ok",
                "totalEsg": total_mentions,
                "environmentScore": counts["environment"],
                "socialScore": counts["social"],
                "governanceScore": counts["governance"],
                "controversyLevel": None,
                "data_mode": "live_official",
                "window": proxy_window(),
                "rows": proxy_rows,
                "warnings": [
                    "No vendor ESG score available for this ticker; values are a "
                    f"derived SEC text proxy (10-K filing counts, last "
                    f"{_PROXY_WINDOW_YEARS} years), not risk scores."
                ],
                "methodology": _PROXY_METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
            },
            sources=["sec_edgar"],
            metadata={
                "source_kind": "sec_text_proxy",
                "provider_errors": warnings,
            },
        )
