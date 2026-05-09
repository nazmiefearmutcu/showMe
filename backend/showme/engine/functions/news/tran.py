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
            raise ValueError
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
        # Optional Whisper transcription
        whisper_result = None
        audio_url = params.get("audio_url")
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
        audio_path = params.get("audio_path")
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
        allow_synthetic = _truthy(params.get("allow_synthetic"))
        if not items and not whisper_result and not allow_synthetic:
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
                        "Use allow_synthetic=true only when you explicitly want template data.",
                    ],
                },
                sources=sources,
                metadata={
                    "provider_errors": warnings or ["transcript providers returned no usable rows"],
                    "live": live,
                },
            )
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "transcripts": items or _template_transcripts(instrument),
                "whisper": whisper_result,
            },
            sources=sources or ["transcript_template"],
            metadata={"provider_errors": warnings, "live": live},
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
