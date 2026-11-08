"""REGM seed-to-payload contract (p2a-g02 follow-up).

The seed promised a logistic feature model: a ``features`` array with Shapley
contributions, ``regime_label`` and ``data_mode`` outputs, z-score and logit
formulas, and semantic tests for them. ``regm.py`` computes none of that. It
returns a rule-based composite label, input_coverage and the four components.
Each promised key must be emitted, and no methodology may claim a model the
function does not run.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.macro.regm import REGMFunction  # noqa: E402
from showme.manifest.seeds.regm_seed import regm  # noqa: E402


class _FakeYFinance:
    """Deterministic benchmark fixture (seeded random walk), not live data."""

    async def fetch(self, request):  # noqa: ANN001 - fake seam
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(7)
        close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, size=300)))
        idx = pd.date_range(end="2026-09-20", periods=300, freq="D")
        return pd.DataFrame({"close": close}, index=idx)


class _Boom:
    async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
        raise RuntimeError("network down")


@pytest.fixture(scope="module")
def payload() -> dict:
    fn = REGMFunction(FunctionDeps(yfinance=_FakeYFinance()))
    fn._http_client = _Boom()
    return asyncio.run(fn.execute(symbol="SPY")).data


def test_output_contract_keys_are_emitted(payload: dict) -> None:
    missing = [k for k in regm.output_contract.must_have if k not in payload]
    assert not missing, missing


def test_card_slot_keys_are_emitted_top_level(payload: dict) -> None:
    missing = [s.key for s in regm.card_schema.slots if s.key not in payload]
    assert not missing, f"card slots with no payload producer: {missing}"


def test_field_dict_entries_are_emitted(payload: dict) -> None:
    current = payload["current"]
    for key in regm.field_dict:
        head, _, rest = key.partition(".")
        if head == "current":
            assert rest in current, key
        else:
            assert head in payload, key


def test_no_formula_describes_an_unrun_model() -> None:
    assert not regm.formula_dict, sorted(regm.formula_dict)


def test_semantic_tests_assert_only_emitted_behaviour() -> None:
    stale = ("zscore", "logit", "features", "data_mode", "contribution", "shapley")
    for test in regm.semantic_tests:
        text = f"{test.name} {test.description} {' '.join(test.assertions)}".lower()
        for word in stale:
            assert word not in text, (test.name, word)


def test_methodology_describes_only_the_model_that_runs() -> None:
    text = regm.methodology.lower()
    for claim in ("shapley", "logistic", "features array", "data_mode", "z-score"):
        assert claim not in text, claim


def test_intent_does_not_promise_a_feature_model() -> None:
    text = regm.intent.lower()
    for claim in ("ism", "credit spread", "real rate", "per-feature"):
        assert claim not in text, claim


def test_confidence_floor_label_is_not_confidence_named() -> None:
    floor = next(i for i in regm.inputs if i.name == "model_threshold")
    assert "confidence" not in floor.label.lower(), floor.label


@pytest.mark.parametrize("name", ["regime_taxonomy", "features", "window", "provider_mode"])
def test_unread_inputs_say_so(name: str) -> None:
    spec = next(i for i in regm.inputs if i.name == name)
    text = spec.description.lower()
    assert "not wired" in text or "not applied" in text, (name, spec.description)
