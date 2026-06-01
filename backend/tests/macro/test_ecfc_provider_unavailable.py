"""ECFC — Bug #N5 regression, updated for the 2026-06-01 de-garbage.

OLD (removed) contract: ECFC was gated behind a ``live`` flag and, when live
data was not explicitly requested, returned identical fabricated 2.0% GDP /
2.8% inflation / 4.1% unemployment rows for USA/CHN/BRA/JPN (or an empty
provider_unavailable stub). The cockpit displayed those as a real forecast
table.

NEW honest contract: ECFC ALWAYS pulls keyless IMF World Economic Outlook
forecasts from the IMF DataMapper API — there is no ``live`` gate anymore
(``live=False`` is ignored). With network it returns REAL per-country IMF rows
(status ok); only a genuine IMF outage yields an honest provider_unavailable
envelope with empty rows + a methodology that explains it never fabricates
values. The original anti-garbage intent (never fabricate identical per-country
constants) is preserved here but asserted against the new real source, and the
provider_unavailable branch is exercised deterministically by monkeypatching the
IMF fetch to fail (so the file is green regardless of live connectivity). The
real live path is covered by ``tests/test_degarbage_macro_ecfc.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.macro.ecfc import ECFCFunction  # noqa: E402


class _BoomClient:
    """A fake IMF client whose every request fails — forces a total outage."""

    async def get(self, *args, **kwargs):
        raise httpx.ConnectError("imf datamapper unreachable")


def _make_unavailable_handler() -> ECFCFunction:
    fn = ECFCFunction()
    # _http_client is the test-injection seam honoured by ECFCFunction._client().
    fn._http_client = _BoomClient()
    return fn


def test_ecfc_returns_empty_rows_when_live_not_requested() -> None:
    """``live=False`` is now ignored; only a real IMF outage empties the rows.

    To assert the honest provider_unavailable shape deterministically we inject a
    failing IMF client. The function must NOT fabricate forecast values — its
    methodology must say so explicitly.
    """
    result = asyncio.run(
        _make_unavailable_handler().execute(country="USA", live=False)
    )
    assert result.data["rows"] == []
    assert result.data["status"] == "provider_unavailable"
    assert result.data["data_state"] == "provider_unavailable"
    assert "no_live_source" in result.sources
    assert result.warnings
    # Never fabricate: the honest envelope's methodology must say so.
    assert "fabricat" in result.data["methodology"].lower()


def test_ecfc_does_not_return_identical_growth_for_each_country() -> None:
    """The original bug: USA/CHN/BRA/JPN all got value=2.0 for GDP.

    With a forced IMF outage every country degrades to empty rows (we refuse to
    fabricate), so the identical-fake-2.0% leak can never happen. When live data
    IS available the rows are real IMF projections that differ per country — the
    live path is covered by ``tests/test_degarbage_macro_ecfc.py``.
    """
    rows = []
    for country in ("USA", "CHN", "BRA", "JPN"):
        result = asyncio.run(
            _make_unavailable_handler().execute(country=country, live=False)
        )
        rows.append((country, result.data["rows"]))
    assert all(rows_for_country == [] for _, rows_for_country in rows), rows


def test_ecfc_methodology_explains_provider_unavailable() -> None:
    """On a genuine outage the methodology must name IMF and the honest state."""
    result = asyncio.run(_make_unavailable_handler().execute(country="USA"))
    assert result.data["status"] == "provider_unavailable"
    methodology = result.data["methodology"].lower()
    assert "imf" in methodology or "oecd" in methodology
    assert "provider_unavailable" in methodology or "no provider" in methodology
