"""COUN — an unknown country with live rows must not report needs_input as its status.

``needs_input`` describes a request that cannot be answered. When FRED serves a
live indicator for an unknown country, the payload has live rows, so its
top-level status must not contradict them. The missing curated reference profile
is still disclosed, under ``profile_state``. With no live rows at all the
top-level ``needs_input`` state is kept.

All providers are patched; no network is used.
"""

from __future__ import annotations

import asyncio

import pandas as pd

import showme.engine.functions.macro.coun as coun_mod
import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.coun import COUNFunction


def _run(coro):
    return asyncio.run(coro)


class _BtmmDown:
    def __init__(self, deps) -> None:
        self.deps = deps

    async def execute(self, **kwargs):
        raise RuntimeError("btmm offline (test)")


class _BtmmLive:
    """BTMM serves a live policy row for the unknown country."""

    def __init__(self, deps) -> None:
        self.deps = deps

    async def execute(self, **kwargs):
        class _Out:
            data = {
                "rows": [
                    {"policy_rate": 5.0, "as_of": "2026-06-01", "source": "BTMM", "freshness": "fresh"}
                ]
            }

        return _Out()


class _FredAll:
    """Serves a live observation for every id it is asked for."""

    async def series(self, sid, *args, **kwargs):
        return pd.DataFrame({"date": ["2026-04-01"], "value": [101.5]})

    async def info(self, sid):
        raise RuntimeError("info unavailable (test)")


class _FredNone:
    async def series(self, sid, *args, **kwargs):
        raise RuntimeError(f"keyless FRED CSV unavailable for {sid!r}")

    async def info(self, sid):
        raise RuntimeError("info unavailable (test)")


def _patch(monkeypatch, fred, btmm=_BtmmDown) -> None:
    monkeypatch.setattr(coun_mod, "BTMMFunction", btmm)
    monkeypatch.setattr(
        ecst_mod, "fred_with_keyless_fallback", lambda deps_fred, client=None: fred
    )


def test_unknown_country_with_live_rows_is_not_status_needs_input(monkeypatch):
    _patch(monkeypatch, _FredAll(), btmm=_BtmmLive)
    result = _run(COUNFunction(FunctionDeps()).execute(country="ZZ", live_macro=True))

    data = result.data
    assert any(row.get("value") is not None for row in data["rows"]), "live rows expected"
    assert data.get("status") != "needs_input", "status contradicts the live rows"
    assert data["rows"] and all(
        row["source_mode"] != "country_reference_profile" for row in data["rows"]
    ), "no reference values for an unknown country"
    assert data["profile_state"]["status"] == "needs_input"
    assert "ZZ" in data["profile_state"]["reason"]
    assert data["source_mode"] == "live_macro"


def test_unknown_country_without_live_rows_keeps_top_level_needs_input(monkeypatch):
    _patch(monkeypatch, _FredNone())
    result = _run(COUNFunction(FunctionDeps()).execute(country="ZZ", live_macro=True))

    assert result.data["status"] == "needs_input"
    assert "profile_state" not in result.data
    assert result.data["rows"] == []
