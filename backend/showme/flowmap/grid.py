"""Time-weighted density grid with epochs and a float16 column ring.

Port of ``flowmap_server.core.grid`` (linear price scale only — the sidecar
never opts into a non-uniform scale, which upstream gates behind an explicit
band/hybrid request). Semantics that are load-bearing and ported 1:1:

- **Density is time-weighted resting size.** Each book update integrates the
  *previous* book state over ``(ts_ns - prev_ts)`` into the current column's
  accumulator; finalize divides the accumulator by ``dt_ns``. Two different
  update cadences over the same book therefore produce identical columns.
- **Precision:** accumulation happens in float64; the division by ``dt_ns``
  happens in float64 and only the finished density is cast to float16 for
  ring storage (saturated below f16's max finite first).
- **Epochs:** all columns in an epoch share ``(p0, tick, tick_multiple, dt)``.
  When mid exits the central 70 % of the span, :meth:`Grid.maybe_reanchor`
  bumps the epoch and recenters ``p0`` (snapped to the ``tick * tick_multiple``
  grid). History in the ring is NEVER rewritten; the in-progress accumulator
  is row-shifted into the new epoch's coordinates (the p0 delta is always an
  integer number of rows), so a column finalized after a mid-interval
  re-anchor is exact and carries the new epoch.
- **Interval boundaries:** interval ``k`` covers ``[k*dt, (k+1)*dt)``. An
  ``on_book`` at exactly a boundary finalizes the ending interval using the
  previous book integrated to the boundary; the new state applies forward.
  Huge timestamp jumps skip straight to the last ``ring_columns`` intervals
  (col_seq still advances by the skipped count).
- **Bars:** ``vol_buy`` / ``vol_sell`` and OHLC are per-interval;
  ``cvd_cum`` / ``vwap_num_cum`` / ``vwap_den_cum`` are session-cumulative.
  Unknown-side trades feed neither volume bucket and leave cvd unchanged,
  but DO count toward the vwap sums. Intervals without trades carry the
  previous close as ``o == h == l == c`` (NaN before the first trade ever).

Time advancement is driven by :meth:`Grid.on_book` (and by
:meth:`Grid.on_trade` anchoring before the first book); trades never
finalize columns.

One deliberate extension vs upstream: :class:`FinalizedColumn` carries a
``mode`` per column. The backfill path seeds SYNTH_PROFILE (single-channel)
columns while live columns are MODE_L2, and both share one ring; the wire
conversion (:meth:`Grid.to_depth`) honors the column's mode so the ask[]
channel is omitted exactly for the synth columns.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import events
from .events import BarColumn, EpochParams

_NAN = float("nan")
_F16_MAX = float(np.finfo(np.float16).max)
_CANDLE_SPAN_NS = 60 * 10**9  # 1 m backfill candles


@dataclass(frozen=True, slots=True)
class GridCfg:
    """Immutable grid configuration for one session (linear scale)."""

    tick: float
    tick_multiple: int
    dt_ns: int
    p0: float
    rows: int
    ring_columns: int
    mode: int = events.MODE_L2  # live render mode for this grid
    # Percentage coverage around the reference mid (fractions: 0.5 = +50%).
    # ``None`` keeps the legacy fixed-span grid (central-70% re-anchor rule).
    band_up: float | None = None
    band_down: float | None = None


@dataclass(slots=True)
class FinalizedColumn:
    """A finalized density column plus its bar, as stored in the ring."""

    epoch: int
    col_seq: int
    t0_ns: int
    bid: np.ndarray  # float16 (or f64 partial), length rows
    ask: np.ndarray  # float16, length rows (zeroed for SYNTH_PROFILE columns)
    bar: BarColumn
    mode: int = events.MODE_L2


@dataclass(slots=True)
class Candle:
    """One OHLCV candle for backfill (canonical, provider-agnostic).

    ``t0_ns`` is the candle-open UTC ns. ``buy_volume``/``sell_volume`` are
    the taker aggressor split (Binance 1m klines carry it); ``None`` keeps
    the reconstructed CVD flat instead of inventing a direction.
    """

    t0_ns: int
    o: float
    h: float
    l: float
    c: float
    volume: float
    buy_volume: float | None = None
    sell_volume: float | None = None


# Normalized peak of the reconstructed backfill density: a bounded RELATIVE
# intensity (raw venue volume cast to float16 would overflow the ring; one
# global scale keeps every texel ~1e3 while preserving ratios).
PEAK_TARGET = 1000.0

# Banded regime (upstream core/grid.py): the frame covers a PERCENTAGE of the
# reference mid with BAND_MARGIN headroom, the tick_multiple is FROZEN at the
# first anchor, and afterwards the grid re-anchors on a RATIO trip — a span
# fraction here would storm epochs on asymmetric bands.
BAND_MARGIN = 1.25
BAND_TRIP_RATIO = 1.25


def _finite(*vals: float) -> bool:
    return all(v is not None and math.isfinite(v) for v in vals)


class Grid:
    """Per-session density grid: time-weighted accumulation, epochs, ring."""

    def __init__(self, cfg: GridCfg) -> None:
        if cfg.rows <= 0 or cfg.ring_columns <= 0 or cfg.dt_ns <= 0:
            raise ValueError("rows, ring_columns and dt_ns must be positive")
        if not (cfg.tick > 0.0) or cfg.tick_multiple <= 0:
            raise ValueError("tick and tick_multiple must be positive")
        self._cfg = cfg
        self._tick_multiple = cfg.tick_multiple
        self._step = cfg.tick * self._tick_multiple
        self._p0 = cfg.p0
        self._epoch = 0
        # Banded regime state: reference mid of the current frame (None until
        # the first usable mid anchors the percentage frame).
        self._anchor_mid: float | None = None
        self._epoch_params: dict[int, EpochParams] = {
            0: EpochParams(
                epoch=0, tick=cfg.tick, tick_multiple=cfg.tick_multiple,
                dt_ns=cfg.dt_ns, p0=cfg.p0, rows=cfg.rows,
            )
        }

        rows = cfg.rows
        # Current-interval accumulator and dense book state, [2, rows] f64
        # (channel 0 = bid, channel 1 = ask).
        self._acc = np.zeros((2, rows), dtype=np.float64)
        self._state = np.zeros((2, rows), dtype=np.float64)
        # Raw last book (price/size copies) so the dense state can be rebuilt
        # against a new p0 at re-anchor (out-of-range levels return then).
        self._last_book: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None

        self._prev_ts: int | None = None
        self._cur_idx: int | None = None  # current interval index; t0 = idx * dt_ns
        self._count = 0  # next col_seq (never resets)
        self._oldest_seq = 0

        # Ring storage: float16 [ring_columns, 2, rows] + parallel metadata.
        rc = cfg.ring_columns
        self._ring = np.zeros((rc, 2, rows), dtype=np.float16)
        self._ring_epoch = np.zeros(rc, dtype=np.uint32)
        self._ring_t0 = np.zeros(rc, dtype=np.int64)
        self._ring_seq = np.zeros(rc, dtype=np.uint32)
        self._ring_mode = np.zeros(rc, dtype=np.uint8)
        self._ring_bars: list[BarColumn | None] = [None] * rc

        # Bar state for the current interval.
        self._o = self._h = self._l = self._c = _NAN
        self._prev_close = _NAN
        self._bar_has_trade = False
        self._vol_buy = 0.0
        self._vol_sell = 0.0
        # Session-cumulative accumulators.
        self._cvd_cum = 0.0
        self._vwap_num_cum = 0.0
        self._vwap_den_cum = 0.0

    @property
    def cfg(self) -> GridCfg:
        return self._cfg

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def count(self) -> int:
        """Number of columns finalized so far (next col_seq)."""
        return self._count

    # -- rehydration (backfill / recorded tail) ---------------------------------

    def preload(self, columns: list[FinalizedColumn], epochs: list[EpochParams]) -> None:
        """Seed the ring from a historical tail (backfill or recording).

        Only valid on a *virgin* grid — before any :meth:`on_book` or
        :meth:`on_trade` (raises ``RuntimeError`` otherwise). ``columns``
        must be chronological with strictly increasing, CONTIGUOUS
        ``col_seq``/``t0_ns``; ``epochs`` must cover every epoch referenced.
        """
        if self._cur_idx is not None or self._count != 0:
            raise RuntimeError("preload is only valid before any on_book/on_trade")
        if not columns:
            return
        cfg = self._cfg
        ep_map = {e.epoch: e for e in epochs}
        missing = {c.epoch for c in columns} - ep_map.keys()
        if missing:
            raise ValueError(f"columns reference unknown epochs {sorted(missing)}")
        for e in ep_map.values():
            if (e.tick, e.tick_multiple, e.dt_ns, e.rows) != (
                cfg.tick, self._tick_multiple, cfg.dt_ns, cfg.rows,
            ):
                raise ValueError(
                    f"epoch {e.epoch} params do not match grid cfg "
                    f"(tick={cfg.tick}, dt_ns={cfg.dt_ns}, rows={cfg.rows})"
                )
        columns = columns[-cfg.ring_columns:]
        prev: FinalizedColumn | None = None
        for c in columns:
            if len(c.bid) != cfg.rows or len(c.ask) != cfg.rows:
                raise ValueError(f"column seq={c.col_seq} has wrong row count")
            if prev is not None:
                # Contiguity — not just monotonicity — is load-bearing:
                # history() must never dereference a slot that was never written.
                if c.col_seq != prev.col_seq + 1:
                    raise ValueError(
                        f"columns must be contiguous to rehydrate; "
                        f"seq {prev.col_seq} -> {c.col_seq}"
                    )
                if c.t0_ns <= prev.t0_ns:
                    raise ValueError("columns must be strictly increasing in t0_ns")
            prev = c

        rc = cfg.ring_columns
        for c in columns:
            i = c.col_seq % rc
            self._ring[i, 0] = np.asarray(c.bid, dtype=np.float16)
            self._ring[i, 1] = np.asarray(c.ask, dtype=np.float16)
            self._ring_epoch[i] = c.epoch
            self._ring_t0[i] = c.t0_ns
            self._ring_seq[i] = c.col_seq
            self._ring_mode[i] = c.mode
            self._ring_bars[i] = c.bar
        last = columns[-1]
        self._count = last.col_seq + 1
        self._oldest_seq = columns[0].col_seq
        self._epoch = last.epoch
        self._epoch_params.update(ep_map)
        self._p0 = ep_map[last.epoch].p0

    # -- book / density --------------------------------------------------------

    def on_book(
        self,
        ts_ns: int,
        bid_px: np.ndarray,
        bid_sz: np.ndarray,
        ask_px: np.ndarray,
        ask_sz: np.ndarray,
    ) -> list[FinalizedColumn]:
        """Apply a book state observed at ``ts_ns``.

        Time-weighted: the PREVIOUS book state is integrated over
        ``(ts_ns - prev_ts)``. May finalize 0..k columns (k > 1 if ts jumps
        intervals; skipped intervals beyond ring_columns are capped).
        Returns the finalized columns.
        """
        dt = self._cfg.dt_ns
        out: list[FinalizedColumn] = []

        if self._cur_idx is None:
            self._cur_idx = ts_ns // dt
            self._prev_ts = ts_ns
            self._set_book(bid_px, bid_sz, ask_px, ask_sz)
            return out

        duplicate = ts_ns == self._prev_ts
        # Non-monotonic timestamps: clamp to zero span (state still replaced).
        cursor = self._prev_ts
        ts_eff = max(ts_ns, cursor)

        # Gap cap: a huge ts jump would otherwise finalize gap/dt columns only
        # for all but the last ring_columns of them to be evicted. Finalize the
        # current (partial) interval normally, then skip straight to the last
        # ring_columns intervals before ts; col_seq advances by the SKIPPED
        # count so (col_seq delta == t0 delta / dt_ns) stays true.
        rc = self._cfg.ring_columns
        if ts_eff // dt - self._cur_idx > rc + 1:
            end = (self._cur_idx + 1) * dt
            span = end - cursor
            if span > 0:
                self._acc += self._state * span
            out.append(self._finalize_current())
            self._cur_idx += 1
            new_idx = ts_eff // dt - rc
            self._count += new_idx - self._cur_idx  # skipped interval count
            self._cur_idx = new_idx
            cursor = new_idx * dt

        while True:
            end = (self._cur_idx + 1) * dt
            if ts_eff < end:
                break
            span = end - cursor
            if span > 0:
                self._acc += self._state * span
            out.append(self._finalize_current())
            cursor = end
            self._cur_idx += 1
        span = ts_eff - cursor
        if span > 0:
            self._acc += self._state * span

        self._prev_ts = ts_eff
        self._set_book(bid_px, bid_sz, ask_px, ask_sz)

        if duplicate and not out and self._count > 0:
            # Zero-span call at exactly the end of the most recently finalized
            # column: re-return it (idempotent; callers dedup by col_seq).
            i = (self._count - 1) % self._cfg.ring_columns
            if int(self._ring_t0[i]) + dt == ts_ns:
                out.append(self._column_from_ring(i))
        return out

    def _set_book(
        self,
        bid_px: np.ndarray,
        bid_sz: np.ndarray,
        ask_px: np.ndarray,
        ask_sz: np.ndarray,
    ) -> None:
        self._last_book = (
            np.array(bid_px, dtype=np.float64, copy=True),
            np.array(bid_sz, dtype=np.float64, copy=True),
            np.array(ask_px, dtype=np.float64, copy=True),
            np.array(ask_sz, dtype=np.float64, copy=True),
        )
        self._state[0] = self._map_levels(bid_px, bid_sz)
        self._state[1] = self._map_levels(ask_px, ask_sz)

    def _map_levels(self, px: np.ndarray, sz: np.ndarray) -> np.ndarray:
        """Scatter price levels into a dense [rows] float64 profile.

        ``row = round((px - p0) / (tick * tick_multiple))``; out-of-range
        levels are dropped (they return after a re-anchor). Non-finite prices
        or sizes are dropped BEFORE the rint/int cast.
        """
        rows = self._cfg.rows
        px64 = np.asarray(px, dtype=np.float64).reshape(-1)
        sz64 = np.asarray(sz, dtype=np.float64).reshape(-1)
        finite = np.isfinite(px64) & np.isfinite(sz64)
        px64 = px64[finite]
        sz64 = sz64[finite]
        r = np.rint((px64 - self._p0) / self._step).astype(np.int64)
        mask = (r >= 0) & (r < rows)
        return np.bincount(r[mask], weights=sz64[mask], minlength=rows)

    def _finalize_current(self) -> FinalizedColumn:
        dt = self._cfg.dt_ns
        t0 = self._cur_idx * dt
        # Division in float64, saturate below f16 max, then a single cast.
        density64 = np.minimum(self._acc / float(dt), _F16_MAX)
        density16 = density64.astype(np.float16)
        bar = self._snap_bar(t0)

        i = self._count % self._cfg.ring_columns
        self._ring[i] = density16
        self._ring_epoch[i] = self._epoch
        self._ring_t0[i] = t0
        self._ring_seq[i] = self._count
        self._ring_mode[i] = self._cfg.mode
        self._ring_bars[i] = bar

        col = FinalizedColumn(
            epoch=self._epoch,
            col_seq=self._count,
            t0_ns=t0,
            bid=density16[0],
            ask=density16[1],
            bar=bar,
            mode=self._cfg.mode,
        )
        self._count += 1
        self._acc[:] = 0.0
        self._reset_interval_bar()
        return col

    def _column_from_ring(self, i: int) -> FinalizedColumn:
        bar = self._ring_bars[i]
        assert bar is not None
        return FinalizedColumn(
            epoch=int(self._ring_epoch[i]),
            col_seq=int(self._ring_seq[i]),
            t0_ns=int(self._ring_t0[i]),
            bid=self._ring[i, 0].copy(),
            ask=self._ring[i, 1].copy(),
            bar=bar,
            mode=int(self._ring_mode[i]),
        )

    # -- trades / bars ---------------------------------------------------------

    def on_trade(self, ts_ns: int, price: float, size: float, side: int) -> None:
        """Feed a trade into the current interval's bar accumulators.

        Never advances intervals or finalizes columns. A trade arriving
        before any book update anchors the current interval at
        ``ts_ns // dt_ns``. A malformed print (non-finite or non-positive
        price, negative size) is ignored ENTIRELY — ``cvd_cum`` and the
        ``vwap_*`` sums are session-cumulative, so a single NaN or negative
        print would poison every later bar. A zero-size print is kept.
        """
        if not (price > 0.0) or not math.isfinite(size) or size < 0.0:
            return
        if self._cur_idx is None:
            self._cur_idx = ts_ns // self._cfg.dt_ns
            self._prev_ts = ts_ns

        if self._bar_has_trade:
            self._h = max(self._h, price)
            self._l = min(self._l, price)
        else:
            self._o = self._h = self._l = price
            self._bar_has_trade = True
        self._c = price

        if side == events.SIDE_BUY:
            self._vol_buy += size
            self._cvd_cum += size
        elif side == events.SIDE_SELL:
            self._vol_sell += size
            self._cvd_cum -= size
        # SIDE_UNKNOWN: neither volume bucket, cvd unchanged.
        self._vwap_num_cum += price * size
        self._vwap_den_cum += size

    def _snap_bar(self, t0_ns: int) -> BarColumn:
        return BarColumn(
            epoch=self._epoch,
            col_seq=self._count,
            t0_ns=t0_ns,
            o=self._o,
            h=self._h,
            l=self._l,
            c=self._c,
            vol_buy=self._vol_buy,
            vol_sell=self._vol_sell,
            cvd_cum=self._cvd_cum,
            vwap_num_cum=self._vwap_num_cum,
            vwap_den_cum=self._vwap_den_cum,
        )

    def _reset_interval_bar(self) -> None:
        self._prev_close = self._c  # may be NaN before the first trade ever
        self._o = self._h = self._l = self._c = self._prev_close
        self._bar_has_trade = False
        self._vol_buy = 0.0
        self._vol_sell = 0.0
        # *_cum accumulators persist across intervals (session-cumulative).

    # -- partial (right-edge) emission -----------------------------------------

    def _make_depth(self, col: FinalizedColumn, final: bool) -> events.DepthColumn:
        """Single owner of the density->wire conversion: cast to float32 and
        drop the ask channel for SYNTH_PROFILE columns."""
        synth = col.mode == events.MODE_SYNTH_PROFILE
        return events.DepthColumn(
            epoch=col.epoch,
            col_seq=col.col_seq,
            t0_ns=col.t0_ns,
            mode=col.mode,
            final=final,
            bid=col.bid.astype(np.float32),
            ask=None if synth else col.ask.astype(np.float32),
        )

    def to_depth(self, col: FinalizedColumn) -> events.DepthColumn:
        """Convert a finalized (f16 ring) column to a wire DepthColumn
        (float32, ``final=True``, ask dropped in SYNTH_PROFILE mode)."""
        return self._make_depth(col, final=True)

    def current_partial(self) -> events.DepthColumn | None:
        """Progressive right-edge emit: the in-progress column so far.

        The partial integral (accumulated through the latest ``on_book``
        timestamp) is divided by the full ``dt_ns``, so the value converges
        to the finalized column as the interval fills. Returns ``None``
        before the grid has been anchored by any event.
        """
        if self._cur_idx is None:
            return None
        density = self._acc / float(self._cfg.dt_ns)
        col = FinalizedColumn(
            epoch=self._epoch,
            col_seq=self._count,
            t0_ns=self._cur_idx * self._cfg.dt_ns,
            bid=density[0],
            ask=density[1],
            bar=self.bar_partial(),
            mode=self._cfg.mode,
        )
        return self._make_depth(col, final=False)

    def bar_partial(self) -> BarColumn:
        """The current interval's bar state (not yet finalized)."""
        t0 = 0 if self._cur_idx is None else self._cur_idx * self._cfg.dt_ns
        return self._snap_bar(t0)

    # -- epochs / re-anchor ----------------------------------------------------

    def maybe_reanchor(self, mid: float) -> EpochParams | None:
        """Re-anchor the price frame when mid drifts too far.

        Banded grids re-anchor on a RATIO trip (mid outside
        ``[anchor/BAND_TRIP_RATIO, anchor*BAND_TRIP_RATIO]``); the first
        usable mid builds the percentage frame and freezes ``tick_multiple``.
        Legacy fixed-span grids use the central-70% rule.

        History in the ring is NEVER rewritten; the in-progress accumulator is
        row-shifted into the new row coordinates so the current column stays
        exact. A non-finite / non-positive ``mid`` is ignored rather than
        raised — this is called straight off feed data with no ``try``.
        """
        cfg = self._cfg
        if not math.isfinite(mid) or mid <= 0.0:
            return None
        if cfg.band_up is not None:
            return self._reanchor_banded(mid)
        span = cfg.rows * self._step
        lo = self._p0 + 0.15 * span
        hi = self._p0 + 0.85 * span
        if lo <= mid <= hi:
            return None
        new_p0 = round((mid - span / 2.0) / self._step) * self._step
        return self._commit_anchor(new_p0)

    def anchor_banded(self, mid: float) -> EpochParams | None:
        """Force the FIRST banded anchor (boot backfill reference frame).

        Uses ``mid`` as the reference price, builds the percentage frame and
        freezes ``tick_multiple``. Returns the published params, or ``None``
        for legacy grids / unusable mids.
        """
        if self._cfg.band_up is None or not (math.isfinite(mid) and mid > 0.0):
            return None
        self._anchor_mid = None
        return self._reanchor_banded(mid)

    def _reanchor_banded(self, mid: float) -> EpochParams | None:
        cfg = self._cfg
        if self._anchor_mid is None:
            # First anchor: derive the multiple from the percentage band and
            # FREEZE it — recomputing it later would change step mid-session
            # and redraw every resident column at wrong prices.
            lo = mid * (1.0 - cfg.band_down)
            hi = mid * (1.0 + cfg.band_up)
            span = (hi - lo) * BAND_MARGIN
            if not math.isfinite(span) or span <= 0.0:
                return None
            tm = max(1, math.ceil(span / (cfg.rows * cfg.tick)))
            step = cfg.tick * tm
            new_p0 = round((mid - span / 2.0) / step) * step
            # Snapped re-check (upstream band_frame): rounding p0 onto the
            # step grid can uncover the top of the requested band — widen
            # until the frame provably covers it.
            while new_p0 + cfg.rows * step < hi and tm < (1 << 30):
                tm += 1
                step = cfg.tick * tm
                new_p0 = round((mid - span / 2.0) / step) * step
            self._tick_multiple = tm
            self._step = step
            self._anchor_mid = mid
            return self._commit_anchor(new_p0, rebuild_state=True)
        ratio = mid / self._anchor_mid
        if 1.0 / BAND_TRIP_RATIO <= ratio <= BAND_TRIP_RATIO:
            return None
        # p0 ONLY — the multiple is frozen, so this is an exact row shift.
        span = cfg.rows * self._step
        new_p0 = round((mid - span / 2.0) / self._step) * self._step
        self._anchor_mid = mid
        return self._commit_anchor(new_p0)

    def _commit_anchor(self, new_p0: float, *, rebuild_state: bool = False) -> EpochParams:
        """Move the frame to ``new_p0``, bump the epoch, publish the params."""
        cfg = self._cfg
        if rebuild_state:
            # First banded anchor: the step itself changed, so row-shift math
            # does not apply — drop the nominal-frame accumulator and rebuild
            # the dense state from the raw book on the new grid. `_prev_ts` is
            # deliberately KEPT: resetting it here (with `_cur_idx` still set)
            # crashed the next `on_book` on `max(ts_ns, None)`, and upstream
            # never resets it — the live state simply integrates across the
            # anchor moment.
            self._acc[:] = 0.0
            self._state[:] = 0.0
        elif self._p0 != new_p0:
            delta = (new_p0 - self._p0) / self._step
            offset = round(delta)
            if abs(delta - offset) < 1e-9:
                self._shift_rows(self._acc, offset)
            else:  # pragma: no cover — snapped p0 keeps this unreachable
                self._acc[:] = 0.0
        self._p0 = new_p0
        self._epoch += 1
        if self._last_book is not None:
            bid_px, bid_sz, ask_px, ask_sz = self._last_book
            self._state[0] = self._map_levels(bid_px, bid_sz)
            self._state[1] = self._map_levels(ask_px, ask_sz)
        params = EpochParams(
            epoch=self._epoch,
            tick=cfg.tick,
            tick_multiple=self._tick_multiple,
            dt_ns=cfg.dt_ns,
            p0=new_p0,
            rows=cfg.rows,
        )
        self._epoch_params[self._epoch] = params
        return params

    def epoch_params_for(self, epoch: int) -> EpochParams:
        """Params of any epoch this grid has lived through."""
        return self._epoch_params[epoch]

    def current_epoch_params(self) -> EpochParams:
        """Params of the live (current) epoch."""
        return self._epoch_params[self._epoch]

    def _shift_rows(self, a: np.ndarray, offset: int) -> None:
        """In-place row shift along the last axis: ``new[r] = old[r + offset]``.

        Rows shifted out of range are dropped; vacated rows become zero.
        """
        if offset == 0:
            return
        rows = self._cfg.rows
        if abs(offset) >= rows:
            a[...] = 0.0
            return
        if offset > 0:
            a[..., : rows - offset] = a[..., offset:]
            a[..., rows - offset:] = 0.0
        else:
            k = -offset
            a[..., k:] = a[..., : rows - k]
            a[..., :k] = 0.0

    # -- history ---------------------------------------------------------------

    def oldest_retained_t0_ns(self) -> int | None:
        """``t0_ns`` of the oldest column still retained, or ``None``."""
        rc = self._cfg.ring_columns
        retained = min(self._count - self._oldest_seq, rc)
        if retained == 0:
            return None
        return int(self._ring_t0[(self._count - retained) % rc])

    def history(self, before_t_ns: int, n: int) -> list[FinalizedColumn]:
        """The most recent ``n`` retained columns with ``t0_ns < before_t_ns``.

        ``before_t_ns`` is EXCLUSIVE. Returns chronological (oldest first).
        Arrays are copies.
        """
        rc = self._cfg.ring_columns
        retained = min(self._count - self._oldest_seq, rc)
        if retained == 0 or n <= 0:
            return []
        seqs = np.arange(self._count - retained, self._count, dtype=np.int64)
        idxs = seqs % rc
        keep = self._ring_t0[idxs] < before_t_ns
        chosen = idxs[keep][-n:]
        return [self._column_from_ring(int(i)) for i in chosen]


