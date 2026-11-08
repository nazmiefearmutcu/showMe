"""WHAL#6 — the manifest seed must describe what the handler actually ships.

The seed is what the catalogue shows. It must name the alert types the handler
emits, the SEC forms the handler reads (the `interesting` set in whal.py: 3, 4,
5, 13F-HR, 13D, 13G; never 8-K), and the crypto lookback behaviour (latest 1000
Binance trades, filtered to the window).
"""
from __future__ import annotations

import re
from pathlib import Path

from showme.manifest.seeds.whal_seed import whal

HANDLER = Path(__file__).resolve().parents[1] / "showme" / "engine" / "functions" / "misc" / "whal.py"

HANDLER_ALERT_TYPES = (
    "crypto_large_trade",
    "crypto_top_trade",
    "crypto_trade",
    "large_volume_proxy",
    "liquidity_impulse_proxy",
    "top_volume_window",
    "top_impulse_window",
    "sec_ownership_filing",
)

STALE_TERMS = (
    r"\blarge_trade\b",
    r"\blarge_volume\b",
    r"\bsec_filing\b",
    r"\btop_holder\b",
    r"8-K",
    r"yfinance",
    r"cached_snapshot",
)


def _seed_text(manifest) -> str:
    parts = [manifest.intent, manifest.methodology]
    parts += [f"{k}: {v.description}" for k, v in manifest.field_dict.items()]
    parts += [inp.description or "" for inp in manifest.inputs]
    parts += [str(p) for p in manifest.provider_chain.fallbacks]
    return "\n".join(parts)


def test_handler_emits_the_alert_types_the_seed_names() -> None:
    source = HANDLER.read_text(encoding="utf-8")
    for alert_type in HANDLER_ALERT_TYPES:
        assert f'"{alert_type}"' in source, f"{alert_type} is no longer emitted by the handler"
    text = _seed_text(whal)
    for alert_type in HANDLER_ALERT_TYPES:
        assert alert_type in text, f"seed does not name the shipped alert type {alert_type}"


def test_seed_has_no_stale_taxonomy_or_sources() -> None:
    text = _seed_text(whal)
    for term in STALE_TERMS:
        assert not re.search(term, text), f"seed still describes {term}"


def _handler_sec_forms() -> set[str]:
    source = HANDLER.read_text(encoding="utf-8")
    match = re.search(r"interesting = \{([^}]*)\}", source)
    assert match, "whal.py no longer declares the SEC form set"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_seed_describes_the_shipped_sec_form_set() -> None:
    methodology = whal.methodology
    for form in ("Forms 3, 4, 5", "13D", "13G", "13F-HR"):
        assert form in methodology, f"methodology should name SEC {form}"


def test_every_sec_form_the_handler_reads_is_named_in_the_seed() -> None:
    methodology = whal.methodology
    for form in _handler_sec_forms():
        bare = form.replace("SC ", "")
        assert bare in methodology, f"handler reads SEC form {form} but the seed does not name {bare}"


def test_runtime_crypto_methodology_matches_the_shipped_rows() -> None:
    from showme.engine.functions.misc.whal import _methodology

    text = _methodology("CRYPTO")
    assert "latest 1000" in text, text
    assert "largest observed trade" not in text, text


def test_seed_states_the_crypto_lookback_limit() -> None:
    manifest = whal
    assert "latest 1000" in manifest.methodology, manifest.methodology
    lookback = next(inp for inp in manifest.inputs if inp.name == "lookback_hours")
    assert "latest" in (lookback.description or "").lower(), lookback.description


def test_all_providers_down_semantics_name_the_status_the_handler_emits() -> None:
    # The handler returns status "provider_unavailable" with rows []; it emits no
    # data_mode, so the seed must not describe a data_mode of "not_configured".
    test = next(t for t in whal.semantic_tests if t.name == "whal_explicit_unavailable_when_all_providers_down")
    text = "\n".join([test.description, *test.assertions])
    assert "data_mode" not in text, text
    assert "status_equals_provider_unavailable" in test.assertions
    assert "provider_unavailable" in test.description


def test_all_providers_down_returns_provider_unavailable_with_no_rows() -> None:
    import asyncio

    import httpx

    import showme.engine.functions.misc.whal as whal_mod

    class _Down:
        def __init__(self, *_a, **_k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            return None

        async def get(self, url, params=None, **_k):
            return httpx.Response(503, text="down", request=httpx.Request("GET", url))

    original = whal_mod.httpx.AsyncClient
    whal_mod.httpx.AsyncClient = _Down  # type: ignore[assignment]
    try:
        payload, _sources, warnings = asyncio.run(
            whal_mod._crypto_whales(
                symbol="BTCUSDT", threshold_usd=1_000_000.0, row_limit=25,
                trade_limit=1000, lookback_hours=24, timeout=3.0,
            )
        )
    finally:
        whal_mod.httpx.AsyncClient = original  # type: ignore[assignment]
    assert payload["status"] == "provider_unavailable"
    assert payload["rows"] == []
    assert any("binance" in w.lower() for w in warnings), warnings
