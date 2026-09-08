"""Default-polarity conformance for the 2026-09-08 flip bundle.

Survey S2 H-2/c#2: MOSS, CHGS, TRA, MARS, EVTS, EE, LITM, APPL, FTS, and
FLY used to be synthetic/template-by-default behind opt-in ``live=true``
flags while their siblings defaulted live. After the flip every one of
them attempts its LIVE provider path with NO parameters, and serves the
labelled template ONLY behind an explicit ``reference=true`` — any
upstream failure must degrade to an honestly-labelled fallback
(fallback metadata + warning), never a silent synthetic ``ok``.

All tests are offline: provider adapters are fakes, the ECO HTTP leg is
driven through the ``_http_client`` injection seam.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402

EQ = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _run(coro):
    return asyncio.run(coro)


def _ohlcv(days: int = 60, with_dividends: bool = False) -> pd.DataFrame:
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=days, freq="1D", tz="UTC")
    close = pd.Series([100.0 + i * 0.5 for i in range(days)], index=idx)
    frame = pd.DataFrame({"close": close})
    if with_dividends:
        frame["dividends"] = 0.0
    return frame


class _FakeYfinance:
    """Satisfies the OHLCV/REFDATA fetch shapes used by the flip bundle."""

    def __init__(self, result: Any = None, boom: bool = False):
        self._result = result
        self._boom = boom
        self.calls = 0

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self._boom:
            raise RuntimeError("yfinance down")
        return self._result


class _BoomClient:
    async def get(self, url, timeout=None):
        raise RuntimeError("no network in unit tests")


# ────────────────────────────────────────────────────────────────────────
# 1. Default (no params) must attempt live and degrade HONESTLY.
# ────────────────────────────────────────────────────────────────────────


def test_moss_default_is_live_not_template():
    result = _run(_moss().execute(universe=["AAPL"]))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False
    assert result.sources == ["no_live_source"]


def _moss():
    from showme.engine.functions.misc._bonus import MOSSFunction
    return MOSSFunction(FunctionDeps())


def test_chgs_default_defers_to_live_tech():
    from showme.engine.functions.misc._bonus import CHGSFunction
    result = _run(CHGSFunction(FunctionDeps()).execute(instrument=EQ))
    # TECH with no provider returns an empty envelope + warning — never
    # the fabricated template-01..10 OHLC rows.
    assert not result.data.get("rows"), "CHGS default must not serve chart template rows"
    assert result.warnings, "no-provider CHGS must warn"
    assert (result.metadata or {}).get("alias_of") == "TECH"


def test_tra_default_is_live_and_failure_is_labelled():
    from showme.engine.functions.portfolio._more import TRAFunction
    result = _run(TRAFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.sources == ["total_return_model"]
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False
    assert result.warnings, "template fallback must carry an explicit warning"
    assert "template" in " ".join(result.warnings).lower()


def test_mars_default_is_live_and_failure_is_labelled():
    from showme.engine.functions.portfolio._more import MARSFunction
    result = _run(MARSFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.sources == ["multi_asset_risk_model"]
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False
    assert result.warnings


def test_evts_default_is_live_attempt():
    from showme.engine.functions.news.evts import EVTSFunction
    result = _run(EVTSFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.data["status"] == "empty"
    assert result.data["rows"] == []
    assert result.metadata.get("live") is False
    assert result.metadata.get("fallback") is True


def test_ee_default_failure_is_labelled_placeholder():
    from showme.engine.functions.equity.ee import EEFunction
    result = _run(EEFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.warnings, "placeholder earnings row must be flagged"
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False
    rows = result.data["rows"]
    assert rows and rows[0]["source_mode"] == "earnings_calendar_unavailable"


def test_litm_default_failure_is_labelled():
    from showme.engine.functions.misc._bonus import LITMFunction
    result = _run(LITMFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.sources == ["litigation_monitor_model"]
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False
    assert result.warnings


def test_appl_default_failure_is_labelled():
    from showme.engine.functions.misc._bonus import APPLFunction
    result = _run(APPLFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.sources == ["taxonomy_model"]
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("live") is False
    assert result.warnings


def test_fts_default_failure_is_honest():
    from showme.engine.functions.equity.fts import FTSFunction
    result = _run(FTSFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.metadata.get("fallback") is True


def test_fly_default_failure_is_honest():
    from showme.engine.functions.misc._extras import FLYFunction
    result = _run(FLYFunction(FunctionDeps()).execute())
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.metadata.get("fallback") is True


def test_eco_default_failure_is_honest_empty_error():
    from showme.engine.functions.macro import eco as _eco_mod
    from showme.engine.functions.macro.eco import ECOFunction
    # The ForexFactory leg caches at module scope (30-min TTL); a full-suite
    # run can populate it before this test, which would bypass the boom
    # client entirely. Reset so the failure path is what's under test.
    _eco_mod._ff_cache["fetched_at"] = 0.0
    _eco_mod._ff_cache["rows"] = []
    fn = ECOFunction(FunctionDeps())
    fn._http_client = _BoomClient()
    result = _run(fn.execute(days=30))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.warnings


# ────────────────────────────────────────────────────────────────────────
# 2. reference=true opts back into the labelled template.
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "code",
    ["MOSS", "CHGS", "TRA", "MARS", "EVTS", "EE", "LITM", "APPL", "FTS", "FLY"],
)
def test_reference_true_never_claims_live(code: str):
    result = _run(_execute_reference(code))
    metadata = result.metadata or {}
    assert metadata.get("live") is not True, f"{code}: reference=true must not claim live"
    data_mode = str(metadata.get("data_mode") or (result.data or {}).get("data_mode") or "")
    assert data_mode in {"modeled", "reference", "empty"}, (
        f"{code}: reference payload data_mode {data_mode!r} is off-vocabulary"
    )


def _execute_reference(code: str):
    from showme.engine.functions.misc._bonus import APPLFunction, CHGSFunction, LITMFunction, MOSSFunction
    from showme.engine.functions.misc._extras import FLYFunction
    from showme.engine.functions.equity.ee import EEFunction
    from showme.engine.functions.equity.fts import FTSFunction
    from showme.engine.functions.macro.eco import ECOFunction
    from showme.engine.functions.news.evts import EVTSFunction
    from showme.engine.functions.portfolio._more import MARSFunction, TRAFunction

    makers = {
        "MOSS": lambda: MOSSFunction(FunctionDeps()).execute(universe=["AAPL"], reference=True),
        "CHGS": lambda: CHGSFunction(FunctionDeps()).execute(instrument=EQ, reference=True),
        "TRA": lambda: TRAFunction(FunctionDeps()).execute(instrument=EQ, reference=True),
        "MARS": lambda: MARSFunction(FunctionDeps()).execute(instrument=EQ, reference=True),
        "EVTS": lambda: EVTSFunction(FunctionDeps()).execute(instrument=EQ, reference=True),
        "EE": lambda: EEFunction(FunctionDeps()).execute(instrument=EQ, reference=True),
        "LITM": lambda: LITMFunction(FunctionDeps()).execute(instrument=EQ, reference=True),
        "APPL": lambda: APPLFunction(FunctionDeps()).execute(instrument=EQ, reference=True),
        "FTS": lambda: FTSFunction(FunctionDeps()).execute(instrument=EQ, reference=True),
        "FLY": lambda: FLYFunction(FunctionDeps()).execute(reference=True),
    }
    if code == "ECO":
        fn = ECOFunction(FunctionDeps())
        fn._http_client = _BoomClient()
        return fn.execute(reference=True)
    return makers[code]()


# ────────────────────────────────────────────────────────────────────────
# 3. Positive flips: with a mocked live provider the default IS live.
# ────────────────────────────────────────────────────────────────────────


def test_moss_default_live_with_mocked_provider():
    result = _run(_moss_with_provider().execute(universe=["AAPL"], limit=5))
    assert result.data["status"] == "ok"
    assert result.metadata.get("live") is True
    assert result.sources == ["yfinance"]
    assert result.data["rows"], "mocked provider must produce ranked rows"


def _moss_with_provider():
    from showme.engine.functions.misc._bonus import MOSSFunction
    return MOSSFunction(FunctionDeps(yfinance=_FakeYfinance(_ohlcv())))


def test_tra_default_live_with_mocked_provider():
    from showme.engine.functions.portfolio._more import TRAFunction
    fn = TRAFunction(FunctionDeps(yfinance=_FakeYfinance(_ohlcv(400, with_dividends=True))))
    result = _run(fn.execute(instrument=EQ))
    assert result.metadata.get("live") is True
    assert result.sources == ["yfinance"]
    assert not result.warnings
    assert result.data["n_observations"] > 100


def test_mars_default_live_with_mocked_provider():
    from showme.engine.functions.portfolio._more import MARSFunction
    fn = MARSFunction(FunctionDeps(yfinance=_FakeYfinance(_ohlcv(400))))
    result = _run(fn.execute(instrument=EQ, symbols=["AAPL"]))
    assert result.metadata.get("live") is True
    assert result.sources == ["yfinance"]
    assert result.data["factor_loadings"]


def test_evts_default_live_with_mocked_provider():
    from showme.engine.functions.news.evts import EVTSFunction
    today = datetime.now(timezone.utc).date()
    events = {"calendar": {"Next Earnings Date": today + timedelta(days=30)}}
    fn = EVTSFunction(FunctionDeps(yfinance=_FakeYfinance(events)))
    result = _run(fn.execute(instrument=EQ))
    assert result.data["status"] == "ok"
    assert result.data["rows"]
    assert result.metadata.get("live") is True
    assert result.sources == ["yfinance"]


def test_ee_default_live_with_mocked_provider():
    from showme.engine.functions.equity.ee import EEFunction

    class _Finnhub:
        async def _get(self, path: str, **kwargs: Any):
            return [
                {"period": "2026-Q2", "actual": 1.5, "estimate": 1.4, "surprisePercent": 7.1},
                {"period": "2026-Q1", "actual": 1.3, "estimate": 1.35, "surprisePercent": -3.7},
            ]

    result = _run(EEFunction(FunctionDeps(finnhub=_Finnhub())).execute(instrument=EQ))
    assert result.metadata.get("live") is True
    assert "finnhub" in result.sources
    assert result.data["rows"][0]["actual"] == 1.5


def test_appl_default_live_with_mocked_provider():
    from showme.engine.functions.misc._bonus import APPLFunction
    refdata = SimpleNamespace(
        sector="Technology", industry="Software", country="US",
        currency="USD", exchange="NMS",
    )
    fn = APPLFunction(FunctionDeps(yfinance=_FakeYfinance(refdata)))
    result = _run(fn.execute(instrument=EQ))
    assert result.metadata.get("live") is True
    assert result.sources == ["yfinance"]
    assert result.data["status"] == "ok"
    assert result.data["sector"] == "Technology"


def test_fts_default_live_with_mocked_provider():
    from showme.engine.functions.equity.fts import FTSFunction

    class _SecEfts:
        async def search(self, query: str, forms=None, start=None, end=None, limit: int = 50):
            return [{
                "company": "Apple Inc.",
                "form": "10-K",
                "filing_date": "2025-11-01",
                "snippet": "risk factors",
            }]

    result = _run(FTSFunction(FunctionDeps(sec_efts=_SecEfts())).execute(instrument=EQ))
    assert result.metadata.get("live") is True
    assert result.sources == ["sec_efts"]
    assert result.data["status"] == "ok"
    assert result.data["rows"][0]["company"] == "Apple Inc."


def test_fly_default_live_with_mocked_provider():
    from showme.engine.functions.misc._extras import FLYFunction

    class _OpenSky:
        async def fetch(self, *_args: Any, **_kwargs: Any):
            return {
                "time": 1760000000,
                "states": [[
                    "abc123", "THY123", "Turkey", 1760000000, 1760000000,
                    28.9, 41.2, 10000.0, False, 230.0, 90.0, 0.0, None,
                    10000.0, None, None, None,
                ]],
            }

    result = _run(FLYFunction(FunctionDeps(opensky=_OpenSky())).execute())
    assert result.data["status"] == "live"
    assert result.data["rows"][0]["callsign"] == "THY123"
    assert result.metadata.get("live") is True


def test_litm_default_live_with_mocked_cact():
    from showme.engine.core.base_function import FunctionResult
    from showme.engine.functions.misc._bonus import LITMFunction

    class _FakeCACT:
        def __init__(self, deps):
            self.deps = deps

        async def execute(self, instrument=None, **params):
            return FunctionResult(
                code="CACT", instrument=instrument,
                data={"events_8k": [{
                    "code": "1.03", "category": "bankruptcy",
                    "filing_date": "2026-08-01", "accession": "0001",
                    "document": "https://sec.gov/x",
                }]},
                sources=["sec_edgar"],
            )

    import showme.engine.functions.equity.cact as cact_mod
    original = cact_mod.CACTFunction
    cact_mod.CACTFunction = _FakeCACT
    try:
        result = _run(LITMFunction(FunctionDeps(sec_edgar=object())).execute(instrument=EQ))
    finally:
        cact_mod.CACTFunction = original
    assert result.data["status"] == "ok"
    assert result.data["rows"][0]["item_code"] == "1.03"
    assert "sec_edgar" in result.sources
