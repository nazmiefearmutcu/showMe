"""EREV — analyst recommendation momentum.

Scores the Finnhub analyst recommendation buckets (strongBuy..strongSell)
per monthly period, counts net upgrades/downgrades between periods and
reports the change in the average score vs the prior period. This is NOT an
EPS or revenue estimate-revision series: no EPS estimate data is read.
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
    description = "Analyst recommendation buckets month-over-month + momentum (no EPS estimate data)."

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
            # A period with no analysts has no consensus: null, never a neutral 0.
            avg = (score / n_total) if n_total else None
            trend.append({
                "period": r.get("period"),
                "score": score, "n": n_total, "avg": avg,
                **{k: int(r.get(k, 0) or 0) for k in _BUCKET_WEIGHTS},
            })
        # Momentum = latest avg − previous monthly avg; null unless both periods have coverage.
        velocity = None
        if len(trend) >= 2 and trend[-1]["avg"] is not None and trend[-2]["avg"] is not None:
            velocity = trend[-1]["avg"] - trend[-2]["avg"]
        # Net upgrades/downgrades by period.
        revs: list[dict[str, Any]] = []
        for i in range(1, len(trend)):
            cur = trend[i]
            prev = trend[i - 1]
            net = (cur["strongBuy"] + cur["buy"]) - (prev["strongBuy"] + prev["buy"])
            net_neg = (cur["sell"] + cur["strongSell"]) - (prev["sell"] + prev["strongSell"])
            delta = (
                cur["avg"] - prev["avg"]
                if cur["avg"] is not None and prev["avg"] is not None
                else None
            )
            revs.append({
                "period": cur["period"],
                "net_pos_change": net,
                "net_neg_change": net_neg,
                "delta_avg": delta,
            })
        has_coverage = any(t["n"] for t in trend)
        status = "ok" if has_coverage else "empty"
        empty_reason = (
            None if has_coverage
            else f"finnhub returned recommendation periods for {sym} with zero analysts in every period"
        )
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                "reason": empty_reason,
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
            warnings=[empty_reason] if empty_reason else [],
            metadata={"live": has_coverage, "data_mode": "live_official" if has_coverage else "empty_coverage"},
        )


_METHODOLOGY = (
    "EREV scores analyst recommendation buckets (not EPS or revenue estimates): "
    "Strong Buy=+2, Buy=+1, Hold=0, Sell=-1, Strong Sell=-2, averaged per analyst. "
    "Momentum is the latest monthly average-score change vs the prior month; "
    "null when either month has no analysts."
)

_FIELD_DICTIONARY = {
    "score": "Weighted recommendation score for the period.",
    "avg": "Score divided by analyst count; null when the period has no analysts.",
    "velocity_avg": "Latest monthly average-score change vs previous month; null with fewer than two covered months.",
    "net_pos_change": "Change in Strong Buy + Buy count.",
}
