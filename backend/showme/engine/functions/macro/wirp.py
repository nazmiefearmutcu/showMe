"""WIRP — World Interest Rate Probability (CME FedWatch)."""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


@FunctionRegistry.register
class WIRPFunction(BaseFunction):
    code = "WIRP"
    name = "World Interest Rate Probability"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        central_bank = str(params.get("central_bank") or params.get("bank") or "FED").upper()
        meetings_limit = _int_param(params.get("meetings"), default=4, floor=1, ceiling=8)

        # CME FedWatch only models the Fed. For other central banks the
        # deterministic reference table remains the source of truth until
        # adapters for ECB/BoE are wired.
        rows: list[dict[str, Any]] = []
        data_mode = "modeled"
        sources: list[str] = []
        warnings: list[str] = []

        adapter = getattr(self.deps, "cme_fedwatch", None)
        cme_attempted = central_bank == "FED" and adapter is not None
        if cme_attempted:
            try:
                payload = await adapter.probabilities()
                rows = _rows_from_cme(payload, central_bank)
            except Exception as exc:  # pragma: no cover - exercised by test
                rows = []
                warnings.append(
                    f"cme_fedwatch adapter error: {exc.__class__.__name__}: {exc}"
                )
            if rows:
                data_mode = "live_official"
                sources.append("cme_fedwatch")
            else:
                # Adapter returned no usable rows — surface the gap before falling
                # back so the UI can pill it accurately.
                warnings.append(
                    "cme_fedwatch returned no usable meeting probabilities; "
                    "falling back to reference probability table"
                )

        if not rows:
            rows = _probability_rows(central_bank)
            sources.append("reference_rate_probability_table")
            if cme_attempted:
                # The deterministic table is still a modeled fallback.
                pass
            warnings.append("live futures-implied probability adapter is not configured")

        rows = rows[:meetings_limit]

        surface = []
        for row in rows:
            for scenario in ("cut_25bp", "hold", "hike_25bp"):
                surface.append({
                    "meeting": row["date"],
                    "scenario": scenario,
                    "probability": row[scenario],
                    "value": row[scenario] * 100,
                    "central_bank": row["central_bank"],
                })

        source_mode = (
            "cme_fedwatch" if data_mode == "live_official"
            else "reference_rate_probability_table"
        )
        methodology = (
            "WIRP displays labelled probabilities for central-bank meetings. "
            "For each meeting cut, hold, and hike probabilities sum to 1; "
            "implied_change_bp is (-25 * cut_25bp) + (25 * hike_25bp). "
        )
        if data_mode == "live_official":
            methodology += (
                "When the CME FedWatch adapter is available, probabilities for "
                "the Fed are bucketed from market-implied fed funds futures: "
                "cut/hold/hike are the sum of CME range probabilities below, "
                "at, and above the current target range."
            )
        else:
            methodology += (
                "A live futures/FedWatch adapter is not configured for this run; "
                "the table below comes from a reference snapshot."
            )

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "central_bank": central_bank,
                "rows": rows,
                "surface": surface,
                "cards": [
                    {"label": "Central bank", "value": central_bank},
                    {"label": "Meetings", "value": len(rows)},
                    {"label": "Next hold %", "value": round(rows[0]["hold"] * 100, 2) if rows else None},
                    {"label": "Mode", "value": data_mode},
                ],
                "methodology": methodology,
                "field_dictionary": {
                    "cut_25bp": "Probability of a 25 bp cut.",
                    "hold": "Probability of no policy-rate change.",
                    "hike_25bp": "Probability of a 25 bp hike.",
                    "implied_change_bp": "Probability-weighted expected policy-rate move in basis points.",
                },
                "source_mode": source_mode,
                "data_mode": data_mode,
                "provenance": {"sources": list(sources)},
            },
            sources=sources or [source_mode],
            warnings=warnings,
        )


