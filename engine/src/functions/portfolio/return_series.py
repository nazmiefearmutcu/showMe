"""Shared helpers for aligning daily portfolio return series."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


def close_to_daily_returns(frame: pd.DataFrame, close_key: str = "close") -> pd.Series:
    """Convert a price frame into date-indexed daily close returns.

    Yahoo returns equities, futures, FX, and crypto with different intraday
    timestamps. Portfolio functions need calendar-date alignment before joining
    those series; otherwise mixed universes can lose every live row.
    """
    if frame is None or frame.empty or close_key not in frame:
        return pd.Series(dtype=float)
    close = pd.to_numeric(frame[close_key], errors="coerce").dropna()
    if close.empty:
        return pd.Series(dtype=float)
    idx = pd.to_datetime(close.index, utc=True, errors="coerce")
    mask = pd.notna(idx)
    if not bool(mask.any()):
        return pd.Series(dtype=float)
    daily = pd.Series(close.to_numpy()[mask], index=pd.Index(idx[mask].date))
    daily = daily.groupby(level=0).last().sort_index()
    daily.index = pd.to_datetime(daily.index)
    return daily.pct_change().dropna()


def align_return_series(pairs: Iterable[tuple[str, pd.Series]]) -> pd.DataFrame:
    """Join non-empty return series on common calendar dates."""
    clean = {
        str(symbol): pd.to_numeric(series, errors="coerce").dropna()
        for symbol, series in pairs
        if str(symbol) and series is not None and not series.empty
    }
    if not clean:
        return pd.DataFrame()
    return pd.concat(clean, axis=1).sort_index().dropna(how="any")
