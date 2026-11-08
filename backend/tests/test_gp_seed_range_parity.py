"""GP range options match the pane (GP#8).

GP.tsx RANGES is 1M, 3M, 6M, 1Y, 5Y, MAX. The seed manifest is the contract,
so it must not advertise an option the pane cannot send.
"""
from __future__ import annotations

from showme.manifest.seeds.gp_seed import gp as gp_manifest


def test_gp_range_options_match_the_pane() -> None:
    range_input = next(i for i in gp_manifest.inputs if i.name == "range")
    assert list(range_input.options) == ["1M", "3M", "6M", "1Y", "5Y", "MAX"]


def test_gp_semantic_tests_only_use_offered_ranges() -> None:
    # A semantic test that names a range the pane cannot send exercises an
    # unknown option, not a real interval/range pairing.
    offered = set(next(i for i in gp_manifest.inputs if i.name == "range").options)
    for test in gp_manifest.semantic_tests:
        range_value = test.inputs.get("range")
        if range_value is not None:
            assert range_value in offered, (test.name, range_value)
