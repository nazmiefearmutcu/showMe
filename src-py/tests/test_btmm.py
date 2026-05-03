from __future__ import annotations

import asyncio
import csv
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import src.functions.macro.btmm as btmm
from src.functions.macro.btmm import BTMMFunction


def test_parse_bis_cbpol_zip_builds_policy_rate_rows() -> None:
    payload = _fake_bis_zip(
        [
            {
                "FREQ": "D",
                "Frequency": "Daily",
                "REF_AREA": "US",
                "Reference area": "United States",
                "2026-01-01": "4.00",
                "2026-04-28": "3.75",
            },
            {
                "FREQ": "D",
                "Frequency": "Daily",
                "REF_AREA": "XM",
                "Reference area": "Euro area",
                "2026-01-01": "2.25",
                "2026-04-28": "2.00",
            },
        ],
    )

    rows = btmm._parse_bis_zip(payload)

    us = next(row for row in rows if row["country_code"] == "US")
    eu = next(row for row in rows if row["country_code"] == "EU")
    assert us["policy_rate"] == 3.75
    assert us["previous_rate"] == 4.0
    assert us["change_bp"] == -25.0
    assert us["last_move"] == "cut"
    assert eu["bis_ref_area"] == "XM"
    assert eu["central_bank"] == "European Central Bank"


def test_execute_filters_country_and_returns_summary(monkeypatch) -> None:
    def fake_loader(_timeout: float, _force_refresh: bool = False):
        return [
            {
                "country_code": "US",
                "country": "United States",
                "policy_rate": 3.75,
                "change_bp": -25.0,
                "last_move": "cut",
                "region": "americas",
                "source": "BIS CBPOL",
            },
            {
                "country_code": "EU",
                "country": "Euro area",
                "policy_rate": 2.0,
                "change_bp": -25.0,
                "last_move": "cut",
                "region": "europe",
                "source": "BIS CBPOL",
            },
        ]

    monkeypatch.setattr(btmm, "_load_bis_rows", fake_loader)

    result = asyncio.run(BTMMFunction().execute(country="ECB"))

    assert result.sources == ["BIS CBPOL"]
    assert result.data["country"] == "EU"
    assert result.data["rows"][0]["country_code"] == "EU"
    assert result.data["summary"]["rows"] == 1
    assert result.data["summary"]["cuts"] == 1


def test_execute_region_g10_excludes_non_g10(monkeypatch) -> None:
    def fake_loader(_timeout: float, _force_refresh: bool = False):
        return [
            {"country_code": "US", "policy_rate": 3.75, "last_move": "cut", "region": "americas"},
            {"country_code": "EU", "policy_rate": 2.0, "last_move": "cut", "region": "europe"},
            {"country_code": "TR", "policy_rate": 37.0, "last_move": "cut", "region": "europe"},
        ]

    monkeypatch.setattr(btmm, "_load_bis_rows", fake_loader)

    result = asyncio.run(BTMMFunction().execute(region="g10"))
    codes = {row["country_code"] for row in result.data["rows"]}

    assert codes == {"US", "EU"}


def _fake_bis_zip(rows: list[dict[str, str]]) -> bytes:
    base_fields = [
        "FREQ",
        "Frequency",
        "REF_AREA",
        "Reference area",
        "TIME_FORMAT",
        "Time Format",
        "COMPILATION",
        "DECIMALS",
        "Decimals",
        "SOURCE_REF",
        "SUPP_INFO_BREAKS",
        "TITLE",
        "Series",
    ]
    period_fields = ["2026-01-01", "2026-04-28"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=base_fields + period_fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("WS_CBPOL_csv_col.csv", buffer.getvalue())
    return zipped.getvalue()
