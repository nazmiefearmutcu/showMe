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


_METHODOLOGY = (
    "DPF reports weekly FINRA ATS/off-exchange share volume and computes dark-pool "
    "percent as ATS volume divided by the REAL consolidated weekly volume from yfinance "
    "for the same week. When the real total volume is unavailable for a week, "
    "dark_pool_pct and estimated_total_volume are left null rather than fabricated. "
    "When FINRA cannot be read or returns no weeks, the weekly table is empty and the "
    "status is provider_unavailable or empty: no placeholder volumes are shown. Stale "
    "FINRA snapshots are labelled provider_unavailable instead of being presented as "
    "current data."
)

_NEXT_ACTIONS = ["Connect or refresh FINRA ATS feed for current venue-level volume."]


def _unavailable_data(symbol: str, reason: str, status: str = "provider_unavailable") -> dict[str, Any]:
    """Honest empty payload: no weekly rows, a reason and next actions."""
    return {
        "status": status,
        "reason": reason,
        "symbol": symbol,
        "weekly": [],
        "rows": [],
        "history": [],
        "raw_rows": 0,
        "latest_dark_pool_pct": None,
        "latest_ats_volume": None,
        "data_mode": "provider_unavailable",
        "as_of": None,
        "methodology": _METHODOLOGY,
        "field_dictionary": _field_dictionary(),
        "next_actions": list(_NEXT_ACTIONS),
    }


def _field_dictionary() -> dict[str, str]:
    return {
        "weekStartDate": "FINRA reporting week start date.",
        "ats_share_volume": "ATS/off-exchange shares reported for the symbol.",
        "estimated_total_volume": "Real consolidated weekly volume (yfinance) for that week; null when unavailable.",
        "dark_pool_pct": "ATS share of the real total weekly volume (%); null when the real denominator is unavailable.",
        "source_mode": "Live FINRA row (finra_ats_weekly), or finra_ats_weekly_stale when the newest week is too old.",
    }


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
            return FunctionResult(
                code=self.code, instrument=instrument,
                data=_unavailable_data(instrument.symbol, reason),
                sources=[],
                warnings=[reason],
                metadata={
                    "note": "Anonymous FINRA endpoint may rate-limit; OAuth recommended.",
                    "provider_errors": [reason],
                },
            )

    async def _execute_inner(self, instrument: Instrument, **params: Any) -> FunctionResult:
        weeks = max(1, int(params.get("weeks", 12)))
        warnings: list[str] = []
        sources: list[str] = []
        df = pd.DataFrame()
        if getattr(self.deps, "finra", None):
            try:
                # The adapter's limit counts published WEEKS and returns the newest
                # ones with every row of each week (see FINRAAdapter.ats_weekly).
                df = await self.deps.finra.ats_weekly(instrument.symbol, limit=weeks)
                # Only a provider that actually returned rows is a source.
                if not df.empty:
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

        if agg.empty:
            reason = (
                f"FINRA ATS weekly data unavailable for {instrument.symbol}: "
                + ("; ".join(warnings) if warnings else "no weeks returned by FINRA.")
            )
            return FunctionResult(
                code=self.code, instrument=instrument,
                data=_unavailable_data(instrument.symbol, reason),
                sources=sources,
                warnings=[reason],
                metadata={
                    "note": "Anonymous FINRA endpoint may rate-limit; OAuth recommended.",
                    "provider_errors": warnings,
                },
            )

        weekly = agg.to_dict(orient="records")
        stale_reason = _stale_reason(weekly[0].get("weekStartDate") if weekly else None)
        status = "ok"
        if stale_reason:
            status = "provider_unavailable"
            for row in weekly:
                row["source_mode"] = "finra_ats_weekly_stale"
                row["data_warning"] = stale_reason
        latest = weekly[0] if status == "ok" and weekly else None
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                "reason": stale_reason,
                "weekly": weekly,
                "rows": weekly,
                "history": weekly,
                "raw_rows": int(len(df)),
                # Card slots (manifest card_schema) read these top-level keys; they
                # are filled only from a live, non-stale latest week (DPF card fix).
                "latest_dark_pool_pct": latest.get("dark_pool_pct") if latest else None,
                "latest_ats_volume": latest.get("ats_share_volume") if latest else None,
                "data_mode": "delayed_reference" if status == "ok" else "provider_unavailable",
                "as_of": latest.get("weekStartDate") if latest else None,
                "methodology": _METHODOLOGY,
                "field_dictionary": _field_dictionary(),
                "next_actions": [] if status == "ok" else list(_NEXT_ACTIONS),
            },
            sources=sources,
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
        # A malformed FINRA date must not be treated as fresh.
        return f"FINRA latest week {value!r} could not be parsed; treating as stale until reprocessed."
    return None
