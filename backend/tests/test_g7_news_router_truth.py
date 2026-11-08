"""G7 news-router truth regressions: TLDR and SAT.

Network-free. Quote, news, calendar, LLM and GIBS/Open-Meteo calls are patched
the way the sibling tests patch them, so these pin the routed contract only.
"""

from __future__ import annotations

import asyncio

import pytest

from showme import server
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.news.tldr import TLDRFunction

PORTFOLIO_SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY", "TLT", "GLD", "BTC-USD"]
PEER_GROUP = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


class _FakeInstrument:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


class _FakePosition:
    def __init__(self, symbol: str) -> None:
        self.instrument = _FakeInstrument(symbol)


class _FakePortfolio:
    symbols: list[str] = list(PORTFOLIO_SYMBOLS)

    def __init__(self, *args, **kwargs) -> None:
        self.positions = [_FakePosition(s) for s in type(self).symbols]

    def import_legacy_crypto(self, *args, **kwargs) -> int:
        return 0


def _patch_offline(monkeypatch) -> None:
    """Patch every network-backed dependency of TLDR to fail or answer locally."""
    import showme.engine.agents.llm_router as llm_mod
    import showme.engine.functions.macro.eco as eco_mod
    import showme.engine.functions.news.top as top_mod
    import showme.engine.portfolio.state as state_mod
    import showme.quotes as quotes_mod

    async def _quote(symbol: str):
        return {"symbol": symbol, "last": 100.0, "previous_close": 100.0,
                "change_pct": 0.0, "source": "test_snapshot"}

    async def _offline(self, *args, **kwargs):
        raise RuntimeError("offline in test")

    monkeypatch.setattr(quotes_mod, "fetch_quote_snapshot", _quote)
    monkeypatch.setattr(state_mod, "PortfolioState", _FakePortfolio)
    monkeypatch.setattr(top_mod.TOPFunction, "execute", _offline)
    monkeypatch.setattr(eco_mod.ECOFunction, "execute", _offline)
    monkeypatch.setattr(llm_mod.LLMRouter, "complete", _offline)


def _tldr_index(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [server.FunctionIndexEntry(code="TLDR", name="Daily TL;DR", category="news", asset_classes=[])],
    )


def test_tldr_default_route_does_not_inject_peer_symbols(monkeypatch) -> None:
    """TLDR#1: the routed layer must not turn the agent peer group into the
    user's watchlist when the caller sent no symbols."""
    _tldr_index(monkeypatch)
    routed = server._route_function_params("TLDR", {})
    assert not routed.get("symbols"), f"peer group injected: {routed.get('symbols')}"


def test_tldr_routed_default_summarises_portfolio_not_peer_group(monkeypatch) -> None:
    """TLDR#1 end to end: the default routed call must describe the portfolio."""
    _patch_offline(monkeypatch)
    _FakePortfolio.symbols = list(PORTFOLIO_SYMBOLS)
    _tldr_index(monkeypatch)
    routed = server._route_function_params("TLDR", {})
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(**routed))
    assert result.data["watchlist"] == PORTFOLIO_SYMBOLS
    assert not set(result.data["watchlist"]) & set(PEER_GROUP)


def test_tldr_explicit_symbols_still_win_over_portfolio(monkeypatch) -> None:
    _patch_offline(monkeypatch)
    _FakePortfolio.symbols = list(PORTFOLIO_SYMBOLS)
    _tldr_index(monkeypatch)
    routed = server._route_function_params("TLDR", {"symbols": ["MSFT", "AAPL"]})
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(**routed))
    assert result.data["watchlist"] == ["MSFT", "AAPL"]


def test_tldr_empty_portfolio_has_no_invented_watchlist(monkeypatch) -> None:
    """With no positions and no symbols the handler must not substitute a
    hard-coded list (AAPL/MSFT/TSLA/BTCUSDT/EURUSD/DGS10)."""
    _patch_offline(monkeypatch)
    _FakePortfolio.symbols = []
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute())
    assert result.data["watchlist"] == []
    assert result.data["status"] == "provider_unavailable"


def _patch_news_calendar(monkeypatch, top, eco) -> None:
    """Replace TOP and ECO with canned results (or exceptions)."""
    import showme.engine.functions.macro.eco as eco_mod
    import showme.engine.functions.news.top as top_mod

    def _make(value):
        async def _execute(self, *args, **kwargs):
            if isinstance(value, Exception):
                raise value
            return value

        return _execute

    monkeypatch.setattr(top_mod.TOPFunction, "execute", _make(top))
    monkeypatch.setattr(eco_mod.ECOFunction, "execute", _make(eco))


