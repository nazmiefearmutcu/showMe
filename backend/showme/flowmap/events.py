"""Canonical FlowMap events (port of flowmap_server.proto.events).

These dataclasses are the **in-process representation only**; the wire
encoding lives in :mod:`showme.flowmap.wire`:

- Hot messages (DepthColumn, BarColumn, Trade, BBO, Ping, Pong,
  HistoryResponse) are hand-packed little-endian binary.
- Cold messages (Hello, EpochStart, Status, Marker, Subscribe, Unsubscribe,
  Seek, SetSpeed, Pause, Resume, HistoryRequest) travel as UTF-8 JSON
  payloads flagged with FLAG_JSON in the envelope.

Field order in each class is load-bearing for cold messages: the JSON
encoders emit keys in declaration order, and the golden fixtures freeze
that order. The upstream reference used ``msgspec.Struct``; the sidecar
does not depend on msgspec, so the JSON encoders here reproduce its
compact output byte-for-byte with :mod:`json` (see ``wire._json_bytes``).

``EpochParams`` replicates upstream ``omit_defaults=True`` for the seven
trailing price-scale fields: a LINEAR epoch encodes to byte-identical JSON
with those fields absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# --- DepthColumn.mode (wire u8) ------------------------------------------------
MODE_L2 = 0
MODE_L1_BAND = 1
MODE_SYNTH_PROFILE = 2  # single-channel density: only bid[] is present

# --- Trade.side / Trade.side_src (wire u8) ------------------------------------
SIDE_BUY = 0
SIDE_SELL = 1
SIDE_UNKNOWN = 2

SIDE_SRC_EXCHANGE = 0
SIDE_SRC_INFERRED = 1
SIDE_SRC_NA = 2

MARKER_KINDS = (
    "liquidation", "halt", "luld", "gap", "session_break", "large_lot", "iceberg", "info",
)
FEED_STATES = ("live", "degraded", "closed", "reconnecting")
STREAM_MODES = ("live", "replay")


# --- Cold (JSON) messages ------------------------------------------------------


@dataclass(slots=True)
class EpochParams:
    """Row<->price geometry for one epoch.

    LINEAR affine ``price = p0 + row * step`` (``step = tick * tick_multiple``).
    The trailing seven fields mirror upstream's piecewise-scale extension and
    are omitted from the JSON when they carry their defaults (linear).
    """

    epoch: int
    tick: float
    tick_multiple: int
    dt_ns: int
    p0: float
    rows: int
    scale_kind: int = 0
    dn_rows: int = 0
    core_rows: int = 0
    core_p0: float = 0.0
    core_step: float = 0.0
    lo_price: float = 0.0
    hi_price: float = 0.0

    _SCALE_FIELDS = (
        "scale_kind", "dn_rows", "core_rows", "core_p0", "core_step", "lo_price", "hi_price",
    )
    _SCALE_DEFAULTS = (0, 0, 0, 0.0, 0.0, 0.0, 0.0)

    def to_json_dict(self) -> dict[str, Any]:
        """Ordered dict matching upstream msgspec output (omit_defaults)."""
        out: dict[str, Any] = {
            "epoch": self.epoch,
            "tick": self.tick,
            "tick_multiple": self.tick_multiple,
            "dt_ns": self.dt_ns,
            "p0": self.p0,
            "rows": self.rows,
        }
        for name, default in zip(self._SCALE_FIELDS, self._SCALE_DEFAULTS):
            value = getattr(self, name)
            if value != default:
                out[name] = value
        return out

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> EpochParams:
        try:
            return cls(
                epoch=int(d["epoch"]),
                tick=float(d["tick"]),
                tick_multiple=int(d["tick_multiple"]),
                dt_ns=int(d["dt_ns"]),
                p0=float(d["p0"]),
                rows=int(d["rows"]),
                scale_kind=int(d.get("scale_kind", 0)),
                dn_rows=int(d.get("dn_rows", 0)),
                core_rows=int(d.get("core_rows", 0)),
                core_p0=float(d.get("core_p0", 0.0)),
                core_step=float(d.get("core_step", 0.0)),
                lo_price=float(d.get("lo_price", 0.0)),
                hi_price=float(d.get("hi_price", 0.0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed EpochParams payload: {exc}") from exc


@dataclass(slots=True)
class Hello:
    protocol_version: int
    session_id: str
    grid_epoch: int
    epoch_params: EpochParams
    capability: dict[str, Any]
    norm_seed: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
            "grid_epoch": self.grid_epoch,
            "epoch_params": self.epoch_params.to_json_dict(),
            "capability": dict(self.capability),
            "norm_seed": self.norm_seed,
        }


@dataclass(slots=True)
class EpochStart:
    epoch: int
    epoch_params: EpochParams

    def to_json_dict(self) -> dict[str, Any]:
        return {"epoch": self.epoch, "epoch_params": self.epoch_params.to_json_dict()}


@dataclass(slots=True)
class Marker:
    ts_ns: int
    kind: str
    text: str = ""
    price: float | None = None
    size: float | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ts_ns": self.ts_ns,
            "kind": self.kind,
            "text": self.text,
            "price": self.price,
            "size": self.size,
        }


@dataclass(slots=True)
class Status:
    feed_state: str
    capability: dict[str, Any]
    latency_ms: float
    clock_skew_ms: float
    next_open_ts: int | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "feed_state": self.feed_state,
            "capability": dict(self.capability),
            "latency_ms": self.latency_ms,
            "clock_skew_ms": self.clock_skew_ms,
            "next_open_ts": self.next_open_ts,
        }


@dataclass(slots=True)
class Subscribe:
    market: str
    symbol: str
    mode: str
    source: str | None = None
    start_t: int | None = None
    band: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "symbol": self.symbol,
            "mode": self.mode,
            "source": self.source,
            "start_t": self.start_t,
            "band": self.band,
        }

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> Subscribe:
        try:
            return cls(
                market=str(d["market"]),
                symbol=str(d["symbol"]),
                mode=str(d["mode"]),
                source=None if d.get("source") is None else str(d["source"]),
                start_t=None if d.get("start_t") is None else int(d["start_t"]),
                band=None if d.get("band") is None else str(d["band"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed Subscribe payload: {exc}") from exc


@dataclass(slots=True)
class Unsubscribe:
    def to_json_dict(self) -> dict[str, Any]:
        return {}


@dataclass(slots=True)
class Seek:
    t: int

    def to_json_dict(self) -> dict[str, Any]:
        return {"t": self.t}


@dataclass(slots=True)
class SetSpeed:
    x: float

    def to_json_dict(self) -> dict[str, Any]:
        return {"x": self.x}


@dataclass(slots=True)
class Pause:
    def to_json_dict(self) -> dict[str, Any]:
        return {}


@dataclass(slots=True)
class Resume:
    def to_json_dict(self) -> dict[str, Any]:
        return {}


@dataclass(slots=True)
class HistoryRequest:
    req_id: int
    before_t: int
    n_cols: int

    def to_json_dict(self) -> dict[str, Any]:
        return {"req_id": self.req_id, "before_t": self.before_t, "n_cols": self.n_cols}

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> HistoryRequest:
        try:
            return cls(req_id=int(d["req_id"]), before_t=int(d["before_t"]),
                       n_cols=int(d["n_cols"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed HistoryRequest payload: {exc}") from exc


# --- Hot (hand-packed binary) messages -----------------------------------------


@dataclass(slots=True)
class DepthColumn:
    epoch: int
    col_seq: int
    t0_ns: int
    mode: int  # MODE_L2 | MODE_L1_BAND | MODE_SYNTH_PROFILE
    final: bool
    bid: np.ndarray  # float32, length n_rows
    ask: np.ndarray | None  # None iff mode == MODE_SYNTH_PROFILE


@dataclass(slots=True, frozen=True)
class BarColumn:
    epoch: int
    col_seq: int
    t0_ns: int
    o: float
    h: float
    l: float
    c: float
    vol_buy: float
    vol_sell: float
    cvd_cum: float
    vwap_num_cum: float
    vwap_den_cum: float


@dataclass(slots=True)
class Trade:
    ts_ns: int
    price: float
    size: float
    side: int  # SIDE_BUY | SIDE_SELL | SIDE_UNKNOWN
    side_src: int  # SIDE_SRC_EXCHANGE | SIDE_SRC_INFERRED | SIDE_SRC_NA
    venue: str  # wire: u8 length + UTF-8 bytes (<= 255 bytes)


@dataclass(slots=True)
class BBO:
    ts_ns: int
    bid_px: float
    bid_sz: float
    ask_px: float
    ask_sz: float


@dataclass(slots=True)
class Ping:
    server_send_ns: int


@dataclass(slots=True)
class Pong:
    echo_ns: int
    client_recv_ns: int


@dataclass(slots=True)
class HistoryResponse:
    req_id: int
    epoch: int
    oldest_available_t_ns: int
    depth_cols: list[DepthColumn] = field(default_factory=list)
    bar_cols: list[BarColumn] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    big_trades: list[Trade] = field(default_factory=list)
