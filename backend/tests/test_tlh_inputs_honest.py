"""TLH#5 regressions: declared inputs are read or reported, never silently ignored,
and the seed field dictionary names the keys the handler really emits.

The local book and yfinance are patched through the helpers in
test_tlh_real_portfolio; no network is used.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path

from showme.engine.functions.portfolio import tlh
from showme.manifest.seeds import tlh_seed
from test_tlh_real_portfolio import _book, _deps, _pos


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


_TLH_SOURCE = Path(inspect.getsourcefile(tlh)).read_text(encoding="utf-8")


# ── TLH#5: paper_mode is read; TLH never trades, so false is reported ────


def test_paper_mode_false_is_reported_not_silently_ignored(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})), paper_mode=False)
    assert any("paper_mode" in w for w in res.warnings)
    # TLH has no execution path, so the output stays preview-only.
    assert res.data["paper_mode"] is True


def test_paper_mode_true_produces_no_paper_mode_warning(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})), paper_mode=True)
    assert not any("paper_mode" in w for w in res.warnings)
    assert res.data["paper_mode"] is True


# ── TLH#5: provider_mode is read; the quote source is yfinance only ──────


def test_non_default_provider_mode_is_reported_not_silently_ignored(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})), provider_mode="cached_snapshot")
    assert any("provider_mode" in w and "cached_snapshot" in w for w in res.warnings)
    assert res.data["candidates"][0]["current_price"] == 150.0


def test_live_exchange_provider_mode_produces_no_warning(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})), provider_mode="live_exchange")
    assert not any("provider_mode" in w for w in res.warnings)


# ── TLH#5: every declared manifest input is referenced by the handler ────


def test_every_declared_input_is_referenced_by_the_handler():
    manifest = tlh_seed.tlh
    missing = [
        spec.name for spec in manifest.inputs
        if not re.search(rf"params(?:\.get\(|\[)\s*[\"']{re.escape(spec.name)}[\"']", _TLH_SOURCE)
    ]
    assert missing == [], f"declared but never read by tlh.py: {missing}"


# ── TLH#5 / contract drift: seed field_dict matches the emitted candidate keys ──


def test_seed_field_dict_names_the_emitted_replacement_key():
    field_dict = tlh_seed.tlh.field_dict
    assert "candidates[].suggested_replacement" not in field_dict
    assert "candidates[].replacement_etf" in field_dict
