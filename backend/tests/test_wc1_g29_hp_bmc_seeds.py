"""WC1-G29 — HP and BMC seed/handler truth (HP#5, BMC#1, BMC#2).

No network: the HP seed is checked statically and the BMC handler is a
local static curriculum, so it runs offline.
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.misc._extras import BMCFunction
from showme.manifest.seeds.bmc_seed import bmc
from showme.manifest.seeds.hp_seed import hp

# Parameters the HP alias handler (server.py _execute_price_history_alias)
# reads, plus the ones the HP pane sends. Anything else declared in the seed
# is an input the handler never sees.
HP_HANDLER_PARAMS = {"symbol", "range", "interval", "days", "bars", "bar_count", "tail", "limit", "deep_history", "deep", "resolution"}

# Parameters the BMC handler reads (module filter); the pane sends none.
BMC_HANDLER_PARAMS = {"module"}


# ── HP#5 — seed inputs and methodology match the handler ─────────────────


def test_hp_seed_declares_no_input_the_handler_ignores() -> None:
    """The 'depth' select was never read by the handler or sent by the pane."""
    manifest = hp
    declared = {spec.name for spec in manifest.inputs}
    assert "depth" not in declared, "HP seed declares 'depth', which the handler never reads"
    assert "depth" not in manifest.defaults
    for test in manifest.semantic_tests:
        assert "depth" not in test.inputs, f"{test.name} feeds the ignored 'depth' input"


def test_hp_seed_declared_inputs_are_handled() -> None:
    """Every declared HP input is either read by the handler or a pane-only control."""
    pane_only = {"chart_style", "compare", "provider_mode"}
    declared = {spec.name for spec in hp.inputs}
    unknown = declared - HP_HANDLER_PARAMS - pane_only
    assert not unknown, f"HP seed declares inputs nothing reads: {sorted(unknown)}"


def test_hp_methodology_describes_the_real_race() -> None:
    """chart_history.fetch_longest_history races Yahoo, Binance (crypto) and Stooq (keyed)."""
    text = hp.methodology.lower()
    assert "yahoo" in text
    assert "binance" in text
    assert "stooq" in text
    assert "stooq_api_key" in text
    # coingecko is not a racer in fetch_longest_history; it is only a
    # fallback adapter in the alias, which the methodology must not present
    # as part of the deep race.
    assert "coingecko, then" not in text
    assert "depth" not in text


# ── BMC#1 — seed describes the handler's curriculum ──────────────────────


def test_bmc_seed_name_matches_the_handler() -> None:
    manifest = bmc
    assert manifest.name == BMCFunction.name == "Market Concepts Education"


def test_bmc_seed_declares_only_inputs_the_handler_reads() -> None:
    """layout/sources were declared but BMC returns identical rows for any value."""
    declared = {spec.name for spec in bmc.inputs}
    assert declared <= BMC_HANDLER_PARAMS, (
        f"BMC seed declares inputs the curriculum handler ignores: {sorted(declared - BMC_HANDLER_PARAMS)}"
    )


def test_bmc_seed_does_not_describe_kpi_tiles() -> None:
    manifest = bmc
    text = " ".join([manifest.intent, manifest.methodology]).lower()
    assert "kpi tile" not in text
    assert "watch" not in text
    assert "bot pnl" not in text


# ── BMC#2 — no constant progress field ───────────────────────────────────


def test_bmc_rows_carry_no_constant_progress_field() -> None:
    """Progress was always 'not_started'; completion is tracked in the pane."""
    result = asyncio.run(BMCFunction().execute())
    rows = result.data["rows"]
    assert rows, "curriculum must return lessons"
    assert all("progress" not in row for row in rows), (
        "BMC rows carry a constant 'progress' field that never reflects completion"
    )
