"""BTMM - central bank policy-rate monitor."""

from __future__ import annotations

import asyncio
import csv
import io
import math
import os
import threading
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


BIS_CBPOL_URL = "https://data.bis.org/static/bulk/WS_CBPOL_csv_col.zip"
CACHE_TTL_SECONDS = 60 * 60 * 6

_CACHE_LOCK = threading.Lock()
_CACHE_AT = 0.0
_CACHE_ROWS: list[dict[str, Any]] | None = None

_COUNTRY_ALIASES = {
    "ALL": "ALL",
    "GLOBAL": "ALL",
    "WORLD": "ALL",
    "US": "US",
    "USA": "US",
    "UNITED STATES": "US",
    "FED": "US",
    "EU": "EU",
    "EA": "EU",
    "EZ": "EU",
    "XM": "EU",
    "EURO": "EU",
    "EURO AREA": "EU",
    "EUROZONE": "EU",
    "ECB": "EU",
    "UK": "GB",
    "GB": "GB",
    "UNITED KINGDOM": "GB",
    "BOE": "GB",
    "JP": "JP",
    "JAPAN": "JP",
    "BOJ": "JP",
    "TR": "TR",
    "TRY": "TR",
    "TURKEY": "TR",
    "TURKIYE": "TR",
    "TCMB": "TR",
}

_DISPLAY_CODE = {"XM": "EU"}
_BIS_CODE = {"EU": "XM"}

_CENTRAL_BANK = {
    "AR": "Central Bank of Argentina",
    "AT": "European Central Bank",
    "AU": "Reserve Bank of Australia",
    "BE": "European Central Bank",
    "BR": "Central Bank of Brazil",
    "CA": "Bank of Canada",
    "CH": "Swiss National Bank",
    "CL": "Central Bank of Chile",
    "CN": "People's Bank of China",
    "CO": "Bank of the Republic",
    "CZ": "Czech National Bank",
    "DE": "European Central Bank",
    "DK": "Danmarks Nationalbank",
    "ES": "European Central Bank",
    "EU": "European Central Bank",
    "FR": "European Central Bank",
    "GB": "Bank of England",
    "GR": "European Central Bank",
    "HK": "Hong Kong Monetary Authority",
    "HR": "European Central Bank",
    "HU": "Magyar Nemzeti Bank",
    "ID": "Bank Indonesia",
    "IL": "Bank of Israel",
    "IN": "Reserve Bank of India",
    "IS": "Central Bank of Iceland",
    "IT": "European Central Bank",
    "JP": "Bank of Japan",
    "KR": "Bank of Korea",
    "KW": "Central Bank of Kuwait",
    "MA": "Bank Al-Maghrib",
    "MK": "National Bank of North Macedonia",
    "MX": "Bank of Mexico",
    "MY": "Bank Negara Malaysia",
    "NL": "European Central Bank",
    "NO": "Norges Bank",
    "NZ": "Reserve Bank of New Zealand",
    "PE": "Central Reserve Bank of Peru",
    "PH": "Bangko Sentral ng Pilipinas",
    "PL": "National Bank of Poland",
    "PT": "European Central Bank",
    "RO": "National Bank of Romania",
    "RS": "National Bank of Serbia",
    "RU": "Bank of Russia",
    "SA": "Saudi Central Bank",
    "SE": "Sveriges Riksbank",
    "TH": "Bank of Thailand",
    "TR": "Central Bank of the Republic of Turkiye",
    "US": "Federal Reserve",
    "ZA": "South African Reserve Bank",
}

