"""FlowMap wire framing (port of flowmap_server.proto.wire, msgspec-free).

Envelope
--------
Every message starts with an 8-byte little-endian envelope::

    struct.pack("<BBHI", msg_type, PROTO_VER, flags, payload_len)

followed by the payload. ``FLAG_JSON`` (0x0001) marks the payload as UTF-8
JSON (cold messages); otherwise the payload is hand-packed little-endian
binary (hot messages).

Padding rule (uniform for hot AND cold messages)
------------------------------------------------
``payload_len`` in the envelope is ALWAYS the **unpadded** payload byte
length. On the wire the payload is zero-padded up to the next 4-byte
boundary, and readers advance the cursor by the padded length::

    next_offset = offset + 8 + ceil4(payload_len)

Decoders read exactly ``payload_len`` payload bytes, so JSON payloads never
need trailing-NUL trimming. Because every message length (8 + ceil4(len)) is
a multiple of 4, message starts inside a batched frame stay 4-byte aligned,
which keeps DEPTH_COL's f32 arrays (absolute offset 32 within the message)
aligned for zero-copy Float32Array views on the client.

Error taxonomy (same as upstream): ALL malformed input (truncated
envelope/payload, version mismatch, payload_len inconsistent with the type's
layout, venue/count overruns, bad UTF-8/JSON) raises ``ValueError`` — never a
raw struct.error, IndexError or UnicodeDecodeError. Unknown msg_types are NOT
errors: they are skipped via payload_len (``decode`` returns
``(None, next_offset)``).

Payload layouts (little-endian throughout)
------------------------------------------
DEPTH_COL   <IIqBBHI> epoch, col_seq, t0_ns, mode, final, _pad(u16)=0, n_rows
            then bid f32*n_rows, ask f32*n_rows (ask omitted iff mode==SYNTH_PROFILE)
BAR_COL     <IIq> epoch, col_seq, t0_ns; <dddd> o,h,l,c;
            <ddddd> vol_buy, vol_sell, cvd_cum, vwap_num_cum, vwap_den_cum
TRADE       <qddBBBB> ts_ns, price, size, side, side_src, _pad, _pad;
            then venue as u8 length + UTF-8 bytes (message padded to 4 per the rule)
BBO         <qdddd> ts_ns, bid_px, bid_sz, ask_px, ask_sz
PING        <q> server_send_ns
PONG        <qq> echo_ns, client_recv_ns
HISTORY_RESP <IIq> req_id, epoch, oldest_available_t_ns; <HHHH> n_depth, n_bar,
            n_marker, n_trade; then that many nested full messages (each with
            its own envelope) concatenated in that order.

BYTE-TRUTH: the golden fixtures under ``backend/tests/fixtures/flowmap/``
(copied from flowmap/client/tests/golden) must keep encoding 1:1.
"""
from __future__ import annotations

import json
import struct
from collections.abc import Callable

import numpy as np

from . import events

PROTO_VER = 1
FLAG_JSON = 0x0001

# --- MsgType tags: 0x01-0x3F data, 0x40-0x7F control, 0x80+ reserved -----------
MSG_HELLO = 0x01
MSG_EPOCH_START = 0x02
MSG_DEPTH_COL = 0x03
MSG_BAR_COL = 0x04
MSG_TRADE = 0x05
MSG_BBO = 0x06
MSG_MARKER = 0x07
MSG_STATUS = 0x08
MSG_PING = 0x09
MSG_HISTORY_RESP = 0x0A
MSG_SUBSCRIBE = 0x40
MSG_UNSUBSCRIBE = 0x41
MSG_SEEK = 0x42
MSG_SET_SPEED = 0x43
MSG_PAUSE = 0x44
MSG_RESUME = 0x45
MSG_HISTORY_REQ = 0x46
MSG_PONG = 0x47

_ENVELOPE = struct.Struct("<BBHI")  # 8 bytes
_DEPTH_HDR = struct.Struct("<IIqBBHI")  # 24 bytes -> f32 data at msg offset 32
_BAR = struct.Struct("<IIqddddddddd")  # 88 bytes
_TRADE_HDR = struct.Struct("<qddBBBB")  # 28 bytes
_BBO = struct.Struct("<qdddd")  # 40 bytes
_PING = struct.Struct("<q")
_PONG = struct.Struct("<qq")
_HIST_HDR = struct.Struct("<IIqHHHH")  # 24 bytes


def _ceil4(n: int) -> int:
    return (n + 3) & ~3


