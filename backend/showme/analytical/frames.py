"""Polars-based pure tabular helpers for the analytical core.

Every function here is pure: it takes a ``pl.DataFrame`` (and optionally a
PyArrow ``Table``) and returns a new ``pl.DataFrame``. No I/O, no DuckDB
chatter, no module-level state. Polars (not pandas) is the only tabular
library allowed in this module.
"""
from __future__ import annotations

from typing import Optional

import polars as pl
import pyarrow as pa


def to_polars_from_arrow(table: pa.Table) -> pl.DataFrame:
    """Convert a PyArrow ``Table`` to a Polars ``DataFrame`` (zero-copy where possible)."""
    return pl.from_arrow(table)


def resample_ohlcv(df: pl.DataFrame, interval: str, time_col: str = "time") -> pl.DataFrame:
    """Resample an OHLCV frame into ``interval``-sized buckets.

    The frame is expected to carry the standard ``open``/``high``/``low``/
    ``close``/``volume`` columns alongside ``time_col``. Bucketing uses
    ``group_by_dynamic`` so the time index aligns with truncation boundaries
    (e.g. ``"1h"`` → 09:00, 10:00, ...). Missing columns are silently
    skipped so the helper works on subsets like ``time + close``.

    The input is sorted on ``time_col`` first since ``group_by_dynamic``
    requires monotonic input.
    """
    if df.is_empty():
        return df
    df = df.sort(time_col)
    schema_cols = set(df.columns)
    agg_exprs = []
    if "open" in schema_cols:
        agg_exprs.append(pl.col("open").first().alias("open"))
    if "high" in schema_cols:
        agg_exprs.append(pl.col("high").max().alias("high"))
    if "low" in schema_cols:
        agg_exprs.append(pl.col("low").min().alias("low"))
    if "close" in schema_cols:
        agg_exprs.append(pl.col("close").last().alias("close"))
    if "volume" in schema_cols:
        agg_exprs.append(pl.col("volume").sum().alias("volume"))
    if not agg_exprs:
        # Nothing to aggregate; just truncate the timestamp.
        return df.with_columns(pl.col(time_col).dt.truncate(interval).alias(time_col))
    return df.group_by_dynamic(time_col, every=interval).agg(agg_exprs)


def join_asof(
    left: pl.DataFrame,
    right: pl.DataFrame,
    on: str,
    by: Optional[str] = None,
) -> pl.DataFrame:
    """As-of (last-known) join of ``right`` onto ``left``.

    Both frames are sorted on ``on`` before joining (a Polars precondition).
    When ``by`` is given the join is grouped per-key — useful for
    per-symbol joins where rows from different symbols must not bleed into
    each other.
    """
    if by is None:
        left_sorted = left.sort(on)
        right_sorted = right.sort(on)
        return left_sorted.join_asof(right_sorted, on=on)
    # When `by` is provided, both sides must be sorted by `on` within the
    # `by` group; the simplest stable form is to sort by both.
    left_sorted = left.sort([by, on])
    right_sorted = right.sort([by, on])
    return left_sorted.join_asof(right_sorted, on=on, by=by)


def rank_by(df: pl.DataFrame, col: str, descending: bool = True) -> pl.DataFrame:
    """Append a ``rank`` column derived from ``col``.

    Uses ``method="ordinal"`` so ties get distinct ranks (deterministic
    ordering across reruns). The added column is named ``rank``.
    """
    expr = pl.col(col).rank(method="ordinal", descending=descending).alias("rank")
    return df.with_columns(expr)


def pct_change(df: pl.DataFrame, col: str, periods: int = 1) -> pl.DataFrame:
    """Append ``{col}_pct_change`` column = pct change of ``col`` over ``periods``."""
    expr = pl.col(col).pct_change(n=periods).alias(f"{col}_pct_change")
    return df.with_columns(expr)


def rolling_mean(df: pl.DataFrame, col: str, window: int) -> pl.DataFrame:
    """Append ``{col}_rolling_mean`` column over a ``window``-sized window."""
    expr = pl.col(col).rolling_mean(window_size=window).alias(f"{col}_rolling_mean")
    return df.with_columns(expr)


def correlation_matrix(
    df: pl.DataFrame,
    value_col: str,
    key_col: str,
    time_col: str,
) -> pl.DataFrame:
    """Pivot a long frame to wide, then return a long-form correlation matrix.

    Input expected shape: rows of ``(time_col, key_col, value_col)``.
    Output shape: rows of ``(key_a, key_b, correlation)``.

    A pair is excluded from the result if either column has fewer than two
    non-null observations (Polars' ``corr`` would return null in that case).
    """
    if df.is_empty():
        return pl.DataFrame(
            {"key_a": [], "key_b": [], "correlation": []},
            schema={"key_a": pl.Utf8, "key_b": pl.Utf8, "correlation": pl.Float64},
        )
    wide = df.pivot(values=value_col, index=time_col, on=key_col, aggregate_function="mean")
    keys = [c for c in wide.columns if c != time_col]
    rows: list[dict] = []
    for a in keys:
        for b in keys:
            col_a = wide.get_column(a)
            col_b = wide.get_column(b)
            # Drop pairs where either side is null using a mask.
            mask = col_a.is_not_null() & col_b.is_not_null()
            pair = pl.DataFrame({a: col_a.filter(mask), b: col_b.filter(mask)})
            if pair.height < 2:
                corr_val = None
            elif a == b:
                corr_val = 1.0
            else:
                # pl.corr returns a scalar wrapped in a 1-row frame.
                corr_val = pair.select(pl.corr(a, b)).item()
            rows.append({"key_a": a, "key_b": b, "correlation": corr_val})
    return pl.DataFrame(
        rows,
        schema={"key_a": pl.Utf8, "key_b": pl.Utf8, "correlation": pl.Float64},
    )


__all__ = [
    "to_polars_from_arrow",
    "resample_ohlcv",
    "join_asof",
    "rank_by",
    "pct_change",
    "rolling_mean",
    "correlation_matrix",
]
