"""ECST compare overlay must not carry values onto dates they were not observed (G5 review).

The overlay merged main and compare frames with an outer join and then
``ffill().bfill()``. A monthly main series overlaid by a daily or longer compare
series therefore got its main value forward-filled onto dates with no main
observation, and leading compare-only dates got a back-filled main value. The
data policy forbids silent substitution, so an overlay row is emitted only for
a date on which the main series itself was observed, and ``compare_value`` only
where the compare series was observed on that date. All providers are patched;
no network is used.
"""

from __future__ import annotations

import asyncio
import math

import pandas as pd

import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps


def _run(coro):
    return asyncio.run(coro)


class _TwoSeriesFred:
    """Main series is monthly with a gap in February; compare is denser."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    async def series(self, sid, *args, **kwargs):
        return self.frames[sid].copy()

    async def info(self, sid):
        raise RuntimeError("info unavailable")


def _execute(monkeypatch, fred, **params):
    monkeypatch.setattr(
        ecst_mod, "fred_with_keyless_fallback", lambda deps_fred, client=None: fred
    )
    return _run(ecst_mod.ECSTFunction(FunctionDeps()).execute(**params))


def _frames() -> dict[str, pd.DataFrame]:
    main = pd.DataFrame(
        {"date": ["2026-01-01", "2026-03-01"], "value": [1.0, 3.0]}
    )
    compare = pd.DataFrame(
        {
            "date": ["2025-12-01", "2026-01-01", "2026-02-01", "2026-03-01"],
            "value": [10.0, 11.0, 12.0, 13.0],
        }
    )
    return {"MAINX": main, "CMPX": compare}


def test_overlay_emits_only_dates_the_main_series_observed(monkeypatch):
    result = _execute(
        monkeypatch,
        _TwoSeriesFred(_frames()),
        series_id="MAINX",
        compare_with="CMPX",
        date_range="MAX",
    )
    rows = result.data["rows"]
    dates = [row["date"] for row in rows]

    # 2025-12-01 (compare-only, leading) and 2026-02-01 (no main observation)
    # must not appear; the old bfill/ffill produced both with main values.
    assert dates == ["2026-01-01", "2026-03-01"], dates
    assert [row["value"] for row in rows] == [1.0, 3.0]
    assert "2026-02-01" not in dates


def test_overlay_compare_value_is_only_the_compare_observation(monkeypatch):
    result = _execute(
        monkeypatch,
        _TwoSeriesFred(_frames()),
        series_id="MAINX",
        compare_with="CMPX",
        date_range="MAX",
    )
    rows = result.data["rows"]

    assert [row["compare_value"] for row in rows] == [11.0, 13.0]
    for row in rows:
        assert isinstance(row["compare_value"], float)
        assert not math.isnan(row["compare_value"])