_CURRENCY = {
    "AR": "ARS",
    "AT": "EUR",
    "AU": "AUD",
    "BE": "EUR",
    "BR": "BRL",
    "CA": "CAD",
    "CH": "CHF",
    "CL": "CLP",
    "CN": "CNY",
    "CO": "COP",
    "CZ": "CZK",
    "DE": "EUR",
    "DK": "DKK",
    "ES": "EUR",
    "EU": "EUR",
    "FR": "EUR",
    "GB": "GBP",
    "GR": "EUR",
    "HK": "HKD",
    "HR": "EUR",
    "HU": "HUF",
    "ID": "IDR",
    "IL": "ILS",
    "IN": "INR",
    "IS": "ISK",
    "IT": "EUR",
    "JP": "JPY",
    "KR": "KRW",
    "KW": "KWD",
    "MA": "MAD",
    "MK": "MKD",
    "MX": "MXN",
    "MY": "MYR",
    "NL": "EUR",
    "NO": "NOK",
    "NZ": "NZD",
    "PE": "PEN",
    "PH": "PHP",
    "PL": "PLN",
    "PT": "EUR",
    "RO": "RON",
    "RS": "RSD",
    "RU": "RUB",
    "SA": "SAR",
    "SE": "SEK",
    "TH": "THB",
    "TR": "TRY",
    "US": "USD",
    "ZA": "ZAR",
}

_REGION = {
    "AR": "americas",
    "BR": "americas",
    "CA": "americas",
    "CL": "americas",
    "CO": "americas",
    "MX": "americas",
    "PE": "americas",
    "US": "americas",
    "AT": "europe",
    "BE": "europe",
    "CH": "europe",
    "CZ": "europe",
    "DE": "europe",
    "DK": "europe",
    "ES": "europe",
    "EU": "europe",
    "FR": "europe",
    "GB": "europe",
    "GR": "europe",
    "HR": "europe",
    "HU": "europe",
    "IS": "europe",
    "IT": "europe",
    "MK": "europe",
    "NL": "europe",
    "NO": "europe",
    "PL": "europe",
    "PT": "europe",
    "RO": "europe",
    "RS": "europe",
    "RU": "europe",
    "SE": "europe",
    "TR": "europe",
    "AU": "asia_pacific",
    "CN": "asia_pacific",
    "HK": "asia_pacific",
    "ID": "asia_pacific",
    "IN": "asia_pacific",
    "JP": "asia_pacific",
    "KR": "asia_pacific",
    "MY": "asia_pacific",
    "NZ": "asia_pacific",
    "PH": "asia_pacific",
    "TH": "asia_pacific",
    "IL": "mea",
    "KW": "mea",
    "MA": "mea",
    "SA": "mea",
    "ZA": "mea",
}

_REGION_ALIASES = {
    "ALL": "all",
    "GLOBAL": "all",
    "WORLD": "all",
    "AMERICAS": "americas",
    "AMERICA": "americas",
    "EUROPE": "europe",
    "ASIA": "asia_pacific",
    "APAC": "asia_pacific",
    "ASIA_PACIFIC": "asia_pacific",
    "MEA": "mea",
    "EM": "em",
    "EMERGING": "em",
    "G10": "g10",
}

_G10 = {"AU", "CA", "EU", "GB", "JP", "NO", "NZ", "SE", "CH", "US"}
_EM = {
    "AR",
    "BR",
    "CL",
    "CN",
    "CO",
    "CZ",
    "HK",
    "HU",
    "ID",
    "IL",
    "IN",
    "KR",
    "KW",
    "MA",
    "MK",
    "MX",
    "MY",
    "PE",
    "PH",
    "PL",
    "RO",
    "RS",
    "RU",
    "SA",
    "TH",
    "TR",
    "ZA",
}

_SORT_ORDER = [
    "US",
    "EU",
    "GB",
    "JP",
    "TR",
    "CA",
    "CH",
    "AU",
    "NZ",
    "SE",
    "NO",
    "CN",
    "IN",
    "BR",
    "MX",
]