def _rows_from_cme(payload: dict[str, Any] | None, central_bank: str) -> list[dict[str, Any]]:
    """Bucket the CME normalised payload into cut/hold/hike per meeting.

    The CME normaliser emits ``{"meetings": [{"date": ..., "ranges": {bin: pct}}]}``
    where each ``bin`` is a textual target range and ``pct`` is the
    market-implied probability that the FOMC ends the meeting inside that
    range. We:

    1. Identify the modal range (highest probability) of the *first*
       meeting as the "current" target range. CME's first meeting is
       typically the nearest scheduled FOMC date, so its modal range is a
       robust proxy for today's standing target.
    2. For every meeting, sum the probabilities by their relation to the
       current range — strictly below ➜ cut, equal ➜ hold, strictly above
       ➜ hike. We rank ranges by the midpoint of their bin so multi-cut /
       multi-hike scenarios still collapse cleanly into the three buckets
       the WIRP contract guarantees.
    3. Renormalise so cut+hold+hike == 1 ± 1e-6 to keep the existing
       ``wirp_probs_sum_to_one`` semantic test green even if CME's input
       sums slightly off due to scaling or rounding.
    """
    if not payload or not isinstance(payload, dict):
        return []
    meetings = payload.get("meetings") or []
    if not isinstance(meetings, list) or not meetings:
        return []

    # Build {date: [(rank, pct), ...]} preserving textual range as the
    # tiebreak when midpoints collide.
    parsed_meetings: list[tuple[str, list[tuple[float, str, float]]]] = []
    for meeting in meetings:
        if not isinstance(meeting, dict):
            continue
        date = str(meeting.get("date") or "").strip()
        ranges = meeting.get("ranges") or {}
        if not date or not isinstance(ranges, dict) or not ranges:
            continue
        entries: list[tuple[float, str, float]] = []
        for bin_text, raw_pct in ranges.items():
            mid = _range_midpoint(str(bin_text))
            try:
                pct = float(raw_pct)
            except (TypeError, ValueError):
                continue
            if mid is None or pct < 0:
                continue
            entries.append((mid, str(bin_text), pct))
        if entries:
            parsed_meetings.append((date, entries))

    if not parsed_meetings:
        return []

    # Anchor "current" target range on the modal bucket of the first
    # meeting. This is what CME themselves use to label the row in the
    # public FedWatch tool.
    first_entries = parsed_meetings[0][1]
    anchor_mid, _, _ = max(first_entries, key=lambda item: item[2])

    rows: list[dict[str, Any]] = []
    for date, entries in parsed_meetings:
        total = sum(pct for _, _, pct in entries)
        if total <= 0:
            continue
        cut_raw = sum(pct for mid, _, pct in entries if mid < anchor_mid - _MID_EPS)
        hold_raw = sum(pct for mid, _, pct in entries if abs(mid - anchor_mid) <= _MID_EPS)
        hike_raw = sum(pct for mid, _, pct in entries if mid > anchor_mid + _MID_EPS)
        # Renormalise to 1.0 — preserves contract regardless of CME scale
        # (some endpoints emit 0-100 percent, others 0-1 fractions).
        bucket_total = cut_raw + hold_raw + hike_raw
        if bucket_total <= 0:
            continue
        cut = cut_raw / bucket_total
        hold = hold_raw / bucket_total
        hike = hike_raw / bucket_total
        rows.append({
            "central_bank": central_bank,
            "date": date,
            "cut_25bp": round(cut, 6),
            "hold": round(hold, 6),
            "hike_25bp": round(hike, 6),
            "implied_change_bp": round((-25 * cut) + (25 * hike), 2),
            "source_mode": "cme_fedwatch",
        })
    return rows


_MID_EPS = 1e-9


def _range_midpoint(text: str) -> float | None:
    """Best-effort midpoint extraction from a CME range bin label.

    Accepts the shapes CME uses in practice — ``"4.25-4.50"``, ``"425-450"``,
    ``"425 - 450 bps"``, ``"4.50%"`` (single-point bins). Returns the
    midpoint in *percent* (so 4.25-4.50 → 4.375) or ``None`` if the label
    can't be parsed.
    """
    if not text:
        return None
    cleaned = (
        text.replace("bps", "")
        .replace("bp", "")
        .replace("%", "")
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )
    if not cleaned:
        return None
    parts = [p.strip() for p in cleaned.split("-") if p.strip()]
    if not parts:
        return None
    nums: list[float] = []
    for part in parts:
        try:
            nums.append(float(part))
        except ValueError:
            return None
    if not nums:
        return None
    # CME's "425-450" form is in basis points; "4.25-4.50" is in percent.
    # Anything ≥ 50 we treat as basis points and divide by 100.
    midpoint = sum(nums) / len(nums)
    if any(n >= 50 for n in nums):
        midpoint = midpoint / 100.0
    return midpoint


def _probability_rows(central_bank: str) -> list[dict[str, Any]]:
    # Verified against Fed calendar 2026-05-24
    # FED: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    # Meetings span two days; we use the decision-day (second day).
    # ECB: governing-council monetary-policy meetings 2026.
    # BOE: MPC schedule 2026 (decision Thursdays).
    templates = {
        "FED": [
            ("2026-06-17", 0.18, 0.72, 0.10),
            ("2026-07-29", 0.28, 0.62, 0.10),
            ("2026-09-16", 0.36, 0.55, 0.09),
            ("2026-10-28", 0.42, 0.50, 0.08),
            ("2026-12-09", 0.45, 0.48, 0.07),
        ],
        "ECB": [
            ("2026-06-04", 0.22, 0.68, 0.10),
            ("2026-07-23", 0.30, 0.61, 0.09),
            ("2026-09-10", 0.34, 0.58, 0.08),
            ("2026-10-29", 0.38, 0.55, 0.07),
            ("2026-12-17", 0.40, 0.53, 0.07),
        ],
        "BOE": [
            ("2026-06-18", 0.20, 0.70, 0.10),
            ("2026-08-06", 0.31, 0.60, 0.09),
            ("2026-09-17", 0.35, 0.57, 0.08),
            ("2026-11-05", 0.40, 0.53, 0.07),
            ("2026-12-17", 0.42, 0.51, 0.07),
        ],
    }
    rows = []
    for date, cut, hold, hike in templates.get(central_bank, templates["FED"]):
        rows.append({
            "central_bank": central_bank,
            "date": date,
            "cut_25bp": cut,
            "hold": hold,
            "hike_25bp": hike,
            "implied_change_bp": round((-25 * cut) + (25 * hike), 2),
            "source_mode": "reference_rate_probability_table",
        })
    return rows


def _int_param(value: Any, *, default: int, floor: int, ceiling: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))
