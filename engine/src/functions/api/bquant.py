"""BQuant — JupyterLab embed pointer (real launch by run_dashboard.py)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class BQuantFunction(BaseFunction):
    code = "BQUANT"
    name = "BQuant Notebook"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        return FunctionResult(code=self.code, instrument=None,
                              data={"jupyter_url": "/notebook",
                                    "preloaded_modules": ["showme.data", "showme.functions",
                                                          "showme.portfolio"],
                                    "examples": ["examples/01_quickstart.ipynb",
                                                 "examples/02_backtest.ipynb"]})
