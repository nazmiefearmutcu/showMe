"""DARK — Dark pool / off-exchange ATS volume aggregation.

Live data path uses FINRA's keyless OTC Transparency Weekly Summary API
(https://api.finra.org/data/group/otcMarket/name/weeklySummary) for per-venue
(MPID) weekly off-exchange ATS share volume, then joins yfinance weekly total
volume so the dark-pool % is a REAL ratio (ATS volume / total weekly volume),
not a hardcoded constant. When FINRA is unreachable the handler returns an
honest provider_unavailable shape with empty venues + next_actions — it does
NOT fabricate venue rows.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import FIELD_DICTIONARIES, finite

# FINRA OTC Transparency — keyless public Query API.
_FINRA_WEEKLY_URL = (
    "https://api.finra.org/data/group/otcMarket/name/weeklySummary"
)
# ATS (Alternative Trading System) weekly, broken out by symbol.
_FINRA_ATS_TYPE = "ATS_W_SMBL"

_METHODOLOGY = (
    "DARK pulls FINRA OTC Transparency weekly ATS aggregates (off-exchange share "
    "volume + trade count per reporting venue/MPID) and joins them against yfinance "
    "weekly total volume. dark_pool_pct = ATS weekly volume / total weekly volume "
    "for the matching week (capped at 100). Venues are ranked by ATS volume inside "
    "the most-recent reported week so the operator can see who provides the "
    "off-exchange liquidity. When FINRA is unreachable the handler returns "
    "status=provider_unavailable with empty venues and next_actions instead of "
    "synthesising placeholder rows."
)

_FIELD_DICTIONARY = {
    "venue": "FINRA reporting MPID / ATS venue identifier for the off-exchange prints.",
    "ats_share_volume": "Weekly off-exchange ATS share volume reported by the venue.",
    "ats_trade_count": "Weekly off-exchange ATS trade count reported by the venue.",
    "dark_pool_pct": "ATS weekly volume divided by total weekly volume (lit + ATS), capped at 100.",
    "weekStartDate": "FINRA reporting week start date (week the prints settled).",
    "top_venue_share_pct": "Largest venue's share of aggregate ATS volume in the latest week.",
}


@FunctionRegistry.register
class DARKFunction(BaseFunction):
    code = "DARK"
    name = "Dark Pool Volume"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"
    description = "FINRA ATS (Alternative Trading System) weekly off-exchange volume by venue."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (instrument.symbol if instrument else
               params.get("symbol") or "AAPL").upper()
        try:
            return await asyncio.wait_for(
                self._execute_inner(instrument, **params),
                timeout=9.0,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = f"DARK execution timed out: {exc}"
            return FunctionResult(
                code=self.code, instrument=instrument,
                data=_unavailable(sym, reason, [reason]),
                sources=["finra"],
                warnings=[reason],
                metadata={"provider_errors": [reason]},
            )

    async def _execute_inner(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (instrument.symbol if instrument else
               params.get("symbol") or "AAPL").upper()
        try:
            weeks = int(params.get("weeks", 8))
        except (TypeError, ValueError):
            weeks = 8
        weeks = max(2, min(26, weeks))

        provider_errors: list[str] = []

        # 1) Pull FINRA weekly ATS rows and yfinance weekly total volume concurrently.
        raw_rows: list[dict[str, Any]] = []
        week_total_volume: dict[str, float] = {}

        async def _safe_finra():
            try:
                return await self._fetch_finra_ats(sym)
            except Exception as exc:
                provider_errors.append(f"finra: {exc}")
                return []

        async def _safe_weekly():
            try:
                return await self._weekly_total_volume(sym)
            except Exception as exc:
                provider_errors.append(f"yfinance weekly volume: {exc}")
                return {}

        raw_rows, week_total_volume = await asyncio.gather(
            _safe_finra(),
            _safe_weekly()
        )

        if not raw_rows:
            reason = (
                "FINRA OTC Transparency weekly ATS endpoint returned no rows for "
                f"{sym} (symbol may be non-ATS-reported or the FINRA API is down)."
            )
            return FunctionResult(
                code=self.code, instrument=instrument,
                data=_unavailable(sym, reason, provider_errors),
                sources=["finra"],
                warnings=[reason],
                metadata={"provider_errors": provider_errors},
            )

        df = pd.DataFrame(raw_rows)

        # 2) Aggregate by venue (across reported weeks) and by week.
        df["ats_share_volume"] = df["ats_share_volume"].apply(lambda v: finite(v) or 0.0)
        df["ats_trade_count"] = df["ats_trade_count"].apply(lambda v: finite(v) or 0.0)

        by_week = (
            df.groupby("weekStartDate")
            .agg(
                ats_share_volume=("ats_share_volume", "sum"),
                ats_trade_count=("ats_trade_count", "sum"),
                n_venues=("venue", "nunique"),
            )
            .reset_index()
            .sort_values("weekStartDate", ascending=False)
        )
        week_records: list[dict[str, Any]] = []
        for rec in by_week.head(weeks).to_dict(orient="records"):
            wk = str(rec["weekStartDate"])[:10]
            ats_vol = float(rec["ats_share_volume"] or 0.0)
            total_vol = week_total_volume.get(wk)
            dark_pct: float | None = None
            if total_vol and total_vol > 0:
                dark_pct = round(min(100.0, ats_vol / total_vol * 100.0), 2)
            week_records.append({
                "weekStartDate": wk,
                "ats_share_volume": round(ats_vol),
                "ats_trade_count": round(float(rec["ats_trade_count"] or 0.0)),
                "n_venues": int(rec["n_venues"] or 0),
                "total_weekly_volume": round(total_vol) if total_vol else None,
                "dark_pool_pct": dark_pct,
                "source_mode": "finra_otc_weekly_ats",
            })

        latest_week = week_records[0]["weekStartDate"] if week_records else None

        # Venue ranking: prefer the latest reported week; that is what the
        # manifest table_schema/card "Venues" expects.
        latest_df = df[df["weekStartDate"].astype(str).str[:10] == latest_week] if latest_week else df
        by_venue = (
            latest_df.groupby("venue")
            .agg(
                ats_share_volume=("ats_share_volume", "sum"),
                ats_trade_count=("ats_trade_count", "sum"),
            )
            .reset_index()
            .sort_values("ats_share_volume", ascending=False)
        )
        latest_total = float(by_venue["ats_share_volume"].sum() or 0.0)
        latest_week_total_vol = week_total_volume.get(latest_week) if latest_week else None
        venue_records: list[dict[str, Any]] = []
        for rec in by_venue.to_dict(orient="records"):
            vol = float(rec["ats_share_volume"] or 0.0)
            v_dark_pct: float | None = None
            if latest_week_total_vol and latest_week_total_vol > 0:
                v_dark_pct = round(min(100.0, vol / latest_week_total_vol * 100.0), 2)
            venue_records.append({
                "venue": str(rec["venue"]),
                "ats_share_volume": round(vol),
                "ats_trade_count": round(float(rec["ats_trade_count"] or 0.0)),
                "share_of_ats_pct": round(vol / latest_total * 100.0, 2) if latest_total else None,
                "dark_pool_pct": v_dark_pct,
                "weekStartDate": latest_week,
                "source_mode": "finra_otc_weekly_ats",
            })

        # Stale guard: a months-old latest week should not masquerade as current.
        stale = _stale_reason(latest_week)
        status = "provider_unavailable" if stale else "ok"
        warnings: list[str] = []
        if stale:
            warnings.append(stale)

        latest_dark_pct = week_records[0]["dark_pool_pct"] if week_records else None
        top_venue_share = venue_records[0]["share_of_ats_pct"] if venue_records else None

        cards = {
            "latest_dark_pool_pct": latest_dark_pct,
            "latest_ats_volume": week_records[0]["ats_share_volume"] if week_records else None,
            "venue_count": len(venue_records),
            "data_mode": "delayed_reference" if status == "ok" else "provider_unavailable",
            "as_of": latest_week,
        }

        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                "reason": stale,
                "symbol": sym,
                "n_rows": int(len(df)),
                "total_shares_off_exchange": round(float(df["ats_share_volume"].sum() or 0.0)),
                "top_venue_share_pct": top_venue_share,
                "rows": venue_records,
                "venues": venue_records,
                "by_venue": venue_records,
                "by_week": week_records,
                "history": week_records,
                "cards": cards,
                "summary": {
                    "latest_week": latest_week,
                    "latest_dark_pool_pct": latest_dark_pct,
                    "venue_count": len(venue_records),
                },
                "methodology": _METHODOLOGY,
                "field_dictionary": {
                    **FIELD_DICTIONARIES["corporate_actions"],
                    **_FIELD_DICTIONARY,
                },
            },
            sources=["finra", "yfinance"],
            warnings=warnings,
            metadata={"provider_errors": provider_errors} if provider_errors else {},
        )

    async def _fetch_finra_ats(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch keyless FINRA OTC Transparency weekly ATS rows for ``symbol``.

        Prefers a wired ``self.deps.finra`` adapter if it exposes ``ats_weekly``;
        otherwise queries the public FINRA Query API directly. Returns a list of
        normalised dicts (venue, ats_share_volume, ats_trade_count, weekStartDate)
        or an empty list when nothing is reported.
        """
        # Wired adapter path (kept for parity with existing wiring / tests).
        adapter = getattr(self.deps, "finra", None)
        if adapter is not None and hasattr(adapter, "ats_weekly"):
            df = await adapter.ats_weekly(symbol=symbol, limit=200)
            if df is not None and len(df) > 0:
                return _normalise_adapter_frame(df)

        # Direct keyless FINRA Query API.
        from showme.providers._http import get_client

        client = await get_client()
        payload = {
            "compareFilters": [
                {
                    "fieldName": "summaryTypeCode",
                    "fieldValue": _FINRA_ATS_TYPE,
                    "compareType": "EQUAL",
                },
                {
                    "fieldName": "issueSymbolIdentifier",
                    "fieldValue": symbol,
                    "compareType": "EQUAL",
                },
            ],
            "limit": 200,
        }
        resp = await client.post(
            _FINRA_WEEKLY_URL,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=8.0,
        )
        resp.raise_for_status()
        body = resp.json()
        rows = body if isinstance(body, list) else body.get("data") or body.get("rows") or []
        return _normalise_finra_rows(rows)

    async def _weekly_total_volume(self, symbol: str) -> dict[str, float]:
        """Return {weekStartDate(Mon iso): total_volume} from yfinance weekly bars.

        Best-effort: any failure yields an empty map so dark_pool_pct is simply
        omitted rather than fabricated.
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
                v = finite(vol)
                if v is None or v <= 0:
                    continue
                try:
                    d = idx.date() if hasattr(idx, "date") else datetime.fromisoformat(str(idx)[:10]).date()
                except Exception:
                    continue
                # Snap to Monday so it lines up with FINRA week-start dates.
                monday = d - timedelta(days=d.weekday())
                out[monday.isoformat()] = float(v)
            return out
        except Exception:
            return {}


def _normalise_finra_rows(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        venue = (
            r.get("MPID")
            or r.get("mpid")
            or r.get("firmCRDNumber")
            or r.get("marketParticipantName")
            or r.get("tierIdentifier")
            or "ALL_ATS"
        )
        week = (
            r.get("weekStartDate")
            or r.get("week_start_date")
            or r.get("lastUpdateDate")
            or r.get("summaryStartDate")
        )
        vol = (
            r.get("totalWeeklyShareQuantity")
            or r.get("totalWeeklyShareQty")
            or r.get("ats_share_volume")
            or r.get("totalShareQuantity")
        )
        trades = (
            r.get("totalWeeklyTradeCount")
            or r.get("ats_trade_count")
            or r.get("totalTradeCount")
        )
        if week is None and vol is None:
            continue
        out.append({
            "venue": str(venue),
            "ats_share_volume": vol,
            "ats_trade_count": trades,
            "weekStartDate": str(week)[:10] if week else None,
        })
    return [r for r in out if r["weekStartDate"]]


def _normalise_adapter_frame(df: Any) -> list[dict[str, Any]]:
    """Map a wired adapter DataFrame into the normalised row shape."""
    frame = df.fillna(0)
    venue_col = next(
        (c for c in ("MPID", "ATSCode", "atsCode", "venue", "mpid") if c in frame.columns),
        None,
    )
    out: list[dict[str, Any]] = []
    for rec in frame.to_dict(orient="records"):
        week = rec.get("weekStartDate") or rec.get("week_start_date")
        if not week:
            continue
        out.append({
            "venue": str(rec.get(venue_col) if venue_col else "ALL_ATS"),
            "ats_share_volume": rec.get("totalWeeklyShareQuantity") or rec.get("ats_share_volume"),
            "ats_trade_count": rec.get("totalWeeklyTradeCount") or rec.get("ats_trade_count"),
            "weekStartDate": str(week)[:10],
        })
    return out


def _unavailable(symbol: str, reason: str, provider_errors: list[str]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "status": "provider_unavailable",
        "reason": reason,
        "n_rows": 0,
        "total_shares_off_exchange": 0.0,
        "top_venue_share_pct": None,
        "rows": [],
        "venues": [],
        "by_venue": [],
        "by_week": [],
        "history": [],
        "cards": {
            "latest_dark_pool_pct": None,
            "latest_ats_volume": None,
            "venue_count": 0,
            "data_mode": "provider_unavailable",
            "as_of": None,
        },
        "summary": {"latest_week": None, "latest_dark_pool_pct": None, "venue_count": 0},
        "methodology": _METHODOLOGY,
        "field_dictionary": _FIELD_DICTIONARY,
        "next_actions": [
            "Retry once the FINRA OTC Transparency API is reachable.",
            "Confirm the symbol reports off-exchange ATS volume (not all tickers do).",
        ],
        "provider_errors": provider_errors,
    }


def _stale_reason(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value)[:10]).date()
    except (TypeError, ValueError):
        # Malformed FINRA dates must NOT be treated as "fresh". Surface as a
        # data-quality reason instead so DARK's status flips to
        # provider_unavailable, matching the intent of the methodology line.
        return f"FINRA latest week {value!r} could not be parsed; treating as stale until reprocessed."
    if dt < (datetime.now(timezone.utc).date() - timedelta(days=180)):
        return f"FINRA latest week {dt.isoformat()} is stale for a current market cockpit."
    return None
