"""MARS#2 follow-up: factor and universe series are PRICE returns, not total returns.

The live series come from the chart `close` (events=div,splits, no adjclose), which
is dividend-unadjusted. Every MARS label, description and methodology string must
therefore say price return. Offline: no network, only static text is inspected.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _mars_seed():
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    return REGISTRY.get("MARS")


def _seed_texts(entry) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = [
        ("intent", entry.intent),
        ("methodology", entry.methodology),
    ]
    for test in entry.semantic_tests or []:
        texts.append((f"semantic_test.name:{test.name}", test.name))
        texts.append((f"semantic_test.description:{test.name}", test.description))
    return texts


def test_factor_meanings_say_price_return_not_total_return():
    from showme.engine.functions.portfolio._more import _factor_meaning

    for factor, ticker in {
        "MKT": "SPY", "SMB": "IWM", "HML": "VLUE",
        "MOM": "MTUM", "QMJ": "QUAL", "BAB": "USMV",
    }.items():
        meaning = _factor_meaning(factor)
        assert ticker in meaning
        assert "total return" not in meaning.lower(), meaning
        assert "price return" in meaning.lower(), meaning


def test_function_description_says_price_return_not_total_return():
    from showme.engine.functions.portfolio._more import MARSFunction

    desc = MARSFunction.description.lower()
    assert "total return" not in desc, MARSFunction.description
    assert "total-return" not in desc, MARSFunction.description
    assert "price-return" in desc or "price return" in desc, MARSFunction.description


def test_seed_text_never_claims_total_return_for_the_proxies():
    entry = _mars_seed()
    for where, text in _seed_texts(entry):
        lowered = text.lower()
        assert "total return" not in lowered, f"{where}: {text!r}"
        assert "total-return" not in lowered, f"{where}: {text!r}"
    assert any("price" in text.lower() for _, text in _seed_texts(entry)), "seed must name price return"
