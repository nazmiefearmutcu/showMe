"""Shared helpers for aligning daily portfolio return series.

Audit Q3 #7 / #21 — dropna policy.

The legacy `align_return_series()` always did `concat(...).dropna(how="any")`
which throws away every calendar date where *any* series has a NaN. For mixed
universes (CRYPTO trades 7 days, EQUITY only trading days) this routinely
drops ~70% of rows. Risk-parity / blak / pvar / pcas / port_opt then compute
covariance on a tiny, biased remnant and weights silently tilt to the asset
class with the longest contiguous coverage (typically crypto).

`policy` parameter:
  * ``"intersection"`` — legacy behavior (drop any NaN row). Use when the
    downstream stat genuinely requires perfectly-aligned timestamps.
  * ``"pairwise"``     — keep NaNs; `pandas.DataFrame.cov()` / `corr()` use
    pairwise-complete observations natively. Default for ERC + Black-Litterman.
  * ``"forward_fill"`` — forward-fill missing returns with 0 so non-trading
    days for one asset don't drop rows for others. Use when downstream code
    needs a dense matrix (e.g. eigen-decomposition for PCA stress).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

import pandas as pd

DropnaPolicy = Literal["intersection", "pairwise", "forward_fill"]


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


def align_return_series(
    pairs: Iterable[tuple[str, pd.Series]],
    *,
    policy: DropnaPolicy = "intersection",
) -> pd.DataFrame:
    """Join non-empty return series with the requested NaN-handling policy.

    See module docstring for the trade-offs between policies. The default
    is the legacy "intersection" for backward compatibility; callers that
    care about cross-asset bias (rpar/blak/pvar/pcas/port_opt) pass
    `policy="pairwise"`.
    """
    clean = {
        str(symbol): pd.to_numeric(series, errors="coerce").dropna()
        for symbol, series in pairs
        if str(symbol) and series is not None and not series.empty
    }
    if not clean:
        return pd.DataFrame()
    joined = pd.concat(clean, axis=1, sort=False).sort_index()
    if policy == "intersection":
        return joined.dropna(how="any")
    if policy == "forward_fill":
        # Forward-fill missing returns with 0 (no-return day) so the matrix
        # stays dense without faking direction.
        return joined.fillna(0.0)
    # "pairwise": keep NaNs; pandas cov()/corr() use pairwise observations.
    # We still drop leading rows where every column is NaN so the head is
    # not made up entirely of "no data" rows.
    mask = joined.notna().any(axis=1)
    return joined[mask]
