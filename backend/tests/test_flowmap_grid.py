"""Grid semantics tests: time-weighted density, epochs, row-shift, ring.

The load-bearing property: density is TIME-WEIGHTED resting size — each book
state integrates over the microseconds until the next update, and finalize
divides by dt. Two different update cadences over the same book produce
identical columns.
"""
from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pytest

from showme.flowmap import events, wire
from showme.flowmap.grid import (
    PEAK_TARGET,
    Candle,
    FinalizedColumn,
    Grid,
    GridCfg,
    columns_from_candles,
)

DT = 250_000_000  # 250 ms


def make_grid(rows: int = 8, ring: int = 16, p0: float = 100.0,
              tick: float = 1.0, multiple: int = 1) -> Grid:
    return Grid(GridCfg(
        tick=tick, tick_multiple=multiple, dt_ns=DT, p0=p0,
        rows=rows, ring_columns=ring, mode=events.MODE_L2,
    ))


def book(grid: Grid, ts_ns: int, bid_px, bid_sz, ask_px, ask_sz):
    return grid.on_book(
        ts_ns,
        np.asarray(bid_px, dtype=np.float64),
        np.asarray(bid_sz, dtype=np.float64),
        np.asarray(ask_px, dtype=np.float64),
        np.asarray(ask_sz, dtype=np.float64),
    )


# --- time weighting ---------------------------------------------------------------


def test_time_weighted_density_exact() -> None:
    """Two book states with known dt -> exact expected density.

    State A (size 10 at row 1) rests for 100 ms, state B (size 20) for the
    remaining 150 ms of the 250 ms interval:
        density = (10*100ms + 20*150ms) / 250ms = 16.0
    """
    grid = make_grid()
    book(grid, 0, [101.0], [10.0], [103.0], [7.0])
    book(grid, 100_000_000, [101.0], [20.0], [103.0], [9.0])
    cols = book(grid, 250_000_000, [101.0], [20.0], [103.0], [9.0])
    assert len(cols) == 1
    col = cols[0]
    assert col.col_seq == 0
    assert col.t0_ns == 0
    assert float(col.bid[1]) == pytest.approx(16.0, abs=1e-3)
    # the ring stores float16: spacing at ~8.2 is 0.0625
    assert float(col.ask[3]) == pytest.approx(
        9.0 * 150 / 250 + 7.0 * 100 / 250, abs=0.05)
    # every other row is exactly zero
    assert float(np.sum(col.bid)) == pytest.approx(16.0, abs=1e-3)


def test_cadence_invariance() -> None:
    """The same resting book sampled at two cadences -> identical columns."""
    steady = make_grid()
    book(steady, 0, [101.0], [30.0], [103.0], [10.0])
    cols_steady = book(steady, DT, [101.0], [30.0], [103.0], [10.0])

    jittered = make_grid()
    book(jittered, 0, [101.0], [30.0], [103.0], [10.0])
    book(jittered, 37_000_000, [101.0], [30.0], [103.0], [10.0])
    book(jittered, 111_000_000, [101.0], [30.0], [103.0], [10.0])
    book(jittered, 199_999_999, [101.0], [30.0], [103.0], [10.0])
    cols_jittered = book(jittered, DT, [101.0], [30.0], [103.0], [10.0])

    assert len(cols_steady) == len(cols_jittered) == 1
    assert np.allclose(cols_steady[0].bid, cols_jittered[0].bid)
    assert np.allclose(cols_steady[0].ask, cols_jittered[0].ask)
    assert float(cols_steady[0].bid[1]) == pytest.approx(30.0, abs=1e-3)


def test_boundary_book_finalizes_previous_interval() -> None:
    """A book at exactly a boundary finalizes the ending interval with the
    PREVIOUS state integrated to the boundary; the new state applies forward."""
    grid = make_grid()
    book(grid, 0, [101.0], [10.0], [103.0], [10.0])
    cols = book(grid, DT, [101.0], [999.0], [103.0], [999.0])
    assert len(cols) == 1
    # full interval integrated with size 10
    assert float(cols[0].bid[1]) == pytest.approx(10.0, abs=1e-3)
    # the new (999) state now rests in the accumulator: next finalize shows it
    cols = book(grid, 2 * DT, [101.0], [999.0], [103.0], [999.0])
    assert float(cols[0].bid[1]) == pytest.approx(999.0, abs=0.5)


