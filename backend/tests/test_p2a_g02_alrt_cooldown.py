"""ALRT#7 — a cooldown that is not a whole number of seconds is never silently coerced.

Reviewer follow-up on p2a-g02: ``int()`` silently truncated 60.7 to 60 and
turned boolean True into 1. Both must now fall back to the default with a
warning that names the rejected value.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.engine.functions.misc.alrt import ALRTFunction, _parse_cooldown  # noqa: E402


@pytest.fixture
def alrt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yield tmp_path


@pytest.mark.parametrize("raw", [60.7, True, False, float("nan"), "60.7", "1e3"])
def test_non_integer_cooldown_falls_back_with_warning(raw) -> None:
    seconds, warning = _parse_cooldown(raw)
    assert seconds == 300, (raw, seconds)
    assert warning is not None and "300" in warning, warning


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(60, 60), (60.0, 60), ("60", 60), ("  120 ", 120), (0, 0)],
)
def test_whole_number_cooldown_is_accepted_silently(raw, expected) -> None:
    seconds, warning = _parse_cooldown(raw)
    assert seconds == expected
    assert warning is None


@pytest.mark.asyncio
async def test_add_with_fractional_cooldown_warns_and_stores_default(alrt_home: Path) -> None:
    res = await ALRTFunction().execute(action="add", condition="AAPL.price > 200", cooldown=60.7)
    assert res.data["cooldown_seconds"] == 300, res.data
    assert any("60.7" in w for w in res.warnings), res.warnings
