"""WHAL#4 — severity must not come from an invented USD figure.

Price-impulse rows have no USD notional. The old code used abs(return%) x 1,000,000
as if it were dollars, so the same FX move changed rating whenever the user
changed Min USD. Severity for those rows now comes from the impulse versus the
recent median, which does not move with the threshold.
"""
from __future__ import annotations

import asyncio

import showme.engine.functions.misc.whal as whal_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc.whal import WHALFunction

HOUR = 3600


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


FIXED_START = 1_800_000_000.0  # fixed so both runs produce identical bar timestamps


def _fx_bars() -> list[dict]:
    start = FIXED_START
    # Small noise around 1.1000 with one 0.067% move, no volume.
    closes = [1.1000, 1.1001, 1.0999, 1.1000, 1.1001, 1.1000, 1.0999, 1.1000, 1.1001, 1.1000,
              1.1000, 1.1001, 1.0999, 1.1000, 1.1001, 1.1000, 1.0999, 1.1000, 1.1001, 1.1000,
              1.1000 * 1.00067, 1.1000, 1.1001, 1.1000]
    return [
        {"timestamp": _iso(start + i * 300), "open": c, "high": c, "low": c,
         "close": c, "volume": 0, "interval": "5m", "range": "5d"}
        for i, c in enumerate(closes)
    ]


async def _fx_bars_fetch(*_args, **_kwargs):
    return _fx_bars()


def _severity_map(threshold_usd: float) -> dict[tuple, str]:
    result = asyncio.run(WHALFunction(FunctionDeps()).execute(
        symbol="EURUSD", market="FX", threshold_usd=threshold_usd))
    return {(row.get("timestamp"), row.get("alert_type")): row.get("severity")
            for row in result.data["rows"]}


def test_fx_severity_does_not_change_with_min_usd(monkeypatch) -> None:
    monkeypatch.setattr(whal_mod, "_fetch_yahoo_bars", _fx_bars_fetch)
    at_one_million = _severity_map(1_000_000)
    at_hundred_k = _severity_map(100_000)
    assert at_one_million, "expected FX impulse rows"
    assert at_one_million.keys() == at_hundred_k.keys()
    assert at_one_million == at_hundred_k, "the rating moved with the USD threshold"