def _top_ok():
    from showme.engine.core.base_function import FunctionResult

    return FunctionResult(
        code="TOP", instrument=None,
        data={"items": [{"title": "Fed holds rates"}, {"title": "Chip rally"}], "alerts": [], "status": "ok"},
        sources=["rss"],
    )


def _eco_ok():
    from showme.engine.core.base_function import FunctionResult

    events = [{"event": "CPI", "country": "US"}, {"event": "Payrolls", "country": "US"}]
    return FunctionResult(
        code="ECO", instrument=None,
        data={"status": "ok", "events": events, "rows": events, "surface": [], "cards": []},
        sources=["forex_factory"],
    )


def test_tldr_dict_payloads_are_read_not_sliced(monkeypatch) -> None:
    """TLDR#3: TOP and ECO return dict envelopes; TLDR must read their rows
    instead of slicing the dict (which raised KeyError and emptied both lists)."""
    _patch_offline(monkeypatch)
    _patch_news_calendar(monkeypatch, _top_ok(), _eco_ok())
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(symbols=["MSFT"]))
    assert not [w for w in result.warnings if "slice" in w], result.warnings
    assert result.data["news"] == ["Fed holds rates", "Chip rally"]
    assert len(result.data["events"]) == 2
    markdown = result.data["markdown"]
    assert "Calendar items:** 2 scheduled" in markdown
    assert "Fed holds rates" in markdown


def test_tldr_failed_calendar_is_unavailable_not_zero(monkeypatch) -> None:
    """TLDR#3: a failed calendar call must not be reported as '0 scheduled'."""
    _patch_offline(monkeypatch)
    _patch_news_calendar(monkeypatch, _top_ok(), RuntimeError("eco timeout"))
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(symbols=["MSFT"]))
    markdown = result.data["markdown"]
    assert "0 scheduled" not in markdown
    assert "Calendar items:** unavailable" in markdown
    assert result.data["calendar_status"] == "unavailable"


def test_tldr_unavailable_news_is_labelled_not_blank(monkeypatch) -> None:
    from showme.engine.core.base_function import FunctionResult

    _patch_offline(monkeypatch)
    top_down = FunctionResult(
        code="TOP", instrument=None,
        data={"items": [], "alerts": [], "status": "provider_unavailable", "reason": "rss down"},
        sources=[],
    )
    _patch_news_calendar(monkeypatch, top_down, _eco_ok())
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(symbols=["MSFT"]))
    assert result.data["news_status"] == "unavailable"
    assert "**News themes:** unavailable" in result.data["markdown"]


# ── SAT ─────────────────────────────────────────────────────────────────────


def _png(width: int, height: int, rgb: tuple[int, int, int] | None) -> bytes:
    """Build an 8-bit RGBA PNG with filter-0 rows. rgb=None gives an all-black tile."""
    import struct
    import zlib

    r, g, b = rgb or (0, 0, 0)
    row = b"\x00" + bytes([r, g, b, 255]) * width
    raw = row * height

    def _chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


def _imagery_png() -> bytes:
    return _png(768, 768, (200, 180, 120))


def _blank_png() -> bytes:
    return _png(768, 768, None)


class _Resp:
    def __init__(self, status: int = 200, content: bytes = b"", payload=None, ctype: str = "image/png") -> None:
        self.status_code = status
        self.content = content
        self._payload = payload
        self.headers = {"content-type": ctype}
        self.text = ""

    def json(self):
        return self._payload


def _tile_index(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [server.FunctionIndexEntry(code="SAT", name="Satellite Imagery", category="misc", asset_classes=[])],
    )


def _patch_sat_http(monkeypatch, tile_for) -> list[str]:
    """Fake GIBS (tile_for(date) -> PNG bytes) and Open-Meteo. Returns the GIBS URLs requested."""
    import re

    import showme.engine.functions.misc.sat as sat_mod

    requested: list[str] = []

    async def _get(url, params=None):
        if "gibs.earthdata" in url:
            requested.append(url)
            day = re.search(r"TIME=([0-9-]+)", url).group(1)
            content = tile_for(day)
            if content is None:  # tile_for signals a transport failure for this day
                raise ConnectionError("connection reset")
            return _Resp(content=content)
        return _meteo_resp()

    monkeypatch.setattr(sat_mod, "_http_get_raw", _get)
    return requested