def _frame(msg_type: int, payload: bytes, flags: int = 0) -> bytes:
    pad = _ceil4(len(payload)) - len(payload)
    return _ENVELOPE.pack(msg_type, PROTO_VER, flags, len(payload)) + payload + b"\x00" * pad


def _json_bytes(payload: dict) -> bytes:
    """Compact UTF-8 JSON, byte-identical to upstream's msgspec.json output:
    no spaces, insertion-ordered keys, shortest-roundtrip float repr."""
    # allow_nan=False: msgspec fail-fast parity — a NaN reaching a cold
    # payload must raise here, never emit invalid JSON on the wire.
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _json_decode(payload: bytes) -> dict:
    try:
        obj = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed JSON payload: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("cold JSON payload must be an object")  # noqa: TRY004 — ValueError taxonomy is the wire contract
    return obj


# --- hot encoders (event -> payload bytes) -------------------------------------


def _f32_row(values) -> np.ndarray:
    return np.asarray(values, dtype="<f4").reshape(-1)


def _enc_depth(ev: events.DepthColumn) -> bytes:
    bid = _f32_row(ev.bid)
    n_rows = len(bid)
    parts = [
        _DEPTH_HDR.pack(ev.epoch, ev.col_seq, ev.t0_ns, ev.mode,
                        1 if ev.final else 0, 0, n_rows),
        bid.tobytes(),
    ]
    if ev.mode == events.MODE_SYNTH_PROFILE:
        if ev.ask is not None:
            raise ValueError("SYNTH_PROFILE DepthColumn must not carry ask[]")
    else:
        if ev.ask is None:
            raise ValueError("DepthColumn.ask is required unless mode == SYNTH_PROFILE")
        ask = _f32_row(ev.ask)
        if len(ask) != n_rows:
            raise ValueError(f"bid/ask length mismatch: {n_rows} != {len(ask)}")
        parts.append(ask.tobytes())
    return b"".join(parts)


def _enc_bar(ev: events.BarColumn) -> bytes:
    return _BAR.pack(
        ev.epoch, ev.col_seq, ev.t0_ns,
        ev.o, ev.h, ev.l, ev.c,
        ev.vol_buy, ev.vol_sell, ev.cvd_cum, ev.vwap_num_cum, ev.vwap_den_cum,
    )


def _enc_trade(ev: events.Trade) -> bytes:
    venue = ev.venue.encode("utf-8")
    if len(venue) > 255:
        raise ValueError("Trade.venue exceeds 255 UTF-8 bytes")
    hdr = _TRADE_HDR.pack(ev.ts_ns, ev.price, ev.size, ev.side, ev.side_src, 0, 0)
    return hdr + bytes([len(venue)]) + venue


def _enc_bbo(ev: events.BBO) -> bytes:
    return _BBO.pack(ev.ts_ns, ev.bid_px, ev.bid_sz, ev.ask_px, ev.ask_sz)


def _enc_ping(ev: events.Ping) -> bytes:
    return _PING.pack(ev.server_send_ns)


def _enc_pong(ev: events.Pong) -> bytes:
    return _PONG.pack(ev.echo_ns, ev.client_recv_ns)


def _enc_history(ev: events.HistoryResponse) -> bytes:
    for name, seq in (("depth_cols", ev.depth_cols), ("bar_cols", ev.bar_cols),
                      ("markers", ev.markers), ("big_trades", ev.big_trades)):
        if len(seq) > 0xFFFF:
            raise ValueError(f"HistoryResponse.{name} exceeds u16 count")
    hdr = _HIST_HDR.pack(
        ev.req_id, ev.epoch, ev.oldest_available_t_ns,
        len(ev.depth_cols), len(ev.bar_cols), len(ev.markers), len(ev.big_trades),
    )
    nested = b"".join(
        encode(m) for group in (ev.depth_cols, ev.bar_cols, ev.markers, ev.big_trades)
        for m in group
    )
    return hdr + nested


# --- hot decoders ((buf, payload_offset, payload_len) -> event) -----------------


