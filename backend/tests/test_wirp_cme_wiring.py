"""WIRP — CME FedWatch wiring regression.

The audit found ``CMEFedWatchAdapter`` was loaded into
``FunctionDeps.cme_fedwatch`` by the factory but the WIRP handler
ignored it, so the surfaced probabilities always came from the
deterministic reference table. These tests pin the new contract:

* When ``deps.cme_fedwatch`` returns usable probabilities, WIRP stamps
  ``data_mode = "live_official"`` and threads ``cme_fedwatch`` through
  ``sources`` + ``provenance.sources``.
* When the adapter raises, WIRP falls back to the reference table with
  ``data_mode = "modeled"`` and a warning that names the failure.
* The ``cut + hold + hike == 1.0`` invariant from the WIRP manifest
  semantic test still holds on the CME path even though CME's input
  buckets are arbitrary integer / decimal range labels.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.macro.wirp import WIRPFunction  # noqa: E402


class _StubCMEAdapter:
    """Async adapter stub honouring the real adapter's ``probabilities()`` shape."""

    def __init__(self, payload: dict[str, Any] | Exception) -> None:
        self._payload = payload

    async def probabilities(self) -> dict[str, Any]:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _canned_payload() -> dict[str, Any]:
    """A CME-shaped payload covering three meetings with hike, hold, cut bias.

    The first meeting's modal bin is the anchor; bins below it count as
    cut probability, equal counts as hold, above counts as hike.
    """
    return {
        "raw": {"source": "stub"},
        "meetings": [
            {
                # Anchor: modal bin is 4.25-4.50 (hold) → cut + hike sum to 0.30.
                "date": "2026-06-17",
                "ranges": {
                    "4.00-4.25": 10.0,  # cut
                    "4.25-4.50": 70.0,  # hold
                    "4.50-4.75": 20.0,  # hike
                },
            },
            {
                # Skewed cut bias.
                "date": "2026-07-29",
                "ranges": {
                    "3.75-4.00": 25.0,  # cut (multi-bucket cut)
                    "4.00-4.25": 35.0,  # cut
                    "4.25-4.50": 30.0,  # hold
                    "4.50-4.75": 10.0,  # hike
                },
            },
            {
                # Hike-biased.
                "date": "2026-09-16",
                "ranges": {
                    "4.25-4.50": 20.0,  # hold
                    "4.50-4.75": 55.0,  # hike
                    "4.75-5.00": 25.0,  # hike (multi-bucket hike)
                },
            },
        ],
    }


def _execute_with_adapter(adapter: Any, **params: Any) -> Any:
    deps = FunctionDeps()
    deps.cme_fedwatch = adapter
    fn = WIRPFunction(deps=deps)
    return asyncio.run(fn.execute(**params))


def test_wirp_uses_cme_when_available() -> None:
    adapter = _StubCMEAdapter(_canned_payload())
    result = _execute_with_adapter(adapter, central_bank="FED", meetings=3)

    assert result.data["data_mode"] == "live_official", result.data
    assert "cme_fedwatch" in result.sources
    assert "cme_fedwatch" in result.data["provenance"]["sources"]
    assert result.data["source_mode"] == "cme_fedwatch"

    rows = result.data["rows"]
    assert len(rows) == 3
    dates = [row["date"] for row in rows]
    assert dates == ["2026-06-17", "2026-07-29", "2026-09-16"]

    # First meeting: cut=0.10, hold=0.70, hike=0.20 (after renormalisation).
    first = rows[0]
    assert first["cut_25bp"] == pytest.approx(0.10, abs=1e-6)
    assert first["hold"] == pytest.approx(0.70, abs=1e-6)
    assert first["hike_25bp"] == pytest.approx(0.20, abs=1e-6)
    # implied_change_bp = -25*0.10 + 25*0.20 = +2.5
    assert first["implied_change_bp"] == pytest.approx(2.5, abs=1e-3)
    assert first["source_mode"] == "cme_fedwatch"

    # Multi-bucket cut collapses to 0.60 (25+35), hike to 0.10.
    second = rows[1]
    assert second["cut_25bp"] == pytest.approx(0.60, abs=1e-6)
    assert second["hold"] == pytest.approx(0.30, abs=1e-6)
    assert second["hike_25bp"] == pytest.approx(0.10, abs=1e-6)

    # Multi-bucket hike collapses to 0.80 (55+25).
    third = rows[2]
    assert third["cut_25bp"] == pytest.approx(0.0, abs=1e-6)
    assert third["hold"] == pytest.approx(0.20, abs=1e-6)
    assert third["hike_25bp"] == pytest.approx(0.80, abs=1e-6)


