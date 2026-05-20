"""ANR — Analyst Recommendations + Price Target."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import finite


BUCKETS: tuple[tuple[str, str, int], ...] = (
    ("strongBuy", "Strong Buy", 5),
    ("buy", "Buy", 4),
    ("hold", "Hold", 3),
    ("sell", "Sell", 2),
    ("strongSell", "Strong Sell", 1),
)


def _today() -> datetime:
    return datetime.now(timezone.utc)


def _date_from_row(row: dict[str, Any]) -> datetime | None:
    raw = (
        row.get("period")
        or row.get("date")
        or row.get("lastUpdate")
        or row.get("last_updated")
        or row.get("updatedAt")
    )
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    text = str(raw).strip()
    if not text or text.lower() in {"latest", "none", "nan"}:
        return None
    lower = text.lower()
    if lower.endswith("m") and lower[:-1].lstrip("-").isdigit():
        months = int(lower[:-1] or "0")
        return _today() + timedelta(days=months * 30)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(text[:10] if fmt != "%Y-%m" else text[:7], fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _bucket_count(row: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(row.get(key) or 0))
    except Exception:
        return 0


def _aggregate_recommendations(rows: list[dict[str, Any]]) -> dict[str, int]:
    totals = {key: 0 for key, _, _ in BUCKETS}
    for row in rows:
        for key, _, _ in BUCKETS:
            totals[key] += _bucket_count(row, key)
    return totals


def _consensus_score(totals: dict[str, int]) -> float | None:
    total = sum(totals.values())
    if total <= 0:
        return None
    weighted = sum(totals[key] * score for key, _, score in BUCKETS)
    return round(weighted / total, 2)


def _consensus_label(score: float | None) -> str:
    if score is None:
        return "No consensus"
    if score >= 4.2:
        return "Strong Buy"
    if score >= 3.6:
        return "Buy-leaning"
    if score >= 2.8:
        return "Neutral"
    if score >= 2.2:
        return "Sell-leaning"
    return "Strong Sell"


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((part / total) * 100.0, 1)


def _target_source(target: dict[str, Any], spot: float | None) -> tuple[str, str, bool]:
    mode = str(target.get("source_mode") or "")
    if mode == "price_target_unavailable_no_spot":
        return "target_price_unavailable", "Target price unavailable", True
    if mode.startswith("price_target_reference"):
        if spot is not None:
            return "derived_reference_range_from_spot", "Derived reference range from spot", True
        return "target_price_unavailable", "Target price unavailable", True
    return "live_analyst_targets", "Live analyst targets", False


def _target_rows(target: dict[str, Any], source_mode: str, not_analyst_target: bool) -> list[dict[str, Any]]:
    mapping = (
        ("targetHigh", "High target"),
        ("targetMean", "Mean target"),
        ("targetMedian", "Median target"),
        ("targetLow", "Low target"),
    )
    return [
        {
            "metric": label,
            "price": finite(target.get(key)),
            "source_mode": source_mode,
            "not_analyst_target": not_analyst_target,
        }
        for key, label in mapping
    ]


def _latest_recommendation_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated = [(row, _date_from_row(row)) for row in rows if isinstance(row, dict)]
    dated_values = [dt for _, dt in dated if dt is not None]
    if dated_values:
        latest = max(dated_values)
        return [row for row, dt in dated if dt is not None and dt.date() == latest.date()]
    return [rows[0]] if rows else []


def _yfinance_recommendations(raw: dict[str, Any]) -> list[dict[str, Any]]:
    records = raw.get("recommendations_summary") or raw.get("recommendations") or []
    if not isinstance(records, list):
        return []
    out: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        row = {
            "period": record.get("period") or record.get("Period") or record.get("index"),
            "strongBuy": _bucket_count(record, "strongBuy"),
            "buy": _bucket_count(record, "buy"),
            "hold": _bucket_count(record, "hold"),
            "sell": _bucket_count(record, "sell"),
            "strongSell": _bucket_count(record, "strongSell"),
            "source_mode": "yfinance_recommendations_summary",
        }
        if sum(_bucket_count(row, key) for key, _, _ in BUCKETS) > 0:
            out.append(row)
    return out


def _target_from_yfinance_raw(raw: dict[str, Any]) -> dict[str, Any]:
    target = {
        "targetHigh": finite(raw.get("targetHighPrice")),
        "targetLow": finite(raw.get("targetLowPrice")),
        "targetMean": finite(raw.get("targetMeanPrice")),
        "targetMedian": finite(raw.get("targetMedianPrice")),
        "lastUpdated": _today().date().isoformat(),
        "source_mode": "yfinance_analyst_targets",
    }
    if any(finite(v) for k, v in target.items() if k.startswith("target")):
        return target
    return {}


def _analyst_rows_from_yfinance_raw(raw: dict[str, Any], cutoff: datetime, *, limit: int = 30) -> list[dict[str, Any]]:
    records = raw.get("upgrades_downgrades") or []
    if not isinstance(records, list):
        return []
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        date_raw = record.get("GradeDate") or record.get("Date") or record.get("index")
        dated = _date_from_row({"date": date_raw})
        if dated is not None and dated < cutoff:
            continue
        target = finite(record.get("currentPriceTarget"))
        prior_target = finite(record.get("priorPriceTarget"))
        price_action = str(record.get("priceTargetAction") or "").strip()
        action = str(record.get("Action") or "").strip()
        action_label = " / ".join(part for part in (action, price_action) if part)
        rows.append({
            "broker": record.get("Firm") or record.get("broker") or "Yahoo Finance",
            "analyst": None,
            "rating": record.get("ToGrade") or record.get("rating"),
            "previous_rating": record.get("FromGrade") or record.get("previous_rating"),
            "action": action_label or None,
            "target_price": target if target and target > 0 else None,
            "prior_target_price": prior_target if prior_target and prior_target > 0 else None,
            "target_period": "provider",
            "date": dated.date().isoformat() if dated else str(date_raw or ""),
            "last_update": dated.isoformat() if dated else str(date_raw or ""),
            "source": "yfinance_upgrades_downgrades",
        })
        if len(rows) >= limit:
            break
    return rows


@FunctionRegistry.register
class ANRFunction(BaseFunction):
    code = "ANR"
    name = "Analyst Recommendations"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO)
    category = "equity"
    description = "Equity analyst consensus; crypto için canlı market-consensus proxy."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        """Equity analyst consensus pane.

        Per PY-LINT-04 (R3A): this used to be one CC≈67 mega-function. It now
        delegates to four named stages so each stage can be tested + reasoned
        about independently:

          1. ``_resolve_inputs``  — fetch provider data + fill target ranges.
          2. ``_collect_signals`` — apply the 1-year stale rule, aggregate.
          3. ``_assemble_cards``  — bucket / target / analyst row scaffolding.
          4. ``_compose_result``  — build the final ``FunctionResult``.
        """
        if instrument is None:
            # BUG-HUNT S01: previously raise ValueError which the generic
            # Exception handler in function_index.py converted to a
            # provider_unavailable envelope (misleading). Return an
            # explicit input_required so the contract envelope routes to
            # input_error and the UI prompts for a symbol.
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_required",
                    "reason": "ANR requires a symbol (instrument).",
                    "rows": [],
                    "next_actions": [
                        "Provide a symbol via the function symbol field or Params JSON.",
                    ],
                },
                sources=[],
            )
        if instrument.asset_class == AssetClass.CRYPTO:
            return await self._execute_crypto(instrument, **params)
        inputs = await self._resolve_inputs(instrument, params)
        signals = self._collect_signals(inputs)
        cards = self._assemble_cards(instrument, inputs, signals)
        return self._compose_result(instrument, inputs, signals, cards)

    async def _resolve_inputs(
        self, instrument: Instrument, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Stage 1 — provider fetches (Finnhub + Yahoo) + target fallback."""
        state: dict[str, Any] = {
            "warnings": [],
            "sources": [],
            "recs": [],
            "target": {},
            "spot": None,
            "yfinance_raw": {},
        }
        await self._fetch_finnhub(instrument, state)
        await self._fetch_yfinance(instrument, params, state)
        if not state["recs"] and self.deps.yfinance:
            await self._fetch_yfinance_retry(instrument, params, state)
        if state["recs"] and "yfinance_recommendations" in state["sources"]:
            state["warnings"] = [
                w for w in state["warnings"] if "FINNHUB_API_KEY not set" not in w
            ]
        if not state["recs"]:
            state["warnings"].append(
                "Analyst consensus live feed unavailable; no consensus buckets were fabricated."
            )
        self._fill_target_fallback(state)
        return state

    async def _fetch_finnhub(self, instrument: Instrument, state: dict[str, Any]) -> None:
        try:
            if self.deps.finnhub:
                state["recs"] = await self.deps.finnhub.recommendations(instrument.symbol)
                state["target"] = await self.deps.finnhub.price_target(instrument.symbol)
                state["sources"].append("finnhub")
        except Exception as e:
            state["warnings"].append(f"finnhub: {e}")

    async def _fetch_yfinance(
        self, instrument: Instrument, params: dict[str, Any], state: dict[str, Any]
    ) -> None:
        try:
            if not self.deps.yfinance:
                return
            rd = await self.deps.yfinance.fetch(DataRequest(
                kind=DataKind.REFDATA,
                instrument=instrument,
                extra={
                    "timeout": float(params.get("yfinance_timeout", 24)),
                    "info_timeout": float(params.get("yfinance_info_timeout", 8)),
                    "recommendations_timeout": float(params.get("yfinance_recommendations_timeout", 10)),
                    "actions_timeout": float(params.get("yfinance_actions_timeout", 6)),
                    "include_recommendations": True,
                },
            ))
            yfinance_raw = (rd.extras or {}).get("raw", {}) if hasattr(rd, "extras") else {}
            state["yfinance_raw"] = yfinance_raw
            state["spot"] = finite(
                yfinance_raw.get("currentPrice")
                or yfinance_raw.get("regularMarketPrice")
                or yfinance_raw.get("previousClose")
            )
            yf_recs = _yfinance_recommendations(yfinance_raw)
            if not state["recs"] and yf_recs:
                state["recs"] = yf_recs
                state["sources"].append("yfinance_recommendations")
            yf_target = _target_from_yfinance_raw(yfinance_raw)
            target = state["target"]
            if (not target or not any(finite(v) for v in target.values())) and yf_target:
                state["target"] = yf_target
                state["sources"].append("yfinance_targets")
            if (state["spot"] is not None or yf_recs or yf_target) and "yfinance" not in state["sources"]:
                state["sources"].append("yfinance")
        except Exception as e:
            state["warnings"].append(f"yfinance: {e}")

    async def _fetch_yfinance_retry(
        self, instrument: Instrument, params: dict[str, Any], state: dict[str, Any]
    ) -> None:
        try:
            retry_rd = await self.deps.yfinance.fetch(DataRequest(
                kind=DataKind.REFDATA,
                instrument=instrument,
                extra={
                    "timeout": float(params.get("yfinance_retry_timeout", 40)),
                    "info_timeout": float(params.get("yfinance_retry_info_timeout", 2)),
                    "recommendations_timeout": float(params.get("yfinance_retry_recommendations_timeout", 20)),
                    "actions_timeout": float(params.get("yfinance_retry_actions_timeout", 2)),
                    "include_recommendations": True,
                },
            ))
            retry_raw = (retry_rd.extras or {}).get("raw", {}) if hasattr(retry_rd, "extras") else {}
            retry_recs = _yfinance_recommendations(retry_raw)
            if retry_recs:
                state["yfinance_raw"] = {**state["yfinance_raw"], **retry_raw}
                state["recs"] = retry_recs
                for source in ("yfinance_recommendations", "yfinance"):
                    if source not in state["sources"]:
                        state["sources"].append(source)
            retry_target = _target_from_yfinance_raw(retry_raw)
            target = state["target"]
            if (not target or not any(finite(v) for v in target.values())) and retry_target:
                state["target"] = retry_target
                if "yfinance_targets" not in state["sources"]:
                    state["sources"].append("yfinance_targets")
            if state["spot"] is None:
                state["spot"] = finite(
                    retry_raw.get("currentPrice")
                    or retry_raw.get("regularMarketPrice")
                    or retry_raw.get("previousClose")
                )
        except Exception as e:
            state["warnings"].append(f"yfinance retry: {e}")

    def _fill_target_fallback(self, state: dict[str, Any]) -> None:
        target = state["target"]
        spot = state["spot"]
        if target and any(finite(v) for v in target.values()):
            return
        if spot is not None:
            state["target"] = {
                "targetHigh": round(spot * 1.28, 2),
                "targetLow": round(spot * 0.82, 2),
                "targetMean": round(spot * 1.08, 2),
                "targetMedian": round(spot * 1.06, 2),
                "source_mode": "price_target_reference_from_spot",
            }
        else:
            state["target"] = {
                "targetHigh": None,
                "targetLow": None,
                "targetMean": None,
                "targetMedian": None,
                "source_mode": "price_target_unavailable_no_spot",
            }
        if "analyst_target_reference" not in state["sources"]:
            state["sources"].append("analyst_target_reference")

    def _collect_signals(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Stage 2 — apply the 365-day staleness rule and aggregate buckets."""
        recs = inputs["recs"]
        warnings = inputs["warnings"]
        cutoff = _today() - timedelta(days=365)
        consensus_recs = _latest_recommendation_rows(recs)
        dated_recs = [(row, _date_from_row(row)) for row in consensus_recs if isinstance(row, dict)]
        included = [row for row, dt in dated_recs if dt is None or dt >= cutoff]
        excluded_stale = [row for row, dt in dated_recs if dt is not None and dt < cutoff]
        if consensus_recs and not included:
            warnings.append(
                "All recommendation rows are stale by the one-year rule; consensus totals are zero."
            )

        totals = _aggregate_recommendations(included)
        analyst_count = sum(totals.values())
        score = _consensus_score(totals)
        included_dates = [dt for _, dt in dated_recs if dt is not None and dt >= cutoff]
        stale_dates = [dt for _, dt in dated_recs if dt is not None and dt < cutoff]
        last_updated = max(included_dates).date().isoformat() if included_dates else None
        oldest_included = min(included_dates).date().isoformat() if included_dates else None
        stale_rule = {
            "cutoff_days": 365,
            "cutoff_date": cutoff.date().isoformat(),
            "included_count": analyst_count,
            "excluded_stale_count": sum(_aggregate_recommendations(excluded_stale).values()),
            "oldest_included_rating_date": oldest_included,
            "oldest_stale_rating_date": min(stale_dates).date().isoformat() if stale_dates else None,
            "undated_provider_rows": sum(1 for _, dt in dated_recs if dt is None),
            "rule": "Recommendation rows older than one year are excluded from consensus.",
        }
        return {
            "cutoff": cutoff,
            "consensus_recs": consensus_recs,
            "totals": totals,
            "analyst_count": analyst_count,
            "score": score,
            "last_updated": last_updated,
            "oldest_included": oldest_included,
            "stale_rule": stale_rule,
        }

    def _assemble_cards(
        self,
        instrument: Instrument,
        inputs: dict[str, Any],
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        """Stage 3 — bucket / target / analyst row scaffolding + summary card."""
        totals = signals["totals"]
        analyst_count = signals["analyst_count"]
        target = inputs["target"]
        spot = inputs["spot"]
        positive = totals["strongBuy"] + totals["buy"]
        neutral = totals["hold"]
        negative = totals["sell"] + totals["strongSell"]
        target_source_mode, target_source_label, not_analyst_target = _target_source(target, spot)
        target_rows = _target_rows(target, target_source_mode, not_analyst_target)
        bucket_rows = [
            {
                "bucket": label,
                "count": totals[key],
                "sentiment_score": score_value,
                "pct_of_consensus": _pct(totals[key], analyst_count),
                "included_in_consensus": True,
            }
            for key, label, score_value in BUCKETS
        ]
        analyst_rows = _analyst_rows_from_yfinance_raw(inputs["yfinance_raw"], signals["cutoff"])
        if analyst_rows:
            analyst_detail_status = "broker_actions_available"
            analyst_detail_reason = (
                "Yahoo Finance supplied recent broker rating actions. Named analyst identifiers "
                "are not supplied by this provider."
            )
        else:
            analyst_detail_status = "provider_not_configured"
            analyst_detail_reason = (
                "The configured provider returns aggregate recommendation buckets, not "
                "broker/analyst-level ratings. ShowMe does not fabricate broker rows."
            )
        summary = {
            "title": f"{instrument.symbol} Analyst Consensus",
            "analyst_count": analyst_count,
            "consensus_score": signals["score"],
            "label": _consensus_label(signals["score"]),
            "positive_pct": _pct(positive, analyst_count),
            "neutral_pct": _pct(neutral, analyst_count),
            "negative_pct": _pct(negative, analyst_count),
            "last_updated": signals["last_updated"],
            "included_count": analyst_count,
            "excluded_stale_count": signals["stale_rule"]["excluded_stale_count"],
            "oldest_included_rating_date": signals["oldest_included"],
            "target_price_source": target_source_label,
            "target_price_source_mode": target_source_mode,
            "not_analyst_target": not_analyst_target,
            "analyst_detail_status": analyst_detail_status,
        }
        sources = inputs["sources"]
        if "finnhub" in sources:
            consensus_source = "finnhub"
        elif "yfinance_recommendations" in sources:
            consensus_source = "yfinance_recommendations"
        else:
            consensus_source = "provider_unavailable"
        summary["consensus_source"] = consensus_source
        return {
            "summary": summary,
            "bucket_rows": bucket_rows,
            "target_rows": target_rows,
            "analyst_rows": analyst_rows,
            "analyst_detail_status": analyst_detail_status,
            "analyst_detail_reason": analyst_detail_reason,
            "consensus_source": consensus_source,
            "target_source_mode": target_source_mode,
            "target_source_label": target_source_label,
            "not_analyst_target": not_analyst_target,
        }

    def _compose_result(
        self,
        instrument: Instrument,
        inputs: dict[str, Any],
        signals: dict[str, Any],
        cards: dict[str, Any],
    ) -> FunctionResult:
        """Stage 4 — final ``FunctionResult`` assembly."""
        target = inputs["target"]
        analyst_count = signals["analyst_count"]
        summary = cards["summary"]
        analyst_rows = cards["analyst_rows"]
        analyst_detail_status = cards["analyst_detail_status"]
        source_details = [
            {
                "name": cards["consensus_source"],
                "status": "aggregate_consensus_available"
                if cards["consensus_source"] in {"finnhub", "yfinance_recommendations"}
                else "unavailable_no_fabricated_consensus",
                "asOf": signals["last_updated"],
                "fields": "recommendation buckets used for consensus score",
            },
            {
                "name": "target_price",
                "status": cards["target_source_mode"],
                "asOf": target.get("lastUpdated") or target.get("last_update") or signals["last_updated"],
                "fields": "high, mean, median, low target-price statistics",
            },
            {
                "name": "broker_level_analyst_feed",
                "status": analyst_detail_status,
                "asOf": None,
                "fields": "broker, analyst, rating, previous rating, action, target price, target period, date, last update",
            },
        ]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok",
                "symbol": instrument.symbol,
                "summary": summary,
                "metrics": {
                    "analyst_count": analyst_count,
                    "consensus_score": signals["score"],
                    "positive_pct": summary["positive_pct"],
                    "neutral_pct": summary["neutral_pct"],
                    "negative_pct": summary["negative_pct"],
                    "included_count": analyst_count,
                    "excluded_stale_count": signals["stale_rule"]["excluded_stale_count"],
                },
                "rows": analyst_rows,
                "analyst_rows": analyst_rows,
                "analyst_columns": [
                    "broker",
                    "analyst",
                    "rating",
                    "previous_rating",
                    "action",
                    "target_price",
                    "target_period",
                    "date",
                    "last_update",
                ],
                "analyst_detail_status": analyst_detail_status,
                "analyst_detail_reason": cards["analyst_detail_reason"],
                "bucket_rows": cards["bucket_rows"],
                "target_rows": cards["target_rows"],
                "target_price_source": {
                    "mode": cards["target_source_mode"],
                    "label": cards["target_source_label"],
                    "not_analyst_target": cards["not_analyst_target"],
                },
                "stale_rule": signals["stale_rule"],
                "recommendations": inputs["recs"],
                "consensus_recommendations": signals["consensus_recs"],
                "price_target": target,
                "analyst_count": analyst_count,
                "spot": inputs["spot"],
                "source_details": source_details,
                "data_notes": [
                    "Broker-level analyst rows require a provider that supplies analyst-detail recommendations.",
                    "Derived target-price ranges are display references, not analyst targets.",
                    "When aggregate analyst buckets are unavailable, ShowMe leaves consensus empty instead of reusing a static distribution.",
                ],
                "analyst_quality": {
                    "status": analyst_detail_status,
                    "required_inputs": [
                        "broker-level rating history",
                        "named analyst identifiers",
                        "target-price revisions",
                        "realized forward returns",
                    ],
                    "methodology": (
                        "Accuracy scoring should compare each analyst's historical rating/target "
                        "changes against subsequent realized returns. Broker rating actions, when "
                        "supplied, capture upgrade/downgrade and target revisions but still miss "
                        "named-analyst identifiers and realized forward returns required for a full "
                        "hit-rate score."
                    ),
                },
                "alert_rules": [
                    {
                        "rule": "consensus_label_change",
                        "status": "ui_editable_local_rule",
                        "description": "Alert when the consensus label changes after refresh.",
                    },
                    {
                        "rule": "consensus_score_threshold",
                        "status": "ui_editable_local_rule",
                        "description": "Alert when the consensus score crosses a user threshold.",
                    },
                ],
                "methodology": (
                    "Recommendation buckets are reported as Strong Buy/Buy/Hold/Sell/Strong Sell and "
                    "converted to a 1-5 consensus score. Recommendation rows older than one year are "
                    "excluded from consensus totals. Broker-level analyst rows are shown only when a "
                    "provider supplies broker/analyst detail; ShowMe does not generate fake broker rows. "
                    "When live target-price statistics are unavailable, ShowMe labels the target range as "
                    "derived from spot and marks it as not an analyst target. If no usable spot is "
                    "available, ShowMe leaves target prices blank instead of using a synthetic base."
                ),
                "field_dictionary": {
                    "broker": "Financial institution or research provider issuing the recommendation.",
                    "analyst": "Named analyst, when supplied by a broker-level provider.",
                    "rating": "Current analyst rating.",
                    "previous_rating": "Prior rating used to identify upgrade/downgrade/reiterate actions.",
                    "action": "Rating action such as upgrade, downgrade, initiate, maintain, or reiterate.",
                    "target_price": "Broker-level target price when supplied by an analyst-detail provider.",
                    "target_period": "Target horizon such as 12M.",
                    "date": "Rating publication date.",
                    "last_update": "Most recent provider update timestamp for the rating row.",
                    "count": "Number of analysts in the recommendation bucket after stale exclusions.",
                    "price": "12-month price target statistic in the quote currency.",
                    "sentiment_score": "Bucket score: Strong Buy=5, Buy=4, Hold=3, Sell=2, Strong Sell=1.",
                    "target_price_source": "Live analyst targets when available; otherwise a derived reference range explicitly marked as not an analyst target.",
                    "included_count": "Analysts included in consensus after the one-year stale rule.",
                    "excluded_stale_count": "Analysts excluded because the recommendation row is older than one year.",
                    "oldest_included_rating_date": "Oldest rating date still included in the current consensus.",
                },
            },
            metadata={"stale_cutoff_date": signals["cutoff"].date().isoformat()},
            sources=inputs["sources"], warnings=inputs["warnings"],
        )

    async def _execute_crypto(self, instrument: Instrument, **params: Any) -> FunctionResult:
        warnings: list[str] = []
        sources: list[str] = []
        quote_timeout = max(1.0, min(float(params.get("quote_timeout", 5)), 10.0))
        lookback = max(30, min(int(params.get("lookback_days", 90)), 365))
        quote, quote_source = await self._crypto_quote(instrument, quote_timeout, warnings)
        frame, frame_source = await self._crypto_ohlcv(instrument, lookback, quote_timeout, warnings)
        if quote_source:
            sources.append(quote_source)
        if frame_source and frame_source not in sources:
            sources.append(frame_source)

        spot = finite(getattr(quote, "last", None)) if quote is not None else None
        frame = _normalize_crypto_frame(frame)
        if spot is None and not frame.empty:
            spot = finite(frame["close"].iloc[-1])
        if spot is None:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "symbol": instrument.symbol,
                    "asset_class": "CRYPTO",
                    "reason": "No live crypto quote or OHLCV close was available for ANR crypto consensus.",
                    "next_actions": ["Retry the symbol, use a liquid USDT pair, or check crypto data provider connectivity."],
                },
                sources=sources or ["crypto_market_data"],
                warnings=warnings or ["crypto quote unavailable"],
            )

        indicators = _crypto_indicators(frame, spot, quote)
        signal_rows = _crypto_signal_rows(indicators)
        signal_count = len(signal_rows)
        consensus_score = _weighted_signal_score(signal_rows)
        label = _consensus_label(consensus_score)
        positive_count = sum(1 for r in signal_rows if float(r["score"]) >= 3.6)
        neutral_count = sum(1 for r in signal_rows if 2.8 <= float(r["score"]) < 3.6)
        negative_count = sum(1 for r in signal_rows if float(r["score"]) < 2.8)
        bucket_rows = _signal_bucket_rows(signal_rows)
        last_updated = _latest_market_timestamp(frame, quote)
        reference_rows = _crypto_reference_rows(frame, spot)
        source_mode = "crypto_market_reference_band" if reference_rows else "target_price_unavailable"
        source_label = "Crypto market reference bands" if reference_rows else "Target price unavailable"
        summary = {
            "title": f"{instrument.symbol} Crypto Market Consensus",
            "asset_class": "CRYPTO",
            "consensus_kind": "crypto_market_proxy",
            "count_label": "signals",
            "signal_count": signal_count,
            "analyst_count": signal_count,
            "consensus_score": consensus_score,
            "label": label,
            "positive_pct": _pct(positive_count, signal_count),
            "neutral_pct": _pct(neutral_count, signal_count),
            "negative_pct": _pct(negative_count, signal_count),
            "last_updated": last_updated,
            "included_count": signal_count,
            "excluded_stale_count": 0,
            "oldest_included_rating_date": None,
            "target_price_source": source_label,
            "target_price_source_mode": source_mode,
            "not_analyst_target": True,
            "analyst_detail_status": "not_applicable_crypto",
            "consensus_source": "crypto_market_data",
        }
        source_details = [
            {
                "name": quote_source or "crypto_quote",
                "status": "live_quote_available" if quote is not None else "unavailable",
                "asOf": getattr(getattr(quote, "timestamp", None), "isoformat", lambda: None)(),
                "fields": "last price, 24h high/low/volume when supplied",
            },
            {
                "name": frame_source or "crypto_ohlcv",
                "status": "live_ohlcv_available" if not frame.empty else "unavailable",
                "asOf": _frame_asof(frame),
                "fields": "close returns, volatility, drawdown, RSI, volume confirmation",
            },
            {
                "name": "broker_level_analyst_feed",
                "status": "not_applicable_crypto",
                "asOf": None,
                "fields": "Crypto ANR does not fabricate sell-side broker/analyst recommendations.",
            },
        ]
        stale_rule = {
            "rule_type": "market_data_freshness",
            "cutoff_days": None,
            "cutoff_date": None,
            "included_count": signal_count,
            "excluded_stale_count": 0,
            "oldest_included_rating_date": None,
            "oldest_stale_rating_date": None,
            "undated_provider_rows": 0,
            "latest_market_data_at": last_updated,
            "rule": "Crypto ANR uses live market-data freshness; the one-year sell-side recommendation stale rule is not applicable.",
        }
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "symbol": instrument.symbol,
                "asset_class": "CRYPTO",
                "summary": summary,
                "metrics": {
                    "signal_count": signal_count,
                    "consensus_score": consensus_score,
                    "positive_pct": summary["positive_pct"],
                    "neutral_pct": summary["neutral_pct"],
                    "negative_pct": summary["negative_pct"],
                    "included_count": signal_count,
                    "excluded_stale_count": 0,
                },
                "rows": signal_rows,
                "signal_rows": signal_rows,
                "analyst_rows": [],
                "analyst_columns": [
                    "broker",
                    "analyst",
                    "rating",
                    "previous_rating",
                    "action",
                    "target_price",
                    "target_period",
                    "date",
                    "last_update",
                ],
                "analyst_detail_status": "not_applicable_crypto",
                "analyst_detail_reason": "Crypto pairs do not have a Bloomberg-style sell-side ANR feed in the configured providers. ShowMe uses a labelled market-consensus proxy instead.",
                "bucket_rows": bucket_rows,
                "target_rows": reference_rows,
                "target_price_source": {
                    "mode": source_mode,
                    "label": source_label,
                    "display_name": "Crypto Reference Bands",
                    "not_analyst_target": True,
                },
                "stale_rule": stale_rule,
                "recommendations": [],
                "price_target": {"source_mode": source_mode},
                "analyst_count": signal_count,
                "signal_count": signal_count,
                "spot": spot,
                "crypto_indicators": indicators,
                "source_details": source_details,
                "data_notes": [
                    "Crypto ANR is not a sell-side analyst recommendation feed.",
                    "Reference bands come from recent market data and are not analyst target prices.",
                    "Broker/analyst rows are intentionally empty for crypto unless a real analyst-detail provider is configured.",
                ],
                "analyst_quality": {
                    "status": "not_applicable_crypto",
                    "methodology": "Sell-side analyst hit-rate scoring requires broker-level analyst history; crypto ANR uses market-data signals instead.",
                },
                "alert_rules": [
                    {
                        "rule": "crypto_consensus_label_change",
                        "status": "ui_editable_local_rule",
                        "description": "Alert when the crypto market-consensus label changes after refresh.",
                    },
                    {
                        "rule": "crypto_consensus_score_threshold",
                        "status": "ui_editable_local_rule",
                        "description": "Alert when the crypto consensus score crosses a user threshold.",
                    },
                ],
                "methodology": (
                    "For CRYPTO, ANR is a labelled market-consensus proxy, not a Bloomberg sell-side analyst feed. "
                    "Score = weighted 1-5 blend of 30d trend, 7d momentum, 24h move, RSI, drawdown risk, "
                    "annualized volatility, and volume confirmation when available. Reference bands use recent "
                    "market highs/lows or volatility bands and are explicitly not analyst target prices."
                ),
                "field_dictionary": {
                    "signal": "Market-data input used by the crypto consensus proxy.",
                    "value": "Observed live or recent-market value for the signal.",
                    "score": "Signal score on a 1-5 scale where higher is more constructive.",
                    "weight": "Weight applied to the signal in the final consensus score.",
                    "target_price_source": "Crypto market reference bands; not analyst target prices.",
                    "latest_market_data_at": "Most recent quote/candle timestamp used by the crypto proxy.",
                },
            },
            metadata={"lookback_days": lookback, "consensus_kind": "crypto_market_proxy"},
            sources=sources or ["crypto_market_proxy"],
            warnings=warnings,
        )

    async def _crypto_quote(self, instrument: Instrument, timeout: float, warnings: list[str]) -> tuple[Any | None, str | None]:
        for name in ("ccxt_failover", "cryptocompare", "coingecko", "yfinance"):
            src = getattr(self.deps, name, None)
            if not src:
                continue
            try:
                quote = await asyncio.wait_for(
                    src.fetch(DataRequest(kind=DataKind.QUOTE, instrument=instrument, extra={"timeout": timeout})),
                    timeout=timeout + 1.0,
                )
                if finite(getattr(quote, "last", None)) is not None:
                    return quote, str(getattr(quote, "source", None) or name)
            except Exception as exc:
                warnings.append(f"{name}_quote: {exc}")
        return None, None

    async def _crypto_ohlcv(self, instrument: Instrument, lookback: int, timeout: float, warnings: list[str]) -> tuple[Any | None, str | None]:
        for name in ("yfinance", "cryptocompare", "coingecko", "ccxt_failover"):
            src = getattr(self.deps, name, None)
            if not src:
                continue
            try:
                frame = await asyncio.wait_for(
                    src.fetch(DataRequest(
                        kind=DataKind.OHLCV,
                        instrument=instrument,
                        start=_today() - timedelta(days=lookback + 5),
                        interval="1d",
                        limit=lookback,
                        extra={"timeout": timeout, "days": min(max(lookback, 30), 365), "period": f"{lookback}d"},
                    )),
                    timeout=timeout + 3.0,
                )
                normalized = _normalize_crypto_frame(frame)
                if not normalized.empty:
                    return normalized, name
            except Exception as exc:
                warnings.append(f"{name}_ohlcv: {exc}")
        return None, None


def _normalize_crypto_frame(frame: Any) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    df = frame.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if "price" in df.columns and "close" not in df.columns:
        df["close"] = df["price"]
    if "volume" not in df.columns:
        for key in ("volume_quote", "volumeto", "volume_base", "volumefrom"):
            if key in df.columns:
                df["volume"] = df[key]
                break
    if "close" not in df.columns:
        return pd.DataFrame()
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    out = df[keep].copy()
    for col in keep:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["close"])
    if out.empty:
        return pd.DataFrame()
    return out.sort_index()


def _crypto_indicators(frame: pd.DataFrame, spot: float, quote: Any | None) -> dict[str, Any]:
    closes = frame["close"] if not frame.empty else pd.Series(dtype=float)
    returns = closes.pct_change().dropna()
    ret_1d = _window_return(closes, 1)
    ret_7d = _window_return(closes, 7)
    ret_30d = _window_return(closes, 30)
    quote_prev = finite(getattr(quote, "close_prev", None)) if quote is not None else None
    move_24h = (spot / quote_prev - 1.0) if quote_prev and quote_prev > 0 else ret_1d
    high_30d = finite(closes.tail(30).max()) if len(closes) else None
    low_30d = finite(closes.tail(30).min()) if len(closes) else None
    drawdown_30d = (spot / high_30d - 1.0) if high_30d and high_30d > 0 else None
    vol_30d = float(returns.tail(30).std() * math.sqrt(365)) if len(returns.tail(30)) >= 10 else None
    volume_z = None
    if "volume" in frame.columns:
        volume = frame["volume"].dropna()
        if len(volume) >= 20:
            recent = volume.tail(20)
            std = float(recent.std() or 0)
            if std > 0:
                volume_z = float((volume.iloc[-1] - recent.mean()) / std)
    return {
        "spot": spot,
        "return_24h": move_24h,
        "return_7d": ret_7d,
        "return_30d": ret_30d,
        "rsi_14": _rsi(closes, 14),
        "drawdown_30d": drawdown_30d,
        "volatility_30d_ann": vol_30d,
        "volume_z_20d": volume_z,
        "high_30d": high_30d,
        "low_30d": low_30d,
        "last_close": finite(closes.iloc[-1]) if len(closes) else None,
    }


def _window_return(series: pd.Series, days: int) -> float | None:
    if len(series) <= days:
        return None
    start = finite(series.iloc[-days - 1])
    end = finite(series.iloc[-1])
    if start is None or end is None or start <= 0:
        return None
    return float(end / start - 1.0)


def _rsi(series: pd.Series, period: int = 14) -> float | None:
    if len(series) <= period:
        return None
    diff = series.diff().dropna()
    gains = diff.clip(lower=0).tail(period).mean()
    losses = (-diff.clip(upper=0)).tail(period).mean()
    if losses == 0:
        return 100.0
    rs = gains / losses
    return float(100 - (100 / (1 + rs)))


def _crypto_signal_rows(ind: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [
        ("30d trend", ind.get("return_30d"), _score_return(ind.get("return_30d")), 0.30, "Thirty-day close return."),
        ("7d momentum", ind.get("return_7d"), _score_return(ind.get("return_7d")), 0.20, "Seven-day close return."),
        ("24h move", ind.get("return_24h"), _score_return(ind.get("return_24h"), short=True), 0.10, "Last price versus 24h/open reference."),
        ("RSI 14", ind.get("rsi_14"), _score_rsi(ind.get("rsi_14")), 0.15, "Momentum balance; extreme overbought/oversold is penalized."),
        ("30d drawdown", ind.get("drawdown_30d"), _score_drawdown(ind.get("drawdown_30d")), 0.10, "Distance from recent 30-day high."),
        ("30d volatility", ind.get("volatility_30d_ann"), _score_volatility(ind.get("volatility_30d_ann")), 0.10, "Annualized realized volatility from daily returns."),
        ("Volume confirmation", ind.get("volume_z_20d"), _score_volume(ind.get("volume_z_20d")), 0.05, "Latest volume z-score versus 20-day average."),
    ]
    rows: list[dict[str, Any]] = []
    for signal, value, score, weight, explanation in specs:
        if score is None:
            continue
        rows.append({
            "source": "crypto_market_data",
            "signal": signal,
            "value": _format_signal_value(value, signal),
            "score": round(float(score), 2),
            "weight": weight,
            "weighted_score": round(float(score) * weight, 3),
            "explanation": explanation,
        })
    return rows


def _score_return(value: Any, *, short: bool = False) -> float | None:
    ret = finite(value)
    if ret is None:
        return None
    levels = (0.08, 0.03, -0.03, -0.08) if short else (0.20, 0.08, -0.08, -0.20)
    if ret >= levels[0]:
        return 5.0
    if ret >= levels[1]:
        return 4.0
    if ret > levels[2]:
        return 3.0
    if ret > levels[3]:
        return 2.0
    return 1.0


def _score_rsi(value: Any) -> float | None:
    rsi = finite(value)
    if rsi is None:
        return None
    if 45 <= rsi <= 65:
        return 4.0
    if 35 <= rsi < 45 or 65 < rsi <= 75:
        return 3.2
    if 25 <= rsi < 35:
        return 2.6
    if 75 < rsi <= 85:
        return 2.4
    return 1.8


def _score_drawdown(value: Any) -> float | None:
    dd = finite(value)
    if dd is None:
        return None
    if dd >= -0.05:
        return 4.2
    if dd >= -0.15:
        return 3.4
    if dd >= -0.30:
        return 2.5
    return 1.6


def _score_volatility(value: Any) -> float | None:
    vol = finite(value)
    if vol is None:
        return None
    if vol <= 0.65:
        return 4.0
    if vol <= 1.10:
        return 3.2
    if vol <= 1.80:
        return 2.5
    return 1.8


def _score_volume(value: Any) -> float | None:
    z = finite(value)
    if z is None:
        return None
    if z >= 1.0:
        return 4.0
    if z >= 0.0:
        return 3.4
    if z >= -1.0:
        return 3.0
    return 2.3


def _weighted_signal_score(rows: list[dict[str, Any]]) -> float | None:
    total_weight = sum(float(r.get("weight") or 0) for r in rows)
    if total_weight <= 0:
        return None
    score = sum(float(r["score"]) * float(r.get("weight") or 0) for r in rows) / total_weight
    return round(score, 2)


def _signal_bucket_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = {key: 0 for key, _, _ in BUCKETS}
    for row in rows:
        score = float(row.get("score") or 0)
        if score >= 4.5:
            counts["strongBuy"] += 1
        elif score >= 3.6:
            counts["buy"] += 1
        elif score >= 2.8:
            counts["hold"] += 1
        elif score >= 2.0:
            counts["sell"] += 1
        else:
            counts["strongSell"] += 1
    total = sum(counts.values())
    return [
        {
            "bucket": label,
            "count": counts[key],
            "sentiment_score": score,
            "pct_of_consensus": _pct(counts[key], total),
            "included_in_consensus": True,
        }
        for key, label, score in BUCKETS
    ]


def _crypto_reference_rows(frame: pd.DataFrame, spot: float) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    close = frame["close"].tail(30)
    if close.empty:
        return []
    returns = close.pct_change().dropna()
    vol = float(returns.std() * math.sqrt(30)) if len(returns) >= 10 else None
    high = finite(close.max())
    low = finite(close.min())
    mean = finite(close.mean())
    rows = [
        ("30d high reference", high),
        ("30d mean reference", mean),
        ("Spot", spot),
        ("30d low reference", low),
    ]
    if vol is not None and spot > 0:
        rows.insert(0, ("+1 sigma 30d band", round(spot * (1 + vol), 8)))
        rows.append(("-1 sigma 30d band", round(max(0.0, spot * (1 - vol)), 8)))
    return [
        {
            "metric": metric,
            "price": finite(price),
            "source_mode": "crypto_market_reference_band",
            "not_analyst_target": True,
        }
        for metric, price in rows
    ]


def _latest_market_timestamp(frame: pd.DataFrame, quote: Any | None) -> str | None:
    qts = getattr(quote, "timestamp", None) if quote is not None else None
    if isinstance(qts, datetime):
        return qts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return _frame_asof(frame)


def _frame_asof(frame: pd.DataFrame) -> str | None:
    if frame.empty:
        return None
    try:
        idx = frame.index[-1]
        if hasattr(idx, "to_pydatetime"):
            idx = idx.to_pydatetime()
        if isinstance(idx, datetime):
            if idx.tzinfo is None:
                idx = idx.replace(tzinfo=timezone.utc)
            return idx.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return str(idx)
    except Exception:
        return None


def _format_signal_value(value: Any, signal: str) -> str:
    numeric = finite(value)
    if numeric is None:
        return "—"
    signal_name = signal.lower()
    if any(word in signal_name for word in ("return", "move", "drawdown", "trend", "momentum")):
        return f"{numeric * 100:.2f}%"
    if "volatility" in signal_name:
        return f"{numeric * 100:.1f}% ann"
    if "rsi" in signal_name:
        return f"{numeric:.1f}"
    if "volume" in signal_name:
        return f"{numeric:.2f} z"
    return f"{numeric:.4g}"
