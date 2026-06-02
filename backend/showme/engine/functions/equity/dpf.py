"""DPF — Dark Pool / ATS Volume.

Plan §6.4: FINRA OTC Transparency üzerinden ATS volume ve dark pool %.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import recent_week_rows


async def _weekly_total_volume(symbol: str) -> dict[str, float]:
    """Return ``{weekStartDate(Mon iso): total_volume}`` from yfinance weekly bars.

    Best-effort: any failure yields an empty map so ``dark_pool_pct`` is simply
    omitted rather than fabricated. Mirrors DARK's real-denominator approach so
    DPF stops reporting a hardcoded constant dark-pool percentage.
    """
    try:
        import yfinance as yf

        hist = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: yf.Ticker(symbol).history(
                    period="6mo", interval="1wk", auto_adjust=False
                )
            ),
            timeout=4.0,
        )
        if hist is None or hist.empty or "Volume" not in hist.columns:
            return {}
        out: dict[str, float] = {}
        for idx, vol in hist["Volume"].items():
            try:
                v = float(vol)
            except (TypeError, ValueError):
                continue
            if v != v or v <= 0:  # NaN / non-positive
                continue
            try:
                d = idx.date() if hasattr(idx, "date") else datetime.fromisoformat(str(idx)[:10]).date()
            except Exception:
                continue
            monday = d - timedelta(days=d.weekday())  # align to FINRA week-start
            out[monday.isoformat()] = v
        return out
    except Exception:
        return {}


@FunctionRegistry.register
class DPFFunction(BaseFunction):
    code = "DPF"
    name = "Dark Pool / ATS Volume"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"
    description = "FINRA-reported off-exchange (ATS) volume + dark-pool % of total."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("DPF requires instrument")
        try:
            return await asyncio.wait_for(
                self._execute_inner(instrument, **params),
                timeout=9.0,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = f"DPF execution timed out: {exc}"
            weekly = recent_week_rows(instrument.symbol, int(params.get("weeks", 12)), source_mode="labelled_current_shape_model")
            for row in weekly:
                row["source_mode"] = "finra_ats_weekly_stale"
                row["data_warning"] = reason
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": reason,
                    "weekly": weekly,
                    "rows": weekly,
                    "history": weekly,
                    "raw_rows": 0,
                    "methodology": "DPF reports weekly FINRA ATS/off-exchange share volume and computes dark-pool percent as ATS volume divided by the REAL consolidated weekly volume from yfinance for the same week. When the real total volume is unavailable for a week, dark_pool_pct and estimated_total_volume are left null rather than fabricated. Stale FINRA snapshots are labelled provider_unavailable instead of being presented as current data.",
                    "field_dictionary": {
                        "weekStartDate": "FINRA reporting week start date.",
                        "ats_share_volume": "ATS/off-exchange shares reported for the symbol.",
                        "estimated_total_volume": "Real consolidated weekly volume (yfinance) for that week; null when unavailable.",
                        "dark_pool_pct": "ATS share of the real total weekly volume (%); null when the real denominator is unavailable.",
                        "source_mode": "Live FINRA row or labelled fallback shape.",
                    },
                    "next_actions": ["Connect or refresh FINRA ATS feed for current venue-level volume."],
                },
                sources=["dark_pool_model"],
                metadata={
                    "note": "Anonymous FINRA endpoint may rate-limit; OAuth recommended.",
                    "provider_errors": [reason],
                },
            )

    async def _execute_inner(self, instrument: Instrument, **params: Any) -> FunctionResult:
        weeks = int(params.get("weeks", 12))
        warnings: list[str] = []
        sources: list[str] = []
        df = pd.DataFrame()
        if getattr(self.deps, "finra", None):
            try:
                df = await self.deps.finra.ats_weekly(instrument.symbol, limit=weeks * 4)
                sources.append("finra")
            except Exception as e:
                warnings.append(f"finra: {e}")
        # Aggregate by week & ATS code
        agg = pd.DataFrame()
        if not df.empty and "weekStartDate" in df.columns:
            qty_col = next((c for c in df.columns if "ShareQuantity" in c), None)
            tc_col = next((c for c in df.columns if "TradeCount" in c), None)
            if qty_col:
                df = df.copy()
                df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce")
                if tc_col:
                    df[tc_col] = pd.to_numeric(df[tc_col], errors="coerce")
                grp = df.groupby("weekStartDate")
                agg = grp[qty_col].sum().reset_index().rename(
                    columns={qty_col: "ats_share_volume"}
                )
                if tc_col:
                    agg["ats_trade_count"] = grp[tc_col].sum().values
                # Real dark-pool % = ATS volume / the REAL consolidated weekly
                # volume from yfinance — never the old hardcoded 38.0 constant.
                # When the real denominator is unavailable for a week, leave the
                # percentage and estimate as None rather than fabricating them.
                week_total = await _weekly_total_volume(instrument.symbol)

                def _total_for(week_start: Any) -> float | None:
                    return week_total.get(str(week_start)[:10])

                def _dark_pct(row: pd.Series) -> float | None:
                    total = _total_for(row["weekStartDate"])
                    ats = row["ats_share_volume"]
                    if total and total > 0 and ats == ats:
                        return round(min(100.0, float(ats) / float(total) * 100.0), 2)
                    return None

                agg["estimated_total_volume"] = agg["weekStartDate"].map(_total_for)
                agg["dark_pool_pct"] = agg.apply(_dark_pct, axis=1)
                agg["source_mode"] = "finra_ats_weekly"
                agg = agg.sort_values("weekStartDate", ascending=False).head(weeks)
                if week_total:
                    sources.append("yfinance")
        weekly = agg.to_dict(orient="records") if hasattr(agg, "to_dict") and not agg.empty else recent_week_rows(instrument.symbol, weeks, source_mode="labelled_current_shape_model")
        status = "ok" if hasattr(agg, "empty") and not agg.empty else "provider_unavailable"
        stale_reason = _stale_reason((weekly[0] or {}).get("weekStartDate") if weekly else None)
        if stale_reason:
            status = "provider_unavailable"
            for row in weekly:
                row["source_mode"] = "finra_ats_weekly_stale"
                row["data_warning"] = stale_reason
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                "reason": stale_reason,
                "weekly": weekly,
                "rows": weekly,
                "history": weekly,
                "raw_rows": int(len(df)),
                "methodology": "DPF reports weekly FINRA ATS/off-exchange share volume and computes dark-pool percent as ATS volume divided by the REAL consolidated weekly volume from yfinance for the same week. When the real total volume is unavailable for a week, dark_pool_pct and estimated_total_volume are left null rather than fabricated. Stale FINRA snapshots are labelled provider_unavailable instead of being presented as current data.",
                "field_dictionary": {
                    "weekStartDate": "FINRA reporting week start date.",
                    "ats_share_volume": "ATS/off-exchange shares reported for the symbol.",
                    "estimated_total_volume": "Real consolidated weekly volume (yfinance) for that week; null when unavailable.",
                    "dark_pool_pct": "ATS share of the real total weekly volume (%); null when the real denominator is unavailable.",
                    "source_mode": "Live FINRA row or labelled fallback shape.",
                },
                "next_actions": [] if status == "ok" else ["Connect or refresh FINRA ATS feed for current venue-level volume."],
            },
            sources=sources or ["dark_pool_model"],
            metadata={
                "note": "Anonymous FINRA endpoint may rate-limit; OAuth recommended.",
                "provider_errors": warnings,
            },
        )


def _stale_reason(value: Any) -> str | None:
    try:
        dt = datetime.fromisoformat(str(value)[:10]).date()
        if dt < (datetime.now(timezone.utc).date() - timedelta(days=180)):
            return f"FINRA latest week {dt.isoformat()} is stale for a current market cockpit."
    except Exception:
        return None
    return None