def test_multi_interval_jump_finalizes_k_columns() -> None:
    grid = make_grid()
    book(grid, 0, [101.0], [10.0], [103.0], [10.0])
    cols = book(grid, 3 * DT, [101.0], [10.0], [103.0], [10.0])
    assert [c.col_seq for c in cols] == [0, 1, 2]
    assert [c.t0_ns for c in cols] == [0, DT, 2 * DT]
    for c in cols:
        assert float(c.bid[1]) == pytest.approx(10.0, abs=1e-3)


def test_duplicate_boundary_call_is_idempotent() -> None:
    grid = make_grid()
    book(grid, 0, [101.0], [10.0], [103.0], [10.0])
    first = book(grid, DT, [101.0], [10.0], [103.0], [10.0])
    dup = book(grid, DT, [101.0], [10.0], [103.0], [10.0])
    assert dup[0].col_seq == first[0].col_seq
    # col_seq untouched by the duplicate
    nxt = book(grid, 2 * DT, [101.0], [10.0], [103.0], [10.0])
    assert nxt[0].col_seq == first[0].col_seq + 1


# --- epochs / re-anchor / row-shift -----------------------------------------------


def test_reanchor_bumps_epoch_and_shifts_rows_exact() -> None:
    """mid exits the central 70% -> new epoch; the in-progress accumulator is
    row-shifted so the column finalized after the re-anchor is EXACT.

    p0=100, rows=8, step=1 -> span 8, central 70% is [101.2, 106.8].
    mid=110 trips. new_p0 = round((110 - 4)) = 106 -> the frame moves UP six
    rows, so the same price now sits SIX rows lower: the slice resting at
    old row 6 (px 106) reappears at new row 0 and old rows <6 drop off.
    """
    grid = make_grid()
    book(grid, 0, [106.0], [5.0], [107.0], [5.0])
    # integrate 125 ms of the pre-anchor state (px 106 rests at row 6)
    book(grid, 125_000_000, [106.0], [5.0], [107.0], [5.0])
    # mid 110 exits the central band -> re-anchor
    params = grid.maybe_reanchor(110.0)
    assert params is not None
    assert params.epoch == 1
    assert params.p0 == pytest.approx(106.0)
    assert grid.epoch == 1
    # finalize the interval AFTER the re-anchor: continuity holds — the
    # shifted PRE-anchor slice (row 6 -> 0) and the rebuilt resting state
    # (px 106 -> new row 0) coincide, so the column is exactly what a
    # no-re-anchor grid would have produced: 5.0.
    cols = book(grid, DT, [107.0], [5.0], [109.0], [5.0])
    assert len(cols) == 1
    col = cols[0]
    assert col.epoch == 1
    assert col.col_seq == 0
    assert float(col.bid[0]) == pytest.approx(5.0, abs=1e-3)
    # px 107 sits at row (107-106)=1 in the NEW frame; it rests in the NEXT
    # interval (the finalize above consumed the pre-anchor accumulator).
    assert float(col.bid[1]) == pytest.approx(0.0, abs=1e-3)
    cols = book(grid, 2 * DT, [107.0], [5.0], [109.0], [5.0])
    assert float(cols[0].bid[1]) == pytest.approx(5.0, abs=1e-3)


def test_no_reanchor_inside_central_band() -> None:
    grid = make_grid()
    book(grid, 0, [101.0], [5.0], [103.0], [5.0])
    assert grid.maybe_reanchor(104.0) is None  # inside [101.2, 106.8]
    assert grid.maybe_reanchor(float("nan")) is None
    assert grid.maybe_reanchor(0.0) is None
    assert grid.epoch == 0


