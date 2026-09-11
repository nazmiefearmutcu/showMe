"""F14 — seed-vs-handler truth resync (campaign 2026-09-11).

Pins that the rewritten manifest seeds describe what the SHIPPED handlers
actually do. Each assertion names the drift it closes so a future seed
edit that re-introduces a phantom contract fails loudly.
"""
from __future__ import annotations

from showme.manifest import REGISTRY, load_seeds


def _entry(code: str):
    load_seeds()
    return REGISTRY.get(code)


def _semantic_blob(entry) -> str:
    return " ".join(
        f"{t.name} {' '.join(t.assertions)}" for t in entry.semantic_tests
    )


def test_moss_seed_describes_shipped_most_volatile_handler() -> None:
    """MOSS seed is 'Most Volatile' (not the never-implemented 'Sectoral Movers')."""
    from showme.engine.functions.misc._bonus import MOSSFunction

    entry = _entry("MOSS")
    assert entry.name == MOSSFunction.name == "Most Volatile"
    keys = {c.key for c in entry.table_schema.columns}
    assert {"symbol", "asset_class", "vol_pct", "samples", "last_close", "start", "end"}.issubset(keys), keys
    blob = _semantic_blob(entry) + entry.methodology
    assert "provider_unavailable" in blob
    assert "modeled" in blob
    assert "moss_default_is_live_and_outage_is_labelled" in blob


def test_psc_seed_describes_shipped_position_sizing_handler() -> None:
    """PSC seed is 'Position Sizing Calculator' (not the phantom 'Price Scenario Center')."""
    from showme.engine.functions.portfolio.psc import PSCFunction

    entry = _entry("PSC")
    assert entry.name == PSCFunction.name == "Position Sizing Calculator"
    # The family contract keeps research surfaces paper-safe by default.
    assert entry.defaults.get("paper_mode") is True
    blob = _semantic_blob(entry) + entry.methodology
    assert "shares_equals_risk_dollars_over_unit_risk" in blob
    assert "entry == stop" in blob or "entry_equals_stop" in blob
    for field in ("shares", "risk_dollars", "kelly_fraction"):
        assert field in entry.output_contract.must_have


def test_lang_seed_matches_handler_supported_locale_set() -> None:
    """LANG seed is 'Language Switch' with the handler's 12 locales (not en/tr only)."""
    from showme.engine.functions.misc._extras import LANGFunction

    entry = _entry("LANG")
    assert entry.name == LANGFunction.name == "Language Switch"
    lang_input = next(i for i in entry.inputs if i.name == "lang")
    assert set(lang_input.options) == set(LANGFunction.SUPPORTED)
    assert "i18n" in entry.methodology.lower()
    blob = _semantic_blob(entry)
    assert "lang_unsupported_code_returns_input_error_with_warning" in blob


def test_cde_seed_describes_shipped_custom_data_fields_handler() -> None:
    """CDE seed is 'Custom Data Fields' with the F6 count-truth contract."""
    from showme.engine.functions.misc.cde import CDEFunction

    entry = _entry("CDE")
    assert entry.name == CDEFunction.name == "Custom Data Fields"
    action_input = next(i for i in entry.inputs if i.name == "action")
    assert set(action_input.options) == {"list", "add", "remove", "evaluate"}
    blob = _semantic_blob(entry) + entry.field_dict["count"].description
    assert "count_equals_len_store" in blob
    assert "not the returned row count" in entry.field_dict["count"].description


def test_greeks_seed_describes_params_driven_book_handler() -> None:
    """GREEKS seed is the params-driven positions book (no broker credential_id)."""
    from showme.engine.functions.portfolio.greeks import GREEKSFunction

    entry = _entry("GREEKS")
    assert entry.name == GREEKSFunction.name == "Portfolio Greeks"
    assert entry.provider_chain.primary == "internal"
    assert any(i.name == "positions" for i in entry.inputs)
    blob = _semantic_blob(entry) + entry.methodology
    assert "positions_is_list" in blob
    assert "input_required" in blob
    assert "credential_id" not in " ".join(i.name for i in entry.inputs)


def test_erev_seed_primary_is_finnhub_outage_contract_matches() -> None:
    """EREV is Finnhub-only; outage returns provider_unavailable + empty trend."""
    entry = _entry("EREV")
    assert entry.provider_chain.primary == "finnhub"
    blob = _semantic_blob(entry) + entry.methodology
    assert "trend_is_empty_array" in blob
    assert "4-week" not in entry.methodology


def test_ee_seed_primary_is_finnhub_and_placeholder_outage_is_pinned() -> None:
    """EE reads Finnhub first; the outage contract is the labelled placeholder row."""
    from showme.engine.functions.equity.ee import EEFunction

    entry = _entry("EE")
    assert entry.name == EEFunction.name == "Earnings & Estimates"
    assert entry.provider_chain.primary == "finnhub"
    assert any(i.name == "reference" for i in entry.inputs)
    assert not any(i.name == "live" for i in entry.inputs)
    blob = _semantic_blob(entry)
    assert "placeholder_row_source_mode_is_earnings_calendar_unavailable" in blob
    assert "rows_is_empty_array" not in blob
