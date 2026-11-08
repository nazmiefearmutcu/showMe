"""EE#2 follow-up: the EE seed text must describe the shipped reference behaviour.

After d098e80 ``reference=true`` returns status ``empty`` with no rows. The seed
still advertised the removed ``earnings_calendar_model`` template with
``status=reference_model`` and ``data_mode=modeled``. These tests pin the
user-visible seed text to the shipped behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.manifest.seeds.ee_seed import ee  # noqa: E402

STALE_TOKENS = ("earnings_calendar_model", "reference_model", "data_mode=modeled", "labelled template", "labelled modeled template")


def _manifest():
    # ``@manifest()`` replaces the seed function with the FunctionManifest itself.
    return ee


def _reference_input():
    for spec in _manifest().inputs:
        if spec.name == "reference":
            return spec
    raise AssertionError("EE seed has no 'reference' input")


def test_reference_input_description_does_not_advertise_removed_template() -> None:
    desc = _reference_input().description.lower()
    for token in STALE_TOKENS:
        assert token.lower() not in desc, f"stale token {token!r} in reference description"
    assert "modeled" not in desc
    assert "empty" in desc or "no earnings figures" in desc


def test_methodology_does_not_advertise_removed_template() -> None:
    text = _manifest().methodology
    assert "earnings_calendar_model" not in text
    assert "status=reference_model" not in text
    assert "data_mode=modeled" not in text
    assert "status=empty" in text


def test_seed_header_does_not_advertise_removed_template() -> None:
    import showme.manifest.seeds.ee_seed as seed_module

    doc = (seed_module.__doc__ or "")
    assert "labelled template" not in doc
    assert "reference=true" in doc
