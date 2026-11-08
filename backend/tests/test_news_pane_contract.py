"""Cross-checks between the news panes (ui/src/functions) and the backend news functions and seeds.

Each pane option list is read from the pane source, so a pane offering an option the
backend does not accept (CRYPTO before its preset existed, TOP "low", NSE 90 days past
the awareness maximum, asset classes spelled "equity") fails here instead of silently
returning empty or clamped data.
"""

from __future__ import annotations

import re
from pathlib import Path

from showme.engine.functions.news.ni import TOPIC_PRESETS
from showme.manifest.seeds.ni_seed import ni as ni_manifest
from showme.manifest.seeds.nse_seed import nse as nse_manifest
from showme.manifest.seeds.top_seed import top as top_manifest

REPO = Path(__file__).resolve().parents[2]
FUNCTIONS = REPO / "ui" / "src" / "functions"


def _pane_array(file_name: str, const_name: str) -> list[str]:
    source = (FUNCTIONS / file_name).read_text(encoding="utf-8")
    match = re.search(rf"const\s+{const_name}\s*:\s*readonly\s+\w+\[\]\s*=\s*\[(.*?)\];", source, re.S)
    assert match, f"{const_name} not found in {file_name}"
    body = match.group(1)
    return re.findall(r'"([^"]+)"', body) or [part.strip() for part in body.split(",") if part.strip()]


def _pane_numbers(file_name: str, const_name: str) -> list[int]:
    source = (FUNCTIONS / file_name).read_text(encoding="utf-8")
    match = re.search(rf"const\s+{const_name}\s*:\s*readonly\s+number\[\]\s*=\s*\[(.*?)\];", source, re.S)
    assert match, f"{const_name} not found in {file_name}"
    return [int(part) for part in re.findall(r"\d+", match.group(1))]


def _input(manifest: object, name: str):  # type: ignore[no-untyped-def]
    return next(i for i in manifest.inputs if i.name == name)  # type: ignore[attr-defined]


def test_every_ni_pane_option_is_a_backend_preset() -> None:
    pane_topics = _pane_array("NI.tsx", "TOPIC_PRESETS")
    assert pane_topics, "NI pane offers no topics"
    missing = [t for t in pane_topics if t not in TOPIC_PRESETS]
    assert missing == [], f"NI pane offers topics the backend has no preset for: {missing}"


def test_ni_seed_options_match_the_backend_presets() -> None:
    seed_topics = _input(ni_manifest, "topic").options
    assert set(seed_topics) == set(TOPIC_PRESETS)
    assert _input(ni_manifest, "topic").options and ni_manifest.defaults["topic"] in TOPIC_PRESETS


def test_crypto_preset_is_offered_and_wired_to_the_taxonomy() -> None:
    assert "CRYPTO" in _pane_array("NI.tsx", "TOPIC_PRESETS")
    assert TOPIC_PRESETS["CRYPTO"] == {"topics": ["crypto_market"], "asset_classes": ["crypto"]}


def test_top_asset_class_options_are_the_seed_vocabulary() -> None:
    pane_assets = _pane_array("TOP.tsx", "ASSET_OPTIONS")
    seed_assets = set(_input(top_manifest, "asset_classes").options)
    non_all = [a for a in pane_assets if a != "all"]
    assert non_all, "TOP offers no asset classes"
    assert [a for a in non_all if a not in seed_assets] == []
    assert {"equities", "commodities", "indices", "credit"} <= set(non_all)


def test_top_quality_floor_options_are_premium_and_standard_only() -> None:
    pane_floors = _pane_array("TOP.tsx", "FLOOR_OPTIONS")
    assert set(pane_floors) == set(_input(top_manifest, "min_quality").options)
    assert "low" not in pane_floors


def test_nse_window_options_stay_within_the_awareness_maximum() -> None:
    windows = _pane_numbers("NSE.tsx", "HOUR_OPTIONS")
    maximum = _input(nse_manifest, "hours").max
    assert max(windows) <= maximum
    assert max(windows) == 1440 and maximum == 1440
