"""LANG honesty regressions (wc1-g48: LANG#1, LANG#2, LANG#3).

LANG#1: a call without an explicit ``lang`` must not silently persist Turkish.
LANG#2: rows must not claim a coverage tier or a registry source the handler
        never computed or read.
LANG#3: the unsupported-language next action must name the valid codes, not
        the generic symbol/asset-class advice.

No network: the runtime preference file is redirected into pytest's tmp dir.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc import _extras
from showme.engine.functions.misc._extras import LANGFunction
from showme.function_contracts import normalize_function_contract


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def lang_file(tmp_path, monkeypatch):
    target = tmp_path / "lang.txt"
    target.write_text("de")

    def _runtime_path(name: str):
        assert name == "lang.txt"
        return target

    import showme.app_paths as app_paths

    monkeypatch.setattr(app_paths, "runtime_path", _runtime_path)
    return target


# LANG#1 ---------------------------------------------------------------

def test_lang_missing_param_is_input_error_and_keeps_saved_preference(lang_file) -> None:
    res = _run(LANGFunction(deps=FunctionDeps()).execute())
    assert res.data["status"] == "input_error"
    assert lang_file.read_text() == "de", "a parameterless call must not overwrite runtime/lang.txt"


@pytest.mark.parametrize("value", ["", "   "])
def test_lang_blank_param_is_input_error_and_keeps_saved_preference(lang_file, value) -> None:
    res = _run(LANGFunction(deps=FunctionDeps()).execute(lang=value))
    assert res.data["status"] == "input_error"
    assert lang_file.read_text() == "de"


def test_lang_explicit_param_still_persists(lang_file) -> None:
    res = _run(LANGFunction(deps=FunctionDeps()).execute(lang="fr"))
    assert res.data["status"] == "ready"
    assert res.data["lang"] == "fr"
    assert lang_file.read_text() == "fr"


# LANG#2 ---------------------------------------------------------------

def test_lang_rows_do_not_claim_hardcoded_core_labels_coverage(lang_file) -> None:
    res = _run(LANGFunction(deps=FunctionDeps()).execute(lang="en"))
    coverages = {row.get("coverage") for row in res.data["rows"]}
    assert "core_labels" not in coverages


def test_lang_does_not_cite_registry_it_never_reads(lang_file) -> None:
    res = _run(LANGFunction(deps=FunctionDeps()).execute(lang="en"))
    assert "showme_i18n_registry" not in res.sources
    assert res.sources == ["local_locale_catalog"]


def test_lang_local_catalog_source_is_classified_as_reference() -> None:
    from showme.server import _classify_source_state

    assert _classify_source_state("local_locale_catalog") == "reference"


# LANG#3 ---------------------------------------------------------------

def test_lang_unsupported_next_actions_name_the_valid_codes(lang_file) -> None:
    res = _run(LANGFunction(deps=FunctionDeps()).execute(lang="zz"))
    actions = res.data.get("next_actions") or []
    assert actions, "input_error must carry a next action"
    blob = " ".join(actions)
    for code in LANGFunction.SUPPORTED:
        assert code in blob
    assert "symbol" not in blob.lower()
    assert "asset class" not in blob.lower()


def test_lang_unsupported_envelope_next_action_is_language_specific(lang_file) -> None:
    res = _run(LANGFunction(deps=FunctionDeps()).execute(lang="zz"))
    env = normalize_function_contract("LANG", {"lang": "zz"}, {
        "data": res.data, "sources": res.sources, "metadata": {}, "warnings": res.warnings,
    })
    assert env["status"] == "input_error"
    assert "asset class" not in (env.get("nextAction") or "").lower()
    assert "tr" in (env.get("nextAction") or "")