def _meteo_resp() -> _Resp:
    return _Resp(payload={
        "current": {"temperature_2m": 12.0, "cloud_cover": 40.0, "wind_speed_10m": 3.0, "weather_code": 1},
        "daily": {"cloud_cover_mean": [35.0], "temperature_2m_max": [15.0],
                  "temperature_2m_min": [5.0], "precipitation_sum": [0.0]},
    })


def test_sat_routed_default_does_not_pin_san_francisco_bbox(monkeypatch) -> None:
    """SAT#1: the routed layer must not inject the SF Bay bbox for every AOI."""
    _tile_index(monkeypatch)
    routed = server._route_function_params("SAT", {"aoi": "singapore_strait"})
    assert not routed.get("bbox"), f"routed bbox pinned: {routed.get('bbox')}"


def test_sat_selected_aoi_is_rendered_not_san_francisco(monkeypatch) -> None:
    """SAT#1 end to end: the selected AOI must drive the bbox, label and tile."""
    import showme.engine.functions.misc.sat as sat_mod

    _patch_sat_http(monkeypatch, lambda day: _imagery_png())
    _tile_index(monkeypatch)
    routed = server._route_function_params("SAT", {"aoi": "singapore_strait"})
    result = asyncio.run(sat_mod.SATFunction().execute(**routed))
    data = result.data
    assert data["aoi"] == "singapore_strait"
    assert data["aoi_label"] == "Singapore Strait"
    assert data["bbox"] == pytest.approx([103.5198, 0.95, 104.1198, 1.55])
    assert "BBOX=0.950000,103.519800,1.550000,104.119800" in data["tile_url"]


def _png_filtered(width: int, height: int, rgb_fn) -> bytes:
    """Reference PNG encoder that cycles through all five scanline filters."""
    import struct
    import zlib

    bpp = 4
    raw_rows: list[list[int]] = []
    for y in range(height):
        row: list[int] = []
        for x in range(width):
            r, g, b = rgb_fn(x, y)
            row.extend([r, g, b, 255])
        raw_rows.append(row)

    def _paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        return b if pb <= pc else c

    out = bytearray()
    stride = width * bpp
    for y, row in enumerate(raw_rows):
        ftype = y % 5
        out.append(ftype)
        prev = raw_rows[y - 1] if y else [0] * stride
        for i in range(stride):
            x = row[i]
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 0:
                pred = 0
            elif ftype == 1:
                pred = a
            elif ftype == 2:
                pred = b
            elif ftype == 3:
                pred = (a + b) // 2
            else:
                pred = _paeth(a, b, c)
            out.append((x - pred) & 0xFF)

    def _chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(out))) + _chunk(b"IEND", b""))


def test_png_decoder_counts_nonzero_rgb_across_all_filters() -> None:
    """SAT#2 support: the tile check must decode real PNG filters, not guess."""
    import showme.engine.functions.misc.sat as sat_mod

    pattern = lambda x, y: (200, 10, 5) if x < 8 else (0, 0, 0)  # noqa: E731
    png = _png_filtered(16, 10, pattern)
    fraction = sat_mod._png_nonzero_fraction(png)
    assert fraction == pytest.approx(0.5)
    assert sat_mod._png_nonzero_fraction(_png_filtered(16, 10, lambda x, y: (0, 0, 0))) == 0.0
    assert sat_mod._png_nonzero_fraction(b"not a png") is None


def test_sat_blank_todays_tile_walks_back_to_real_capture(monkeypatch) -> None:
    """SAT#2: an all-black GIBS tile for the requested day must not be shown
    as the latest capture; the newest real tile is used and its lag reported."""
    from datetime import datetime, timedelta, timezone

    import showme.engine.functions.misc.sat as sat_mod

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    blank_today = _blank_png()
    real = _imagery_png()
    _patch_sat_http(monkeypatch, lambda day: blank_today if day == today.isoformat() else real)
    result = asyncio.run(sat_mod.SATFunction().execute(aoi="cushing_ok", layer="true_color"))
    data = result.data
    assert data["capture_date"] == yesterday, data["capture_date"]
    assert data["capture_lag_days"] == 1
    assert data["status"] == "partial"
    assert f"TIME={yesterday}" in data["tile_url"]
    assert data["cards"][0]["latest_capture"] == yesterday
    assert data["rows"][0]["capture_utc"] == yesterday


