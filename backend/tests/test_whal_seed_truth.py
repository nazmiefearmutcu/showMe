"""WHAL#6 — the manifest seed must describe what the handler actually ships.

The seed is what the catalogue shows. It must name the alert types the handler
emits, the SEC forms it reads (3, 4, 5, 13D, 13G; not 13F or 8-K), and the
crypto lookback behaviour (latest 1000 Binance trades, filtered to the window).
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
    r"13F",
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


def test_seed_describes_the_shipped_sec_form_set() -> None:
    methodology = whal.methodology
    for form in ("Forms 3, 4, 5", "13D", "13G"):
        assert form in methodology, f"methodology should name SEC {form}"


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
