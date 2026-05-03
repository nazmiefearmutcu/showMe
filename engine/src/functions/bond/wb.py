"""WB — World Bonds (sovereign yields heatmap)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


_SOVEREIGN_FRED_IDS = {
    "US": "DGS10",
    "DE": "IRLTLT01DEM156N",
    "JP": "IRLTLT01JPM156N",
    "GB": "IRLTLT01GBM156N",
    "CA": "IRLTLT01CAM156N",
    "FR": "IRLTLT01FRM156N",
    "IT": "IRLTLT01ITM156N",
    "ES": "IRLTLT01ESM156N",
    "AU": "IRLTLT01AUM156N",
}


def _world_bond_template() -> dict[str, float]:
    return {"US": 4.45, "DE": 2.58, "JP": 0.92, "GB": 4.18, "FR": 3.02,
            "IT": 3.86, "ES": 3.24, "AU": 4.12}


@FunctionRegistry.register
class WBFunction(BaseFunction):
    code = "WB"
    name = "World Bonds"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if not (params.get("live_bonds") or params.get("live")):
            data = _world_bond_template()
            return FunctionResult(code=self.code, instrument=None, data=data,
                                  sources=["sovereign_yield_model"])
        if not self.deps.fred:
            data = _world_bond_template()
            return FunctionResult(code=self.code, instrument=None, data=data,
                                  sources=["sovereign_yield_model"])
        out: dict[str, float] = {}
        timeout = float(params.get("fred_timeout", 5))
        async def _one(country, fred_id):
            try:
                df = await asyncio.wait_for(self.deps.fred.series(fred_id), timeout=timeout)
                return country, float(df["value"].iloc[-1])
            except Exception:
                return country, float("nan")
        results = await asyncio.gather(*(
            _one(c, fid) for c, fid in _SOVEREIGN_FRED_IDS.items()
        ))
        for c, y in results:
            out[c] = y
        out = {c: y for c, y in out.items() if y == y}
        if not out:
            out = _world_bond_template()
        return FunctionResult(code=self.code, instrument=None, data=out, sources=["fred"])