def _dec_depth(buf: bytes, off: int, plen: int) -> events.DepthColumn:
    if plen < _DEPTH_HDR.size:
        raise ValueError(f"DEPTH_COL payload too short: {plen} < {_DEPTH_HDR.size}")
    epoch, col_seq, t0_ns, mode, final, _pad, n_rows = _DEPTH_HDR.unpack_from(buf, off)
    channels = 1 if mode == events.MODE_SYNTH_PROFILE else 2
    expected = _DEPTH_HDR.size + 4 * n_rows * channels
    if plen != expected:
        raise ValueError(
            f"DEPTH_COL payload_len mismatch: {plen} != {expected} "
            f"(n_rows={n_rows}, mode={mode})"
        )
    f32_off = off + _DEPTH_HDR.size
    # .copy() so the returned arrays do not pin the (potentially large) frame buffer
    bid = np.frombuffer(buf, dtype="<f4", count=n_rows, offset=f32_off).copy()
    if mode == events.MODE_SYNTH_PROFILE:
        ask = None
    else:
        ask = np.frombuffer(buf, dtype="<f4", count=n_rows, offset=f32_off + 4 * n_rows).copy()
    return events.DepthColumn(epoch=epoch, col_seq=col_seq, t0_ns=t0_ns,
                              mode=mode, final=bool(final), bid=bid, ask=ask)


def _dec_bar(buf: bytes, off: int, plen: int) -> events.BarColumn:
    if plen != _BAR.size:
        raise ValueError(f"BAR_COL payload_len mismatch: {plen} != {_BAR.size}")
    (epoch, col_seq, t0_ns, o, h, l, c,
     vol_buy, vol_sell, cvd_cum, vwap_num_cum, vwap_den_cum) = _BAR.unpack_from(buf, off)
    return events.BarColumn(epoch=epoch, col_seq=col_seq, t0_ns=t0_ns, o=o, h=h, l=l, c=c,
                            vol_buy=vol_buy, vol_sell=vol_sell, cvd_cum=cvd_cum,
                            vwap_num_cum=vwap_num_cum, vwap_den_cum=vwap_den_cum)


def _dec_trade(buf: bytes, off: int, plen: int) -> events.Trade:
    if plen < _TRADE_HDR.size + 1:
        raise ValueError(f"TRADE payload too short: {plen} < {_TRADE_HDR.size + 1}")
    ts_ns, price, size, side, side_src, _p1, _p2 = _TRADE_HDR.unpack_from(buf, off)
    vlen_off = off + _TRADE_HDR.size
    vlen = buf[vlen_off]
    if _TRADE_HDR.size + 1 + vlen > plen:
        raise ValueError(
            f"TRADE venue overruns payload_len: {_TRADE_HDR.size + 1}+{vlen} > {plen}"
        )
    venue = bytes(buf[vlen_off + 1:vlen_off + 1 + vlen]).decode("utf-8")
    return events.Trade(ts_ns=ts_ns, price=price, size=size,
                        side=side, side_src=side_src, venue=venue)


def _dec_bbo(buf: bytes, off: int, plen: int) -> events.BBO:
    if plen != _BBO.size:
        raise ValueError(f"BBO payload_len mismatch: {plen} != {_BBO.size}")
    ts_ns, bid_px, bid_sz, ask_px, ask_sz = _BBO.unpack_from(buf, off)
    return events.BBO(ts_ns=ts_ns, bid_px=bid_px, bid_sz=bid_sz, ask_px=ask_px, ask_sz=ask_sz)


def _dec_ping(buf: bytes, off: int, plen: int) -> events.Ping:
    if plen != _PING.size:
        raise ValueError(f"PING payload_len mismatch: {plen} != {_PING.size}")
    (server_send_ns,) = _PING.unpack_from(buf, off)
    return events.Ping(server_send_ns=server_send_ns)


def _dec_pong(buf: bytes, off: int, plen: int) -> events.Pong:
    if plen != _PONG.size:
        raise ValueError(f"PONG payload_len mismatch: {plen} != {_PONG.size}")
    echo_ns, client_recv_ns = _PONG.unpack_from(buf, off)
    return events.Pong(echo_ns=echo_ns, client_recv_ns=client_recv_ns)


