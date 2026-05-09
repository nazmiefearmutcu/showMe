"""ESG — Environment / Social / Governance scoring."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class ESGFunction(BaseFunction):
    code = "ESG"
    name = "ESG Scores"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        scores = {}
        try:
            if self.deps.yfinance:
                import yfinance as yf
                timeout = float(params.get("timeout", 8))
                t = await asyncio.wait_for(asyncio.to_thread(yf.Ticker, instrument.symbol), timeout=timeout)
                sus = await asyncio.wait_for(
                    asyncio.to_thread(getattr, t, "sustainability", None),
                    timeout=timeout,
                )
                if sus is not None:
                    scores = sus.to_dict() if hasattr(sus, "to_dict") else dict(sus)
        except Exception as e:
            warnings.append(f"yfinance esg: {e}")
        if not scores:
            scores = {
                "status": "provider_unavailable",
                "reason": "Yahoo sustainability scores are unavailable for this symbol or account context.",
                "totalEsg": None,
                "environmentScore": None,
                "socialScore": None,
                "governanceScore": None,
                "controversyLevel": None,
                "rows": [
                    {"pillar": "total", "score": None, "scale": "0-100 vendor scale", "source_mode": "vendor_unavailable"},
                    {"pillar": "environment", "score": None, "scale": "0-100 vendor scale", "source_mode": "vendor_unavailable"},
                    {"pillar": "social", "score": None, "scale": "0-100 vendor scale", "source_mode": "vendor_unavailable"},
                    {"pillar": "governance", "score": None, "scale": "0-100 vendor scale", "source_mode": "vendor_unavailable"},
                ],
                "next_actions": ["Connect an ESG vendor feed or retry a symbol with Yahoo sustainability coverage."],
                "methodology": "ESG is vendor-scored. ShowMe does not fabricate missing ESG scores; missing provider rows are labelled provider_unavailable.",
                "field_dictionary": {
                    "score": "Vendor ESG pillar score, typically 0-100 where lower may indicate lower unmanaged risk depending on vendor.",
                    "controversyLevel": "Vendor controversy/risk level when available.",
                    "source_mode": "Provider state for the displayed row.",
                },
            }
            warnings = []
        else:
            rows = []
            flat = scores
            if "Value" in scores:
                flat = scores.get("Value") or scores
            for key, label in [
                ("totalEsg", "total"),
                ("environmentScore", "environment"),
                ("socialScore", "social"),
                ("governanceScore", "governance"),
                ("controversyLevel", "controversy"),
            ]:
                value = flat.get(key) if isinstance(flat, dict) else None
                rows.append({"pillar": label, "score": value, "scale": "vendor scale", "source_mode": "live_yfinance"})
            if isinstance(scores, dict):
                scores = {
                    **scores,
                    "status": "ok",
                    "rows": rows,
                    "methodology": "Scores are passed through from the vendor sustainability table and rendered by pillar. Scale and controversy semantics depend on the upstream provider.",
                    "field_dictionary": {
                        "pillar": "ESG component.",
                        "score": "Provider score for the pillar.",
                        "source_mode": "Provider state for the row.",
                    },
                }
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=scores,
            sources=["yfinance"] if not warnings else ["esg_model"],
            metadata={"provider_errors": warnings} if warnings else {},
        )
