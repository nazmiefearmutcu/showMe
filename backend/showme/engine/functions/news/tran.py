"""TRAN — Earnings Call Transcripts (best-effort, IR site fallback)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class TRANFunction(BaseFunction):
    code = "TRAN"
    name = "Earnings Call Transcripts"
    asset_classes = (AssetClass.EQUITY,)
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError(
                "TRAN requires an instrument — pass `symbol=<ticker>` or open the pane via "
                "the symbol search so an earnings call transcript can be located."
            )
        items: list = []
        sources: list[str] = []
        warnings: list[str] = []
        live = _truthy(params.get("live_transcripts") or params.get("live_news") or params.get("live"))
        if live and self.deps.seekingalpha:
            try:
                items = await asyncio.wait_for(
                    self.deps.seekingalpha.transcripts(instrument.symbol),
                    timeout=float(params.get("transcript_timeout", 8)),
                )
                sources.append("seekingalpha")
            except Exception as e:
                warnings.append(f"seekingalpha: {e}")
        # Optional Whisper transcription. Tier 0 is the bundled
        # ``openai/whisper-large-v3`` singleton (see whisper_analyzer.py);
        # the legacy tiered service is consulted automatically if it isn't
        # warmed yet. When the caller asked for Whisper but the singleton
        # hasn't finished loading we still attempt the legacy tiers, but
        # add an explicit warning so the UI can hint the user to retry in
        # ~30s once large-v3 is ready (load failure is permanent for the
        # process; warm-pending is transient).
        whisper_result = None
        audio_url = params.get("audio_url")
        audio_path = params.get("audio_path")
        if audio_url or audio_path:
            try:
                from showme.whisper_analyzer import WhisperAnalyzer  # noqa: PLC0415
                if not WhisperAnalyzer.is_available() and WhisperAnalyzer.load_error() is None:
                    warnings.append("whisper: large-v3 not yet warmed, retry in ~30s")
            except Exception:  # noqa: BLE001 - singleton optional
                pass
        if audio_url:
            try:
                from showme.engine.services.transcription import transcribe_url
                whisper_result = await transcribe_url(
                    audio_url, language=params.get("language"),
                    model_name=params.get("model", "base"),
                )
                sources.append("whisper")
            except Exception as e:
                warnings.append(f"whisper: {e}")
        if audio_path and not whisper_result:
            try:
                from showme.engine.services.transcription import transcribe
                whisper_result = await transcribe(
                    audio_path, language=params.get("language"),
                    model_name=params.get("model", "base"),
                )
                sources.append("whisper")
            except Exception as e:
                warnings.append(f"whisper local: {e}")
        # BugHunt 2026-05-24: previously TRAN happily emitted a hardcoded
        # "Prepared remarks template" while attributing the data to
        # `sources=["seekingalpha"]` whenever `allow_synthetic=true` was set.
        # That looked like a real provider response to downstream callers.
        # We now ignore the legacy `allow_synthetic` switch and only emit the
        # template behind an explicit `include_synthetic=true` query, with
        # honest sourcing/data_state metadata so consumers cannot mistake the
        # placeholder for real Seeking Alpha content.
        include_synthetic = _truthy(params.get("include_synthetic"))
        if not items and not whisper_result and not include_synthetic:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": f"No live earnings call transcript returned for {instrument.symbol}.",
                    "transcripts": [],
                    "whisper": None,
                    "next_actions": [
                        "Enable a transcript provider or pass audio_url/audio_path.",
                        "Pass include_synthetic=true to opt into the placeholder template (clearly labelled).",
                    ],
                },
                sources=sources,
                metadata={
                    "provider_errors": warnings or ["transcript providers returned no usable rows"],
                    "live": live,
                    "data_state": "provider_unavailable",
                },
            )
        if not items and not whisper_result and include_synthetic:
            # Explicitly synthetic — disclose it via sources and data_state so
            # callers do not mistake the placeholder for a real transcript.
            template = _template_transcripts(instrument)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "synthetic",
                    "transcripts": template,
                    "whisper": whisper_result,
                    "reason": (
                        f"Returning synthetic placeholder for {instrument.symbol} because "
                        "include_synthetic=true was set and no provider returned a real transcript."
                    ),
                },
                sources=["showme_synthetic_template"],
                metadata={
                    "provider_errors": warnings,
                    "live": live,
                    "data_state": "synthetic",
                    "synthetic": True,
                },
            )
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "transcripts": items,
                "whisper": whisper_result,
                "status": "ok",
            },
            sources=sources or ["transcript_template"],
            metadata={"provider_errors": warnings, "live": live, "data_state": "ok"},
        )


def _template_transcripts(instrument: Instrument) -> list[dict[str, Any]]:
    asset_class = instrument.asset_class.value
    if asset_class != "EQUITY":
        return [{
            "symbol": instrument.symbol,
            "title": "Transcript feed not applicable",
            "status": f"not_applicable_for_{asset_class.lower()}",
            "sections": [],
        }]
    return [{
        "symbol": instrument.symbol,
        "title": f"{instrument.symbol} earnings call transcript template",
        "status": "local_model",
        "sections": [
            {"speaker": "Operator", "text": "Prepared remarks and Q&A sections are available when live_transcripts is enabled."},
            {"speaker": "Management", "text": "Revenue, margin, guidance, and risk commentary placeholders are structured for downstream search."},
        ],
    }]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
