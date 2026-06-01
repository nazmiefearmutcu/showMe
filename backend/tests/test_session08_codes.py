"""Session-08 bug-hunt regression tests for GREEKS/HVT/IVOL/ICX/ISIN/LANG/LITM.

These tests pin the behaviour fixed during the 2026-05-17 BugHunt:
- GREEKS calc-error path now returns explicit status + reason.
- GREEKS rejects non-list positions with status="input_error".
- HVT/IVOL "live" flag honours _truthy() (rejects "false" string).
- HVT non-live path returns status="reference" + rows + live=False.
- IVOL non-live path returns status="reference" + live=False.
- ICX no longer silently substitutes SPX constituents for DAX/CAC/FTSE/STOXX/BIST.
- ICX unknown index returns a single placeholder row (not S&P 500 noise).
- ISIN _detect_id_type uses Luhn-checked ISIN, structural CUSIP, vowel-free SEDOL.
- LANG requires_reload is only true on the selected row.
- LITM does not include 5.07 / 8.01 in its filter set.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


class _DummyDeps:
    """Minimal deps stub for functions that touch self.deps in their executors."""

    sec_edgar = None
    yfinance = None
    sec_13f = None
    openfigi = None
    symbol_registry = None


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_closed() else asyncio.new_event_loop().run_until_complete(coro)


# ---------- GREEKS ----------

def test_greeks_rejects_non_list_positions() -> None:
    from showme.engine.functions.portfolio.greeks import GREEKSFunction

    fn = GREEKSFunction(_DummyDeps())
    res = asyncio.run(fn.execute(positions="not_a_list"))
    assert res.data["status"] == "input_error"
    assert "list" in res.data["reason"].lower()
    assert res.data["rows"] == []


def test_greeks_empty_positions_returns_input_required() -> None:
    from showme.engine.functions.portfolio.greeks import GREEKSFunction

    fn = GREEKSFunction(_DummyDeps())
    res = asyncio.run(fn.execute(positions=[]))
    assert res.data["status"] == "input_required"
    assert res.data["positions"] == 0


# ---------- HVT / IVOL ----------

def test_stubs_truthy_handles_false_string() -> None:
    from showme.engine.functions.derivative._stubs import _truthy

    assert _truthy(True) is True
    assert _truthy("true") is True
    assert _truthy("on") is True
    assert _truthy("yes") is True
    # Critical: the literal string "false" must NOT be truthy.
    assert _truthy("false") is False
    assert _truthy(None) is False
    assert _truthy(0) is False
    assert _truthy("") is False


def test_hvt_non_live_marks_reference_and_live_false() -> None:
    """de-garbage 2026-06-01: HVT now fetches the realized-vol term structure
    LIVE from yfinance by default (no opt-in flag). With no yfinance adapter the
    default path degrades HONESTLY to ``provider_unavailable`` (live=False) and
    still carries a labelled reference vol-window table so the UI renders. The
    explicit ``reference=true`` opt-in (tests / air-gapped demos) still yields
    the canonical ``reference`` shape — never silently substituted as default."""
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.derivative._stubs import HVTFunction

    fn = HVTFunction(_DummyDeps())
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)

    # Default (no live provider) → honest provider_unavailable, never live.
    res = asyncio.run(fn.execute(instrument=inst))
    assert res.data["status"] == "provider_unavailable"
    assert res.metadata is not None and res.metadata.get("live") is False
    # A labelled reference vol-window table must still render.
    assert isinstance(res.data["rows"], list) and len(res.data["rows"]) >= 1
    assert res.data["summary"]["source_mode"] == "reference"

    # Explicit opt-in reference template stays the canonical "reference" shape.
    ref = asyncio.run(fn.execute(instrument=inst, reference=True))
    assert ref.data["status"] == "reference"
    assert ref.metadata is not None and ref.metadata.get("live") is False
    assert isinstance(ref.data["rows"], list) and len(ref.data["rows"]) >= 1


def test_ivol_non_live_marks_reference_and_live_false() -> None:
    """de-garbage 2026-06-01: IVOL now pulls the implied-vol surface LIVE from the
    yfinance option chain by default. With no adapter the default path degrades
    HONESTLY to ``provider_unavailable`` (live=False), and the explicit
    ``reference=true`` opt-in still emits the labelled Black-Scholes reference
    surface (live=False) — the reference shape is never the silent default."""
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.derivative._stubs import IVOLFunction

    fn = IVOLFunction(_DummyDeps())
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)

    # Default (no live provider) → honest provider_unavailable, never live.
    res = asyncio.run(fn.execute(instrument=inst))
    assert res.data["status"] == "provider_unavailable"
    assert res.metadata is not None and res.metadata.get("live") is False

    # Explicit opt-in reference surface stays the canonical "reference" shape.
    ref = asyncio.run(fn.execute(instrument=inst, reference=True))
    assert ref.data["status"] == "reference"
    assert ref.metadata is not None and ref.metadata.get("live") is False


def test_hvt_requires_symbol_with_message() -> None:
    from showme.engine.functions.derivative._stubs import HVTFunction

    fn = HVTFunction(_DummyDeps())
    try:
        asyncio.run(fn.execute(instrument=None))
    except ValueError as exc:
        assert "HVT" in str(exc) and "symbol" in str(exc).lower()
    else:
        raise AssertionError("HVT should raise ValueError when instrument is None")


# ---------- ICX ----------

def test_icx_template_returns_correct_indexes() -> None:
    from showme.engine.functions.screen.icx import _template_constituents

    spx = _template_constituents("SPX")
    dax = _template_constituents("DAX")
    cac = _template_constituents("CAC")
    ftse = _template_constituents("FTSE")
    stoxx = _template_constituents("STOXX")
    bist = _template_constituents("BIST")

    # Critical: DAX must NOT return Apple/Microsoft (the SPX bug).
    assert dax.iloc[0]["symbol"].endswith(".DE")
    assert cac.iloc[0]["symbol"].endswith(".PA")
    assert ftse.iloc[0]["symbol"].endswith(".L")
    assert bist.iloc[0]["symbol"].endswith(".IS")
    # STOXX is multi-exchange but ASML.AS is a real STOXX50 constituent.
    assert stoxx.iloc[0]["symbol"] in {"ASML.AS", "MC.PA", "SAP.DE"}
    # SPX still works.
    assert spx.iloc[0]["symbol"] == "AAPL"


def test_icx_unknown_index_returns_placeholder_row() -> None:
    from showme.engine.functions.screen.icx import _template_constituents

    df = _template_constituents("INVALID_INDEX_CODE")
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "N/A"
    assert "INVALID_INDEX_CODE" in df.iloc[0]["company"]


# ---------- ISIN ----------

def test_isin_luhn_check() -> None:
    from showme.engine.functions.api.isin import _isin_check_digit

    # Real Apple ISIN
    assert _isin_check_digit("US0378331005") is True
    # Bad check digit
    assert _isin_check_digit("US0378331006") is False
    # BlackRock UK ISIN
    assert _isin_check_digit("GB00B03MLX29") is True


def test_isin_detect_id_type_handles_real_identifiers() -> None:
    from showme.engine.functions.api.isin import _detect_id_type

    # Real Apple ISIN with valid Luhn
    assert _detect_id_type("US0378331005") == "ID_ISIN"
    # Mangled ISIN (bad check digit) must NOT classify as ID_ISIN
    assert _detect_id_type("US0378331006") == "TICKER"
    # Real Apple CUSIP (all digits)
    assert _detect_id_type("037833100") == "ID_CUSIP"
    # Real BlackRock UK SEDOL (no vowels in first 6, digit check at pos 7)
    assert _detect_id_type("B6WY7H1") == "ID_SEDOL"
    # Common ticker
    assert _detect_id_type("AAPL") == "TICKER"
    # Empty input must default to TICKER (not raise)
    assert _detect_id_type("") == "TICKER"


# ---------- LANG ----------

def test_lang_requires_reload_only_on_selected_row() -> None:
    from showme.engine.functions.misc._extras import LANGFunction

    fn = LANGFunction(_DummyDeps())
    res = asyncio.run(fn.execute(lang="en"))
    rows = res.data["rows"]
    # Exactly one row must have requires_reload=True, and it must be 'en'.
    reload_rows = [r for r in rows if r.get("requires_reload")]
    assert len(reload_rows) == 1
    assert reload_rows[0]["lang"] == "en"
    assert reload_rows[0]["selected"] is True


def test_lang_unsupported_returns_input_error() -> None:
    from showme.engine.functions.misc._extras import LANGFunction

    fn = LANGFunction(_DummyDeps())
    res = asyncio.run(fn.execute(lang="xx"))
    assert res.data["status"] == "input_error"
    assert "xx" in (res.data.get("reason") or "").lower() or "xx" in str(res.warnings).lower()


# ---------- LITM ----------

def test_litm_keeps_narrow_8k_items() -> None:
    """LITM filter must NOT include 5.07 (proxy vote) or 8.01 (other events)."""
    # Read the source instead of importing — the function delegates to a
    # network call. We assert the filter set is the narrowed one.
    src = (ROOT / "backend" / "showme" / "engine" / "functions" / "misc" / "_bonus.py").read_text()
    # Should contain new tightened filter.
    assert 'keep = {"1.03", "1.04", "3.03", "5.02", "5.03"}' in src
    # Must NOT have legacy items.
    assert '"5.07"' not in src.split("# Narrow filter")[1].split("keep = {")[1].split("}")[0]
    assert '"8.01"' not in src.split("# Narrow filter")[1].split("keep = {")[1].split("}")[0]