def test_sat_blank_today_and_unreachable_yesterday_claims_no_capture(monkeypatch) -> None:
    """SAT#2 mixed case: today's tile is verified blank and yesterday's probe
    failed. Neither is imagery, so no capture date may be attributed (today's
    blank tile must not be shown as latest_capture)."""
    from datetime import datetime, timedelta, timezone

    import showme.engine.functions.misc.sat as sat_mod

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    blank = _blank_png()
    _patch_sat_http(monkeypatch, lambda day: None if day == yesterday else blank)
    result = asyncio.run(sat_mod.SATFunction().execute(aoi="cushing_ok", layer="true_color"))
    data = result.data
    assert data["status"] == "provider_unavailable", data["status"]
    assert data["cards"] == []
    assert data["rows"] == []
    assert not result.data.get("tile_url")
    assert any(check["date"] == today.isoformat() and check["state"] == "blank" for check in data["tile_checks"])


def test_sat_tile_lookup_timeout_claims_no_capture(monkeypatch) -> None:
    """SAT#2 timeout path: when the GIBS lookup times out nothing was verified,
    so the requested day must not be presented as the latest capture."""
    import showme.engine.functions.misc.sat as sat_mod

    monkeypatch.setattr(sat_mod, "_TILE_RESOLVE_TIMEOUT", 0.05)

    async def _slow_get(url, params=None):
        if "gibs.earthdata" in url:
            await asyncio.sleep(2.0)
            return _Resp(content=_imagery_png())
        return _meteo_resp()

    monkeypatch.setattr(sat_mod, "_http_get_raw", _slow_get)
    result = asyncio.run(sat_mod.SATFunction().execute(aoi="cushing_ok", layer="true_color"))
    data = result.data
    assert data["status"] == "provider_unavailable", data["status"]
    assert data["cards"] == []
    assert data["rows"] == []
    assert "exceeded" in data["reason"]


def test_sat_all_blank_tiles_is_explicit_empty_state(monkeypatch) -> None:
    import showme.engine.functions.misc.sat as sat_mod

    _patch_sat_http(monkeypatch, lambda day: _blank_png())
    result = asyncio.run(sat_mod.SATFunction().execute(aoi="cushing_ok", layer="true_color"))
    data = result.data
    assert data["status"] == "empty"
    assert data["rows"] == []
    assert data["cards"] == []
    assert data["reason"]
    assert all(check["state"] == "blank" for check in data["tile_checks"])


def test_tldr_calendar_count_is_full_row_total_not_capped(monkeypatch) -> None:
    """TLDR#3 follow-up: the markdown count must be the real ECO row total.
    The listed events are capped for display, but a 12-row day is not '10 scheduled'."""
    from showme.engine.core.base_function import FunctionResult

    _patch_offline(monkeypatch)
    events = [{"event": f"Event {i}", "country": "US"} for i in range(12)]
    eco = FunctionResult(
        code="ECO", instrument=None,
        data={"status": "ok", "events": events, "rows": events, "surface": [], "cards": []},
        sources=["forex_factory"],
    )
    _patch_news_calendar(monkeypatch, _top_ok(), eco)
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(symbols=["MSFT"]))
    markdown = result.data["markdown"]
    assert "Calendar items:** 12 scheduled" in markdown, markdown
    assert "10 scheduled" not in markdown
    assert result.data["calendar_total"] == 12
    assert len(result.data["events"]) == 10


def test_sat_hanging_open_meteo_is_bounded_by_its_own_budget(monkeypatch) -> None:
    """SAT budget: the tile walk-back is bounded (10 s), and Open-Meteo runs after it.
    A hanging conditions call must not stack another 12 s on top and overrun the
    14 s router timeout; it is cut off and reported as an open_meteo warning."""
    import time

    import showme.engine.functions.misc.sat as sat_mod

    async def _get(url, params=None):
        if "gibs.earthdata" in url:
            return _Resp(content=_imagery_png())
        await asyncio.sleep(8.0)
        return _meteo_resp()

    monkeypatch.setattr(sat_mod, "_http_get_raw", _get)
    started = time.monotonic()
    result = asyncio.run(sat_mod.SATFunction().execute(aoi="cushing_ok", layer="true_color"))
    elapsed = time.monotonic() - started
    assert elapsed < 5.0, f"conditions call was not bounded: {elapsed:.1f}s"
    assert any("open_meteo" in w for w in result.warnings), result.warnings
