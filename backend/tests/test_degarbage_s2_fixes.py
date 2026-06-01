"""Regression tests for the 2026-06-01 de-garbage round-2 fixes.

Four functions returned an honest-but-wrong empty/unavailable envelope because
of concrete, reproducible defects — NOT a real upstream outage. Each test pins
the fix so the defect cannot silently return:

* ECFC  — IMF DataMapper is keyed by ISO-3166 alpha-3; the function was passed
          alpha-2 (``US``) and never mapped it, so ``.get("US")`` always missed.
* SOSC  — the GDELT query used two adjacent parenthesised groups, which GDELT
          rejects ("Parentheses may only be used around OR'd statements.") with
          HTTP 200 + zero articles. The valid shape is a bare symbol ANDed with
          a single OR-group.
* DARK  — ``FINRAAdapter.ats_weekly`` filtered on ``issueSymbolIdentifier`` only
          (no ``summaryTypeCode``) via a GET query-string, returning a stale
          slice that topped out at 2023. The fix POSTs both filters incl.
          ``ATS_W_SMBL``.
* BRIEF — composed news by reading TOP's headlines under ``articles``/``rows``,
          but TOP emits them under ``items`` — so every story was dropped and
          the brief falsely reported ``provider_unavailable``.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest


# ── ECFC: ISO-2 → ISO-3 country normalisation ───────────────────────────────
def test_ecfc_normalize_country_alpha2_to_alpha3() -> None:
    from showme.engine.functions.macro.ecfc import _normalize_country

    assert _normalize_country("US") == "USA"
    assert _normalize_country("us") == "USA"
    assert _normalize_country("JP") == "JPN"
    assert _normalize_country("GB") == "GBR"
    assert _normalize_country("UK") == "GBR"
    assert _normalize_country("TR") == "TUR"
    # Already alpha-3 or an IMF group code passes through untouched.
    assert _normalize_country("USA") == "USA"
    assert _normalize_country("DEU") == "DEU"
    assert _normalize_country("EURO") == "EURO"


# ── SOSC: GDELT query must be a single OR-group, never nested paren groups ────
def test_sosc_query_is_single_or_group() -> None:
    from showme.engine.functions.news.sosc import _query_for

    q = _query_for("AAPL")
    # bare symbol leads, ANDed with exactly one parenthesised OR-group
    assert q.startswith("AAPL (")
    assert q.count("(") == 1 and q.count(")") == 1
    # the old rejected shape had two adjacent groups: ``(...) (...)``
    assert ") (" not in q
    assert " OR " in q


# ── DARK: FINRA ats_weekly POSTs summaryTypeCode=ATS_W_SMBL + symbol ─────────
def test_finra_ats_weekly_posts_summary_type_filter() -> None:
    from showme.engine.data_sources.equity.finra_adapter import FINRAAdapter

    captured: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:  # noqa: D401
            return None

        def json(self) -> list[dict[str, Any]]:
            return [{
                "weekStartDate": "2026-05-04",
                "issueSymbolIdentifier": "AAPL",
                "MPID": "XYZ",
                "totalWeeklyShareQuantity": 1000,
                "totalWeeklyTradeCount": 10,
            }]

    class _Client:
        async def post(self, url: str, json: dict[str, Any] | None = None,
                       headers: dict[str, Any] | None = None, **kw: Any) -> _Resp:
            captured["url"] = url
            captured["json"] = json
            return _Resp()

    adapter = FINRAAdapter({})

    async def _fake_client() -> _Client:
        return _Client()

    async def _fake_auth() -> None:
        return None

    adapter._client_ = _fake_client  # type: ignore[assignment]
    adapter._maybe_auth = _fake_auth  # type: ignore[assignment]

    df = asyncio.run(adapter.ats_weekly("AAPL", limit=50))

    assert isinstance(df, pd.DataFrame) and not df.empty
    body = captured["json"]
    fields = {f["fieldName"]: f["fieldValue"] for f in body["compareFilters"]}
    assert fields.get("summaryTypeCode") == "ATS_W_SMBL"
    assert fields.get("issueSymbolIdentifier") == "AAPL"
    assert captured["url"].endswith("/name/weeklySummary")


# ── BRIEF: composes from TOP's ``items`` key, not articles/rows ──────────────
def test_brief_reads_top_items_key(monkeypatch) -> None:
    from showme.engine.core.base_function import FunctionDeps, FunctionResult
    from showme.engine.functions.news import top as top_mod
    from showme.engine.functions.news.brief import BRIEFFunction

    class _FakeTOP:
        def __init__(self, deps: Any) -> None:
            self.deps = deps

        async def execute(self, **params: Any) -> FunctionResult:
            sym = params.get("symbol") or "MACRO"
            return FunctionResult(
                code="TOP",
                instrument=None,
                # Headlines live under ``items`` — the exact key BRIEF used to
                # ignore. If BRIEF only reads articles/rows this stays empty.
                data={"items": [
                    {"title": f"{sym} headline", "url": f"https://x/{sym}",
                     "source": "rss", "summary": "real story"},
                ], "status": "ok"},
                sources=["rss"],
            )

    # BRIEF imports TOPFunction lazily inside execute() from news.top, so the
    # patch must land on the source module, not on brief's namespace.
    monkeypatch.setattr(top_mod, "TOPFunction", _FakeTOP)

    res = asyncio.run(BRIEFFunction(FunctionDeps()).execute(watchlist=["AAPL"]))
    data = res.data
    assert data["status"] == "ok"
    assert data["article_count"] >= 1
    assert "placeholder" not in str(data).lower()
    # both a macro story and the watchlist story should appear
    sections = {a.get("section") for a in data["articles"]}
    assert "top_stories" in sections or "watchlist" in sections


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
