"""Strict query/import validation and normalized observation types."""
from __future__ import annotations

import calendar
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, TypedDict
from urllib.parse import urlsplit

SCOPES = ("countries", "global", "turkey", "crypto")
METRICS = ("investment", "deals", "fundraising")
STAGES = ("total", "seed", "early", "late")
UNITS = ("USD", "PERCENT_GDP", "COUNT")
MAX_IMPORT_BYTES = 2_000_000
MAX_OBSERVATIONS = 10_000


class InputError(ValueError):
    """Caller supplied invalid or incompatible semantic inputs."""


class Observation(TypedDict, total=False):
    scope: str
    geography: str
    period: str
    period_start: str
    period_end: str
    frequency: str
    metric: str
    stage: str
    unit: str
    value: float | int | None
    status: str
    coverage_note: str
    financing_scope: str
    is_partial: bool
    coverage_cutoff: str


class ValidationSummary(TypedDict):
    input_records: int
    accepted_records: int
    excluded_records: int
    future_records: int
    duplicate_records: int


class Dataset(TypedDict, total=False):
    schema_version: int
    source_id: str
    source_name: str
    source_url: str
    published_at: str | None
    methodology: str
    methodology_version: str
    geography_basis: str
    date_basis: str
    sector: str
    observations: list[Observation]
    validation_summary: ValidationSummary


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def choice(value: Any, options: tuple[str, ...], field: str) -> str:
    if not isinstance(value, str) or value not in options:
        raise InputError(f"{field} must be one of {', '.join(options)}")
    return value


def text(value: Any, field: str, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise InputError(f"{field} must be nonempty text (maximum {limit} characters)")
    return value.strip()


def source_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise InputError("source_id must be a lowercase slug (1-64 characters)")
    return value


def geography(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}|WORLD|TUR_DIASPORA", value):
        raise InputError("geography must be an ISO3 code, WORLD or TUR_DIASPORA")
    return value


def validate_scope_geo(scope: str, geo: str) -> None:
    if (scope == "countries" and geo in {"WORLD", "TUR_DIASPORA"}
            or scope == "global" and geo != "WORLD"
            or scope == "turkey" and geo not in {"TUR", "TUR_DIASPORA"}):
        raise InputError(f"{geo} is incompatible with scope {scope}")


def timestamp(value: Any) -> str:
    value = text(value, "published_at", 64)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)?", value):
        raise InputError("published_at must be an ISO date or datetime")
    offset = re.search(r"[+-](\d{2}):(\d{2})$", value)
    if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
        raise InputError("published_at timezone offset requires hours 00-23 and minutes 00-59")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=result.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError) as exc:
        raise InputError("published_at is not a valid calendar date or representable UTC instant") from exc


def safe_url(value: Any) -> str:
    value = text(value, "source_url", 2048)
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and parsed.username is None
                 and parsed.password is None and not any(ord(c) < 33 for c in value))
        _ = parsed.port
    except ValueError as exc:
        raise InputError("source_url is invalid") from exc
    if not valid:
        raise InputError("source_url must be HTTPS without credentials; it is provenance only")
    return value


def period_fields(value: Any) -> dict[str, str]:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}(?:-Q[1-4])?", value):
        raise InputError("period must be YYYY or YYYY-Q1 through YYYY-Q4")
    year = int(value[:4])
    if not 1900 <= year <= 2100:
        raise InputError("period year must be between 1900 and 2100")
    quarter = int(value[-1]) if "-Q" in value else None
    first = (quarter - 1) * 3 + 1 if quarter else 1
    last = first + 2 if quarter else 12
    return {"frequency": "quarterly" if quarter else "annual",
            "period_start": date(year, first, 1).isoformat(),
            "period_end": date(year, last, calendar.monthrange(year, last)[1]).isoformat()}


def validate_metric_unit(metric: str, unit: str) -> None:
    if (metric == "deals") != (unit == "COUNT"):
        raise InputError("deals requires COUNT; monetary metrics require USD or PERCENT_GDP")
    if metric == "fundraising" and unit != "USD":
        raise InputError("fundraising requires USD")


def _list(value: Any, field: str, validator: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list) or not value or len(value) > 64:
        raise InputError(f"{field} must be a nonempty list or comma separated string (maximum 64)")
    return tuple(sorted({validator(item) for item in value}))


