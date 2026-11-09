"""Read the two fixed NCSES published aggregate workbooks, without an XLSX dependency."""
from __future__ import annotations

import io
import math
import re
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree as ET

from .catalog import SOURCE_CATALOG
from .models import Dataset, period_fields, timestamp

NSF_URLS = {
    "nsf_ncses_2020": "https://ncses.nsf.gov/pubs/nsb20204/assets/supplemental-tables/tables/nsb20204-tabs08-062.xlsx",
    "nsf_ncses": "https://ncses.nsf.gov/pubs/nsb20262/assets/business-dynamics-and-investment/figures/nsb20262-figtrn-028.xlsx",
}
MAX_ARCHIVE_BYTES = 8_000_000
MAX_ARCHIVE_ENTRIES = 64
MAX_UNCOMPRESSED_BYTES = 8_000_000
MAX_XML_BYTES = 2_000_000
MAX_ROWS = 256
MAX_CELLS = 4096
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COUNTRIES = {
    "Canada": "CAN", "Mexico": "MEX", "United States": "USA", "Belgium": "BEL",
    "France": "FRA", "Germany": "DEU", "Italy": "ITA", "Ireland": "IRL",
    "Netherlands": "NLD", "Spain": "ESP", "Sweden": "SWE", "United Kingdom": "GBR",
    "Norway": "NOR", "Russia": "RUS", "Switzerland": "CHE", "China": "CHN",
    "India": "IND", "Indonesia": "IDN", "Japan": "JPN", "Philippines": "PHL",
    "Singapore": "SGP", "South Korea": "KOR", "Taiwan": "TWN", "Thailand": "THA",
    "Vietnam": "VNM", "Australia": "AUS", "Brazil": "BRA", "Israel": "ISR",
    "South Africa": "ZAF",
}
HISTORICAL_LABELS = (
    "Global total", "North America", "Canada", "Mexico", "United States", "Europe", "EU",
    "Belgium", "France", "Germany", "Italy", "Ireland", "Netherlands", "Spain", "Sweden",
    "United Kingdom", "All others", "Other Europe", "Norway", "Russia", "Switzerland",
    "Asia", "China", "India", "Indonesia", "Japan", "Philippines", "Singapore", "South Korea",
    "Taiwan", "Thailand", "Vietnam", "Other countries", "Australia", "Brazil", "Israel",
    "South Africa", "ROW",
)
CURRENT_HEADERS = (
    "Year", "United States", "China", "United Kingdom", "India", "Germany", "France",
    "Rest of world", "World total",
)


class NSFParseError(RuntimeError):
    """Fixed, safe schema/limit errors; never contains upstream document content."""


def _fail() -> NSFParseError:
    return NSFParseError("NCSES workbook schema, units or published coverage changed; saved releases are retained.")


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    raw = archive.read(name)
    if len(raw) > MAX_XML_BYTES:
        raise NSFParseError("NCSES workbook XML exceeds the parsing limit")
    decoded = raw.decode("utf-8-sig")
    if "<!DOCTYPE" in decoded.upper() or "<!ENTITY" in decoded.upper():
        raise NSFParseError("NCSES workbook XML declarations are unsupported")
    return ET.fromstring(decoded)


def _cells(body: bytes) -> dict[tuple[int, int], Any]:
    if len(body) > MAX_ARCHIVE_BYTES:
        raise NSFParseError("NCSES workbook exceeds the 8 MB limit")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (len(entries) > MAX_ARCHIVE_ENTRIES or len(names) != len(set(names))
                    or sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES
                    or any(entry.flag_bits & 1 for entry in entries)):
                raise NSFParseError("NCSES workbook archive exceeds parsing limits or has duplicate/encrypted entries")
            strings_xml = _xml(archive, "xl/sharedStrings.xml")
            sheet = _xml(archive, "xl/worksheets/sheet1.xml")
            if strings_xml.tag != NS + "sst" or sheet.tag != NS + "worksheet":
                raise _fail()
            strings = ["".join(part.text or "" for part in item.iter(NS + "t")).strip()
                       for item in strings_xml.findall(NS + "si")]
            if len(strings) > MAX_CELLS:
                raise NSFParseError("NCSES workbook string limit exceeded")
            rows = sheet.findall(NS + "sheetData/" + NS + "row")
            if len(rows) > MAX_ROWS:
                raise NSFParseError("NCSES workbook row limit exceeded")
            cells: dict[tuple[int, int], Any] = {}
            seen_rows: set[int] = set()
            for row in rows:
                number = int(row.attrib["r"])
                if not 1 <= number <= MAX_ROWS or number in seen_rows:
                    raise _fail()
                seen_rows.add(number)
                for cell in row.findall(NS + "c"):
                    match = re.fullmatch(r"([A-Z]{1,2})([1-9][0-9]*)", cell.attrib["r"])
                    if not match:
                        raise _fail()
                    column = 0
                    for letter in match[1]:
                        column = column * 26 + ord(letter) - ord("A") + 1
                    key = (int(match[2]), column)
                    if key[0] != number or column > 64 or key in cells or len(cells) >= MAX_CELLS:
                        raise _fail()
                    if cell.find(NS + "f") is not None:
                        raise _fail()  # do not silently accept formula caches as published data
                    raw = cell.findtext(NS + "v")
                    kind = cell.attrib.get("t", "n")
                    if kind == "s":
                        index = int(raw or "-1")
                        if not 0 <= index < len(strings):
                            raise _fail()
                        value: Any = strings[index]
                    elif kind == "n":
                        value = None if raw is None else Decimal(raw)
                        if value is not None and not value.is_finite():
                            raise _fail()
                    elif kind == "inlineStr":
                        value = "".join(part.text or "" for part in cell.iter(NS + "t")).strip()
                    else:
                        raise _fail()
                    cells[key] = value
            return cells
    except NSFParseError:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, IndexError, ET.ParseError,
            UnicodeError, InvalidOperation, RuntimeError, NotImplementedError) as exc:
        raise _fail() from exc