def _dec_history(buf: bytes, off: int, plen: int) -> events.HistoryResponse:
    if plen < _HIST_HDR.size:
        raise ValueError(f"HISTORY_RESP payload too short: {plen} < {_HIST_HDR.size}")
    req_id, epoch, oldest, n_depth, n_bar, n_marker, n_trade = _HIST_HDR.unpack_from(buf, off)
    cursor = off + _HIST_HDR.size
    end = off + plen
    groups: list[list] = []
    for count, expected in ((n_depth, events.DepthColumn), (n_bar, events.BarColumn),
                            (n_marker, events.Marker), (n_trade, events.Trade)):
        group = []
        for _ in range(count):
            # Bail BEFORE decoding: a lying count must not consume messages
            # that belong to the surrounding frame.
            if cursor + _ENVELOPE.size > end:
                raise ValueError(
                    "HistoryResponse: nested counts overrun payload_len "
                    f"(cursor={cursor - off}, payload_len={plen})"
                )
            nested, cursor = decode(buf, cursor)
            if cursor > end:
                raise ValueError("HistoryResponse: nested message overruns payload_len")
            if not isinstance(nested, expected):
                raise ValueError(  # noqa: TRY004 — ValueError taxonomy is the wire contract
                    f"HistoryResponse: expected nested {expected.__name__}, "
                    f"got {type(nested).__name__}"
                )
            group.append(nested)
        groups.append(group)
    return events.HistoryResponse(req_id=req_id, epoch=epoch, oldest_available_t_ns=oldest,
                                  depth_cols=groups[0], bar_cols=groups[1],
                                  markers=groups[2], big_trades=groups[3])


# --- cold JSON encoders/decoders ------------------------------------------------

_COLD_ENCODERS: dict[type, Callable[[object], bytes]] = {
    events.Hello: lambda ev: _json_bytes(ev.to_json_dict()),
    events.EpochStart: lambda ev: _json_bytes(ev.to_json_dict()),
    events.Marker: lambda ev: _json_bytes(ev.to_json_dict()),
    events.Status: lambda ev: _json_bytes(ev.to_json_dict()),
    events.Subscribe: lambda ev: _json_bytes(ev.to_json_dict()),
    events.Unsubscribe: lambda ev: _json_bytes(ev.to_json_dict()),
    events.Seek: lambda ev: _json_bytes(ev.to_json_dict()),
    events.SetSpeed: lambda ev: _json_bytes(ev.to_json_dict()),
    events.Pause: lambda ev: _json_bytes(ev.to_json_dict()),
    events.Resume: lambda ev: _json_bytes(ev.to_json_dict()),
    events.HistoryRequest: lambda ev: _json_bytes(ev.to_json_dict()),
}

_COLD_DECODERS: dict[int, Callable[[dict], object]] = {
    MSG_HELLO: lambda d: _cold_hello(d),
    MSG_EPOCH_START: lambda d: _cold_epoch_start(d),
    MSG_MARKER: lambda d: _cold_marker(d),
    MSG_STATUS: lambda d: _cold_status(d),
    MSG_SUBSCRIBE: events.Subscribe.from_json_dict,
    MSG_UNSUBSCRIBE: lambda d: events.Unsubscribe(),
    MSG_SEEK: lambda d: _require(d, ("t",), events.Seek),
    MSG_SET_SPEED: lambda d: _require(d, ("x",), events.SetSpeed),
    MSG_PAUSE: lambda d: events.Pause(),
    MSG_RESUME: lambda d: events.Resume(),
    MSG_HISTORY_REQ: events.HistoryRequest.from_json_dict,
}


def _require(d: dict, keys: tuple[str, ...], cls: type) -> object:
    try:
        return cls(**{k: d[k] for k in keys})  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed {cls.__name__} payload: {exc}") from exc


