"""Wave-2 contract tests for the TRADE/EXECUTION + API/DEV seed family.

Covers 12 codes:

* Trade / execution → AIM, BBGT, EMSX, EXEC, FXGO, TCA, TSOX
* API / dev         → BQL, BQUANT, DAPI, FLDS, ISIN

Asserts each code is registered, classified correctly, and meets the
minimum shape the rebuild relies on (matching code, non-empty inputs,
methodology >= 50 chars, at least one semantic test). Pins the per-code
contracts the spec calls out explicitly:

* Order-ticket codes (AIM/BBGT/EMSX/FXGO/TSOX) must expose a required
  ``paper_mode`` boolean defaulting True — the safe-by-default guard.
* EXEC must declare ``LIVE_EXCHANGE`` and ``CACHED_SNAPSHOT`` as
  acceptable provider modes.
* ISIN must declare ``openfigi`` as its primary provider.
* BQL / BQUANT / DAPI / FLDS must declare ``internal`` as primary —
  these are editor / inspector surfaces, not provider-backed.
"""
from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, Category, ControlKind, DataMode, load_seeds


TRADE_CODES = ("AIM", "BBGT", "EMSX", "EXEC", "FXGO", "TCA", "TSOX")
API_CODES = ("BQL", "BQUANT", "DAPI", "FLDS", "ISIN")
ALL_CODES = TRADE_CODES + API_CODES

ORDER_TICKET_CODES = ("AIM", "BBGT", "EMSX", "FXGO", "TSOX")
INTERNAL_PRIMARY_CODES = ("BQL", "BQUANT", "DAPI", "FLDS")


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    """Populate REGISTRY before any wave-2 test runs."""
    load_seeds()


def test_every_wave2_code_is_registered() -> None:
    """All 12 wave-2 codes are reachable via the registry."""
    codes = set(REGISTRY.codes())
    missing = [c for c in ALL_CODES if c not in codes]
    assert not missing, f"wave-2 manifest seeds not registered: {missing}"


@pytest.mark.parametrize("code", ALL_CODES)
def test_wave2_manifest_meets_floor(code: str) -> None:
    """Every wave-2 seed honours the shape floor the rebuild relies on."""
    entry = REGISTRY.get(code)

    assert entry.code == code, f"{code}: manifest.code mismatch ({entry.code!r})"
    assert entry.inputs, f"{code}: inputs must be non-empty"
    methodology = entry.methodology or ""
    assert len(methodology) >= 50, (
        f"{code}: methodology must be at least 50 chars (got {len(methodology)})"
    )
    assert entry.semantic_tests, f"{code}: semantic_tests must be non-empty"


@pytest.mark.parametrize("code", TRADE_CODES)
def test_trade_seed_classified_under_trade_execution(code: str) -> None:
    """Trade-family codes belong to Category.TRADE_EXECUTION."""
    entry = REGISTRY.get(code)
    assert entry.category == Category.TRADE_EXECUTION, (
        f"{code}: category must be TRADE_EXECUTION, got {entry.category!r}"
    )


@pytest.mark.parametrize("code", API_CODES)
def test_api_seed_classified_under_api_dev(code: str) -> None:
    """API/dev-family codes belong to Category.API_DEV."""
    entry = REGISTRY.get(code)
    assert entry.category == Category.API_DEV, (
        f"{code}: category must be API_DEV, got {entry.category!r}"
    )


@pytest.mark.parametrize("code", ORDER_TICKET_CODES)
def test_order_ticket_paper_mode_required_and_default_true(code: str) -> None:
    """Order-ticket codes must expose paper_mode as a required bool defaulting True."""
    entry = REGISTRY.get(code)
    paper_inputs = [i for i in entry.inputs if i.name == "paper_mode"]
    assert paper_inputs, f"{code}: must expose a 'paper_mode' input"
    paper = paper_inputs[0]
    assert paper.control == ControlKind.BOOLEAN, (
        f"{code}: paper_mode control must be BOOLEAN, got {paper.control!r}"
    )
    assert paper.required is True, (
        f"{code}: paper_mode must be required=True (safe-by-default rebuild contract)"
    )
    assert entry.defaults.get("paper_mode") is True, (
        f"{code}: defaults['paper_mode'] must be True, got {entry.defaults.get('paper_mode')!r}"
    )


def test_isin_primary_provider_is_openfigi() -> None:
    """ISIN must pin OpenFIGI as primary so the rebuild can't swap in a heuristic."""
    entry = REGISTRY.get("ISIN")
    assert entry.provider_chain.primary == "openfigi", (
        f"ISIN.provider_chain.primary must be 'openfigi', got "
        f"{entry.provider_chain.primary!r}"
    )


def test_exec_declares_live_and_cached_modes() -> None:
    """EXEC must accept LIVE_EXCHANGE and CACHED_SNAPSHOT modes per spec."""
    entry = REGISTRY.get("EXEC")
    modes = set(entry.provider_chain.acceptable_modes)
    required = {DataMode.LIVE_EXCHANGE, DataMode.CACHED_SNAPSHOT}
    missing = required - modes
    assert not missing, (
        f"EXEC.provider_chain.acceptable_modes missing required modes: {missing}; got {modes}"
    )


@pytest.mark.parametrize("code", INTERNAL_PRIMARY_CODES)
def test_internal_surface_primary_is_internal(code: str) -> None:
    """BQL/BQUANT/DAPI/FLDS are editor/inspector surfaces — primary must be 'internal'."""
    entry = REGISTRY.get(code)
    assert entry.provider_chain.primary == "internal", (
        f"{code}.provider_chain.primary must be 'internal' (editor/inspector surface), got "
        f"{entry.provider_chain.primary!r}"
    )


def test_bquant_acceptable_modes_include_not_configured() -> None:
    """BQUANT must honestly declare NOT_CONFIGURED so the UI can render the absence of Jupyter."""
    entry = REGISTRY.get("BQUANT")
    assert DataMode.NOT_CONFIGURED in entry.provider_chain.acceptable_modes, (
        "BQUANT must include DataMode.NOT_CONFIGURED in acceptable_modes — it cannot "
        "claim execution readiness without a mounted Jupyter runtime."
    )


def test_tca_exposes_benchmark_choice() -> None:
    """TCA needs the benchmark input (VWAP/TWAP/Arrival/Implementation Shortfall)."""
    entry = REGISTRY.get("TCA")
    benchmark_inputs = [i for i in entry.inputs if i.name == "benchmark"]
    assert benchmark_inputs, "TCA must expose a 'benchmark' input"
    options = set(benchmark_inputs[0].options or [])
    required_choices = {"VWAP", "TWAP", "ARRIVAL", "IMPLEMENTATION_SHORTFALL"}
    missing = required_choices - options
    assert not missing, (
        f"TCA.benchmark must offer VWAP/TWAP/ARRIVAL/IMPLEMENTATION_SHORTFALL; missing {missing}"
    )
