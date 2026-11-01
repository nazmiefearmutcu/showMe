"""Published NCSES workbook fixtures and pre-window coverage; no live network."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from showme.engine.services.vcap.catalog import SOURCE_CATALOG
from showme.engine.services.vcap.models import Query, timestamp, validate_dataset
from showme.engine.services.vcap.nsf import NSF_URLS, NSFParseError, parse_nsf
from showme.engine.services.vcap.providers import Providers, parse_oecd
from showme.engine.services.vcap.service import VCAPService
from showme.engine.services.vcap.store import SnapshotStore

FIXTURES = Path(__file__).parent / "fixtures" / "vcap"
FILES = {"nsf_ncses_2020": "nsb20204-tabs08-062.xlsx", "nsf_ncses": "nsb20262-figtrn-028.xlsx"}
HASHES = {"nsf_ncses_2020": "0843cb1cd56197d5ecb56ec7984e1dae9542a74f0a7cbcce6371593d4cdcc039",
          "nsf_ncses": "8dfc5e74464e76f2c6fcabe1220b2f689d70a014090771472f7f9d6d45973245"}
WORLD_MILLIONS = {
    "nsf_ncses_2020": [24548, 57139, 29457, 22964, 22857, 25967, 29308, 36787, 45615,
                       53237, 37561, 52980, 65667, 63584, 69795, 111224, 152809, 151470,
                       171887, 271369],
    "nsf_ncses": [71468, 118763, 176460, 192095, 208956, 332122, 319200, 367427,
                  693582, 478902, 326583, 354144],
}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_VCAP_DIR", str(tmp_path / "vcap"))
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path / "app"))
    monkeypatch.delenv("SHOWME_DEFILLAMA_API_KEY", raising=False)


def body(source):
    return (FIXTURES / FILES[source]).read_bytes()


def rewrite(source, entry, transform):
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(body(source))) as original, zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as changed:
        for item in original.infolist():
            value = original.read(item.filename)
            if item.filename == entry:
                value = transform(value.decode("utf-8")).encode("utf-8")
            changed.writestr(item.filename, value)
    return result.getvalue()


def saved_service(*sources):
    store = SnapshotStore()
    for source in sources:
        store.save(parse_nsf(body(source), source), origin="official")
        store.record_fetch(source, True)
    return VCAPService(store)


@pytest.mark.parametrize("source,first,last,count", [
    ("nsf_ncses_2020", 1999, 2018, 600), ("nsf_ncses", 2013, 2024, 84),
])
def test_original_official_fixture_exact_world_cells_and_scaling(source, first, last, count):
    assert hashlib.sha256(body(source)).hexdigest() == HASHES[source]
    data = parse_nsf(body(source), source)
    rows = data["observations"]
    assert len(rows) == count
    world = [row for row in rows if row["scope"] == "global"]
    assert [row["period"] for row in world] == [str(year) for year in range(first, last + 1)]
    assert [row["value"] for row in world] == [value * 1_000_000 for value in WORLD_MILLIONS[source]]
    assert {row["geography"] for row in world} == {"WORLD"}
    assert all(row["unit"] == "USD" and row["financing_scope"] == "vc" for row in rows)
    assert all(row["frequency"] == "annual" and row["stage"] == "total" for row in rows)
    assert all(row["source_unit"] == "USD millions" and row["unit_mult"] == 6 for row in rows)
    assert data["source_url"] == NSF_URLS[source]
    assert data["published_at"] == timestamp(SOURCE_CATALOG[source]["published_at"])
    assert data["underlying_access_date"] == SOURCE_CATALOG[source]["underlying_access_date"]
    assert data["published_at"] != data["underlying_access_date"]


def test_only_explicit_country_labels_map_and_true_zero_is_preserved():
    historical = parse_nsf(body("nsf_ncses_2020"), "nsf_ncses_2020")
    rows = historical["observations"]
    assert len({row["geography"] for row in rows if row["scope"] == "countries"}) == 29
    assert next(row["value"] for row in rows if row["geography"] == "USA" and row["period"] == "1999") == 22_545_000_000
    zero = next(row for row in rows if row["geography"] == "MEX" and row["period"] == "1999")
    assert zero["value"] == 0 and zero["status"] == "reported"
    assert not {row["source_geography_label"] for row in rows} & {"EU", "All others", "ROW", "North America", "Europe", "Asia"}
    current = parse_nsf(body("nsf_ncses"), "nsf_ncses")
    assert {row["geography"] for row in current["observations"]} == {"WORLD", "USA", "CHN", "GBR", "IND", "DEU", "FRA"}
    assert all("China includes Hong Kong" in row["coverage_note"] for row in rows)
    # Rounded component cells disagree with the 2018 total by $1m.
    assert 146302 + 118604 + 11793 + 8639 + 5070 + 4788 + 36925 == 332121
    assert next(row["value"] for row in current["observations"] if row["geography"] == "WORLD" and row["period"] == "2018") == 332_122_000_000
    assert next(row["value"] for row in current["observations"] if row["geography"] == "WORLD" and row["period"] == "2024") == 354_144_000_000


@pytest.mark.parametrize("source,entry,old,new", [
    ("nsf_ncses", "xl/sharedStrings.xml", "World total", "Selected country sum"),
    ("nsf_ncses", "xl/sharedStrings.xml", "(Millions of dollars)", "(Percent)"),
    ("nsf_ncses", "xl/sharedStrings.xml", "Figure TRN-28", "Figure TRN-29"),
    ("nsf_ncses", "xl/sharedStrings.xml", "United States", "Other countries"),
    ("nsf_ncses", "xl/sharedStrings.xml", ">2013<", ">2012<"),
    ("nsf_ncses", "xl/worksheets/sheet1.xml", ">71468.0<", ">NaN<"),
    ("nsf_ncses", "xl/worksheets/sheet1.xml", ">71468.0<", ">-1<"),
    ("nsf_ncses", "xl/worksheets/sheet1.xml", ">71468.0<", ">Infinity<"),
    ("nsf_ncses", "xl/worksheets/sheet1.xml", "<v>71468.0</v>", "<f>SUM(B5:H5)</f><v>71468.0</v>"),
    ("nsf_ncses", "xl/worksheets/sheet1.xml", "</sheetData>", '<row r="5"/></sheetData>'),
    ("nsf_ncses", "xl/worksheets/sheet1.xml", 'r="I5"', 'r="H5"'),
    ("nsf_ncses", "xl/worksheets/sheet1.xml", 'r="16"', 'r="257"'),
    ("nsf_ncses", "xl/worksheets/sheet1.xml", '<v>71468.0</v>', ""),
    ("nsf_ncses_2020", "xl/sharedStrings.xml", "Global total", "North America total"),
    ("nsf_ncses_2020", "xl/sharedStrings.xml", "(Millions of U.S. dollars)", "(Billions of U.S. dollars)"),
    ("nsf_ncses_2020", "xl/worksheets/sheet1.xml", ">1999.0<", ">1998.0<"),
])
def test_changed_schema_units_world_duplicates_and_invalid_values_fail_closed(source, entry, old, new):
    changed = rewrite(source, entry, lambda value: value.replace(old, new))
    assert changed != body(source)
    with pytest.raises(NSFParseError):
        parse_nsf(changed, source)


@pytest.mark.parametrize("limit", ["MAX_ARCHIVE_BYTES", "MAX_ARCHIVE_ENTRIES", "MAX_UNCOMPRESSED_BYTES", "MAX_XML_BYTES", "MAX_ROWS", "MAX_CELLS"])
def test_workbook_parsing_limits(monkeypatch, limit):
    from showme.engine.services.vcap import nsf
    monkeypatch.setattr(nsf, limit, 1)
    with pytest.raises(NSFParseError):
        parse_nsf(body("nsf_ncses"), "nsf_ncses")


def test_malformed_entity_and_duplicate_archive_entries_fail_closed():
    with pytest.raises(NSFParseError):
        parse_nsf(b"not a workbook", "nsf_ncses")
    changed = rewrite("nsf_ncses", "xl/sharedStrings.xml", lambda value: '<!DOCTYPE sst [<!ENTITY test "entity">]>' + value)
    with pytest.raises(NSFParseError):
        parse_nsf(changed, "nsf_ncses")
    duplicate = io.BytesIO(body("nsf_ncses"))
    with pytest.warns(UserWarning, match="Duplicate name"), zipfile.ZipFile(duplicate, "a") as archive:
        archive.writestr("xl/sharedStrings.xml", "duplicate")
    with pytest.raises(NSFParseError):
        parse_nsf(duplicate.getvalue(), "nsf_ncses")


def test_global_defaults_catalog_and_manifest_are_explicit():
    from showme.manifest.seeds.vcap_seed import vcap
    query = Query.parse({"scope": "global"})
    assert query.source_ids == ("nsf_ncses", "nsf_ncses_2020")
    assert query.geographies == ("WORLD",) and query.start_year == 1999
    assert query.end_year == datetime.now(UTC).year
    assert Query.parse({"scope": "global", "source_ids": ["kpmg_pitchbook"], "start_year": 1900}).source_ids == ("kpmg_pitchbook",)
    assert Query.parse({}).source_ids == ("oecd",) and Query.parse({}).start_year == 2007
    source_options = next(item for item in vcap.inputs if item.name == "source_ids").options
    assert set(NSF_URLS) <= set(source_options)
    for source in NSF_URLS:
        entry = SOURCE_CATALOG[source]
        assert entry["access_mode"] == "automatic"
        assert entry["lineage"] == "NSF NCSES / PitchBook"
        assert entry["metrics"] == ["investment"] and entry["stages"] == ["total"]
        assert entry["frequencies"] == ["annual"] and entry["units"] == ["USD"]
        assert entry["terms_url"] == "https://ncses.nsf.gov/indicators/permissions"


def test_edition_isolation_real_global_defaults_and_pre_window_coverage():
    service = saved_service(*NSF_URLS)
    result, meta = asyncio.run(service.query(Query.parse({"scope": "global"})))
    assert len(result["rows"]) == 32 and len(result["series"]) == 2
    assert result["summary"]["total"] is None
    assert meta["data_mode"] == "official" and meta["cached"] is True
    assert result["comparison"]["comparable_pairs"] == []
    assert len(result["comparison"]["blocked_pairs"]) == 1
    overlap = {row["source_id"]: row["value"] for row in result["rows"] if row["period"] == "2013"}
    assert overlap == {"nsf_ncses_2020": 69_795_000_000, "nsf_ncses": 71_468_000_000}
    assert all(row["underlying_access_date"] != row["published_at"] for row in result["rows"])
    narrow, _ = asyncio.run(service.query(Query.parse({"scope": "global", "start_year": 1999, "end_year": 2000})))
    assert len(narrow["rows"]) == 2
    coverage = {item["source_id"]: item for item in narrow["coverage"]["series"]}
    assert coverage["nsf_ncses"]["first_period"] == "2013" and coverage["nsf_ncses"]["last_period"] == "2024"
    assert coverage["nsf_ncses_2020"]["periods"] == [str(year) for year in range(1999, 2019)]
    assert narrow["coverage"]["requested_start"] == "1999" and narrow["coverage"]["requested_end"] == "2000"
    countries, _ = asyncio.run(service.query(Query.parse({"source_ids": ["nsf_ncses_2020"], "start_year": 1999, "end_year": 1999})))
    assert countries["rows"][0]["geography"] == "USA" and countries["rows"][0]["value"] == 22_545_000_000


def test_coverage_survives_zero_rows_and_reports_absent_geographies_sources():
    service = saved_service(*NSF_URLS)
    empty, _ = asyncio.run(service.query(Query.parse({"scope": "global", "start_year": 1900, "end_year": 1901})))
    assert empty["status"] == "empty" and empty["rows"] == []
    assert all(item["first_period"] for item in empty["coverage"]["series"])
    missing, _ = asyncio.run(service.query(Query.parse({"source_ids": ["nsf_ncses", "kpmg_pitchbook"], "geographies": ["CAN", "USA"], "start_year": 1900, "end_year": 1901})))
    assert len(missing["coverage"]["series"]) == 4
    for item in missing["coverage"]["series"]:
        if item["source_id"] == "kpmg_pitchbook" or item["geography"] == "CAN":
            assert item["periods"] == [] and item["first_period"] is None and item["last_period"] is None
    assert missing["rows"] == [] and missing["summary"]["observation_count"] == 0


def test_oecd_pre2007_window_reports_later_real_coverage_and_filters_semantics():
    service = VCAPService()
    csv = "REF_AREA,MEASURE,BUSINESS_DEVELOPMENT_STAGE,UNIT_MEASURE,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT_MULT\nUSA,VC_INV_MKT,_T,USD_EXC,A,2007,3,A,6\nUSA,VC_INV_MKT,_T,USD_EXC,A,2023,8,A,6\nUSA,VC_INV_MKT,SEED,USD_EXC,A,2006,1,A,6\nFRA,VC_INV_MKT,_T,USD_EXC,A,2005,1,A,6\n"
    service.store.save(parse_oecd(csv), origin="official")
    service.store.record_fetch("oecd", True)
    result, _ = asyncio.run(service.query(Query.parse({"start_year": 1999, "end_year": 2000})))
    assert result["rows"] == [] and result["status"] == "empty"
    assert result["coverage"]["series"][0]["periods"] == ["2007", "2023"]
    assert result["coverage"]["series"][0]["first_period"] == "2007"


@pytest.mark.parametrize("changes", [{"frequency": "quarterly"}, {"stage": "seed"},
    {"unit": "PERCENT_GDP"}, {"metric": "deals", "unit": "COUNT"}, {"metric": "fundraising"}, {"scope": "turkey", "geographies": ["TUR"]}])
def test_nsf_unsupported_queries_do_not_fetch_or_convert(monkeypatch, changes):
    def never(*args):
        raise AssertionError("unsupported request fetched upstream")
    monkeypatch.setattr(Providers, "_download", never)
    service = saved_service(*NSF_URLS)
    result, meta = asyncio.run(service.query(Query.parse({"scope": "global", "source_ids": list(NSF_URLS), **changes})))
    assert result["rows"] == []
    assert all(item["access_status"] == "unsupported" for item in meta["source_access"].values())
    assert all("annual total-stage" in item["reason"] for item in meta["source_access"].values())
    assert all(item["periods"] == [] for item in result["coverage"]["series"])
    if changes.get("frequency") == "quarterly":
        assert result["coverage"]["requested_start"] == "1999-Q1"
        assert result["coverage"]["requested_end"] == f"{datetime.now(UTC).year}-Q4"


def test_coverage_uses_pinned_release_not_latest_and_filters_quarters():
    service = saved_service("nsf_ncses")
    original = service.store.latest("nsf_ncses")
    changed = copy.deepcopy(original["dataset"])
    changed["published_at"] = "2026-06-01"
    changed["observations"] = [row for row in changed["observations"] if row["period"] == "2024"]
    service.store.save(changed, origin="official")
    pinned, _ = asyncio.run(service.query(Query.parse({"scope": "global", "source_ids": ["nsf_ncses"], "start_year": 1900, "end_year": 1900, "vintage": original["snapshot_id"]})))
    assert pinned["coverage"]["series"][0]["periods"] == [str(year) for year in range(2013, 2025)]
    assert pinned["coverage"]["series"][0]["snapshot_id"] == original["snapshot_id"]
    assert pinned["rows"] == []


def test_same_publication_day_import_and_direct_releases_order_by_retrieval():
    store = SnapshotStore()
    direct_data = parse_nsf(body("nsf_ncses"), "nsf_ncses")
    imported_data = {**direct_data, "published_at": "2026-05-01"}
    imported = store.save(validate_dataset(imported_data), retrieved_at="2026-05-02T00:00:00+00:00")
    direct = store.save(direct_data, origin="official", retrieved_at="2026-05-03T00:00:00+00:00")
    assert direct_data["published_at"] == imported["published_at"] == "2026-05-01T00:00:00+00:00"
    assert direct_data["underlying_access_date"] == "2025-05"
    assert store.latest("nsf_ncses")["snapshot_id"] == direct["snapshot_id"]
    assert store.selected(["nsf_ncses"], imported["snapshot_id"])[0] == imported


@pytest.mark.parametrize("source", list(NSF_URLS))
def test_nsf_download_provenance_cache_and_changed_schema_stale_immutability(source):
    calls = []
    response = [body(source)]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=response[0])
    store = SnapshotStore()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = Providers(store, client)
        assert asyncio.run(provider.ensure(source))["access_status"] == "available"
        original = store.latest(source, "official")
        assert original and original["origin"] == "official"
        assert str(calls[0].url) == NSF_URLS[source]
        assert calls[0].headers["accept"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert asyncio.run(provider.ensure(source))["cached"] is True and len(calls) == 1
        # Expire fetch state, then return a changed unit schema. No replacement.
        with store._connect() as conn:
            conn.execute("UPDATE fetch_state SET last_attempt=?,last_success=?", ("2020-01-01T00:00:00+00:00",) * 2)
        response[0] = rewrite(source, "xl/sharedStrings.xml", lambda value: value.replace("Millions", "Billions"))
        state = asyncio.run(provider.ensure(source, True))
        assert state["access_status"] == "stale" and state["stale"] is True
        assert "schema" in state["reason"]
        assert store.latest(source, "official") == original and len(store.versions()) == 1
        result, meta = asyncio.run(VCAPService(store, provider).query(Query.parse({"scope": "global", "source_ids": [source]})))
        assert result["status"] == "ok" and meta["stale"] is True
        assert {row["snapshot_id"] for row in result["rows"]} == {original["snapshot_id"]}


def test_quarterly_coverage_contains_only_matching_actual_periods():
    service = VCAPService()
    dataset = parse_nsf(body("nsf_ncses"), "nsf_ncses")
    dataset.update(source_id="custom_quarters", source_name="Custom quarterly fixture")
    annual = next(row for row in dataset["observations"] if row["scope"] == "global")
    from showme.engine.services.vcap.models import period_fields
    dataset["observations"] = [annual, {**annual, "period": "2013-Q2", **period_fields("2013-Q2")},
                               {**annual, "period": "2014-Q4", **period_fields("2014-Q4")}]
    service.store.save(dataset)
    result, _ = asyncio.run(service.query(Query.parse({"scope": "global", "source_ids": ["custom_quarters"], "frequency": "quarterly", "start_year": 1999, "end_year": 2000})))
    assert result["rows"] == []
    assert result["coverage"]["series"][0]["periods"] == ["2013-Q2", "2014-Q4"]
    assert result["coverage"]["requested_start"] == "1999-Q1" and result["coverage"]["requested_end"] == "2000-Q4"