_FALLBACK_ROWS = [
    {
        "country_code": "US",
        "bis_ref_area": "US",
        "country": "United States",
        "central_bank": "Federal Reserve",
        "currency": "USD",
        "region": "americas",
        "policy_rate": 3.625,
        "as_of": "2026-04-28",
        "previous_rate": 3.875,
        "previous_date": "2025-12-10",
        "change_bp": -25.0,
        "last_move": "cut",
        "trend_3m_bp": 0.0,
        "source": "local fallback",
    },
    {
        "country_code": "EU",
        "bis_ref_area": "XM",
        "country": "Euro area",
        "central_bank": "European Central Bank",
        "currency": "EUR",
        "region": "europe",
        "policy_rate": 2.0,
        "as_of": "2026-04-28",
        "previous_rate": 2.25,
        "previous_date": "2025-06-10",
        "change_bp": -25.0,
        "last_move": "cut",
        "trend_3m_bp": 0.0,
        "source": "local fallback",
    },
    {
        "country_code": "GB",
        "bis_ref_area": "GB",
        "country": "United Kingdom",
        "central_bank": "Bank of England",
        "currency": "GBP",
        "region": "europe",
        "policy_rate": 3.75,
        "as_of": "2026-04-27",
        "previous_rate": 4.0,
        "previous_date": "2025-12-18",
        "change_bp": -25.0,
        "last_move": "cut",
        "trend_3m_bp": 0.0,
        "source": "local fallback",
    },
    {
        "country_code": "JP",
        "bis_ref_area": "JP",
        "country": "Japan",
        "central_bank": "Bank of Japan",
        "currency": "JPY",
        "region": "asia_pacific",
        "policy_rate": 0.75,
        "as_of": "2026-04-28",
        "previous_rate": 0.5,
        "previous_date": "2025-12-19",
        "change_bp": 25.0,
        "last_move": "hike",
        "trend_3m_bp": 0.0,
        "source": "local fallback",
    },
    {
        "country_code": "TR",
        "bis_ref_area": "TR",
        "country": "Turkiye",
        "central_bank": "Central Bank of the Republic of Turkiye",
        "currency": "TRY",
        "region": "europe",
        "policy_rate": 37.0,
        "as_of": "2026-04-24",
        "previous_rate": 38.0,
        "previous_date": "2026-01-22",
        "change_bp": -100.0,
        "last_move": "cut",
        "trend_3m_bp": 0.0,
        "source": "local fallback",
    },
]


