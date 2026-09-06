"""Byte-truth tests for the FlowMap wire protocol (zone S).

The golden fixtures under ``tests/fixtures/flowmap/`` are copied verbatim from
``flowmap/client/tests/golden/*.bin`` (the client-side lockstep copies). The
server MUST encode the equivalent events byte-for-byte and decode them back.
"""
from __future__ import annotations

import pathlib
import struct

import numpy as np
import pytest

from showme.flowmap import events, wire

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "flowmap"


def _fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.bin").read_bytes()


def test_all_golden_fixtures_encode_byte_identical() -> None:
    """Every golden vector re-encodes 1:1 — the BYTE-TRUTH contract."""
    for name, ev in wire.golden_fixture_events().items():
        assert wire.encode(ev) == _fixture(name), f"golden mismatch: {name}"


def test_golden_fixture_directory_is_complete() -> None:
    expected = set(wire.golden_fixture_events())
    on_disk = {p.stem for p in FIXTURES.glob("*.bin")}
    assert expected <= on_disk, f"missing fixture copies: {sorted(expected - on_disk)}"


def test_cold_hello_decode_roundtrip() -> None:
    ev, offset = wire.decode(_fixture("cold_hello"), 0)
    assert isinstance(ev, events.Hello)
    assert ev.protocol_version == 1
    assert ev.session_id == "golden-session-0001"
    assert ev.grid_epoch == 3
    assert ev.epoch_params.epoch == 3
    assert ev.epoch_params.tick == pytest.approx(0.01)
    assert ev.epoch_params.tick_multiple == 5
    assert ev.epoch_params.dt_ns == 250_000_000
    assert ev.epoch_params.p0 == pytest.approx(100.0)
    assert ev.epoch_params.rows == 2048
    assert ev.capability == {"depth": "L2", "trades": "full", "bbo": "native"}
    assert ev.norm_seed == pytest.approx(42.5)
    # payload 246 -> padded 248; +8 envelope = 256 (frame is exactly consumed)
    assert offset == 256 == len(_fixture("cold_hello"))


def test_cold_subscribe_decode() -> None:
    ev, offset = wire.decode(_fixture("cold_subscribe"), 0)
    assert isinstance(ev, events.Subscribe)
    assert ev.market == "crypto"
    assert ev.symbol == "BTCUSDT"
    assert ev.mode == "live"
    assert ev.source == "crypcodile"
    assert ev.start_t is None
    assert ev.band is None
    assert offset == len(_fixture("cold_subscribe"))


def test_hot_depth_col_l2_decode() -> None:
    buf = _fixture("hot_depth_col_l2")
    ev, offset = wire.decode(buf, 0)
    assert isinstance(ev, events.DepthColumn)
    assert (ev.epoch, ev.col_seq) == (3, 41)
    assert ev.mode == events.MODE_L2
    assert ev.final is True
    assert ev.bid.dtype == np.float32
    assert np.allclose(ev.bid, [0.0, 1.5, 2.25, 3.0, 4.5, 5.75, 6.0, 7.125])
    assert np.allclose(ev.ask, [8.0, 7.5, 6.25, 5.0, 4.5, 3.75, 2.0, 1.125])
    assert offset == len(buf)
    # f32 data starts at message offset 32 and stays 4-byte aligned.
    assert wire.payload_f32_offset(buf) % 4 == 0
    assert wire.payload_f32_offset(buf) == 32


def test_hot_depth_col_synth_decode_has_no_ask() -> None:
    ev, _ = wire.decode(_fixture("hot_depth_col_synth_profile"), 0)
    assert isinstance(ev, events.DepthColumn)
    assert ev.mode == events.MODE_SYNTH_PROFILE
    assert ev.ask is None
    assert np.allclose(ev.bid, [0.125, 0.25, 0.5, 1.0, 2.0, 4.0])


def test_hot_bbo_decode() -> None:
    ev, _ = wire.decode(_fixture("hot_bbo"), 0)
    assert isinstance(ev, events.BBO)
    assert ev.bid_px == pytest.approx(100.25)
    assert ev.bid_sz == pytest.approx(17.5)
    assert ev.ask_px == pytest.approx(100.5)
    assert ev.ask_sz == pytest.approx(4.25)


def test_hot_ping_pong_decode() -> None:
    ping, _ = wire.decode(_fixture("hot_ping"), 0)
    assert isinstance(ping, events.Ping)
    pong, _ = wire.decode(_fixture("hot_pong"), 0)
    assert isinstance(pong, events.Pong)


def test_hot_bar_col_decode() -> None:
    ev, _ = wire.decode(_fixture("hot_bar_col"), 0)
    assert isinstance(ev, events.BarColumn)
    assert (ev.epoch, ev.col_seq, ev.o, ev.h, ev.l, ev.c) == (
        3, 41, 100.25, 101.5, 99.75, 100.875)
    assert (ev.vol_buy, ev.vol_sell, ev.cvd_cum) == (12.5, 7.25, 5.25)
    assert (ev.vwap_num_cum, ev.vwap_den_cum) == (125031.25, 1250.0)


