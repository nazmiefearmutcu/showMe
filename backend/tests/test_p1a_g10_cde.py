"""P1a-g10 CDE regression (CDE#1): the DSL must consume the whole formula.

parse_dsl used to return the first comparison and discard the rest, and let
the optional closing parenthesis go missing. A stored formula such as
"pe < 25 foo > 3" was accepted as ready and evaluated as "pe < 25".
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.equity import eqs
from showme.engine.functions.equity.eqs import EQSFunction, _eval, parse_dsl
from showme.engine.functions.misc import cde as cde_mod


@pytest.mark.parametrize(
    "formula",
    [
        "pe < 25 foo > 3",
        "pe < 25 AND (beta < 1.2",
        "pe < 25 AND beta < 1.2)",
        "(pe < 25",
        "pe < 25 AND",
    ],
)
def test_parse_dsl_rejects_trailing_tokens_and_unbalanced_parens(formula: str) -> None:
    with pytest.raises(ValueError):
        parse_dsl(formula)


def test_parse_dsl_keeps_whole_expression_when_valid() -> None:
    ast = parse_dsl("pe < 25 AND (beta < 1.2 OR pe > 0)")
    assert _eval(ast, {"pe": 20, "beta": 1.0}) is True
    assert _eval(ast, {"pe": 30, "beta": 1.0}) is False


def test_cde_add_rejects_truncated_formula_and_stores_nothing(tmp_path, monkeypatch) -> None:
    store = tmp_path / "cde_fields.json"
    monkeypatch.setattr(cde_mod, "_store", lambda: store)
    fn = cde_mod.CDEFunction()
    result = asyncio.run(fn.execute(action="add", name="bad", formula="pe < 25 foo > 3"))
    assert result.data["status"] == "input_error"
    assert "parse" in result.data["reason"].lower()
    assert result.data["count"] == 0
    assert not store.exists() or "bad" not in store.read_text()


def test_eqs_rejects_the_same_truncated_formula() -> None:
    result = asyncio.run(
        EQSFunction().execute(instrument=None, query="pe < 25 foo > 3", live_screen=False)
    )
    assert isinstance(result.data, dict)
    assert result.data["status"] == "dsl_parse_error"
    assert result.data["rows"] == []
    assert eqs is not None
