"""De-garbage regression test for ONCH (On-Chain Network Vitals).

Asserts the handler returns REAL live data from keyless public sources
(mempool.space + CoinGecko) instead of the legacy gated/hardcoded stub.
Live-network assertions degrade gracefully offline: on a genuine network
failure the handler must return the honest provider_unavailable shape.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.misc import onch
from showme.engine.functions.misc.onch import (
    _LEGACY_DIFFICULTY_T,
    _LEGACY_FASTEST_FEE,
    _LEGACY_HASHRATE_EH,
    _LEGACY_MEMPOOL_COUNT,
    ONCHFunction,
)

OK_SET = {"ok", "empty", "provider_unavailable"}
_LEGACY_VALUES = {
    str(_LEGACY_HASHRATE_EH),
    str(_LEGACY_DIFFICULTY_T),
    str(_LEGACY_MEMPOOL_COUNT),
    str(_LEGACY_FASTEST_FEE),
    "model constant",
}


def _run() -> object:
    return asyncio.run(ONCHFunction().execute())


def test_onch_contract_preserved_and_no_legacy_constants() -> None:
    result = _run()
    data = result.data

    # Public identity preserved.
    assert result.code == "ONCH"
    assert ONCHFunction.code == "ONCH"
    assert ONCHFunction.name == "On-Chain Metrics"
    assert ONCHFunction.category == "misc"

    # Required payload keys + honest provenance.
    assert data["status"] in OK_SET
    assert "rows" in data and isinstance(data["rows"], list)
    assert isinstance(data.get("methodology"), str) and data["methodology"]
    assert isinstance(data.get("field_dictionary"), dict) and data["field_dictionary"]
    assert "model" not in result.sources
    assert "glassnode" not in result.sources
    assert "etherscan" not in result.sources
    assert set(result.sources) == {"mempool", "coingecko"}


def test_onch_live_or_graceful() -> None:
    result = _run()
    data = result.data
    status = data["status"]

    if status == "provider_unavailable":
        # Genuine outage path: honest, empty, with next_actions + warning.
        assert data["rows"] == []
        assert data.get("next_actions")
        assert data.get("warnings")
        return

    # Live path: rows are REAL, not the old constants.
    assert status == "ok"
    rows = data["rows"]
    assert len(rows) >= 6, "expected the full vitals table when live"

    metrics = {r["metric"]: r for r in rows}
    for required in ("Mempool Backlog", "Fastest Fee", "Hashrate", "Difficulty", "Block Height"):
        assert required in metrics, f"missing live metric {required}"

    # None of the displayed values may be the canned legacy constants.
    for row in rows:
        assert row["value"] not in _LEGACY_VALUES
        assert row.get("context") != "model constant"
        assert row.get("source") in {"mempool", "coingecko"}

    # Block height is a real, recent tip (> 800k) and not the 840000 constant.
    bh = metrics["Block Height"]["value"].replace(",", "")
    assert bh.isdigit() and int(bh) > 800_000

    # Fee histogram series for the bar chart_grammar.
    series = data.get("series")
    assert isinstance(series, list) and len(series) >= 1
    assert {"bucket", "count"} <= set(series[0].keys())
    assert all(isinstance(s["count"], int) for s in series)

    # Cards populated.
    cards = data.get("cards", [])
    assert isinstance(cards, list) and len(cards) >= 3


def test_onch_unavailable_shape_on_forced_failure() -> None:
    """Force a fetch failure and confirm the graceful, labeled fallback.

    The fake ``_fetch_live`` is bound on the *instance* (not the class) so it
    is discarded with the handler and cannot leak into sibling tests under any
    ordering (e.g. pytest-randomly).
    """

    async def _boom(self: object, timeout: float) -> dict:
        raise ConnectionError("simulated outage")

    handler = ONCHFunction()
    handler._fetch_live = _boom.__get__(handler, ONCHFunction)  # type: ignore[method-assign]

    result = asyncio.run(handler.execute())
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert data.get("next_actions")
    assert data.get("warnings")
    assert "Live on-chain fetch failed" in data["warnings"][0]
    # Even on failure, honest provider names + methodology stay.
    assert set(result.sources) == {"mempool", "coingecko"}
    assert isinstance(data.get("methodology"), str) and data["methodology"]


# Keep the module binding meaningful for unused-import linters.
assert onch._METHODOLOGY