@FunctionRegistry.register
class BTMMFunction(BaseFunction):
    code = "BTMM"
    name = "Country Rate Environment"
    category = "macro"
    description = (
        "Central bank policy-rate matrix from BIS CBPOL, with latest rate, "
        "last policy move, 3-month trend, and country/region filters."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = _normalize_country(params.get("country"))
        region = _normalize_region(params.get("region"))
        limit = _int_param(params.get("limit"), default=80, floor=1, ceiling=100)
        timeout = _float_param(params.get("timeout"), default=8.0, floor=2.0, ceiling=30.0)
        force_refresh = _truthy(params.get("refresh") or params.get("force_refresh"))

        warnings: list[str] = []
        try:
            rows = await asyncio.to_thread(_load_bis_rows, timeout, force_refresh)
            sources = ["BIS CBPOL"]
        except Exception as exc:
            rows = [dict(row) for row in _FALLBACK_ROWS]
            sources = ["local fallback"]
            warnings.append(f"BIS CBPOL unavailable: {exc}")

        filtered = _filter_rows(rows, country=country, region=region)
        filtered = sorted(filtered, key=_sort_key)[:limit]
        summary = _summary(filtered, universe=rows)

        # Bug #24 fix: surface data staleness as a warning so the UI's
        # "live" pill can flip to "warn" when the BIS cache + freshest row
        # in scope is more than 24 hours old (e.g. weekend, network outage,
        # cached fallback). The sanitizer fix in Agent 4's slice keeps
        # `warnings` instead of erasing them.
        latest_as_of = _max_as_of(filtered) or _max_as_of(rows)
        stale_seconds = _seconds_since(latest_as_of) if latest_as_of else None
        if stale_seconds is not None and stale_seconds > 24 * 3600:
            warnings.append(
                f"data_stale_24h: freshest BIS observation {latest_as_of} "
                f"is {int(stale_seconds // 3600)}h old"
            )

        # Compute the BTMM "as_of" envelope key — the freshest observation
        # available in scope. UI uses this for the "Data as of" stamp.
        as_of_envelope = latest_as_of

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "country": country,
                "region": region,
                "rows": filtered,
                "summary": summary,
                "as_of": as_of_envelope,
                "stale_seconds": stale_seconds,
                "history": _history_for_rows(filtered),
                "usage": {
                    "country": "Use ALL, US, EU, GB, JP, TR, or a BIS ISO country code.",
                    "region": "Use all, g10, em, americas, europe, asia_pacific, or mea.",
                    "source": "Rates are read from BIS WS_CBPOL daily series and cached for 6 hours.",
                },
                "methodology": (
                    "BTMM reads BIS CBPOL policy-rate series. Latest rate is the most recent observation, "
                    "last move is the latest rate minus the previous distinct rate, and 3M bp compares "
                    "the latest rate with the observation on or before roughly 90 calendar days earlier."
                ),
                "field_dictionary": {
                    "policy_rate": "Latest central-bank policy rate in percent.",
                    "change_bp": "Latest move in basis points versus the previous distinct rate.",
                    "trend_3m_bp": "Basis-point change over roughly 90 calendar days.",
                    "as_of": "Latest observation date from BIS CBPOL.",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata={
                "source_url": BIS_CBPOL_URL,
                "cache_age_seconds": max(0, int(time.time() - _CACHE_AT)) if _CACHE_ROWS else None,
                "row_count": len(filtered),
                "universe_count": len(rows),
                "country": country,
                "region": region,
            },
        )


def _load_bis_rows(timeout: float, force_refresh: bool = False) -> list[dict[str, Any]]:
    global _CACHE_AT, _CACHE_ROWS
    now = time.time()
    with _CACHE_LOCK:
        if not force_refresh and _CACHE_ROWS and now - _CACHE_AT < CACHE_TTL_SECONDS:
            return [dict(row) for row in _CACHE_ROWS]

        payload = _read_disk_cache(max_age_seconds=CACHE_TTL_SECONDS if not force_refresh else None)
        if payload is not None and not force_refresh:
            rows = _parse_bis_zip(payload)
            _CACHE_ROWS = rows
            _CACHE_AT = _disk_cache_mtime() or now
            return [dict(row) for row in rows]

        import httpx

        from_network = True
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(
                    BIS_CBPOL_URL,
                    headers={
                        "Accept": "application/zip,application/octet-stream,*/*",
                        "User-Agent": "showMe/1.0 policy-rate-monitor",
                    },
                )
                response.raise_for_status()
                payload = response.content
        except Exception:
            payload = _read_disk_cache(max_age_seconds=None)
            if payload is None:
                raise
            from_network = False
        rows = _parse_bis_zip(payload)
        if not rows:
            raise RuntimeError("BIS CBPOL returned no policy-rate rows")
        if from_network:
            _write_disk_cache(payload)
        _CACHE_ROWS = rows
        _CACHE_AT = now if from_network else (_disk_cache_mtime() or now)
        return [dict(row) for row in rows]


def _parse_bis_zip(payload: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_name = next((name for name in archive.namelist() if name.lower().endswith(".csv")), None)
        if not csv_name:
            raise RuntimeError("BIS CBPOL zip did not contain a CSV")
        with archive.open(csv_name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            rows = [_parse_bis_row(row, reader.fieldnames or []) for row in reader]

    parsed = [row for row in rows if row]
    daily = [row for row in parsed if row["frequency"] == "D"]
    return daily or parsed


def _read_disk_cache(max_age_seconds: int | None) -> bytes | None:
    path = _disk_cache_path()
    try:
        stat = path.stat()
    except OSError:
        return None
    if max_age_seconds is not None and time.time() - stat.st_mtime > max_age_seconds:
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _write_disk_cache(payload: bytes) -> None:
    path = _disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    except OSError:
        return


def _disk_cache_mtime() -> float | None:
    try:
        return _disk_cache_path().stat().st_mtime
    except OSError:
        return None


def _disk_cache_path() -> Path:
    root = os.environ.get("SHOWME_HOME")
    if root:
        base = Path(root).expanduser()
    else:
        base = Path.home() / "Library" / "Application Support" / "showMe"
    return base / "cache" / "bis_cbpol.zip"


def _parse_bis_row(row: dict[str, str], fields: list[str]) -> dict[str, Any] | None:
    freq = row.get("FREQ", "").strip().upper()
    bis_code = row.get("REF_AREA", "").strip().upper()
    if not bis_code:
        return None
    display_code = _DISPLAY_CODE.get(bis_code, bis_code)
    values = _series_values(row, fields, daily=(freq == "D"))
    if not values and freq == "D":
        values = _series_values(row, fields, daily=False)
    if not values:
        return None

    current_date, current_rate = values[-1]
    prev_date, prev_rate = _previous_distinct(values, current_rate)
    ref_date = _parse_date(current_date)
    value_3m = _value_on_or_before(values, ref_date - timedelta(days=90)) if ref_date else None
    change_bp = _round_bp(current_rate - prev_rate) if prev_rate is not None else None
    trend_3m_bp = _round_bp(current_rate - value_3m) if value_3m is not None else None

    return {
        "country_code": display_code,
        "bis_ref_area": bis_code,
        "country": _clean_country_name(row.get("Reference area") or display_code),
        "central_bank": _CENTRAL_BANK.get(display_code, "Central bank"),
        "currency": _CURRENCY.get(display_code),
        "region": _REGION.get(display_code, "other"),
        "policy_rate": round(current_rate, 4),
        "as_of": current_date,
        "previous_rate": round(prev_rate, 4) if prev_rate is not None else None,
        "previous_date": prev_date,
        "change_bp": change_bp,
        "last_move": _last_move(change_bp),
        "trend_3m_bp": trend_3m_bp,
        "frequency": freq or None,
        "history": [
            {"date": period, "policy_rate": round(value, 4), "country_code": display_code}
            for period, value in values[-260:]
        ],
        "source": "BIS CBPOL",
    }


def _series_values(
    row: dict[str, str],
    fields: list[str],
    *,
    daily: bool,
) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for field in fields:
        if not _is_period(field, daily=daily):
            continue
        value = _to_float(row.get(field))
        if value is None:
            continue
        values.append((field, value))
    return values


def _is_period(field: str | None, *, daily: bool) -> bool:
    if not field:
        return False
    if daily:
        return len(field) == 10 and field[4] == "-" and field[7] == "-"
    return len(field) == 7 and field[4] == "-"


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text.lower() == "nan":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _previous_distinct(values: list[tuple[str, float]], current: float) -> tuple[str | None, float | None]:
    for period, value in reversed(values[:-1]):
        if abs(value - current) > 1e-9:
            return period, value
    return None, None


def _value_on_or_before(values: list[tuple[str, float]], target: date) -> float | None:
    for period, value in reversed(values):
        parsed = _parse_date(period)
        if parsed and parsed <= target:
            return value
    return None


def _parse_date(period: str) -> date | None:
    try:
        if len(period) == 7:
            return date.fromisoformat(f"{period}-01")
        return date.fromisoformat(period)
    except ValueError:
        return None


def _round_bp(delta_rate: float) -> float:
    return round(delta_rate * 100, 2)


def _last_move(change_bp: float | None) -> str:
    if change_bp is None or abs(change_bp) < 0.01:
        return "hold"
    return "hike" if change_bp > 0 else "cut"


def _filter_rows(rows: list[dict[str, Any]], *, country: str, region: str) -> list[dict[str, Any]]:
    filtered = rows
    if country != "ALL":
        filtered = [row for row in filtered if row.get("country_code") == country]
    if region != "all":
        if region == "g10":
            filtered = [row for row in filtered if row.get("country_code") in _G10]
        elif region == "em":
            filtered = [row for row in filtered if row.get("country_code") in _EM]
        else:
            filtered = [row for row in filtered if row.get("region") == region]
    return [dict(row) for row in filtered]


def _summary(rows: list[dict[str, Any]], *, universe: list[dict[str, Any]]) -> dict[str, Any]:
    rates = [float(row["policy_rate"]) for row in rows if isinstance(row.get("policy_rate"), (int, float))]
    move_counts = {
        "hikes": sum(1 for row in rows if row.get("last_move") == "hike"),
        "cuts": sum(1 for row in rows if row.get("last_move") == "cut"),
        "holds": sum(1 for row in rows if row.get("last_move") == "hold"),
    }
    hottest = max(rows, key=lambda row: abs(float(row.get("change_bp") or 0)), default=None)

    # Bug #24 fix: Range min/max ignores rows whose ``as_of`` is older than
    # 6 months. Previously a stale 2022 Croatian 0.00% observation surfaced
    # as the "Range min" even though every other CB had moved since. We
    # keep the full ``rates`` list for the average (count is what matters
    # there), but compute min/max from the fresh-only slice.
    today_iso = date.today().isoformat()
    cutoff_iso = (date.today() - timedelta(days=183)).isoformat()
    fresh_rates: list[float] = []
    for row in rows:
        rate = row.get("policy_rate")
        if not isinstance(rate, (int, float)):
            continue
        as_of = row.get("as_of")
        if not as_of or str(as_of) < cutoff_iso:
            continue
        # Guard against future-dated rows polluting min/max.
        if str(as_of) > today_iso:
            continue
        fresh_rates.append(float(rate))
    if not fresh_rates and rates:
        # Edge case: no row passes the freshness gate (e.g. an all-stale
        # fallback table in unit tests). Falling back to the full set is
        # still better than surfacing `None`.
        fresh_rates = rates

    return {
        "rows": len(rows),
        "universe": len(universe),
        "average_policy_rate": round(sum(rates) / len(rates), 4) if rates else None,
        "max_policy_rate": max(fresh_rates) if fresh_rates else None,
        "min_policy_rate": min(fresh_rates) if fresh_rates else None,
        "range_window_days": 183,
        **move_counts,
        "largest_last_move": hottest,
    }


def _max_as_of(rows: list[dict[str, Any]]) -> str | None:
    best: str | None = None
    for row in rows:
        as_of = row.get("as_of") if isinstance(row, dict) else None
        if not as_of:
            continue
        if best is None or str(as_of) > best:
            best = str(as_of)
    return best


def _seconds_since(as_of_iso: str) -> float | None:
    parsed = _parse_date(as_of_iso)
    if parsed is None:
        return None
    today = date.today()
    return max(0.0, (today - parsed).total_seconds())


def _history_for_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for row in rows[:6]:
        for point in row.get("history") or []:
            if isinstance(point, dict):
                history.append({
                    **point,
                    "country": row.get("country"),
                    "central_bank": row.get("central_bank"),
                })
    return history[-400:]


def _normalize_country(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "ALL"
    raw = str(value).strip().upper().replace("-", " ").replace("_", " ")
    normalized = _COUNTRY_ALIASES.get(raw, raw)
    return _DISPLAY_CODE.get(_BIS_CODE.get(normalized, normalized), normalized)


def _normalize_region(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "all"
    raw = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    return _REGION_ALIASES.get(raw, raw.lower())


def _int_param(value: Any, *, default: int, floor: int, ceiling: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))


def _float_param(value: Any, *, default: float, floor: float, ceiling: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "refresh"}


def _sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    code = str(row.get("country_code") or "")
    try:
        major = _SORT_ORDER.index(code)
    except ValueError:
        major = len(_SORT_ORDER)
    return (major, str(row.get("region") or ""), str(row.get("country") or code))


def _clean_country_name(value: str) -> str:
    return value.strip() or "Unknown"
