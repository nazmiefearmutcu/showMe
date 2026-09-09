"""REGM keyless curve wiring (2026-09-09): the 2s10s component comes alive
via the keyless FRED CSV shim when no keyed FRED adapter is configured.

Before this wiring the curve leg required ``deps.fred`` — the common
no-key deployment served ``curve="UNKNOWN"`` with a warning forever even
though fredgraph.csv serves DGS10/DGS2 keylessly (the same tier YAS and
CRVF already use). Offline-deterministic via the ``_http_client``
injection seam; the FRED CSV module cache is reset per test so battery
ordering can never short-circuit the fake client.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.functions._fred_csv import (  # noqa: E402
    reset_fred_csv_cache,
)


def _csv(last: str) -> str:
    return f"observation_date,value\n2026-09-01,4.00\n2026-09-02,{last}\n"


class _FakeResp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeFredClient:
    """Serves per-series fredgraph.csv payloads keyed off the URL."""

    def __init__(self, dgs10: str = "3.40", dgs2: str = "4.20"):
        self._dgs10 = _csv(dgs10)
        self._dgs2 = _csv(dgs2)
        self.calls: list[str] = []

    async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
        self.calls.append(str(url))
        if "DGS10" in str(url):
            return _FakeResp(self._dgs10)
        if "DGS2" in str(url):
            return _FakeResp(self._dgs2)
        raise AssertionError(f"unexpected FRED series requested: {url}")


@pytest.fixture(autouse=True)
def _clean_caches():
    reset_fred_csv_cache()
    yield
    reset_fred_csv_cache()


def test_regm_curve_alive_via_keyless_fred_when_no_keyed_adapter() -> None:
    from showme.engine.functions.macro.regm import REGMFunction

    fn = REGMFunction()
    fn._http_client = _FakeFredClient(dgs10="3.40", dgs2="4.20")
    out = asyncio.run(fn.execute(symbol="SPY", allow_model=True))

    # The regression fixture needs allow_model (no yfinance dep here); the
    # curve leg under test runs BEFORE the benchmark leg either way.
    current = out.data["current"]
    assert current.get("curve") == "INVERTED", (
        f"(3.40 - 4.20) * 100 = -80bp must classify INVERTED, got "
        f"{current.get('curve')!r}"
    )
    assert current.get("curve_2s10s_bp") == pytest.approx(-80.0)
    # The curve component is available, so the unavailability warning is gone.
    assert not any("curve" in w.lower() and "unknown" in w.lower() for w in out.warnings)


def test_regm_curve_falls_back_to_unknown_when_keyless_fails() -> None:
    from showme.engine.functions.macro.regm import REGMFunction

    class _BoomClient:
        async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
            raise RuntimeError("network down")

    fn = REGMFunction()
    fn._http_client = _BoomClient()
    out = asyncio.run(fn.execute(symbol="SPY", allow_model=True))

    current = out.data["current"]
    assert current.get("curve") == "UNKNOWN"
    assert any("curve" in w.lower() and "unknown" in w.lower() for w in out.warnings)
