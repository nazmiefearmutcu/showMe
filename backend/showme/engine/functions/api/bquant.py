"""BQuant — JupyterLab bridge readiness (probe-based, no execution).

Readiness is decided by evidence, not by flags:
  * the notebook route must answer an HTTP probe on a loopback address
    (the Jupyter base URL comes from ``SHOWME_JUPYTER_URL``, set by the launcher);
  * kernel-module availability is checked by importing module specs;
  * example notebooks are scanned in ``examples_dir``.
The caller's ``jupyter_running`` hint is informational only.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


_KERNEL_MODULES = ("showme.data", "showme.functions", "showme.portfolio")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_PROBE_TIMEOUT_S = 2.0
_BASE_URL_ENV = "SHOWME_JUPYTER_URL"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _backend_root() -> Path:
    # backend/showme/engine/functions/api/bquant.py -> backend/
    return Path(__file__).resolve().parents[4]


def _examples_dir(value: Any) -> Path:
    path = Path(str(value or "examples"))
    return path if path.is_absolute() else _backend_root() / path


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _probe_target(notebook_url: str, base_url: str | None) -> tuple[str | None, str | None]:
    """Return (url_to_probe, None) or (None, reason) when no loopback target exists."""
    if notebook_url.startswith(("http://", "https://")):
        url = notebook_url
    elif base_url:
        url = base_url.rstrip("/") + "/" + notebook_url.lstrip("/")
    else:
        return None, (
            f"No Jupyter server address is known to the sidecar ({_BASE_URL_ENV} is unset), "
            "so the notebook route cannot be probed."
        )
    host = urlparse(url).hostname or ""
    if host not in _LOOPBACK_HOSTS:
        return None, f"Probe refused: {host or 'the target'} is not a loopback host."
    return url, None


async def _probe_notebook(url: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S, follow_redirects=False) as client:
            response = await client.get(url)
    except Exception as exc:  # noqa: BLE001 - any transport failure means not reachable
        return False, f"GET {url} failed ({type(exc).__name__})"
    if response.status_code < 400:
        return True, f"GET {url} returned HTTP {response.status_code}"
    return False, f"GET {url} returned HTTP {response.status_code}"


@FunctionRegistry.register
class BQuantFunction(BaseFunction):
    code = "BQUANT"
    name = "BQuant Notebook"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        notebook_url = str(params.get("notebook_url") or "/notebook")
        caller_hint = _truthy(params.get("jupyter_running"))
        base_url = os.environ.get(_BASE_URL_ENV) or None

        probe_url, no_target_reason = _probe_target(notebook_url, base_url)
        if probe_url is not None:
            reachable, probe_detail = await _probe_notebook(probe_url)
            probe_result = "reachable" if reachable else "unreachable"
            sources = ["local_notebook_manifest", "jupyter_http_probe"]
        else:
            reachable, probe_detail = False, no_target_reason or "No probe target."
            probe_result = "no_target"
            sources = ["local_notebook_manifest"]

        kernel_found = [name for name in _KERNEL_MODULES if _module_available(name)]
        kernel_all = len(kernel_found) == len(_KERNEL_MODULES)

        examples_root = _examples_dir(params.get("examples_dir"))
        example_files = (
            sorted(p.name for p in examples_root.glob("*.ipynb")) if examples_root.is_dir() else []
        )

        ready = reachable
        route_row = {
            "component": "Notebook route",
            "status": "configured" if ready else "not_configured",
            "value": probe_url or notebook_url,
            "action": f"{probe_detail}.",
        }
        kernel_row = {
            "component": "Kernel modules",
            "status": "available" if kernel_all else "missing",
            "value": ", ".join(_KERNEL_MODULES),
            "action": (
                "Import these modules in a notebook cell."
                if kernel_all
                else "Not importable in the sidecar: "
                + ", ".join(name for name in _KERNEL_MODULES if name not in kernel_found)
                + "."
            ),
        }
        examples_row = {
            "component": "Examples",
            "status": "found" if example_files else "missing",
            "value": (
                ", ".join(f"{examples_root.name}/{name}" for name in example_files)
                if example_files
                else f"No .ipynb files in {examples_root}"
            ),
            "action": (
                "Notebooks found locally; running them still needs a mounted Jupyter server."
                if example_files
                else "Create or mount notebooks before treating this as an executable notebook surface."
            ),
        }
        rows = [route_row, kernel_row, examples_row]

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok" if ready else "not_configured",
                "reason": None if ready else probe_detail,
                "next_actions": [] if ready else [
                    f"Start a Jupyter server from the ShowMe launcher and set {_BASE_URL_ENV} to its loopback address.",
                    "Make sure the notebook route answers the probe (HTTP status below 400).",
                ],
                "rows": rows,
                "summary": {
                    "notebook_ready": ready,
                    "notebook_url": notebook_url,
                    "probe_result": probe_result,
                    "examples_found": len(example_files),
                    "preloaded_modules": len(kernel_found),
                    "caller_jupyter_hint": caller_hint,
                },
                "methodology": (
                    "BQUANT reports ok only when the notebook route answers a short loopback HTTP probe. "
                    "The caller's jupyter_running hint is recorded but does not change readiness. Kernel "
                    "modules are reported available only when they import; example notebooks are the .ipynb "
                    "files found in examples_dir."
                ),
                "field_dictionary": {
                    "component": "Notebook integration surface being checked.",
                    "status": "Readiness of that component, from a probe or an import check.",
                    "value": "Probed route, module names, or example files found.",
                    "action": "Probe result or concrete next step for the user.",
                    "probe_result": "reachable, unreachable, or no_target (no loopback address to probe).",
                    "preloaded_modules": "Count of kernel modules that import successfully.",
                },
            },
            sources=sources,
        )
