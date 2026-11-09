"""ECST — a live series with no observation inside the date window is ``empty``.

FRED returns observations, but all of them are before the requested window
(``date_range=1Y`` against 2000 data). The response must not claim status ``ok``
with data_state ``live`` and zero rows: it is an explicit ``empty`` state with a
reason, and the provenance (fred) stays truthful. All providers are patched; no
network is used.
"""

from __future__ import annotations

import asyncio

import pandas as pd

import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps


def _run(coro):
    return asyncio.run(coro)


class _OldFred:
    async def series(self, sid, *args, **kwargs):
        return pd.DataFrame({"date": ["2000-01-03", "2000-01-04"], "value": [3.1, 3.2]})

    async def info(self, sid):
        return {"title": f"{sid} title", "units": "%", "frequency": "daily"}


def test_live_series_with_no_rows_in_window_is_empty_not_ok(monkeypatch):
    monkeypatch.setattr(
        ecst_mod, "fred_with_keyless_fallback", lambda deps_fred, client=None: _OldFred()
    )
    result = _run(
        ecst_mod.ECSTFunction(FunctionDeps()).execute(series_id="DGS10", date_range="1Y")
    )
    data = result.data

    assert data["rows"] == []
    assert data["status"] == "empty", data["status"]
    assert data["data_state"] == "empty"
    assert data["source_mode"] == "fred", "the provider did return observations"
    assert "1Y" in data["reason"] or "window" in data["reason"]
    latest = next(card for card in data["cards"] if card["label"] == "Latest")
    assert latest["value"] is None