def test_epoch_params_registry_keeps_history() -> None:
    grid = make_grid()
    book(grid, 0, [101.0], [5.0], [103.0], [5.0])
    p1 = grid.maybe_reanchor(120.0)
    assert p1 is not None
    assert grid.epoch_params_for(0).p0 == pytest.approx(100.0)
    assert grid.epoch_params_for(1).p0 == pytest.approx(116.0)
    assert grid.current_epoch_params().epoch == 1


# --- bars -------------------------------------------------------------------------


def test_trade_side_buckets_and_cumulatives() -> None:
    grid = make_grid()
    book(grid, 0, [101.0], [1.0], [103.0], [1.0])
    grid.on_trade(10_000_000, 101.5, 3.0, events.SIDE_BUY)
    grid.on_trade(20_000_000, 101.0, 2.0, events.SIDE_SELL)
    grid.on_trade(30_000_000, 101.25, 1.0, events.SIDE_UNKNOWN)
    cols = book(grid, DT, [101.0], [1.0], [103.0], [1.0])
    bar = cols[0].bar
    assert (bar.o, bar.h, bar.l, bar.c) == (101.5, 101.5, 101.0, 101.25)
    assert bar.vol_buy == pytest.approx(3.0)
    assert bar.vol_sell == pytest.approx(2.0)
    assert bar.cvd_cum == pytest.approx(1.0)
    assert bar.vwap_num_cum == pytest.approx(3.0 * 101.5 + 2.0 * 101.0 + 1.0 * 101.25)
    assert bar.vwap_den_cum == pytest.approx(6.0)
    # no-trade interval carries the previous close flat; cumulatives persist
    cols = book(grid, 2 * DT, [101.0], [1.0], [103.0], [1.0])
    bar = cols[0].bar
    assert bar.o == bar.h == bar.l == bar.c == 101.25
    assert bar.cvd_cum == pytest.approx(1.0)


def test_malformed_trade_is_ignored_entirely() -> None:
    grid = make_grid()
    book(grid, 0, [101.0], [1.0], [103.0], [1.0])
    grid.on_trade(10_000_000, float("nan"), 5.0, events.SIDE_BUY)
    grid.on_trade(10_000_000, -1.0, 5.0, events.SIDE_BUY)
    grid.on_trade(10_000_000, 101.0, float("nan"), events.SIDE_BUY)
    grid.on_trade(10_000_000, 101.0, -3.0, events.SIDE_SELL)
    cols = book(grid, DT, [101.0], [1.0], [103.0], [1.0])
    bar = cols[0].bar
    assert bar.vol_buy == 0.0 and bar.vol_sell == 0.0
    assert math.isnan(bar.o)


# --- ring / history ---------------------------------------------------------------


def test_ring_eviction_and_history_serving() -> None:
    grid = make_grid(rows=4, ring=4)
    book(grid, 0, [101.0], [1.0], [103.0], [1.0])
    for k in range(1, 7):
        book(grid, k * DT, [101.0], [1.0], [103.0], [1.0])
    assert grid.count == 6
    cols = grid.history(2**63 - 1, 10)
    assert [c.col_seq for c in cols] == [2, 3, 4, 5]
    assert grid.oldest_retained_t0_ns() == 2 * DT
    # exclusive before_t
    cols = grid.history(4 * DT, 10)
    assert [c.col_seq for c in cols] == [2, 3]
    # n clamp
    cols = grid.history(2**63 - 1, 1)
    assert [c.col_seq for c in cols] == [5]
    assert grid.history(2**63 - 1, 0) == []


def _ring_col(seq: int, t0_ns: int, rows: int = 4) -> FinalizedColumn:
    return FinalizedColumn(
        epoch=0, col_seq=seq, t0_ns=t0_ns,
        bid=np.zeros(rows, dtype=np.float16), ask=np.zeros(rows, dtype=np.float16),
        bar=events.BarColumn(
            epoch=0, col_seq=seq, t0_ns=t0_ns, o=1, h=1, l=1, c=1,
            vol_buy=0, vol_sell=0, cvd_cum=0, vwap_num_cum=0, vwap_den_cum=0,
        ),
    )


