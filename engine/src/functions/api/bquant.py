"""BQuant — JupyterLab embed pointer (real launch by run_dashboard.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class BQuantFunction(BaseFunction):
    code = "BQUANT"
    name = "BQuant Notebook"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        notebook_url = str(params.get("notebook_url") or "/notebook")
        example_paths = ["examples/01_quickstart.ipynb", "examples/02_backtest.ipynb"]
        existing_examples = [path for path in example_paths if Path(path).exists()]
        configured = bool(params.get("jupyter_running") or existing_examples)
        rows = [
            {
                "component": "Notebook route",
                "status": "configured" if configured else "not_configured",
                "value": notebook_url,
                "action": "Open only after a Jupyter server is mounted by the launcher.",
            },
            {
                "component": "Kernel modules",
                "status": "available",
                "value": "showme.data, showme.functions, showme.portfolio",
                "action": "Import these modules in a notebook cell.",
            },
            {
                "component": "Examples",
                "status": "found" if existing_examples else "missing",
                "value": ", ".join(existing_examples or example_paths),
                "action": "Create or mount notebooks before treating this as an executable notebook surface.",
            },
        ]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok" if configured else "not_configured",
                "reason": None if configured else "No mounted Jupyter runtime or local example notebooks were detected.",
                "next_actions": [] if configured else [
                    "Start a Jupyter server from the ShowMe launcher before using BQUANT.",
                    "Mount /notebook or provide a reachable notebook_url in Advanced params.",
                ],
                "rows": rows,
                "summary": {
                    "notebook_ready": configured,
                    "notebook_url": notebook_url,
                    "examples_found": len(existing_examples),
                    "preloaded_modules": 3,
                },
                "methodology": (
                    "BQUANT is a local notebook bridge manifest. It should not claim execution readiness unless "
                    "a Jupyter route or local notebook examples are actually available to the packaged sidecar."
                ),
                "field_dictionary": {
                    "component": "Notebook integration surface being checked.",
                    "status": "Readiness of that component.",
                    "value": "Route, module list, or example path.",
                    "action": "Concrete next step for the user.",
                },
            },
            sources=["local_notebook_manifest"],
        )
