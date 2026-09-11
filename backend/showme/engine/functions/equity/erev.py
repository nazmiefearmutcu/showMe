"""EREV — Earnings revision calendar.

Aggregates analyst EPS / revenue revisions from finnhub (recommendations
buckets across time) + EPS estimate trend. Counts upgrades/downgrades by
month and surfaces 4-week revision velocity.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


_BUCKET_WEIGHTS = {
    "strongBuy": 2, "buy": 1, "hold": 0, "sell": -1, "strongSell": -2,
}


@FunctionRegistry.register
class EREVFunction(BaseFunction):
    code = "EREV"
    name = "Earnings Revisions"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Analyst recommendation buckets month-over-month + revision velocity."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (instrument.symbol if instrument else
               params.get("symbol") or "").upper()
        if not sym:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["symbol required"])
        recs: list[dict[str, Any]] | None = None
        provider_error: str | None = None
        if not self.deps.finnhub:
            provider_error = "finnhub provider not wired (no API key configured)"
        else:
            try:
                recs = await self.deps.finnhub.recommendations(sym)
            except Exception as exc:
                provider_error = f"finnhub: {exc}"
        if not recs:
            # F6 honesty fix: previously three hard-coded analyst buckets were
            # substituted and still returned status=ok with sources=["finnhub"]
            # when the provider was absent/failed — every keyless install
            # rendered fabricated months as "live". The manifest's own
            # semantic test (erev_provider_outage_returns_unavailable) requires
            # status=provider_unavailable with an empty trend and no fake rows.
            reason = provider_error or (
                f"finnhub returned no recommendation buckets for {sym}"
            )
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "symbol": sym,
                    "rows": [],
                    "trend": [],
                    "revisions": [],
                    "velocity_avg": None,
                    "current_score": None,
                    "reason": reason,
                    "next_actions": [
                        "Configure a Finnhub API key so analyst recommendation buckets can load.",
                        "Retry later if the provider was rate-limited.",
                    ],
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                },
                sources=[],
                warnings=[reason],
                metadata={
                    "live": False,
                    "fallback": True,
                    "data_mode": (
                        "not_configured" if not self.deps.finnhub
                        else "provider_unavailable"
                    ),
                    "provider_errors": [reason],
                },
            )
        # Sort by period ascending (oldest first)
        rs = sorted(recs, key=lambda r: r.get("period", ""))
        trend: list[dict[str, Any]] = []
        for r in rs:
            score = sum(int(r.get(k, 0) or 0) * w for k, w in _BUCKET_WEIGHTS.items())
            n_total = sum(int(r.get(k, 0) or 0) for k in _BUCKET_WEIGHTS)
            avg = (score / n_total) if n_total else 0
            trend.append({
                "period": r.get("period"),
                "score": score, "n": n_total, "avg": avg,
                **{k: int(r.get(k, 0) or 0) for k in _BUCKET_WEIGHTS},
            })
        # 4-week velocity = latest avg − previous avg (approximation: last vs prev period)
        velocity = (trend[-1]["avg"] - trend[-2]["avg"]) if len(trend) >= 2 else 0
        # Net upgrades/downgrades by period.
        revs: list[dict[str, Any]] = []
        for i in range(1, len(trend)):
            cur = trend[i]
            prev = trend[i - 1]
            net = (cur["strongBuy"] + cur["buy"]) - (prev["strongBuy"] + prev["buy"])
            net_neg = (cur["sell"] + cur["strongSell"]) - (prev["sell"] + prev["strongSell"])
            revs.append({
                "period": cur["period"],
                "net_pos_change": net,
                "net_neg_change": net_neg,
                "delta_avg": cur["avg"] - prev["avg"],
            })
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok",
                "symbol": sym,
                "rows": trend,
                "trend": trend,
                "revisions": revs,
                "velocity_avg": velocity,
                "current_score": trend[-1] if trend else None,
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
            },
            sources=["finnhub"],
            metadata={"live": True, "data_mode": "live_official"},
        )


_METHODOLOGY = (
    "EREV converts analyst recommendation buckets into a weighted score: "
    "Strong Buy=+2, Buy=+1, Hold=0, Sell=-1, Strong Sell=-2. Velocity is the "
    "latest average-score change vs the prior period."
)

_FIELD_DICTIONARY = {
    "score": "Weighted recommendation score for the period.",
    "avg": "Score divided by analyst count.",
    "velocity_avg": "Latest average-score change vs previous period.",
    "net_pos_change": "Change in Strong Buy + Buy count.",
}
