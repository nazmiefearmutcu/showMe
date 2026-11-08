"""SEC-11 — the provider-response cache codec must never unpickle stored bytes.

A payload read back from ``cache.provider_responses`` is attacker-controlled
if anything can write rows to the user's DuckDB file. ``pickle.loads`` would
execute a crafted ``__reduce__``; the codec is JSON-only so it cannot.
"""
from __future__ import annotations

import pickle
from typing import Any

import pytest

from showme.analytical.cache import dumps, loads

_SIDE_EFFECTS: list[str] = []


def _record_side_effect() -> None:
    _SIDE_EFFECTS.append("executed")


class _Canary:
    """Pickle payload whose deserialization calls a module-level function."""

    def __reduce__(self) -> tuple[Any, ...]:
        return (_record_side_effect, ())


def test_roundtrip_json_compatible_object() -> None:
    obj = {"symbol": "NG=F", "rows": [{"last": 3.25, "as_of": None}], "ok": True}
    assert loads(dumps(obj)) == obj


def test_dumps_is_utf8_json_not_pickle() -> None:
    blob = dumps({"a": 1})
    assert blob == b'{"a":1}'
    assert not blob.startswith(b"\x80")  # pickle protocol 2+ header


def test_loads_rejects_pickle_blob_without_executing_it() -> None:
    _SIDE_EFFECTS.clear()
    blob = pickle.dumps(_Canary(), protocol=pickle.HIGHEST_PROTOCOL)
    with pytest.raises(ValueError):
        loads(blob)
    assert _SIDE_EFFECTS == []


def test_loads_rejects_non_json_text() -> None:
    with pytest.raises(ValueError):
        loads(b"not json at all")


def test_dumps_rejects_non_json_types_instead_of_pickling() -> None:
    with pytest.raises(TypeError):
        dumps({"when": object()})
