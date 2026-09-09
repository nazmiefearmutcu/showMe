"""R2 L-2 regression: CRVF monthly-bill FRED ids must survive the pipeline.

The keyed FRED adapter path can serve the monthly Treasury-bill series
``DGS1MO`` / ``DGS2MO`` / ``DGS4MO``. Those raw ids used to fall through
CRVF's ``_SERIES_TO_TENOR`` mapping unmapped, then die in
``_curve_payload``'s ``if tenor in _TENOR_YEARS`` filter — silently
dropping the short end of the live curve. Contract after the fix: every
DGS id in the mapping maps to a tenor label that passes the filter, with
fractional-year maturities (1/12, 2/12, 4/12) end-to-end.

Offline: no provider I/O — the mapping + payload pipeline is exercised
directly, then end-to-end through CRVFFunction with a keyed-adapter fake.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.bond.crvf import (  # noqa: E402
    _SERIES_TO_TENOR,
    _TENOR_YEARS,
    _curve_payload,
    CRVFFunction,
)

_MONTHLY_IDS = {"DGS1MO": "1M", "DGS2MO": "2M", "DGS4MO": "4M"}
_FRACTIONAL_YEARS = {"1M": 1 / 12, "2M": 2 / 12, "4M": 4 / 12}


def _run(coro):
    return asyncio.run(coro)


def test_every_mapped_dgs_id_survives_the_payload_filter():
    """All DGS ids in _SERIES_TO_TENOR map to a tenor that passes the
    ``tenor in _TENOR_YEARS`` filter — no silent drops."""
    curve = {sid: 4.0 + i * 0.1 for i, sid in enumerate(sorted(_SERIES_TO_TENOR))}
    mapped = {
        _SERIES_TO_TENOR.get(k, k): v
        for k, v in curve.items()
        if v is not None and v == v
    }
    payload = _curve_payload("US", mapped, "fred")
    tenors = {row["tenor"] for row in payload["rows"]}
    assert tenors == set(mapped), (
        f"mapped tenors dropped by the pipeline filter: "
        f"{set(mapped.values()) - tenors}"
    )
    assert payload["summary"]["tenors"] == len(mapped)


def test_monthly_tenors_map_to_fractional_years():
    assert _MONTHLY_IDS.items() <= _SERIES_TO_TENOR.items()
    for tenor, years in _FRACTIONAL_YEARS.items():
        assert tenor in _TENOR_YEARS
        assert _TENOR_YEARS[tenor] == years
    payload = _curve_payload(
        "US", {t: 5.0 for t in _MONTHLY_IDS.values()}, "fred"
    )
    years_by_tenor = {row["tenor"]: row["tenor_years"] for row in payload["rows"]}
    assert years_by_tenor == _FRACTIONAL_YEARS
    # The curve is maturity-ordered: the monthly bills sort before 3M.
    ordered = [row["tenor"] for row in payload["rows"]]
    assert ordered == sorted(ordered, key=lambda t: _TENOR_YEARS[t])


def test_crvf_keyed_adapter_monthly_ids_end_to_end():
    """End-to-end: a keyed adapter that returns the full DGS set including
    the monthly bills produces live rows for ALL of them."""

    class _KeyedFred:
        async def yield_curve(self) -> dict[str, float]:
            curve = {sid: 4.2 for sid in _SERIES_TO_TENOR}
            curve["DGS1MO"] = 5.31
            curve["DGS2MO"] = 5.30
            curve["DGS4MO"] = 5.28
            return curve

    result = _run(CRVFFunction(FunctionDeps(fred=_KeyedFred())).execute())
    metadata = result.metadata or {}
    assert metadata.get("live") is True
    assert metadata.get("data_mode") == "live_official"
    assert result.sources == ["fred"]
    assert not result.warnings
    rows = {row["tenor"]: row["yield"] for row in result.data["rows"]}
    for tenor, years in _FRACTIONAL_YEARS.items():
        assert tenor in rows, f"monthly tenor {tenor} silently dropped end-to-end"
    assert rows["1M"] == 5.31 and rows["2M"] == 5.30 and rows["4M"] == 5.28
    assert len(rows) == len(_SERIES_TO_TENOR)
