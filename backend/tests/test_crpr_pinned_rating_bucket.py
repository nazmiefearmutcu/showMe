"""CRPR#7 — a caller-pinned rating carries the bucket implied by its own rating.

The override branch returned ``implied_bucket`` = ``params.get("bucket", "high_grade")``.
The seed also injects ``bucket=high_grade`` as a default, so a pinned CCC rating was
summarised as high grade. The bucket must come from the pinned S&P rating against
the same scale the model uses; when no S&P rating is pinned it is "n/a".
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.bond._stubs import CRPRFunction


def _run(**kwargs):
    return asyncio.run(CRPRFunction().execute(issuer="ACME", **kwargs))


@pytest.mark.parametrize(
    ("sp", "expected"),
    [
        ("AA+", "high_grade"),
        ("AA", "high_grade"),
        ("A-", "investment_grade"),
        ("BBB-", "investment_grade"),
        ("BB+", "crossover"),
        ("B", "high_yield"),
        ("CCC+", "distressed"),
        ("D", "distressed"),
    ],
)
def test_pinned_rating_bucket_follows_the_pinned_sp_rating(sp: str, expected: str) -> None:
    res = _run(rating={"sp": sp, "moodys": "n/a", "fitch": "n/a"})
    assert res.data["status"] == "ok", res.data
    assert res.data["summary"]["implied_bucket"] == expected, res.data["summary"]
    assert res.data["implied_bucket"] == expected


def test_seed_default_bucket_cannot_label_a_pinned_ccc_rating_as_high_grade() -> None:
    # The route injects the seed default bucket=high_grade; it must not decide the bucket.
    res = _run(rating={"sp": "CCC", "moodys": "Caa1", "fitch": "CCC"}, bucket="high_grade")
    assert res.data["summary"]["implied_bucket"] == "distressed", res.data["summary"]
    assert res.data["implied_bucket"] == "distressed"


def test_pinned_rating_without_an_sp_rating_has_no_bucket() -> None:
    res = _run(rating={"moodys": "Baa2", "fitch": "BBB"})
    assert res.data["summary"]["implied_bucket"] == "n/a", res.data["summary"]
    assert res.data["implied_bucket"] == "n/a"
    assert res.data["rows"][0]["rating"] is None
