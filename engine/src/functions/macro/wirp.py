"""WIRP — World Interest Rate Probability (CME FedWatch)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class WIRPFunction(BaseFunction):
    code = "WIRP"
    name = "World Interest Rate Probability"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        central_bank = str(params.get("central_bank") or params.get("bank") or "FED").upper()
        meetings_limit = _int_param(params.get("meetings"), default=4, floor=1, ceiling=8)
        rows = _probability_rows(central_bank)[:meetings_limit]
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
                ],
                "methodology": (
                    "WIRP displays labelled reference probabilities for central-bank meetings. "
                    "For each meeting the cut, hold, and hike probabilities sum to 1; implied_change_bp "
                    "is (-25 * cut_25bp) + (25 * hike_25bp). A live futures/FedWatch adapter is not configured."
                ),
                "field_dictionary": {
                    "cut_25bp": "Probability of a 25 bp cut.",
                    "hold": "Probability of no policy-rate change.",
                    "hike_25bp": "Probability of a 25 bp hike.",
                    "implied_change_bp": "Probability-weighted expected policy-rate move in basis points.",
                },
                "source_mode": "reference_rate_probability_table",
            },
            sources=["reference_rate_probability_table"],
            warnings=["live futures-implied probability adapter is not configured"],
        )


def _probability_rows(central_bank: str) -> list[dict[str, Any]]:
    templates = {
        "FED": [
            ("2026-06-10", 0.18, 0.72, 0.10),
            ("2026-07-29", 0.28, 0.62, 0.10),
            ("2026-09-16", 0.36, 0.55, 0.09),
            ("2026-11-04", 0.42, 0.50, 0.08),
        ],
        "ECB": [
            ("2026-06-11", 0.22, 0.68, 0.10),
            ("2026-07-23", 0.30, 0.61, 0.09),
            ("2026-09-10", 0.34, 0.58, 0.08),
            ("2026-10-29", 0.38, 0.55, 0.07),
        ],
        "BOE": [
            ("2026-06-18", 0.20, 0.70, 0.10),
            ("2026-08-06", 0.31, 0.60, 0.09),
            ("2026-09-17", 0.35, 0.57, 0.08),
            ("2026-11-05", 0.40, 0.53, 0.07),
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