def test_preload_rejects_non_contiguous_tail() -> None:
    grid = make_grid(rows=4, ring=8)
    cols = [_ring_col(5, 0), _ring_col(7, 2 * DT)]  # seq gap 5 -> 7
    with pytest.raises(ValueError):
        grid.preload(cols, [grid.current_epoch_params()])
    grid2 = make_grid(rows=4, ring=8)
    with pytest.raises(ValueError):  # t0 not strictly increasing
        grid2.preload([_ring_col(5, 0), _ring_col(6, 0)],
                      [grid2.current_epoch_params()])


def test_preload_rejects_after_live_data() -> None:
    grid = make_grid(rows=4, ring=8)
    book(grid, 0, [101.0], [1.0], [103.0], [1.0])
    with pytest.raises(RuntimeError):  # virgin-grid guard
        grid.preload([_ring_col(0, 0)], [grid.current_epoch_params()])


def test_preload_seeds_ring_and_continues_sequence() -> None:
    template = make_grid(rows=4, ring=8)
    cols = [
        FinalizedColumn(
            epoch=0, col_seq=i, t0_ns=i * DT,
            bid=np.full(4, i, dtype=np.float16),
            ask=np.zeros(4, dtype=np.float16),
            bar=events.BarColumn(
                epoch=0, col_seq=i, t0_ns=i * DT, o=1, h=1, l=1, c=1,
                vol_buy=0, vol_sell=0, cvd_cum=0, vwap_num_cum=0, vwap_den_cum=0,
            ),
        )
        for i in range(3)
    ]
    grid = make_grid(rows=4, ring=8)
    grid.preload(cols, [template.current_epoch_params()])
    assert grid.count == 3
    assert [c.col_seq for c in grid.history(2**63 - 1, 10)] == [0, 1, 2]
    nxt = book(grid, 3 * DT, [101.0], [1.0], [103.0], [1.0])
    assert nxt == []  # anchor only
    fin = book(grid, 4 * DT, [101.0], [1.0], [103.0], [1.0])
    assert fin[0].col_seq == 3


# --- to_depth / partial -----------------------------------------------------------


def test_to_depth_casts_f32_and_synth_drops_ask() -> None:
    grid = make_grid(rows=4)
    book(grid, 0, [101.0], [1000.0], [103.0], [1000.0])
    cols = book(grid, DT, [101.0], [1000.0], [103.0], [1000.0])
    depth = grid.to_depth(cols[0])
    assert depth.bid.dtype == np.float32
    assert depth.ask.dtype == np.float32
    assert depth.final is True
    assert depth.mode == events.MODE_L2

    partial = grid.current_partial()
    assert partial is not None and partial.final is False


def test_synth_column_to_depth_has_ask_none() -> None:
    grid = make_grid(rows=4)
    col = FinalizedColumn(
        epoch=0, col_seq=0, t0_ns=0,
        bid=np.full(4, 5.0, dtype=np.float16),
        ask=np.zeros(4, dtype=np.float16),
        bar=events.BarColumn(
            epoch=0, col_seq=0, t0_ns=0, o=1, h=1, l=1, c=1,
            vol_buy=0, vol_sell=0, cvd_cum=0, vwap_num_cum=0, vwap_den_cum=0,
        ),
        mode=events.MODE_SYNTH_PROFILE,
    )
    depth = grid.to_depth(col)
    assert depth.mode == events.MODE_SYNTH_PROFILE
    assert depth.ask is None
    # and the wire encoder agrees (single channel: no ask array)
    buf = wire.encode(depth)
    assert len(buf) == 8 + 24 + 4 * 4  # envelope + hdr + bid only, already padded


# --- backfill: candles -> synth columns --------------------------------------------

