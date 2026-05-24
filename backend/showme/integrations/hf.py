"""HF classify + rule-based explain primitives.

Reuses XSEN's bundled RoBERTa for classification. No new model download.
"""
import hashlib
import logging
import time
from typing import Any

LOG = logging.getLogger("showme.integrations.hf")

_PIPELINE = None
_HF_CACHE: dict[str, tuple[float, dict]] = {}
_HF_TTL = 3600.0


def _get_pipeline():
    """Lazy-init the sentiment pipeline using showMe's bundled model.

    showMe's XSEN does not expose ``_ensure_sentiment_pipeline()``; it uses an
    ``XAnalyzer`` singleton whose ``classify([text])`` returns a list of
    ``{sentiment, sentiment_probs, ...}`` dicts. We wrap that into a HF-style
    callable ``pipe(text, top_k=3, truncation=True)`` returning
    ``[{label, score}, ...]`` so downstream code stays HF-pipeline-shaped.

    Returns ``None`` if the bundled model is unavailable.
    """
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    try:
        from showme.x_analysis import XAnalyzer

        analyzer = XAnalyzer.instance()
        # Force load now so we surface model-unavailability synchronously
        # (rather than at first classify call).
        analyzer._ensure_loaded()

        labels = analyzer.label_options().get("sentiment") or []

        def _pipe(text: str, top_k: int = 3, truncation: bool = True):
            results = analyzer.classify([text])
            if not results:
                return []
            row = results[0]
            probs = row.get("sentiment_probs") or []
            label_list = labels or [str(i) for i in range(len(probs))]
            paired = [
                {"label": label_list[i] if i < len(label_list) else str(i),
                 "score": float(probs[i])}
                for i in range(len(probs))
            ]
            paired.sort(key=lambda r: r["score"], reverse=True)
            return paired[: max(int(top_k), 1)]

        _PIPELINE = _pipe
    except Exception as exc:  # noqa: BLE001
        LOG.warning("HF pipeline unavailable: %s", exc)
        _PIPELINE = None
    return _PIPELINE


def classify(text: str) -> dict[str, Any]:
    """Sentiment-style classification via the bundled RoBERTa.

    Returns {label, score, top_3}. On model unavailability returns
    {label: "unknown", score: 0, top_3: [], error: str}.
    """
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    now = time.time()
    cached = _HF_CACHE.get(key)
    if cached and (now - cached[0]) < _HF_TTL:
        return cached[1]
    pipe = _get_pipeline()
    if pipe is None:
        result = {"label": "unknown", "score": 0.0, "top_3": [], "error": "model unavailable"}
        _HF_CACHE[key] = (now, result)
        return result
    try:
        out = pipe(text, top_k=3, truncation=True)
        if isinstance(out, list) and out and isinstance(out[0], list):
            out = out[0]
        top_3 = [{"label": r["label"], "score": float(r["score"])} for r in out]
        best = max(top_3, key=lambda r: r["score"])
        result = {"label": best["label"], "score": best["score"], "top_3": top_3}
    except Exception as exc:  # noqa: BLE001
        result = {"label": "unknown", "score": 0.0, "top_3": [], "error": str(exc)}
    _HF_CACHE[key] = (now, result)
    return result


def explain(spec: dict[str, Any]) -> str:
    """Rule-based NL summary of a StrategySpec dict. Deterministic, no LLM."""
    name = spec.get("name") or "(isimsiz)"
    tf = spec.get("timeframe") or "1h"
    indicators = spec.get("indicators") or []
    entry_rules = spec.get("entry_rules") or []
    exit_rules = spec.get("exit_rules") or []
    entry_logic = spec.get("entry_logic") or "all"
    exit_logic = spec.get("exit_logic") or "any"
    position = spec.get("position") or {}

    parts: list[str] = []
    parts.append(f"**{name}** stratejisi {tf} timeframe'inde çalışır.")
    if indicators:
        ind_summary = ", ".join(
            f"{i.get('alias', '?')}={i.get('id', '?')}"
            + (f"({','.join(f'{k}={v}' for k,v in (i.get('params') or {}).items())})" if i.get("params") else "")
            for i in indicators
        )
        parts.append(f"Kullanılan indikatörler: {ind_summary}.")
    if entry_rules:
        rules_str = " VE ".join(_rule_to_tr(r) for r in entry_rules) if entry_logic == "all" \
                   else " VEYA ".join(_rule_to_tr(r) for r in entry_rules)
        parts.append(f"Pozisyon açar: {rules_str}.")
    if exit_rules:
        rules_str = " VE ".join(_rule_to_tr(r) for r in exit_rules) if exit_logic == "all" \
                   else " VEYA ".join(_rule_to_tr(r) for r in exit_rules)
        parts.append(f"Pozisyon kapatır: {rules_str}.")
    side = position.get("side") or "long"
    sz = position.get("sizing_value")
    if sz:
        parts.append(f"Yön: {side}, büyüklük: {sz} {position.get('sizing_kind') or 'fixed_quote'}.")
    sl = position.get("stop_loss_pct")
    if sl:
        parts.append(f"Stop loss: %{sl}.")
    return " ".join(parts)


def _rule_to_tr(rule: dict[str, Any]) -> str:
    kind = rule.get("kind") or ""
    left = rule.get("left") or "?"
    right = rule.get("right") or "?"
    if kind == "crosses_above":
        return f"{left} {right}'i yukarı kestiğinde"
    if kind == "crosses_below":
        return f"{left} {right}'i aşağı kestiğinde"
    if kind == "greater_than":
        return f"{left} > {right}"
    if kind == "less_than":
        return f"{left} < {right}"
    if kind == "equals_approximately":
        tol = rule.get("tolerance") or 0
        return f"{left} ≈ {right} (±{tol})"
    return f"{kind} {left} {right}"