def _amount(value: Any) -> int | float:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise _fail()
    scaled = value * 1_000_000
    if not math.isfinite(scaled):
        raise _fail()
    return int(scaled) if scaled == scaled.to_integral_value() else float(scaled)


def _observation(label: str, year: int, value: Any, note: str) -> dict[str, Any]:
    world = label in {"Global total", "World total"}
    return {"scope": "global" if world else "countries",
            "geography": "WORLD" if world else COUNTRIES[label], "period": str(year),
            **period_fields(str(year)), "metric": "investment", "stage": "total", "unit": "USD",
            "value": _amount(value), "status": "reported", "financing_scope": "vc",
            "source_geography_label": label, "source_unit": "USD millions", "unit_mult": 6,
            "coverage_note": note}


def parse_nsf(body: bytes, source: str) -> Dataset:
    """Each report edition remains a separate release; world totals are explicit cells."""
    if source not in NSF_URLS:
        raise NSFParseError("Unsupported NCSES publication")
    cells = _cells(body)
    historical = source == "nsf_ncses_2020"
    entry = SOURCE_CATALOG[source]
    note = ("NCSES / PitchBook published aggregate; China includes Hong Kong. "
            "World value is the publisher's explicit total, never a selected-country sum. "
            "Report editions share PitchBook lineage but contain revisions and must not be spliced. ")
    data: Dataset = {
        "schema_version": 1, "source_id": source, "source_name": entry["source_name"],
        "source_url": NSF_URLS[source], "published_at": timestamp(entry["published_at"]),
        "underlying_access_date": entry["underlying_access_date"],
        "publication_id": "NSB-2020-4" if historical else "NSB-2026-2",
        "publication_table": "S8-62" if historical else "TRN-28",
        "methodology_version": "nsb2020-4-s8-62" if historical else "nsb2026-2-trn28",
        "geography_basis": "source_defined" if historical else "company_hq",
        "date_basis": "source_defined", "sector": "all", "observations": [],
        "global_total_basis": "Published Global total row" if historical else "Published World total column",
    }
    if historical:
        if (cells.get((1, 1)) != "Table S8-62"
                or cells.get((3, 1)) != "(Millions of U.S. dollars)"
                or cells.get((4, 1)) != "Region, country, or economy"
                or [cells.get((4, col)) for col in range(2, 22)] != list(range(1999, 2019))
                or [cells.get((row, 1)) for row in range(5, 43)] != list(HISTORICAL_LABELS)
                or any(row > 42 or col > 21 and value not in (None, "") for (row, col), value in cells.items())):
            raise _fail()
        note += "2020 report; underlying database accessed 2019-09-21; current USD. Regional/EU28/Other rows are excluded. Detailed date-assignment/FX rules are not documented."
        data["methodology"] = note
        for row, label in enumerate(HISTORICAL_LABELS, 5):
            # Regions, overlapping EU28, and residual aggregates are deliberately unmapped.
            for col, year in enumerate(range(1999, 2019), 2):
                if label in COUNTRIES or label == "Global total":
                    data["observations"].append(_observation(label, year, cells.get((row, col)), note))
    else:
        if (cells.get((1, 1)) != "Figure TRN-28"
                or cells.get((3, 1)) != "(Millions of dollars)"
                or [cells.get((4, col)) for col in range(1, 10)] != list(CURRENT_HEADERS)
                or [cells.get((row, 1)) for row in range(5, 17)] != [str(year) for year in range(2013, 2025)]
                or any(row > 16 or col > 9 and value not in (None, "") for (row, col), value in cells.items())):
            raise _fail()
        note += "2026 report; PitchBook special tabulations accessed May 2025; completed deals, all VC stages, recipient company HQ. USD is interpreted from publication context; no constant-price base is stated. Underlying country coverage may be incomplete; detailed year-assignment/FX rules are not documented."
        data["methodology"] = note
        for row, year in enumerate(range(2013, 2025), 5):
            for col, label in enumerate(CURRENT_HEADERS[1:], 2):
                if label in COUNTRIES or label == "World total":
                    data["observations"].append(_observation(label, year, cells.get((row, col)), note))
    keys = [(r["scope"], r["geography"], r["period"]) for r in data["observations"]]
    if len(keys) != len(set(keys)):
        raise _fail()
    data["observations"].sort(key=lambda r: (r["scope"], r["geography"], r["period"]))
    return data
