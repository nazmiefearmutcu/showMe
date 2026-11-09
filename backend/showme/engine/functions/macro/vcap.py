"""VCAP — source-aware venture capital research and local dataset imports."""
from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services.vcap.models import InputError, Query
from showme.engine.services.vcap.service import VCAPService


@FunctionRegistry.register
class VCAPFunction(BaseFunction):
    code = "VCAP"
    name = "Venture Capital Research"
    category = "macro"
    description = "Source-specific global, country, Turkey and crypto investment with provenance and immutable local imports."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        service = VCAPService()
        try:
            if any(key in params for key in ("path", "file", "file_path", "url", "fetch_url")):
                raise InputError("VCAP accepts a dataset object, never a filesystem path or fetch URL")
            action = params.get("action", "query")
            if action == "query":
                data, metadata = await service.query(Query.parse(params))
            elif action == "import":
                data, metadata = service.import_dataset(params.get("dataset"))
            elif action == "versions":
                data, metadata = service.versions(params.get("source_id"))
            else:
                raise InputError("action must be query, import or versions")
        except InputError as exc:
            data = service.base()
            data.update(status="input_error", reason=str(exc), next_actions=["Correct the query or schema version 1 dataset and retry."])
            metadata = {"data_mode": "unavailable", "cached": False, "stale": False}
        sources = [f"reference_vcap:{sid}" for sid in sorted({r["source_id"] for r in data["rows"]})]
        # Import/versions are local operations with no upstream rows. Their
        # source markers describe provenance, never synthetic/live fallbacks.
        if not sources and data["status"] == "ok":
            sources = ["reference_vcap_local_store"]
        # Annual reported observations/local releases are reference data, not
        # a live market feed. Preserve that distinction through shared sanitizer.
        metadata["live"] = False
        metadata["data_state"] = "reference"
        return FunctionResult(code=self.code, instrument=None, data=data,
                              metadata=metadata, sources=sources,
                              warnings=data.get("warnings", []))
