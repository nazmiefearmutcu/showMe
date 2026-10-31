"""Bounded direct adapters. Keyed URLs and upstream exceptions never escape."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import math
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .catalog import SOURCE_CATALOG
from .models import Dataset, InputError, period_fields, utcnow
from .store import SnapshotStore

OECD_URL = "https://sdmx.oecd.org/public/rest/v1/data/OECD.SDD.TPS,DSD_VC@DF_VC_INV,1.0/.?startPeriod=2007&format=csvfile"
MAX_RESPONSE_BYTES = 8_000_000
TTL_SECONDS = 86400
COOLDOWN_SECONDS = 60
_LOCKS: dict[tuple[str, str], threading.Lock] = {}


class _RedactKeyedEndpoint(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx itself emits full request URLs at INFO, even when callers do
        # not log them. Redact before any handler/caplog receives the record.
        message = record.getMessage()
        if "pro-api.llama.fi/" in message:
            message = re.sub(r"https?://pro-api\.llama\.fi/[^\s\"'<>]+", "[DefiLlama Pro endpoint]", message)
            record.msg, record.args = message, ()
        return True


logging.getLogger("httpx").addFilter(_RedactKeyedEndpoint())


class ProviderError(RuntimeError):
    """A deliberately sanitized provider failure."""


def _base(source: str) -> Dataset:
    entry = SOURCE_CATALOG[source]
    return {"schema_version": 1, "source_id": source, "source_name": entry["source_name"],
            "source_url": entry["source_url"], "published_at": None,
            "geography_basis": "source_defined", "date_basis": "source_defined",
            "sector": "all", "observations": []}


def parse_oecd(body: str, retrieved_at: str | None = None, last_modified: str | None = None) -> Dataset:
    """USD_EXC is millions in this flow; PT_B1GQ is already percent, not fraction.

    The current flow has no release/publication date. HTTP Last-Modified is
    transport metadata (observed older than some observations), never publication.
    """
    reader = csv.DictReader(io.StringIO(body.lstrip("\ufeff")))
    required = {"REF_AREA", "MEASURE", "BUSINESS_DEVELOPMENT_STAGE", "UNIT_MEASURE", "FREQ", "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "UNIT_MULT"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ProviderError("OECD returned an incompatible CSV schema")
    data = _base("oecd")
    data.update(methodology="OECD VC_INV_MKT, market investment by source-defined country geography and stage. USD scaled by UNIT_MULT; GDP values are percent of GDP. Non-production dataflow; stage comparability varies by country. Observation flags retained. Publication date unavailable in CSV; HTTP Last-Modified is not publication.", methodology_version="OECD.SDD.TPS,DSD_VC@DF_VC_INV,1.0")
    stages = {"_T": "total", "SEED": "seed", "START": "early", "LATER": "late"}
    seen = set()
    for raw in reader:
        if raw["MEASURE"] != "VC_INV_MKT" or raw["FREQ"] != "A" or raw["BUSINESS_DEVELOPMENT_STAGE"] not in stages or raw["UNIT_MEASURE"] not in {"USD_EXC", "PT_B1GQ"}:
            continue
        geo = raw["REF_AREA"]
        if len(geo) != 3 or not geo.isalpha() or not geo.isupper():
            continue  # no WORLD aggregate or codelist-derived membership
        try:
            period = period_fields(raw["TIME_PERIOD"])
            if period["frequency"] != "annual":
                continue
            mult = int(raw["UNIT_MULT"])
            if not -12 <= mult <= 12:
                raise ValueError("multiplier")
            missing = raw["OBS_VALUE"].strip() in {"", "..", "...", ":"}
            value = None if missing else float(raw["OBS_VALUE"]) * 10 ** mult
            unit = "USD" if raw["UNIT_MEASURE"] == "USD_EXC" else "PERCENT_GDP"
            if value is not None and (not math.isfinite(value) or value < 0 or unit == "PERCENT_GDP" and value > 100):
                raise ValueError("value")
        except (ValueError, TypeError, OverflowError, InputError) as exc:
            raise ProviderError("OECD returned an invalid observation or multiplier") from exc
        stage = stages[raw["BUSINESS_DEVELOPMENT_STAGE"]]
        key = (geo, raw["TIME_PERIOD"], stage, unit)
        if key in seen:
            raise ProviderError("OECD returned duplicate observation keys")
        seen.add(key)
        flag = raw["OBS_STATUS"]
        note = "OECD non-production dataflow; source-defined market geography; retain original stage boundaries."
        if geo in {"KOR", "NZL", "RUS", "ZAF"}:
            note += " OECD flags limited stage comparability for this country; stages may not match other countries."
        data["observations"].append({"scope": "countries", "geography": geo, "period": raw["TIME_PERIOD"],
            **period, "metric": "investment", "stage": stage, "unit": unit,
            "value": value, "status": "missing" if value is None else "provisional" if flag in {"P", "E"} else "reported",
            "financing_scope": "vc", "coverage_note": note, "unit_mult": mult,
            "observation_flag": flag, "source_unit": raw["UNIT_MEASURE"],
            "source_stage": raw["BUSINESS_DEVELOPMENT_STAGE"],
            "source_updated_at": raw.get("LAST_UPDATE") or raw.get("LAST_UPDATED") or None})
    if not data["observations"]:
        raise ProviderError("OECD returned no supported observations")
    data["observations"].sort(key=lambda r: (r["geography"], r["period"], r["stage"], r["unit"]))
    return data


def parse_defillama(payload: Any, *, as_of: datetime | None = None) -> Dataset:
    """Documented SDK amount unit: millions USD. This is funding, not strict VC.

    The documented raises schema has no equity/token instrument or headquarters
    classifier. Round names do not establish equity: every automated row belongs
    to the explicit all_raises view. No geography is inferred from investors.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("raises"), list):
        raise ProviderError("DefiLlama returned an incompatible raises schema")
    if len(payload["raises"]) > 100_000:
        raise ProviderError("DefiLlama raises limit exceeded")
    # One captured instant governs future-record filtering and every derived
    # calendar bucket; midnight/quarter rollover cannot split one response.
    observed_at = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    buckets: dict[tuple[str, str], list[float | None]] = defaultdict(list)
    seen: set[str] = set()
    excluded = 0
    future = 0
    duplicates = 0
    accepted = 0
    for raw in payload["raises"]:
        if not isinstance(raw, dict):
            excluded += 1
            continue
        # Exact repeated records are not counted twice; distinct announcements
        # remain distinct. This adapter does not claim deduplicated companies.
        identity = json.dumps(raw, sort_keys=True, separators=(",", ":"))
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        try:
            raw_date = raw.get("date")
            if type(raw_date) not in (int, float) or not math.isfinite(raw_date):
                raise ValueError("date")
            announced = datetime.fromtimestamp(raw_date, timezone.utc)
            if announced.year < 1900:
                raise ValueError("date")
            if announced > observed_at:
                future += 1
                raise ValueError("future date")
            amount = raw.get("amount")
            if amount is not None and (type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0):
                raise ValueError("amount")
            usd = None if amount is None else amount * 1_000_000
            if usd is not None and not math.isfinite(usd):
                raise ValueError("amount")
        except (ValueError, OverflowError, OSError, TypeError):
            excluded += 1
            continue
        accepted += 1
        year = str(announced.year)
        quarter = f"{year}-Q{(announced.month - 1) // 3 + 1}"
        for period in (year, quarter):
            buckets[(period, "total")].append(usd)
    if payload["raises"] and accepted == 0:
        raise ProviderError(f"DefiLlama returned {len(payload['raises'])} raises but none passed validation ({excluded} invalid records excluded, including {future} future records).")
    data = _base("defillama")
    data.update(date_basis="announced", sector="crypto",
        methodology="Reported crypto financing (incl token sales). DefiLlama raises by announcement date; SDK amount in million USD scaled to USD. No instrument or company-HQ classification exists in documented schema, so these rows cannot populate strict VC or country totals. Deal counts include announcements with undisclosed amounts; investment is disclosed funding only. Unfinished calendar buckets are provisional with a UTC coverage cutoff; future announcements are excluded. No empty period is invented or partial value annualized.",
        methodology_version="defillama-raises-all-v2-sdk-f0d43119",
        validation_summary={"input_records": len(payload["raises"]), "accepted_records": accepted,
                            "excluded_records": excluded, "future_records": future, "duplicate_records": duplicates})
    for (period, stage), values in sorted(buckets.items()):
        bounds = period_fields(period)
        period_after = datetime.fromisoformat(bounds["period_end"] + "T00:00:00+00:00") + timedelta(days=1)
        partial = observed_at < period_after
        cutoff = min(observed_at, period_after - timedelta(microseconds=1)).isoformat()
        disclosed = [v for v in values if v is not None]
        note = f"Reported crypto financing (incl token sales); {len(disclosed)}/{len(values)} announcements have disclosed amounts; {excluded} invalid records excluded. Strict VC classification and geography unavailable."
        note += (f" Partial {'year-to-date' if bounds['frequency'] == 'annual' else 'quarter-to-date'} aggregate; observations through {cutoff}; not annualized."
                 if partial else f" Completed calendar period; observations through {cutoff}; source coverage/revisions still apply.")
        for metric, unit, value in (("investment", "USD", sum(disclosed) if disclosed else None), ("deals", "COUNT", len(values))):
            data["observations"].append({"scope": "crypto", "geography": "WORLD", "period": period,
                **bounds, "metric": metric, "stage": stage, "unit": unit,
                "value": value, "status": "missing" if value is None else "provisional" if partial else "reported",
                "financing_scope": "all_raises", "coverage_note": note,
                "is_partial": partial, "coverage_cutoff": cutoff,
                "disclosed_amount_count": len(disclosed), "announcement_count": len(values)})
    return data


