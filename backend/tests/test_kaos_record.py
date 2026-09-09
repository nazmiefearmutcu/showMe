"""KAOS multibot record schema — engine + venues validation.

Zero regression: every record persisted before the ``engine`` field
defaults to engine="spec" / venues=[] and keeps the exact spec-rule path.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from showme.bots.kaos.config import (
    CRYPTO_DEFAULT_SYMBOLS,
    DEFAULT_VENUES,
    NASDAQ_DEFAULT_SYMBOLS,
)
from showme.bots.record import BotRecord, SignalEntry, VenueSpec
from showme.bots.store import BotMeta


def _record(**kw) -> BotRecord:
    base = {
        "strategy_id": "s1", "credential_id": "c1",
        "exchange_id": "binanceusdm", "symbol": "BTC/USDT",
    }
    base.update(kw)
    return BotRecord(**base)


# ---- defaults (zero regression) --------------------------------------------


def test_legacy_record_defaults_to_spec_engine():
    rec = _record()
    assert rec.engine == "spec"
    assert rec.venues == []


def test_legacy_json_without_engine_roundtrips_as_spec():
    rec = _record()
    data = rec.model_dump()
    data.pop("engine")
    data.pop("venues")
    rec2 = BotRecord(**data)
    assert rec2.engine == "spec"
    assert rec2.venues == []


def test_signal_entry_additive_fields_default_none():
    e = SignalEntry(bar_index=0, bar_time="t", kind="entry", price=1.0,
                    action="shadow")
    assert e.symbol is None
    assert e.venue_id is None
    assert e.side is None


# ---- venue schema ----------------------------------------------------------


def test_venue_spec_happy_path():
    v = VenueSpec(id="crypto", exchange_id="binanceusdm",
                  market="crypto-futures", symbols=["BTC/USDT:USDT"],
                  risk_profile="crypto")
    assert v.symbols == ["BTC/USDT:USDT"]


def test_venue_spec_rejects_unknown_market_and_profile():
    with pytest.raises(ValidationError):
        VenueSpec(id="x", exchange_id="e", market="lse", symbols=["A"])
    with pytest.raises(ValidationError):
        VenueSpec(id="x", exchange_id="e", market="crypto-futures",
                  symbols=["A"], risk_profile="gold")


def test_venue_spec_risk_profile_must_match_market():
    with pytest.raises(ValidationError, match="does not match"):
        VenueSpec(id="nasdaq", exchange_id="alpaca", market="us-equities",
                  symbols=["AAPL"], risk_profile="crypto")


def test_venue_spec_rejects_empty_and_duplicate_symbols():
    with pytest.raises(ValidationError):
        VenueSpec(id="x", exchange_id="e", market="crypto-futures", symbols=[])
    with pytest.raises(ValidationError):
        VenueSpec(id="x", exchange_id="e", market="crypto-futures",
                  symbols=["BTC", "BTC"])
    with pytest.raises(ValidationError):
        VenueSpec(id="x", exchange_id="e", market="crypto-futures",
                  symbols=[" "])


def test_kaos_record_requires_at_least_one_venue():
    with pytest.raises(ValidationError, match="at least one venue"):
        _record(engine="kaos")


def test_kaos_record_with_both_venues_is_valid():
    rec = _record(
        engine="kaos",
        venues=[
            {"id": "crypto", "exchange_id": "binanceusdm",
             "market": "crypto-futures",
             "symbols": ["BTC/USDT:USDT"], "risk_profile": "crypto"},
            {"id": "nasdaq", "exchange_id": "alpaca",
             "market": "us-equities", "symbols": ["AAPL"],
             "risk_profile": "equity"},
        ],
    )
    assert [v.id for v in rec.venues] == ["crypto", "nasdaq"]
    assert rec.model_dump()["engine"] == "kaos"


def test_record_rejects_duplicate_venue_ids():
    with pytest.raises(ValidationError, match="unique"):
        _record(
            engine="kaos",
            venues=[
                {"id": "crypto", "exchange_id": "binanceusdm",
                 "market": "crypto-futures", "symbols": ["BTC/USDT:USDT"],
                 "risk_profile": "crypto"},
                {"id": "crypto", "exchange_id": "binanceusdm",
                 "market": "crypto-futures", "symbols": ["ETH/USDT:USDT"],
                 "risk_profile": "crypto"},
            ],
        )


def test_spec_engine_rejects_unknown_engine_ids():
    with pytest.raises(ValidationError):
        _record(engine="gpt")


# ---- default universes (frozen CONTRACT seed) -------------------------------


def test_default_universes_shape():
    assert len(CRYPTO_DEFAULT_SYMBOLS) == 20
    assert len(NASDAQ_DEFAULT_SYMBOLS) == 20
    assert CRYPTO_DEFAULT_SYMBOLS[0] == "BTC/USDT:USDT"
    assert NASDAQ_DEFAULT_SYMBOLS[0] == "SPY"
    # ccxt linear-perp form everywhere on the crypto venue
    assert all(s.endswith(":USDT") and "/" in s
               for s in CRYPTO_DEFAULT_SYMBOLS)


def test_default_venues_match_contract_schema():
    ids = [v["id"] for v in DEFAULT_VENUES]
    assert ids == ["crypto", "nasdaq"]
    by_id = {v["id"]: v for v in DEFAULT_VENUES}
    assert by_id["crypto"]["exchange_id"] == "binanceusdm"
    assert by_id["crypto"]["market"] == "crypto-futures"
    assert by_id["nasdaq"]["exchange_id"] == "alpaca"
    assert by_id["nasdaq"]["market"] == "us-equities"
    assert by_id["nasdaq"]["risk_profile"] == "equity"


# ---- list metadata carries engine -------------------------------------------


def test_bot_meta_includes_engine_default_spec():
    meta = BotMeta(
        id="b1", strategy_id="s", credential_id="c", exchange_id="e",
        symbol="X", timeframe="1h", mode="shadow", enabled=False,
        created_at="", updated_at="",
    )
    assert meta.engine == "spec"
    assert meta.to_dict()["engine"] == "spec"