def _cold_hello(d: dict) -> events.Hello:
    try:
        return events.Hello(
            protocol_version=int(d["protocol_version"]),
            session_id=str(d["session_id"]),
            grid_epoch=int(d["grid_epoch"]),
            epoch_params=events.EpochParams.from_json_dict(d["epoch_params"]),
            capability=dict(d["capability"]),
            norm_seed=float(d["norm_seed"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed Hello payload: {exc}") from exc


def _cold_epoch_start(d: dict) -> events.EpochStart:
    try:
        return events.EpochStart(
            epoch=int(d["epoch"]),
            epoch_params=events.EpochParams.from_json_dict(d["epoch_params"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed EpochStart payload: {exc}") from exc


def _cold_marker(d: dict) -> events.Marker:
    try:
        return events.Marker(
            ts_ns=int(d["ts_ns"]),
            kind=str(d["kind"]),
            text="" if d.get("text") is None else str(d["text"]),
            price=None if d.get("price") is None else float(d["price"]),
            size=None if d.get("size") is None else float(d["size"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed Marker payload: {exc}") from exc


def _cold_status(d: dict) -> events.Status:
    try:
        return events.Status(
            feed_state=str(d["feed_state"]),
            capability=dict(d["capability"]),
            latency_ms=float(d["latency_ms"]),
            clock_skew_ms=float(d["clock_skew_ms"]),
            next_open_ts=None if d.get("next_open_ts") is None else int(d["next_open_ts"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed Status payload: {exc}") from exc


# --- registries (table-driven dispatch) -----------------------------------------

_HOT_ENCODERS: dict[type, tuple[int, Callable]] = {
    events.DepthColumn: (MSG_DEPTH_COL, _enc_depth),
    events.BarColumn: (MSG_BAR_COL, _enc_bar),
    events.Trade: (MSG_TRADE, _enc_trade),
    events.BBO: (MSG_BBO, _enc_bbo),
    events.Ping: (MSG_PING, _enc_ping),
    events.Pong: (MSG_PONG, _enc_pong),
    events.HistoryResponse: (MSG_HISTORY_RESP, _enc_history),
}

_HOT_DECODERS: dict[int, Callable] = {
    MSG_DEPTH_COL: _dec_depth,
    MSG_BAR_COL: _dec_bar,
    MSG_TRADE: _dec_trade,
    MSG_BBO: _dec_bbo,
    MSG_PING: _dec_ping,
    MSG_PONG: _dec_pong,
    MSG_HISTORY_RESP: _dec_history,
}

_COLD_TYPES: dict[type, int] = {
    events.Hello: MSG_HELLO,
    events.EpochStart: MSG_EPOCH_START,
    events.Marker: MSG_MARKER,
    events.Status: MSG_STATUS,
    events.Subscribe: MSG_SUBSCRIBE,
    events.Unsubscribe: MSG_UNSUBSCRIBE,
    events.Seek: MSG_SEEK,
    events.SetSpeed: MSG_SET_SPEED,
    events.Pause: MSG_PAUSE,
    events.Resume: MSG_RESUME,
    events.HistoryRequest: MSG_HISTORY_REQ,
}

_COLD_BY_ID: dict[int, type] = {v: k for k, v in _COLD_TYPES.items()}


# --- public API -----------------------------------------------------------------


def encode(event) -> bytes:
    """Encode one event into a full message (envelope + payload + padding)."""
    kind = type(event)
    hot = _HOT_ENCODERS.get(kind)
    if hot is not None:
        msg_type, enc = hot
        return _frame(msg_type, enc(event))
    cold_enc = _COLD_ENCODERS.get(kind)
    if cold_enc is not None:
        return _frame(_COLD_TYPES[kind], cold_enc(event), flags=FLAG_JSON)
    raise TypeError(f"not a wire event: {kind.__name__}")


def decode(buf, offset: int = 0):
    """Decode one message at ``offset``; return ``(event, next_offset)``.

    Unknown msg_types are skipped via payload_len -> ``(None, next_offset)``.
    """
    if len(buf) - offset < _ENVELOPE.size:
        raise ValueError("truncated envelope")
    msg_type, ver, flags, plen = _ENVELOPE.unpack_from(buf, offset)
    if ver != PROTO_VER:
        raise ValueError(f"protocol version mismatch: got {ver}, expected {PROTO_VER}")
    payload_off = offset + _ENVELOPE.size
    if payload_off + plen > len(buf):
        raise ValueError("truncated payload")
    next_offset = payload_off + _ceil4(plen)
    if flags & FLAG_JSON:
        cold_cls = _COLD_BY_ID.get(msg_type)
        if cold_cls is None:
            return None, next_offset
        cold_dec = _COLD_DECODERS.get(msg_type)
        if cold_dec is None:  # pragma: no cover — table stays in sync
            return None, next_offset
        return cold_dec(_json_decode(buf[payload_off:payload_off + plen])), next_offset
    hot = _HOT_DECODERS.get(msg_type)
    if hot is None:
        return None, next_offset
    try:
        return hot(buf, payload_off, plen), next_offset
    except (struct.error, IndexError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed 0x{msg_type:02X} payload: {exc}") from exc


def payload_f32_offset(buf, offset: int = 0) -> int:
    """Absolute byte offset of the first f32 (bid[0]) of a DEPTH_COL message.

    Envelope (8) + fixed DEPTH_COL header (24) = message offset 32; used by
    tests to assert the 4-byte-alignment invariant for zero-copy client views.
    """
    msg_type, _ver, _flags, _plen = _ENVELOPE.unpack_from(buf, offset)
    if msg_type != MSG_DEPTH_COL:
        raise ValueError(f"not a DEPTH_COL message: 0x{msg_type:02X}")
    return offset + _ENVELOPE.size + _DEPTH_HDR.size


# --- golden vectors -------------------------------------------------------------


def golden_fixture_events() -> dict:
    """Fixed, representative events for cross-language golden-vector tests.

    Hard-coded constants mirrored 1:1 from the upstream reference
    (flowmap_server.proto.wire.golden_fixture_events): NO randomness, NO
    clock reads. The encoded bytes of each event are frozen under
    ``backend/tests/fixtures/flowmap/`` — the client and this server must
    both reproduce them byte-for-byte.
    """
    t0 = 1_752_710_400_000_000_000  # fixed ns timestamp (2025-07-17T00:00:00Z)

    depth_l2 = events.DepthColumn(
        epoch=3, col_seq=41, t0_ns=t0, mode=events.MODE_L2, final=True,
        bid=np.array([0.0, 1.5, 2.25, 3.0, 4.5, 5.75, 6.0, 7.125], dtype=np.float32),
        ask=np.array([8.0, 7.5, 6.25, 5.0, 4.5, 3.75, 2.0, 1.125], dtype=np.float32),
    )
    depth_l1_band = events.DepthColumn(
        epoch=3, col_seq=42, t0_ns=t0 + 250_000_000, mode=events.MODE_L1_BAND, final=False,
        bid=np.array([10.5, 11.25, 12.0, 13.5], dtype=np.float32),
        ask=np.array([9.0, 8.25, 7.5, 6.75], dtype=np.float32),
    )
    depth_synth = events.DepthColumn(
        epoch=4, col_seq=0, t0_ns=t0 + 500_000_000, mode=events.MODE_SYNTH_PROFILE, final=True,
        bid=np.array([0.125, 0.25, 0.5, 1.0, 2.0, 4.0], dtype=np.float32), ask=None,
    )
    bar = events.BarColumn(
        epoch=3, col_seq=41, t0_ns=t0,
        o=100.25, h=101.5, l=99.75, c=100.875,
        vol_buy=12.5, vol_sell=7.25, cvd_cum=5.25,
        vwap_num_cum=125031.25, vwap_den_cum=1250.0,
    )
    trade_exchange = events.Trade(
        ts_ns=t0 + 1_000, price=100.5, size=2.5,
        side=events.SIDE_BUY, side_src=events.SIDE_SRC_EXCHANGE, venue="binance",
    )
    trade_inferred = events.Trade(
        ts_ns=t0 + 2_000, price=100.25, size=0.75,
        side=events.SIDE_SELL, side_src=events.SIDE_SRC_INFERRED, venue="iex",
    )
    bbo = events.BBO(ts_ns=t0 + 3_000, bid_px=100.25, bid_sz=17.5, ask_px=100.5, ask_sz=4.25)
    ping = events.Ping(server_send_ns=t0 + 4_000)
    pong = events.Pong(echo_ns=t0 + 4_000, client_recv_ns=t0 + 5_000)
    marker = events.Marker(ts_ns=t0 + 6_000, kind="liquidation",
                           text="liq 2.5 @ 100.5", price=100.5, size=2.5)
    history = events.HistoryResponse(
        req_id=7, epoch=3, oldest_available_t_ns=t0 - 86_400_000_000_000,
        depth_cols=[depth_l2], bar_cols=[bar], markers=[marker], big_trades=[trade_exchange],
    )
    hello = events.Hello(
        protocol_version=PROTO_VER, session_id="golden-session-0001", grid_epoch=3,
        epoch_params=events.EpochParams(epoch=3, tick=0.01, tick_multiple=5,
                                        dt_ns=250_000_000, p0=100.0, rows=2048),
        capability={"depth": "L2", "trades": "full", "bbo": "native"},
        norm_seed=42.5,
    )
    # FROZEN. `source="crypcodile"` names an engine that no longer exists, and
    # `market="crypto"` is not a subscribable market string. Both are
    # deliberate: this vector exists to catch wire-format drift, and its value
    # comes from the bytes never changing. Treat the contents as opaque bytes.
    subscribe = events.Subscribe(market="crypto", symbol="BTCUSDT", mode="live",
                                 source="crypcodile", start_t=None)

    return {
        "hot_depth_col_l2": depth_l2,
        "hot_depth_col_l1_band": depth_l1_band,
        "hot_depth_col_synth_profile": depth_synth,
        "hot_bar_col": bar,
        "hot_trade_exchange": trade_exchange,
        "hot_trade_inferred": trade_inferred,
        "hot_bbo": bbo,
        "hot_ping": ping,
        "hot_pong": pong,
        "hot_history_resp_nested": history,
        "cold_hello": hello,
        "cold_subscribe": subscribe,
    }
