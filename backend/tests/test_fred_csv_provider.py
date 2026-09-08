"""Keyless FRED fredgraph.csv provider (survey S2 c#3 / lane-A item 4).

Pins the shared ``showme.engine.functions._fred_csv`` module and its
wiring into GC3D / WB / CRVF / YAS / WACC:

* the CSV parser skips headers, ``.`` placeholders and malformed rows;
* ``fetch_fred_csv_series`` returns a date-indexed frame and caches it
  (TTL) — failures return ``None`` instead of raising;
* ``fred_with_keyless_fallback`` prefers the keyed adapter and otherwise
  hands back a shim exposing ``series``/``yield_curve``;
* functions wired with the shim are LIVE BY DEFAULT with no FRED_API_KEY
  (offline-deterministic via the ``_http_client`` injection seam) and
  degrade to honestly-labelled templates when the fetch fails.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions._fred_csv import (  # noqa: E402
    _KeylessFredCSV,
    _parse_csv_frame,
    fetch_fred_csv_series,
    fred_with_keyless_fallback,
    reset_fred_csv_cache,
)


_CSV_TEXT = "observation_date,value\n2026-09-01,4.10\n2026-09-02,.\n2026-09-03,4.30\nbroken-line\n2026-09-04,4.20\n"


class _FakeResp:
    def __init__(self, text: str = _CSV_TEXT):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, text: str = _CSV_TEXT, boom: bool = False):
        self._text = text
        self._boom = boom
        self.calls: list[str] = []

    async def get(self, url, timeout=None):
        self.calls.append(url)
        if self._boom:
            raise RuntimeError("offline")
        return _FakeResp(self._text)


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_fred_csv_cache()
    yield
    reset_fred_csv_cache()


def _run(coro):
    return asyncio.run(coro)


# ── parser ──────────────────────────────────────────────────────────────


def test_parse_csv_frame_skips_header_placeholders_and_garbage():
    frame = _parse_csv_frame(_CSV_TEXT)
    assert list(frame.columns) == ["value"]
    assert len(frame) == 3, "header, '.', and malformed rows must be dropped"
    assert frame["value"].iloc[-1] == 4.20


def test_parse_csv_frame_empty_input():
    assert _parse_csv_frame("").empty
    assert _parse_csv_frame("observation_date,value\n").empty


# ── fetch helper ────────────────────────────────────────────────────────


def test_fetch_fred_csv_series_returns_frame_and_caches():
    client = _FakeClient()
    frame = _run(fetch_fred_csv_series("DGS10", client=client))
    assert isinstance(frame, pd.DataFrame) and not frame.empty
    assert frame["value"].iloc[-1] == 4.20
    assert client.calls and "DGS10" in client.calls[0]
    # Second fetch inside the TTL window must not hit the network again.
    _run(fetch_fred_csv_series("DGS10", client=client))
    assert len(client.calls) == 1


def test_fetch_fred_csv_series_lookback_trims_and_rekeys_cache():
    today = datetime.now(timezone.utc).date()
    lines = [
        "observation_date,value",
        f"{today - timedelta(days=3)},4.10",
        f"{today - timedelta(days=1)},4.30",
        f"{today},4.20",
    ]
    client = _FakeClient(text="\n".join(lines))
    frame = _run(fetch_fred_csv_series("DGS10", client=client, lookback_days=1))
    assert len(frame) == 1, "only the trailing observations survive a 1-day lookback"
    assert frame["value"].iloc[-1] == 4.20


def test_fetch_fred_csv_series_failure_returns_none():
    client = _FakeClient(boom=True)
    assert _run(fetch_fred_csv_series("DGS10", client=client)) is None
    assert _run(fetch_fred_csv_series("", client=_FakeClient())) is None


# ── shim ────────────────────────────────────────────────────────────────


def test_fred_with_keyless_fallback_prefers_keyed_adapter():
    sentinel = object()
    assert fred_with_keyless_fallback(sentinel) is sentinel
    shim = fred_with_keyless_fallback(None)
    assert isinstance(shim, _KeylessFredCSV)


def test_shim_series_raises_on_failure():
    shim = _KeylessFredCSV(client=_FakeClient(boom=True))
    with pytest.raises(RuntimeError):
        _run(shim.series("DGS10"))


def test_shim_yield_curve_aggregates_tenors():
    text = "observation_date,value\n2026-09-04,4.30\n"
    shim = _KeylessFredCSV(client=_FakeClient(text=text))
    curve = _run(shim.yield_curve())
    assert set(curve) == set(shim._CURVE_IDS)
    assert all(v == 4.30 for v in curve.values())


# ── function wiring ─────────────────────────────────────────────────────


def test_gc3d_default_live_keyless_and_offline_fallback_labelled():
    from showme.engine.functions.bond.gc3d import GC3DFunctionLive

    online = GC3DFunctionLive(FunctionDeps())
    online._http_client = _FakeClient()
    result = _run(online.execute())
    assert result.sources == ["fred"]
    assert result.data["surface"], "live curve must produce surface rows"
    assert result.metadata.get("live") is True

    reset_fred_csv_cache()  # the offline branch must not read the TTL cache
    offline = GC3DFunctionLive(FunctionDeps())
    offline._http_client = _FakeClient(boom=True)
    result = _run(offline.execute())
    assert result.sources == ["yield_curve_model"]
    assert result.warnings, "template fallback must be labelled"


def test_gc3d_reference_true_serves_template_without_fetch():
    from showme.engine.functions.bond.gc3d import GC3DFunctionLive

    fn = GC3DFunctionLive(FunctionDeps())
    fn._http_client = _FakeClient(boom=True)
    result = _run(fn.execute(reference=True))
    assert result.sources == ["yield_curve_model"]


def test_wb_default_live_keyless_and_offline_fallback_labelled():
    from showme.engine.functions.bond.wb import WBFunction

    online = WBFunction(FunctionDeps())
    online._http_client = _FakeClient()
    result = _run(online.execute(countries="US,DE,JP"))
    assert result.sources == ["fred"]
    assert result.metadata.get("live") is True

    reset_fred_csv_cache()  # the offline branch must not read the TTL cache
    offline = WBFunction(FunctionDeps())
    offline._http_client = _FakeClient(boom=True)
    result = _run(offline.execute(countries="US,DE,JP"))
    assert result.sources == ["sovereign_yield_model"]
    assert result.warnings


def test_yas_benchmark_uses_keyless_csv_by_default():
    from showme.engine.functions.bond.yas import YASFunction

    fn = YASFunction(FunctionDeps())
    fn._http_client = _FakeClient()
    result = _run(fn.execute())
    assert "fred" in result.sources, "live 10Y benchmark must win over the static assumption"


def test_wacc_risk_free_uses_keyless_csv_without_api_key():
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.equity.wacc import WACCFunction

    fn = WACCFunction(FunctionDeps())
    fn._http_client = _FakeClient()
    result = _run(fn.execute(
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
        beta=1.1, market_cap=2.0e12, total_debt=1.0e11, tax_rate=0.15,
    ))
    assert "fred" in result.sources
    assert result.data["rf"] == pytest.approx(0.042, abs=1e-9)