@dataclass(frozen=True)
class Query:
    scope: str = "countries"
    source_ids: tuple[str, ...] = ("oecd",)
    geographies: tuple[str, ...] = ("USA",)
    metric: str = "investment"
    stage: str = "total"
    frequency: str = "annual"
    unit: str = "USD"
    start_year: int = 2007
    end_year: int = 2026
    refresh: bool = False
    vintage: str | None = None
    financing_scope: str = "vc"

    @classmethod
    def parse(cls, params: dict[str, Any]) -> Query:
        scope = choice(params.get("scope", "countries"), SCOPES, "scope")
        defaults = {"countries": ["USA"], "global": ["WORLD"], "turkey": ["TUR"], "crypto": ["WORLD"]}
        sources = {"countries": ["oecd"], "global": ["kpmg_pitchbook"], "turkey": ["startups_watch"], "crypto": ["defillama"]}
        geos = _list(params.get("geographies", defaults[scope]), "geographies", geography)
        for geo in geos:
            validate_scope_geo(scope, geo)
        metric = choice(params.get("metric", "investment"), METRICS, "metric")
        unit = choice(params.get("unit", "USD"), UNITS, "unit")
        validate_metric_unit(metric, unit)
        years = []
        for field, default in (("start_year", 2007), ("end_year", datetime.now(timezone.utc).year)):
            raw = params.get(field, default)
            if isinstance(raw, str) and re.fullmatch(r"\d{4}", raw):
                raw = int(raw)
            if type(raw) is not int or not 1900 <= raw <= datetime.now(timezone.utc).year:
                raise InputError(f"{field} must be an integer between 1900 and the current year")
            years.append(raw)
        if years[0] > years[1]:
            raise InputError("start_year cannot exceed end_year")
        refresh = params.get("refresh", False)
        if refresh in ("true", "false"):
            refresh = refresh == "true"
        if type(refresh) is not bool:
            raise InputError("refresh must be boolean")
        vintage = params.get("vintage")
        if vintage == "latest":
            vintage = None
        if vintage is not None and (not isinstance(vintage, str) or not re.fullmatch(r"[a-f0-9]{64}", vintage)):
            raise InputError("vintage must be a snapshot_id or latest")
        financing = choice(params.get("financing_scope", "vc"), ("vc", "all_raises"), "financing_scope")
        if financing != "vc" and scope != "crypto":
            raise InputError("all_raises is only supported for crypto")
        return cls(scope, _list(params.get("source_ids", sources[scope]), "source_ids", source_id),
                   geos, metric, choice(params.get("stage", "total"), STAGES, "stage"),
                   choice(params.get("frequency", "annual"), ("annual", "quarterly"), "frequency"),
                   unit, *years, refresh, vintage, financing)


def validate_dataset(raw: Any) -> Dataset:
    if not isinstance(raw, dict):
        raise InputError("dataset must be an object")
    try:
        size = len(json.dumps(raw, allow_nan=False, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise InputError("dataset must be finite JSON") from exc
    if size > MAX_IMPORT_BYTES:
        raise InputError("dataset exceeds the 2 MB JSON limit")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise InputError("schema_version must be 1")
    sid = source_id(raw.get("source_id"))
    from .catalog import SOURCE_CATALOG
    name = (SOURCE_CATALOG.get(sid, {}).get("source_name") if sid != "custom" else None) or text(raw.get("source_name"), "source_name", 160)
    result: Dataset = {
        "schema_version": 1, "source_id": sid, "source_name": name,
        "source_url": safe_url(raw.get("source_url")), "published_at": timestamp(raw.get("published_at")),
        "methodology": text(raw.get("methodology"), "methodology"),
        "methodology_version": text(raw.get("methodology_version"), "methodology_version", 160),
        "geography_basis": choice(raw.get("geography_basis"), ("company_hq", "fund_manager", "source_defined"), "geography_basis"),
        "date_basis": choice(raw.get("date_basis"), ("announced", "closed", "source_defined"), "date_basis"),
        "sector": choice(raw.get("sector"), ("all", "crypto", "web3", "source_defined"), "sector"),
    }
    observations = raw.get("observations")
    if not isinstance(observations, list):
        raise InputError("observations must be an array")
    if len(observations) > MAX_OBSERVATIONS:
        raise InputError("observations exceeds the 10,000 limit")
    rows: list[Observation] = []
    seen: set[tuple[Any, ...]] = set()
    for index, row in enumerate(observations):
        if not isinstance(row, dict):
            raise InputError(f"observation {index} must be an object")
        obs: Observation = {
            "scope": choice(row.get("scope"), SCOPES, "scope"),
            "geography": geography(row.get("geography")), "period": row.get("period"),
            "metric": choice(row.get("metric"), METRICS, "metric"),
            "stage": choice(row.get("stage"), STAGES, "stage"),
            "unit": choice(row.get("unit"), UNITS, "unit"),
            "status": choice(row.get("status"), ("reported", "provisional", "missing"), "status"),
        }
        obs.update(period_fields(obs["period"]))
        validate_scope_geo(obs["scope"], obs["geography"])
        validate_metric_unit(obs["metric"], obs["unit"])
        if "value" not in row:
            raise InputError("every observation requires value (number or null)")
        value = row["value"]
        if value is not None:
            try:
                finite = type(value) in (int, float) and math.isfinite(value) and value >= 0
            except OverflowError:
                finite = False
            if not finite:
                raise InputError("value must be a finite nonnegative number or null")
        if obs["status"] == "missing" and value is not None:
            raise InputError("missing observations require null value")
        if value is None and obs["status"] != "missing":
            raise InputError("null value requires missing status")
        if value is not None and obs["unit"] == "PERCENT_GDP" and value > 100:
            raise InputError("PERCENT_GDP cannot exceed 100")
        if value is not None and obs["unit"] == "COUNT" and int(value) != value:
            raise InputError("COUNT must be an integer")
        obs["value"] = value
        obs["financing_scope"] = choice(row.get("financing_scope", raw.get("financing_scope", "vc")), ("vc", "all_raises"), "financing_scope")
        if obs["financing_scope"] != "vc" and obs["scope"] != "crypto":
            raise InputError("all_raises is only supported for crypto")
        if row.get("coverage_note") is not None:
            obs["coverage_note"] = text(row["coverage_note"], "coverage_note", 2000)
        key = tuple(obs[field] for field in ("scope", "geography", "period", "metric", "stage", "unit", "financing_scope"))
        if key in seen:
            raise InputError(f"duplicate observation for {key}")
        seen.add(key)
        rows.append(obs)
    result["observations"] = sorted(rows, key=lambda r: tuple(str(r[k]) for k in ("scope", "geography", "period", "metric", "stage", "unit", "financing_scope")))
    return result
