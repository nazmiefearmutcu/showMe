"""BQL#4: a small caller limit is honoured, not silently raised to 10."""
from showme.engine.functions.api.bql import _limit_rows


def _rows(n):
    return [{"symbol": "AAPL", "date": f"2026-10-{i + 1:02d}", "close": float(i)} for i in range(n)]


def test_limit_below_ten_is_honoured() -> None:
    assert len(_limit_rows(_rows(30), 5)) == 5
    assert _limit_rows(_rows(30), 5)[-1]["close"] == 29.0  # newest rows kept


def test_bad_limit_uses_the_200_default_and_caps_at_1000() -> None:
    assert len(_limit_rows(_rows(300), "abc")) == 200
    assert len(_limit_rows(_rows(1200), 5000)) == 1000