_BACK_CFG = GridCfg(
    tick=1.0, tick_multiple=1, dt_ns=DT, p0=100.0, rows=32,
    ring_columns=4096, mode=events.MODE_L2,
)


def test_backfill_stretches_candle_across_full_minute() -> None:
    candle = Candle(
        t0_ns=0, o=101.0, h=103.0, l=100.0, c=102.0, volume=2400.0,
        buy_volume=1500.0, sell_volume=900.0,
    )
    result = columns_from_candles([candle], _BACK_CFG)
    assert result is not None
    cols, epoch = result
    assert len(cols) == 240  # 60 s / 250 ms
    assert epoch.epoch == 0
    for i, col in enumerate(cols):
        assert col.col_seq == i
        assert col.t0_ns == i * DT
        assert col.mode == events.MODE_SYNTH_PROFILE
    # volume spread across rows [row(100)=0 .. row(103)=3] -> 4 rows x 600;
    # peak-normalized to PEAK_TARGET: 600 * (1000/600) = 1000 everywhere.
    for col in cols:
        assert col.ask.max() == 0.0
        assert float(col.bid[0]) == pytest.approx(PEAK_TARGET, abs=0.5)
        assert float(col.bid[3]) == pytest.approx(PEAK_TARGET, abs=0.5)
        assert float(col.bid.sum()) == pytest.approx(4 * PEAK_TARGET, abs=1.0)
    # first column carries the candle OHLC + taker split; later ones carry flat
    assert (cols[0].bar.o, cols[0].bar.h, cols[0].bar.l, cols[0].bar.c) == (
        101.0, 103.0, 100.0, 102.0)
    assert cols[0].bar.vol_buy == pytest.approx(1500.0)
    assert cols[0].bar.vol_sell == pytest.approx(900.0)
    assert cols[0].bar.cvd_cum == pytest.approx(600.0)
    assert cols[-1].bar.o == cols[-1].bar.h == cols[-1].bar.c == 102.0
    # cumulative vwap from the typical price
    tp = (103.0 + 100.0 + 102.0) / 3.0
    assert cols[0].bar.vwap_num_cum == pytest.approx(tp * 2400.0)
    assert cols[0].bar.vwap_den_cum == pytest.approx(2400.0)


def test_backfill_cap_keeps_newest_columns_and_contiguity() -> None:
    candles = [
        Candle(t0_ns=i * 60 * 10**9, o=101, h=103, l=100, c=102, volume=240.0)
        for i in range(10)
    ]
    result = columns_from_candles(candles, _BACK_CFG, max_cols=300)
    assert result is not None
    cols, _epoch = result
    assert len(cols) == 300  # contract cap (~1024 in production) applied
    assert [c.col_seq for c in cols] == list(range(300))
    t0s = [c.t0_ns for c in cols]
    assert t0s == sorted(t0s)
    assert all(b - a == DT for a, b in pairwise(t0s))
    # the kept window is the NEWEST 300 columns: last candle fully inside
    assert cols[-1].t0_ns == 9 * 60 * 10**9 + 239 * DT


def test_backfill_returns_none_on_garbage() -> None:
    assert columns_from_candles([], _BACK_CFG) is None
    bad = Candle(t0_ns=0, o=float("nan"), h=1, l=1, c=1, volume=1.0)
    assert columns_from_candles([bad], _BACK_CFG) is None
    zero_vol = Candle(t0_ns=0, o=1, h=1, l=1, c=1, volume=0.0)
    result = columns_from_candles([zero_vol], _BACK_CFG)
    assert result is None  # zero peak: nothing to render


def test_backfill_ring_cap_floor() -> None:
    candle = Candle(t0_ns=0, o=101, h=103, l=100, c=102, volume=240.0)
    tiny = GridCfg(
        tick=1.0, tick_multiple=1, dt_ns=DT, p0=100.0, rows=32,
        ring_columns=8, mode=events.MODE_L2,
    )
    result = columns_from_candles([candle], tiny, max_cols=99999)
    assert result is not None
    assert len(result[0]) == 8  # never exceeds the ring itself
