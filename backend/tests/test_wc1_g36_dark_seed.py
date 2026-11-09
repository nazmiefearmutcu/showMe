"""wc1-g36 DARK#3: the DARK seed must describe the real handler.

The seed methodology claimed a yfinance-only model fallback that the handler
never runs, used a lit+ATS denominator the handler does not use, and listed
yfinance as the primary provider while the handler reads FINRA first.
"""

from __future__ import annotations

from showme.manifest import REGISTRY, load_seeds


def _seed():
    load_seeds()
    return REGISTRY.get("DARK")


def test_dark_seed_methodology_does_not_claim_a_model_fallback() -> None:
    seed = _seed()
    text = seed.methodology.lower()
    assert "falls back to a model" not in text
    assert "estimates dark-pool" not in text
    assert "off-exchange yfinance volume buckets" not in text


def test_dark_seed_methodology_states_the_real_denominator() -> None:
    seed = _seed()
    # The handler divides by total (consolidated) weekly volume, not lit+ATS.
    assert "total weekly volume" in seed.methodology.lower()
    assert "lit + ats" not in seed.methodology.lower()


def test_dark_seed_primary_provider_is_finra() -> None:
    seed = _seed()
    assert seed.provider_chain.primary == "finra"
    assert "yfinance" not in seed.provider_chain.fallbacks




# ---------------------------------------------------------------- DARK#3 (residuals)


def test_dark_seed_docstring_does_not_describe_a_lit_market_fallback() -> None:
    import showme.manifest.seeds.dark_seed as dark_seed

    doc = (dark_seed.__doc__ or "").lower()
    assert "lit-market baseline" not in doc
    assert "when finra is unavailable" not in doc
    assert "provider_unavailable" in doc


def test_dark_seed_never_advertises_cached_snapshot() -> None:
    from showme.manifest.enums import DataMode

    seed = _seed()
    cached = DataMode.CACHED_SNAPSHOT.value
    acceptable = {getattr(m, "value", m) for m in seed.provider_chain.acceptable_modes}
    assert cached not in acceptable
    provider_mode = next(i for i in seed.inputs if i.name == "provider_mode")
    assert cached not in {getattr(o, "value", o) for o in (provider_mode.options or [])}
