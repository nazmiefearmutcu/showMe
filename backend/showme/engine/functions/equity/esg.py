"""ESG — Environment / Social / Governance scoring (real keyless data).

Primary source: Yahoo Finance sustainability frame (Sustainalytics-derived ESG
risk scores) via the wired yfinance adapter / yfinance package. When Yahoo does
not publish a sustainability frame for a ticker (common for smaller or non-US
names), fall back to a SEC EDGAR full-text-mined E/S/G *proxy*: term-frequency
counts of environmental / social / governance language across the company's
recent 10-K filings, fetched keyless from the EDGAR full-text search index. The
proxy is clearly labelled as a derived signal, never presented as a vendor
(Sustainalytics) score.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_YF_METHODOLOGY = (
    "ESG risk scores sourced from Yahoo Finance sustainability data "
    "(Sustainalytics-derived). Lower scores indicate lower unmanaged ESG risk. "
    "Pillar scores (E/S/G) decompose the total ESG risk score; controversy "
    "level is the highest active controversy (1-5)."
)

_PROXY_METHODOLOGY = (
    "DERIVED PROXY (no Yahoo/Sustainalytics ESG score published for this "
    "ticker). The E/S/G signal is the term-frequency of environmental, social "
    "and governance language mined from the company's recent SEC EDGAR 10-K "
    "filings via the keyless full-text search index. Counts are a relative "
    "emphasis signal, NOT risk scores, and are not comparable to vendor ratings."
)

_FIELD_DICTIONARY = {
    "pillar": "ESG component (total / environment / social / governance / controversy).",
    "score": "Vendor ESG pillar score (lower may indicate lower unmanaged risk).",
    "scale": "Scale / unit semantics for the displayed score.",
    "source_mode": "Provider state for the displayed row.",
    "totalEsg": "Composite ESG risk score.",
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
                "source_mode": "live_yfinance",
            }
        )
    return rows if has_value else None


async def _fetch_proxy_counts(symbol: str) -> dict[str, int]:
    """Mine SEC EDGAR full-text search for E/S/G term emphasis (keyless)."""
    from showme.providers._http import get_client

    client = await get_client()
    counts: dict[str, int] = {}
    for pillar, query in _PROXY_TERMS.items():
        resp = await client.get(
            _EFTS_URL,
            params={"q": query, "entityName": symbol, "forms": "10-K"},
            headers=_SEC_UA,
            timeout=10.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        hits = payload.get("hits", {}) if isinstance(payload, dict) else {}
        total = hits.get("total", {}) if isinstance(hits, dict) else {}
        value = total.get("value") if isinstance(total, dict) else None
        counts[pillar] = int(value) if isinstance(value, (int, float)) else 0
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
        except Exception as exc:  # network / parse failure -> try proxy next
            warnings.append(f"yfinance esg: {exc}")

        flat = _flatten_sustainability(scores)
        rows = _build_rows_from_sustainability(flat) if flat else None
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
                metadata={"provider_errors": warnings + [f"sec_edgar: {exc}"]},
            )

        total_mentions = sum(counts.values())
        if total_mentions == 0:
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
                "data_mode": "cached_snapshot",
                "rows": proxy_rows,
                "warnings": [
                    "No vendor ESG score available for this ticker; values are a "
                    "derived SEC text proxy (filing-mention counts), not risk scores."
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
