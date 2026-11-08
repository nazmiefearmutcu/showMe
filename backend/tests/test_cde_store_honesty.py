"""CDE honesty guards (CDE#2, CDE#3, CDE#4).

CDE#2: an unreadable cde_fields.json must never be overwritten by the next add.
CDE#3: missing row fields and unparseable row JSON must not evaluate to a silent FALSE.
CDE#4: removing an unknown name must not report ready; NaN row values are missing.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.equity.eqs import _eval, parse_dsl
from showme.engine.functions.misc import cde as cde_mod


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def _store_at(tmp_path, monkeypatch, text: str | None):
    store = tmp_path / "cde_fields.json"
    if text is not None:
        store.write_text(text)
    monkeypatch.setattr(cde_mod, "_store", lambda: store)
    return store


# ── CDE#2: unreadable store is reported and never overwritten ───────────────


def test_cde_add_refuses_to_overwrite_unreadable_store(tmp_path, monkeypatch) -> None:
    original = '{"keep_me": "pe < 25", '
    store = _store_at(tmp_path, monkeypatch, original)
    result = _run(cde_mod.CDEFunction(), action="add", name="new_field", formula="pe < 20")
    assert result.data["status"] == "input_error"
    assert "could not be parsed" in result.data["reason"]
    assert store.read_text() == original


def test_cde_list_reports_unreadable_store_instead_of_examples(tmp_path, monkeypatch) -> None:
    _store_at(tmp_path, monkeypatch, "[1, 2")
    result = _run(cde_mod.CDEFunction(), action="list")
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []


def test_cde_remove_refuses_to_write_when_store_is_not_an_object(tmp_path, monkeypatch) -> None:
    original = '["pe < 25"]'
    store = _store_at(tmp_path, monkeypatch, original)
    result = _run(cde_mod.CDEFunction(), action="remove", name="anything")
    assert result.data["status"] == "input_error"
    assert store.read_text() == original


# ── CDE#4: unknown remove is reported; NaN counts as missing ────────────────


def test_cde_remove_unknown_name_is_reported_and_writes_nothing(tmp_path, monkeypatch) -> None:
    original = '{"keep_me": "pe < 25"}'
    store = _store_at(tmp_path, monkeypatch, original)
    result = _run(cde_mod.CDEFunction(), action="remove", name="ghost")
    assert result.data["status"] == "input_error"
    assert "ghost" in result.data["reason"]
    assert store.read_text() == original


def test_nan_row_value_is_missing_not_unequal() -> None:
    ast = parse_dsl("pe != 20")
    assert _eval(ast, {"pe": float("nan")}) is False
    assert _eval(parse_dsl("pe < 25"), {"pe": float("nan")}) is False


# ── CDE#3: missing fields are unknown; bad row JSON is an input error ───────


def test_cde_evaluate_missing_field_is_unknown_not_false(tmp_path, monkeypatch) -> None:
    _store_at(tmp_path, monkeypatch, '{"cheap": "pe != 20"}')
    result = _run(cde_mod.CDEFunction(), action="evaluate", name="cheap", row={})
    assert result.data["status"] == "ready"
    evaluation = result.data["evaluation"]
    assert evaluation["value"] is None
    assert evaluation["missing_fields"] == ["pe"]
    assert any("pe" in w for w in result.warnings)


def test_cde_evaluate_complete_row_still_returns_boolean(tmp_path, monkeypatch) -> None:
    _store_at(tmp_path, monkeypatch, '{"cheap": "pe < 25"}')
    result = _run(cde_mod.CDEFunction(), action="evaluate", name="cheap", row={"pe": 20})
    assert result.data["evaluation"]["value"] is True
    assert result.data["evaluation"]["missing_fields"] == []


def test_cde_evaluate_unparseable_row_json_is_input_error(tmp_path, monkeypatch) -> None:
    _store_at(tmp_path, monkeypatch, '{"cheap": "pe < 25"}')
    result = _run(cde_mod.CDEFunction(), action="evaluate", name="cheap", row_json="{not json")
    assert result.data["status"] == "input_error"
    assert "row" in result.data["reason"].lower()
    assert "evaluation" not in result.data


def test_cde_evaluate_non_object_row_json_is_input_error(tmp_path, monkeypatch) -> None:
    _store_at(tmp_path, monkeypatch, '{"cheap": "pe < 25"}')
    result = _run(cde_mod.CDEFunction(), action="evaluate", name="cheap", row_json="[1, 2]")
    assert result.data["status"] == "input_error"
