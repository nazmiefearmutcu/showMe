"""ECST — no synthetic series may be served as data (G5 ECST#1).

When FRED (keyless CSV or keyed) and World Bank return no observations the
function must return an explicit ``provider_unavailable`` envelope with no
rows. The old code substituted a constructed curve: a constant 1.0 for every
unknown series id and hand-built curves for the four named series, labelled
``macro_series_baseline``. All providers are patched; no network is used.
"""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest

import showme.engine.functions.macro.ecst as ecst_mod
from showme.engine.core.base_function import FunctionDeps


def _run(coro):
    return asyncio.run(coro)


class _DownFred:
    """Every FRED request fails, as the keyless CSV does for unknown ids."""

    async def series(self, sid, *args, **kwargs):
        raise RuntimeError(f"keyless FRED CSV unavailable for {sid!r}")

    async def info(self, sid):
        raise RuntimeError("info unavailable")


class _Fred:
    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.fail_ids = fail_ids or set()

    async def series(self, sid, *args, **kwargs):
        if sid in self.fail_ids:
            raise RuntimeError(f"keyless FRED CSV unavailable for {sid!r}")
        base = 4.0 if sid == "DGS10" else 3.5
        return pd.DataFrame(
            {
                "date": ["2026-01-02", "2026-01-05", "2026-01-06"],
                "value": [base, base + 0.05, base + 0.1],
            }
        )

    async def info(self, sid):
        return {"title": f"{sid} title", "units": "%", "frequency": "daily"}


def _execute(monkeypatch, fred, **params):
    monkeypatch.setattr(
        ecst_mod, "fred_with_keyless_fallback", lambda deps_fred, client=None: fred
    )
    return _run(ecst_mod.ECSTFunction(FunctionDeps()).execute(**params))


def test_unknown_series_id_is_not_served_a_constant_curve(monkeypatch):
    result = _execute(monkeypatch, _DownFred(), series_id="ZZTESTID")
    data = result.data

    assert data["rows"] == [], "an unknown id must not produce a synthetic series"
    assert data["status"] == "provider_unavailable"
    assert data["source_mode"] == "provider_unavailable"
    assert "macro_series_baseline" not in result.sources
    assert "ZZTESTID" in data["reason"]
    latest = next(card for card in data["cards"] if card["label"] == "Latest")
    assert latest["value"] is None


@pytest.mark.parametrize("sid", ["CPIAUCSL", "GDPC1", "UNRATE", "DGS10"])
def test_named_series_total_outage_returns_no_hand_built_curve(monkeypatch, sid):
    result = _execute(monkeypatch, _DownFred(), series_id=sid)
    data = result.data

    assert data["rows"] == []
    assert data["status"] == "provider_unavailable"
    assert "macro_series_baseline" not in result.sources
    assert all(row.get("source_mode") != "macro_series_baseline" for row in data["rows"])


def test_compare_leg_outage_omits_overlay_instead_of_baseline(monkeypatch):
    result = _execute(
        monkeypatch, _Fred(fail_ids={"DGS2"}), series_id="DGS10", compare_with="DGS2"
    )
    data = result.data

    assert data["source_mode"] == "fred"
    assert data["compare_source_mode"] == "provider_unavailable"
    assert not any("compare_value" in row for row in data["rows"])
    assert "macro_series_baseline" not in result.sources
    assert any("DGS2" in warning for warning in result.warnings)


def test_main_outage_with_live_compare_does_not_emit_overlay_rows(monkeypatch):
    result = _execute(
        monkeypatch, _Fred(fail_ids={"DGS10"}), series_id="DGS10", compare_with="DGS2"
    )
    data = result.data

    assert data["rows"] == []
    assert data["status"] == "provider_unavailable"
    assert "compare_value" not in str(data["rows"])  # no compare-only NaN rows leak through
    assert "macro_series_baseline" not in result.sources


def test_live_series_still_reports_fred_and_no_warnings(monkeypatch):
    result = _execute(monkeypatch, _Fred(), series_id="DGS10")
    data = result.data

    assert data["status"] == "ok"
    assert data["source_mode"] == "fred"
    assert result.sources == ["fred"]
    assert len(data["rows"]) == 3
    assert result.warnings == []