def _seconds_since(value: str | None) -> float:
    if not value:
        return math.inf
    return (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds()


class Providers:
    def __init__(self, store: SnapshotStore, client: httpx.Client | None = None) -> None:
        self.store = store
        self.client = client

    async def ensure(self, source: str, refresh: bool = False) -> dict[str, Any]:
        return await asyncio.to_thread(self._ensure, source, refresh)

    def _ensure(self, source: str, refresh: bool) -> dict[str, Any]:
        lock = _LOCKS.setdefault((str(self.store.path.resolve()), source), threading.Lock())
        with lock:
            origin = "official" if source == "oecd" else "reference"
            release = self.store.latest(source, origin)
            state = self.store.fetch_state(source)
            age = _seconds_since(state.get("last_success"))
            cached = release is not None
            if source == "defillama" and not os.environ.get("SHOWME_DEFILLAMA_API_KEY"):
                return {"access_status": "not_configured", "status": "not_configured", "cached": cached,
                        "stale": cached, "reason": "DefiLlama Pro key is not configured; use a classified local import or configure server credentials."}
            if (not refresh and cached and age < TTL_SECONDS) or _seconds_since(state.get("last_attempt")) < COOLDOWN_SECONDS:
                stale = cached and (age >= TTL_SECONDS or bool(state.get("error")))
                return {"access_status": "available" if cached else "provider_unavailable", "status": "available" if cached else "provider_unavailable",
                        "cached": cached, "stale": stale, "refresh_cooldown": True if refresh else False,
                        "reason": state.get("error") or ("Refresh cooldown: retry after 60 seconds." if refresh else None)}
            try:
                url = OECD_URL if source == "oecd" else "https://pro-api.llama.fi/" + os.environ["SHOWME_DEFILLAMA_API_KEY"] + "/api/raises"
                body, headers = self._download(url)
                data = parse_oecd(body.decode("utf-8-sig"), last_modified=headers.get("last-modified")) if source == "oecd" else parse_defillama(json.loads(body))
                self.store.save(data, origin=origin)
                self.store.record_fetch(source, True)
                return {"access_status": "available", "status": "available", "cached": False, "stale": False,
                        "last_checked_at": utcnow(), "transport_last_modified": headers.get("last-modified") if source == "oecd" else None}
            except Exception as exc:
                # httpx exceptions contain the keyed URL; only our own fixed messages
                # may cross this boundary. No raw exception is returned or logged.
                reason = str(exc) if isinstance(exc, ProviderError) else f"{SOURCE_CATALOG[source]['source_name']} request failed ({type(exc).__name__}); retry later."
                self.store.record_fetch(source, False, reason)
                return {"access_status": "stale" if cached else "provider_unavailable", "status": "stale" if cached else "provider_unavailable",
                        "cached": cached, "stale": cached, "reason": reason}

    def _download(self, url: str) -> tuple[bytes, dict[str, str]]:
        owns = self.client is None
        client = self.client or httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
        started = time.monotonic()
        try:
            with client.stream("GET", url, timeout=httpx.Timeout(15, connect=5), follow_redirects=False,
                               headers={"Accept": "text/csv" if "sdmx.oecd.org" in url else "application/json", "User-Agent": "ShowMe-VCAP/1.0"}) as response:
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length and int(length) > MAX_RESPONSE_BYTES:
                    raise ProviderError("Provider response exceeds the 8 MB limit")
                chunks = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise ProviderError("Provider response exceeds the 8 MB limit")
                    if time.monotonic() - started > 30:
                        raise ProviderError("Provider request exceeded the 30 second deadline")
                    chunks.append(chunk)
                return b"".join(chunks), dict(response.headers)
        finally:
            if owns:
                client.close()
