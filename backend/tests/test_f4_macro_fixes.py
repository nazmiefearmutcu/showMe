"""F4 macro-family fix regressions (WIRP / ECST / WB).

Covers the audit findings closed by the F4 macro lane:

* WIRP: the live payload carries a TOP-LEVEL ``source_mode`` /
  ``data_mode`` (not buried in ``field_dictionary``) and per-row
  ``source_mode`` equals the live mode the pane classifies on.
* ECST: the date-range window tracks the real system date instead of a
  pinned "today".
* WB: the backend ships the emerging-market roster the pane's EM tab
  filters on, the template rows carry the model vintage (not "today"),
  and the live path fetches the EM series ids.

All tests are offline: every network touchpoint is injected/monkeypatched.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from showme.engine.core.base_function import FunctionDeps


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# WIRP — top-level source_mode (pane classification input)
# --------------------------------------------------------------------------- #
def test_wirp_keyless_payload_exposes_top_level_honest_source_mode(monkeypatch):
    import showme.engine.functions.macro.wirp as wirp_mod

    async def _fake_fred(url: str, timeout: float = 8.0):
        if "DFEDTARU" in url:
            return ("2026-09-10", 4.50)
        if "DFEDTARL" in url:
            return ("2026-09-10", 4.25)
        return ("2026-09-10", 4.33)

    async def _fake_irx():
        return 4.30, "2026-09-10"

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _fake_fred)
    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _fake_irx)

    result = _run(wirp_mod.WIRPFunction(FunctionDeps()).execute(central_bank="FED", meetings=3))
    data = result.data

    # No CME adapter: no futures-implied probabilities exist, so no live label.
    assert data["source_mode"] == "provider_unavailable"
    assert data["data_mode"] == "provider_unavailable"
    assert data["status"] == "provider_unavailable"
    # The mode fields are data-level values, not field_dictionary entries.
    assert "source_mode" not in data["field_dictionary"]
    assert "data_mode" not in data["field_dictionary"]
    assert "provenance" not in data["field_dictionary"]
    assert data["provenance"]["sources"] == ["fred", "yfinance"]
    assert data["rows"] == []
    assert result.sources == ["fred", "yfinance"]


def test_wirp_no_irx_keyless_is_still_honest_unavailable(monkeypatch):
    import showme.engine.functions.macro.wirp as wirp_mod

    async def _fake_fred(url: str, timeout: float = 8.0):
        if "DFEDTARU" in url:
            return ("2026-09-10", 4.50)
        if "DFEDTARL" in url:
            return ("2026-09-10", 4.25)
        return ("2026-09-10", 4.33)

    async def _irx_down():
        return None, None

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _fake_fred)
    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _irx_down)

    result = _run(wirp_mod.WIRPFunction(FunctionDeps()).execute(central_bank="FED", meetings=2))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data["anchor"]["current_target_mid"] == 4.375
    assert result.data["anchor"]["tbill_13w_pct"] is None


# --------------------------------------------------------------------------- #
# ECST — window tracks the real system date
# --------------------------------------------------------------------------- #
def test_ecst_date_range_tracks_system_date(monkeypatch):
    import pandas as pd

    import showme.engine.functions.macro.ecst as ecst_mod

    # A live FRED stand-in covering well before the 1Y window, so the trim to
    # the window (not a synthetic fallback) decides the earliest row.
    class _LiveFred:
        async def series(self, *args, **kwargs):
            idx = pd.date_range("2015-01-01", date.today(), freq="MS")
            return pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "value": 4.0})

        async def info(self, *args, **kwargs):
            raise RuntimeError("info unavailable")

    monkeypatch.setattr(
        ecst_mod,
        "fred_with_keyless_fallback",
        lambda fred, client=None: _LiveFred(),
    )

    result = _run(
        ecst_mod.ECSTFunction(FunctionDeps()).execute(series_id="DGS10", date_range="1Y")
    )
    rows = result.data["rows"]
    assert rows, "live FRED rows must survive the window trim"
    assert result.data["source_mode"] == "fred"

    earliest = min(str(row["date"]) for row in rows)
    cutoff = (date.today() - timedelta(days=367)).isoformat()
    assert earliest >= cutoff, (
        f"1Y window starts before {cutoff} (got {earliest}) — the handler's "
        "'today' is pinned instead of date.today()"
    )


# --------------------------------------------------------------------------- #
# WB — EM roster, template vintage, live EM fetch
# --------------------------------------------------------------------------- #
_EM = {"TR", "BR", "MX", "ZA", "IN", "CN", "RU", "ID"}


def test_wb_ships_emerging_roster_and_fetches_it_live():
    import showme.engine.functions.bond.wb as wb_mod
    from showme.engine.functions._fred_csv import reset_fred_csv_cache

    template = wb_mod._world_bond_template()
    assert _EM.issubset(template.keys()), "template must cover the EM tab roster"
    assert "CA" in template
    assert _EM.issubset(wb_mod._SOVEREIGN_FRED_IDS.keys()), (
        "live FRED ids must cover the EM tab roster"
    )

    class _FakeResp:
        text = "observation_date,value\n2026-09-10,4.20\n"

        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self):
            self.calls: list[str] = []

        async def get(self, url, timeout=None):
            self.calls.append(url)
            return _FakeResp()

    reset_fred_csv_cache()
    fn = wb_mod.WBFunction(FunctionDeps())
    client = _FakeClient()
    fn._http_client = client
    result = _run(fn.execute(countries="US,TR,BR"))

    assert result.sources == ["fred"]
    assert {row["country"] for row in result.data["rows"]} == {"US", "TR", "BR"}
    assert all(row["source_mode"] == "fred" for row in result.data["rows"])
    # Live rows keep the observation date, never the template vintage.
    assert all(row["as_of"] != wb_mod._MODEL_TEMPLATE_VINTAGE for row in result.data["rows"])
    assert any("IRLTLT01TRM156N" in url for url in client.calls)


def test_wb_template_rows_carry_model_vintage_not_today():
    import showme.engine.functions.bond.wb as wb_mod

    result = _run(wb_mod.WBFunction(FunctionDeps()).execute(reference=True))
    rows = result.data["rows"]
    assert rows
    assert {row["country"] for row in rows} >= _EM
    assert all(row["as_of"] == wb_mod._MODEL_TEMPLATE_VINTAGE for row in rows)
    assert all(row["reference_vintage"] == wb_mod._MODEL_TEMPLATE_VINTAGE for row in rows)
    assert result.data["summary"]["reference_vintage"] == wb_mod._MODEL_TEMPLATE_VINTAGE
    assert all(row["source_mode"] == "sovereign_yield_model" for row in rows)
