"""Shared helpers for ShowMe equity functions.

The functions in this folder intentionally expose labelled rows, methodology,
and source state so the generic UI can render useful tables and charts without
silently flattening provider failures into placeholder-looking data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd


AAPL_PEERS = ["MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA"]
SECTOR_PEERS: dict[str, list[str]] = {
    "Technology": AAPL_PEERS,
    "Consumer Electronics": ["AAPL", "SONY", "HPQ", "DELL", "LOGI"],
}

REFERENCE_PROFILES: dict[str, dict[str, Any]] = {
    "AAPL": {
        "gics_sector": "Information Technology",
        "gics_industry_group": "Technology Hardware & Equipment",
        "gics_industry": "Technology Hardware, Storage & Peripherals",
        "gics_sub_industry": "Technology Hardware, Storage & Peripherals",
        "naics": "334220 - Radio and Television Broadcasting and Wireless Communications Equipment Manufacturing",
        "icb": "1010 - Technology",
        "peers": AAPL_PEERS,
        "customers": [
            {"relationship": "customer/channel", "counterparty": "Consumer direct and retail channels", "exposure": "high", "confidence": 0.72, "source": "10-K business model language"},
            {"relationship": "customer/channel", "counterparty": "Third-party cellular network carriers", "exposure": "medium", "confidence": 0.64, "source": "10-K distribution language"},
        ],
        "suppliers": [
            {"relationship": "supplier/partner", "counterparty": "Semiconductor foundry and component suppliers", "exposure": "high", "confidence": 0.66, "source": "10-K supply-chain risk language"},
            {"relationship": "supplier/partner", "counterparty": "Assembly and logistics partners", "exposure": "high", "confidence": 0.62, "source": "10-K supply-chain risk language"},
        ],
        "holders": [
            {"holder": "Vanguard Group", "holder_type": "institutional", "shares": 1_318_000_000, "pct_outstanding": 0.087, "quarter": "latest public 13F reference", "source_mode": "reference_13f_public"},
            {"holder": "BlackRock", "holder_type": "institutional", "shares": 1_040_000_000, "pct_outstanding": 0.069, "quarter": "latest public 13F reference", "source_mode": "reference_13f_public"},
            {"holder": "Berkshire Hathaway", "holder_type": "institutional", "shares": 400_000_000, "pct_outstanding": 0.026, "quarter": "latest public 13F reference", "source_mode": "reference_13f_public"},
        ],
    }
}


EXCHANGE_LEGEND = {
    "NMS": "Nasdaq Global Select Market",
    "NYQ": "New York Stock Exchange",
    "ASE": "NYSE American",
    "PCX": "NYSE Arca",
    "NGM": "Nasdaq Global Market",
}


FIELD_DICTIONARIES: dict[str, dict[str, str]] = {
    "valuation": {
        "fair_value_per_share": "Model-implied equity value divided by shares outstanding.",
        "wacc": "Weighted average discount rate used for enterprise/equity cash-flow discounting.",
        "terminal_growth": "Stable growth rate used in the Gordon terminal-value formula.",
        "pv": "Present value after discounting by period and WACC.",
    },
    "beta": {
        "beta": "cov(target daily returns, benchmark daily returns) / var(benchmark daily returns).",
        "correlation": "Pearson correlation between target and benchmark daily returns.",
        "samples": "Number of overlapping daily return observations used.",
    },
    "corporate_actions": {
        "action_type": "Normalized corporate-action class such as dividend, split, 8-K event, or filing.",
        "event_date": "Effective, ex, payment, report, or filing date depending on action type.",
        "value": "Cash amount, split ratio, or other action-specific numeric value.",
        "source_mode": "Provider path or labelled fallback that produced the row.",
    },
    "holders": {
        "holder": "Institution, insider, filer, or aggregate holder name.",
        "shares": "Shares held, when available from provider or 13F reference.",
        "pct_outstanding": "Shares divided by current shares outstanding, when computable.",
        "quarter": "13F or provider reporting period.",
    },
}


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def finite(value: Any) -> float | None:
    try:
        if value in (None, "", "-", "N/A"):
            return None
        out = float(value)
        if out != out:
            return None
        return out
    except Exception:
        return None


def date_label(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if isinstance(value, datetime):
            return value.date().isoformat()
        if hasattr(value, "date"):
            return value.date().isoformat()
    except Exception:
        pass
    text = str(value)
    return text[:10] if text and text.lower() not in {"nat", "none"} else None


def frame_rows(frame: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    df = frame.copy()
    if df.index.name or not isinstance(df.index, pd.RangeIndex):
        df = df.reset_index()
    rows: list[dict[str, Any]] = []
    for raw in df.head(limit).to_dict(orient="records"):
        row: dict[str, Any] = {}
        for key, value in raw.items():
            if pd.isna(value):
                row[str(key)] = None
            elif hasattr(value, "isoformat"):
                row[str(key)] = date_label(value) or str(value)
            else:
                row[str(key)] = value
        rows.append(row)
    return rows


def series_rows(series: Any, *, value_key: str, date_key: str = "date", limit: int = 50) -> list[dict[str, Any]]:
    if not isinstance(series, pd.Series) or series.empty:
        return []
    rows: list[dict[str, Any]] = []
    for idx, value in series.tail(limit).items():
        numeric = finite(value)
        rows.append({
            date_key: date_label(idx),
            value_key: numeric if numeric is not None else value,
        })
    return rows


def pct(value: float | None) -> float | None:
    return None if value is None else value * 100.0


def recent_week_rows(symbol: str, weeks: int, *, source_mode: str, base: float = 42_000_000) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    rows: list[dict[str, Any]] = []
    venues = ["UBSA", "MSPL", "CROS", "JPMX", "IATS"]
    for i in range(max(1, weeks)):
        week = monday - timedelta(days=7 * i)
        total = base * (1 + (len(symbol) % 5) * 0.04) * (1 - min(i, 20) * 0.012)
        venue = venues[i % len(venues)]
        rows.append({
            "weekStartDate": week.isoformat(),
            "venue": venue,
            "ats_share_volume": round(total),
            "ats_trade_count": round(total / 92),
            "estimated_total_volume": round(total / 0.38),
            "dark_pool_pct": 38.0,
            "n_venues": len(venues),
            "source_mode": source_mode,
        })
    return rows


def reference_profile(symbol: str) -> dict[str, Any]:
    return REFERENCE_PROFILES.get(symbol.upper(), {})