# --- backfill: candles -> reconstructed grid columns ----------------------------


def _synth_profile(cd: Candle, p0: float, step: float, rows: int) -> np.ndarray:
    """Single-channel (bid) volume-at-price profile for one candle.

    Volume is spread evenly across the rows covering ``[low, high]``,
    clamped to the grid. An absurd high/low (mis-scaled venue) is clamped
    BEFORE the range is built so the loop can never explode.
    """
    dens = np.zeros(rows, dtype=np.float64)
    lo_r = round((min(cd.l, cd.h) - p0) / step)
    hi_r = round((max(cd.l, cd.h) - p0) / step)
    lo_r, hi_r = max(lo_r, 0), min(hi_r, rows - 1)
    if lo_r > hi_r:
        return dens
    per = float(cd.volume) / (hi_r - lo_r + 1)
    for r in range(lo_r, hi_r + 1):
        dens[r] += per
    return dens


def columns_from_candles(
    candles: list[Candle],
    cfg: GridCfg,
    *,
    max_cols: int | None = None,
    p0: float | None = None,
    tick_multiple: int | None = None,
    epoch: int = 0,
) -> tuple[list[FinalizedColumn], EpochParams] | None:
    """Stretch 1 m candles across their full minute onto the 250 ms grid.

    Contract (mirrors upstream ``core/backfill.py::columns_from_candles``):
    each candle expands to ``60 s / dt`` single-channel columns
    (mode=SYNTH_PROFILE: bid[] carries the candle's volume spread evenly
    across its ``[low, high]`` row band, ask omitted, ask channel zeroed in
    the ring); one global scale normalizes the densest bucket across ALL
    columns to ``PEAK_TARGET``; col_seq is 0..N-1 contiguous on a strictly
    increasing t0 grid; the shared epoch has ``p0`` equal to the grid's
    anchor frame so live data continues in the same geometry. Banded grids
    pass the anchored ``p0``/``tick_multiple``/``epoch`` explicitly (the cfg
    still carries the pre-anchor nominal frame at boot). Output is capped
    at ``cfg.ring_columns`` columns (the NEWEST ones), further capped to
    ``max_cols`` when given (the contract's backfill budget, ≈1024 — a full
    f16 ring of synthetic columns would evict live data immediately).
    Returns ``None`` when nothing usable can be produced.
    """
    rows = cfg.rows
    tm = cfg.tick_multiple if tick_multiple is None else int(tick_multiple)
    step = cfg.tick * tm
    frame_p0 = cfg.p0 if p0 is None else float(p0)
    dt = cfg.dt_ns
    if rows <= 0 or step <= 0.0 or dt <= 0:
        return None

    cap = cfg.ring_columns if max_cols is None else max(1, min(int(max_cols), cfg.ring_columns))

    clean = [
        cd for cd in candles
        if _finite(cd.o, cd.h, cd.l, cd.c, cd.volume)
        and cd.volume >= 0.0 and cd.c > 0.0
    ]
    if not clean:
        return None
    clean.sort(key=lambda cd: cd.t0_ns)

    cols_per_candle = max(1, _CANDLE_SPAN_NS // dt)
    total = min(len(clean) * cols_per_candle, cap)
    if total <= 0:
        return None

    # Keep only the candles that can still contribute to the newest
    # ``total`` columns (older candles would be dropped by the cap anyway).
    keep_n = min(len(clean), max(1, -(-total // cols_per_candle)))
    clean = clean[-keep_n:]

    # First pass: raw densities + global peak + running bar accumulators.
    raw: list[np.ndarray] = []
    t0s: list[int] = []
    cvd_cum = 0.0
    vwap_num = 0.0
    vwap_den = 0.0
    bars: list[tuple[float, float, float, float, float]] = []  # vb, vs, cvd, vn, vd
    prev_t0: int | None = None
    global_peak = 0.0
    for cd in clean:
        t0 = (cd.t0_ns // dt) * dt
        if prev_t0 is not None and t0 <= prev_t0:
            t0 = prev_t0 + dt  # force strictly increasing on the dt grid
        prev_t0 = t0
        dens = _synth_profile(cd, frame_p0, step, rows)
        raw.append(dens)
        t0s.append(t0)
        global_peak = max(global_peak, float(dens.max()))

        has_split = cd.buy_volume is not None and cd.sell_volume is not None
        vb = float(cd.buy_volume) if has_split else 0.0
        vs = float(cd.sell_volume) if has_split else 0.0
        if has_split and _finite(vb, vs):
            cvd_cum += vb - vs
        else:
            vb = vs = 0.0
        tp = (cd.h + cd.l + cd.c) / 3.0
        vwap_num += tp * float(cd.volume)
        vwap_den += float(cd.volume)
        bars.append((vb, vs, cvd_cum, vwap_num, vwap_den))

    if global_peak <= 0.0:
        return None
    scale = PEAK_TARGET / global_peak

    columns: list[FinalizedColumn] = []
    built = 0
    # The cap keeps the NEWEST slots: skip whole leading slots (possibly into
    # the middle of the oldest kept candle) so the reconstruction ends as
    # close to "now" as possible instead of trailing off at the cap.
    skip = max(0, len(clean) * cols_per_candle - total)
    for ci, (cd, t0, (vb, vs, cvd, vn, vd)) in enumerate(
        zip(clean, t0s, bars, strict=True)
    ):
        if built >= total:
            break
        d16 = (raw[ci] * scale).astype(np.float16)
        for k in range(cols_per_candle):
            if ci * cols_per_candle + k < skip:
                continue  # dropped by the cap (oldest side)
            if built >= total:
                break
            if k == 0:
                o, h, l, c = cd.o, cd.h, cd.l, cd.c
            else:
                # Later columns of the stretch had no fresh print: carry the
                # close flat, exactly like the live grid's no-trade intervals.
                o = h = l = c = cd.c
            bar = BarColumn(
                epoch=epoch,
                col_seq=built,
                t0_ns=t0 + k * dt,
                o=o, h=h, l=l, c=c,
                vol_buy=vb if k == 0 else 0.0,
                vol_sell=vs if k == 0 else 0.0,
                cvd_cum=cvd,
                vwap_num_cum=vn,
                vwap_den_cum=vd,
            )
            columns.append(FinalizedColumn(
                epoch=epoch,
                col_seq=built,
                t0_ns=t0 + k * dt,
                bid=d16,
                ask=np.zeros(rows, dtype=np.float16),
                bar=bar,
                mode=events.MODE_SYNTH_PROFILE,
            ))
            built += 1

    epoch = EpochParams(
        epoch=epoch,
        tick=cfg.tick,
        tick_multiple=tm,
        dt_ns=dt,
        p0=frame_p0,
        rows=rows,
    )
    return columns, epoch