def test_wirp_falls_back_modeled_when_cme_unavailable() -> None:
    adapter = _StubCMEAdapter(RuntimeError("network unreachable"))
    result = _execute_with_adapter(adapter, central_bank="FED", meetings=3)

    assert result.data["data_mode"] == "modeled", result.data
    assert "cme_fedwatch" not in result.sources
    assert "reference_rate_probability_table" in result.sources
    assert "reference_rate_probability_table" in result.data["provenance"]["sources"]
    # Adapter failure must show up in warnings so the UI can pill it.
    assert any("cme_fedwatch" in w for w in result.warnings), result.warnings
    assert any("network unreachable" in w for w in result.warnings), result.warnings
    # Existing fallback warning still fires.
    assert any("not configured" in w for w in result.warnings), result.warnings
    # Rows come from the reference table.
    assert result.data["rows"][0]["source_mode"] == "reference_rate_probability_table"


def test_wirp_falls_back_when_cme_returns_empty_payload() -> None:
    """An adapter that responds successfully but yields no usable meetings
    must still degrade to the reference table with a warning."""
    adapter = _StubCMEAdapter({"meetings": []})
    result = _execute_with_adapter(adapter, central_bank="FED", meetings=3)

    assert result.data["data_mode"] == "modeled"
    assert "cme_fedwatch" not in result.sources
    assert any("no usable" in w for w in result.warnings), result.warnings


def test_wirp_probs_still_sum_to_one_with_cme() -> None:
    """The manifest's ``wirp_probs_sum_to_one`` semantic invariant must
    hold on the CME path as well as the reference path."""
    adapter = _StubCMEAdapter(_canned_payload())
    result = _execute_with_adapter(adapter, central_bank="FED", meetings=3)

    for row in result.data["rows"]:
        total = row["cut_25bp"] + row["hold"] + row["hike_25bp"]
        assert abs(total - 1.0) < 1e-6, row


def test_wirp_non_fed_bank_skips_cme_adapter() -> None:
    """CME FedWatch only covers the Fed — ECB/BOE must take the
    deterministic path without touching the adapter."""

    class _ShouldNotBeCalled:
        async def probabilities(self) -> dict[str, Any]:  # pragma: no cover
            raise AssertionError("CME adapter must not be queried for non-FED banks")

    deps = FunctionDeps()
    deps.cme_fedwatch = _ShouldNotBeCalled()
    fn = WIRPFunction(deps=deps)
    result = asyncio.run(fn.execute(central_bank="ECB", meetings=3))

    assert result.data["data_mode"] == "modeled"
    assert "cme_fedwatch" not in result.sources
    for row in result.data["rows"]:
        total = row["cut_25bp"] + row["hold"] + row["hike_25bp"]
        assert abs(total - 1.0) < 1e-6, row


def test_wirp_no_adapter_at_all_still_falls_back() -> None:
    """No adapter wired ➜ deterministic path, no crash."""
    result = asyncio.run(WIRPFunction().execute(central_bank="FED", meetings=3))
    assert result.data["data_mode"] == "modeled"
    assert "reference_rate_probability_table" in result.sources