def test_hot_history_resp_nested_decode() -> None:
    ev, offset = wire.decode(_fixture("hot_history_resp_nested"), 0)
    assert isinstance(ev, events.HistoryResponse)
    assert ev.req_id == 7
    assert ev.epoch == 3
    assert len(ev.depth_cols) == 1
    assert len(ev.bar_cols) == 1
    assert len(ev.markers) == 1
    assert len(ev.big_trades) == 1
    assert ev.markers[0].kind == "liquidation"
    assert offset == len(_fixture("hot_history_resp_nested"))


def test_decode_skips_unknown_msg_type_via_payload_len() -> None:
    inner = wire.encode(events.Ping(server_send_ns=7))
    unknown = struct.pack("<BBHI", 0x55, wire.PROTO_VER, 0, len(inner)) + inner
    ev, offset = wire.decode(unknown, 0)
    assert ev is None
    assert offset == len(unknown)


def test_batched_frame_decodes_sequentially() -> None:
    buf = wire.encode(events.Ping(server_send_ns=1)) + wire.encode(events.BBO(
        ts_ns=2, bid_px=1.0, bid_sz=2.0, ask_px=3.0, ask_sz=4.0,
    ))
    first, off1 = wire.decode(buf, 0)
    assert isinstance(first, events.Ping)
    second, off2 = wire.decode(buf, off1)
    assert isinstance(second, events.BBO)
    assert off2 == len(buf)


def test_version_mismatch_raises_value_error() -> None:
    bad = struct.pack("<BBHI", wire.MSG_PING, wire.PROTO_VER + 1, 0, 8) + b"\x00" * 8
    with pytest.raises(ValueError):
        wire.decode(bad, 0)


def test_truncated_envelope_and_payload_raise_value_error() -> None:
    with pytest.raises(ValueError):
        wire.decode(b"\x09\x01", 0)
    good = wire.encode(events.Ping(server_send_ns=1))
    with pytest.raises(ValueError):
        wire.decode(good[:-2], 0)


def test_decode_rejects_non_object_cold_payload() -> None:
    bad = struct.pack("<BBHI", wire.MSG_HELLO, wire.PROTO_VER, wire.FLAG_JSON, 2) + b"[]"
    with pytest.raises(ValueError):
        wire.decode(bad, 0)


def test_encode_rejects_non_event() -> None:
    with pytest.raises(TypeError):
        wire.encode(object())


def test_cold_status_and_marker_roundtrip() -> None:
    status = events.Status(
        feed_state="degraded", capability={"depth": "L2"}, latency_ms=1.5,
        clock_skew_ms=0.0,
    )
    dec, _ = wire.decode(wire.encode(status), 0)
    assert isinstance(dec, events.Status)
    assert dec.feed_state == "degraded"
    assert dec.capability == {"depth": "L2"}

    marker = events.Marker(ts_ns=99, kind="gap", text="seam")
    dec, _ = wire.decode(wire.encode(marker), 0)
    assert isinstance(dec, events.Marker)
    assert dec.kind == "gap"


def test_hot_trade_venue_roundtrip() -> None:
    trade = events.Trade(
        ts_ns=5, price=100.5, size=2.5, side=events.SIDE_BUY,
        side_src=events.SIDE_SRC_EXCHANGE, venue="binance",
    )
    dec, _ = wire.decode(wire.encode(trade), 0)
    assert dec == trade


def test_history_request_roundtrip() -> None:
    req = events.HistoryRequest(req_id=3, before_t=1_000, n_cols=64)
    dec, _ = wire.decode(wire.encode(req), 0)
    assert dec == req


def test_history_resp_nested_roundtrip() -> None:
    t0 = 1_000_000_000
    resp = events.HistoryResponse(
        req_id=7, epoch=3, oldest_available_t_ns=t0,
        depth_cols=[events.DepthColumn(
            epoch=3, col_seq=0, t0_ns=t0, mode=events.MODE_L2, final=True,
            bid=np.zeros(4, dtype=np.float32), ask=np.ones(4, dtype=np.float32),
        )],
        bar_cols=[events.BarColumn(
            epoch=3, col_seq=0, t0_ns=t0, o=1.0, h=2.0, l=0.5, c=1.5,
            vol_buy=1.0, vol_sell=2.0, cvd_cum=-1.0, vwap_num_cum=3.0, vwap_den_cum=3.0,
        )],
        markers=[events.Marker(ts_ns=t0, kind="gap")],
        big_trades=[],
    )
    dec, _ = wire.decode(wire.encode(resp), 0)
    assert isinstance(dec, events.HistoryResponse)
    assert dec.req_id == 7
    assert dec.depth_cols[0].col_seq == 0
    assert dec.bar_cols[0].c == pytest.approx(1.5)
    assert dec.markers[0].kind == "gap"
    assert dec.big_trades == []
