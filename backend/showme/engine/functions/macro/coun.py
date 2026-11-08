"""COUN — Country Guide (ekonomi + siyaset + mali, tek sayfada).

Every metric row is either a live provider observation (BTMM policy row or a
keyless FRED series through ECST) or an explicit unavailable row with a reason.
COUN serves no hard-coded or reference macro values (data policy: never invent
or template a number). Currency codes are facts and stay as a card.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.macro.btmm import BTMMFunction
from showme.engine.functions.macro.ecst import ECSTFunction


@FunctionRegistry.register
class COUNFunction(BaseFunction):
    code = "COUN"
    name = "Country Guide"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = (params.get("country") or "US").upper()
        live = _live_flag(params)
        timeout = params.get("timeout", 4)
        country_is_known = country in _KNOWN_PROFILE_COUNTRIES
        requested, metric_warnings = _requested_metric_keys(params.get("metrics"))
        baseline_warnings: list[str] = list(metric_warnings)
        if not country_is_known:
            baseline_warnings.append(
                f"country '{country}' has no curated profile; no reference values are served"
            )

        provider_errors: list[str] = []
        policy_row: dict[str, Any] | None = None
        indicator_rows: list[dict[str, Any]] = []
        history: list[dict[str, Any]] = []
        indicator_warnings: list[str] = []
        series_ids = _series_ids(country)
        if live:
            policy_row, btmm_error = await _fetch_policy(self.deps, country, timeout)
            if btmm_error:
                provider_errors.append(btmm_error)
            for sid in series_ids:
                specs = [spec for spec in _LIVE_SERIES.get(country, ()) if spec.series_id == sid]
                try:
                    r = await ECSTFunction(self.deps).execute(series_id=sid, timeout=timeout)
                except Exception as exc:
                    provider_errors.append(f"ecst.{sid}: {exc}")
                    indicator_rows.extend(_unavailable_series_row(spec, str(exc)) for spec in specs)
                    continue
                for spec in specs:
                    row, points = _series_row(spec, r.data, _today())
                    indicator_rows.append(row)
                    if spec.transform == "level":
                        history.extend(points)
                    if row["value"] is None:
                        indicator_warnings.append(f"{sid}: {row['reason']}")
                    elif row.get("stale"):
                        indicator_warnings.append(f"{sid}: {row['reason']}")

        live_indicator_rows = [row for row in indicator_rows if row["value"] is not None]
        fresh_indicator_rows = [row for row in live_indicator_rows if not row.get("stale")]
        has_live = bool(policy_row) or bool(fresh_indicator_rows)
        stale_only = bool(live_indicator_rows) and not has_live

        # A metric slot is covered when a provider row (value or explicit gap)
        # already exists for it. Only uncovered slots get a generic gap row.
        covered = {str(row["key"]) for row in indicator_rows}
        if policy_row:
            covered.add("policy_rate")
        gap_rows = _gap_rows(
            country,
            covered,
            _gap_reason_for(country, live, provider_errors),
        )
        rows = _country_rows(country, {"rows": gap_rows}, policy_row, indicator_rows)
        rows = _filter_by_key(rows, requested)

        live_sources: list[str] = []
        if policy_row:
            live_sources.append("btmm")
        live_sources.extend(str(row["source_mode"]) for row in live_indicator_rows)
        all_warnings = baseline_warnings + provider_errors + indicator_warnings

        if has_live:
            source_mode = "live_macro"
        elif stale_only:
            source_mode = "stale_macro"
        else:
            source_mode = "provider_unavailable"

        data: dict[str, Any] = {
            "country": country,
            "rows": rows,
            "history": history[-80:],
            "cards": _filter_by_key(
                _country_cards(country, policy_row, fresh_indicator_rows), requested
            ),
            "methodology": _METHODOLOGY,
            "field_dictionary": _FIELD_DICTIONARY,
            "source_mode": source_mode,
            "country_known": country_is_known,
        }
        if not country_is_known:
            # An unknown country gets needs_input as its status only when no
            # live row exists; with live rows the missing profile is disclosed
            # under profile_state so the top-level status does not contradict them.
            if has_live:
                data["profile_state"] = _unknown_country_state(country)
            else:
                data.update(_unknown_country_state(country))
        elif not has_live:
            data.update(_no_live_state(country, live, stale_only))

        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=_unique(live_sources),
            warnings=all_warnings,
            metadata={
                "country": country,
                "live": live,
                "series": series_ids,
                "provider_errors": provider_errors,
                "country_known": country_is_known,
                "metrics_requested": sorted(requested),
            },
        )


_KNOWN_PROFILE_COUNTRIES = frozenset({"US", "EU", "GB", "TR"})

# Currency codes are facts, not statistics; they are the only reference value.
_CURRENCY = {"US": "USD", "EU": "EUR", "GB": "GBP", "TR": "TRY"}

# ECST row modes that are real provider observations. Anything else (a
# constructed or unknown mode, or no rows at all) is not live data.
_LIVE_ECST_MODES = frozenset({"fred", "worldbank"})

_METRIC_OPTIONS = frozenset(
    {
        "policy_rate",
        "inflation",
        "unemployment",
        "gdp_growth",
        "debt_to_gdp",
        "fiscal_balance",
        "ten_year_yield",
        "currency",
    }
)


@dataclass(frozen=True)
class _Metric:
    """A standard workbook slot. Every curated country has one row per slot."""

    key: str
    section: str
    label: str
    unit: str


_STANDARD_METRICS: tuple[_Metric, ...] = (
    _Metric("policy_rate", "rates", "Policy rate", "%"),
    _Metric("inflation", "prices", "Inflation", "% y/y"),
    _Metric("unemployment", "labor", "Unemployment rate", "%"),
    _Metric("gdp_growth", "growth", "Real GDP growth", "% y/y"),
    _Metric("ten_year_yield", "rates", "10Y government yield", "%"),
    _Metric("fiscal_balance", "fiscal", "Fiscal balance", "% GDP"),
    _Metric("debt_to_gdp", "fiscal", "Debt to GDP", "% GDP"),
)


@dataclass(frozen=True)
class _Series:
    """A keyless FRED series and the workbook row it feeds.

    ``transform`` is "level" (the observation itself) or "yoy_pct" (the change
    against the observation one year earlier). ``max_age_days`` is how old the
    latest observation may be before the row is flagged stale.
    """

    series_id: str
    key: str
    section: str
    label: str
    unit: str
    transform: str = "level"
    max_age_days: int = 120
    note: str | None = None
    # Unit of the World Bank fallback when ECST serves the same concept from
    # the World Bank (e.g. GDPC1 -> NY.GDP.MKTP.KD, constant 2015 USD).
    worldbank_unit: str | None = None


# FRED ids. TURGDPRQDSMEI is not on FRED (HTTP 404); NGDPRSAXDCTRQ is the FRED
# id for Real GDP, Republic of Turkiye (verified 2026-11-08).
_LIVE_SERIES: dict[str, tuple[_Series, ...]] = {
    "US": (
        _Series(
            "GDPC1",
            "gdp_level",
            "growth",
            "Real GDP",
            "bn chained USD",
            max_age_days=270,
            worldbank_unit="bn constant 2015 USD",
        ),
        _Series("GDPC1", "gdp_growth", "growth", "Real GDP growth", "% y/y", transform="yoy_pct", max_age_days=270),
        _Series("CPIAUCSL", "inflation", "prices", "Inflation", "% y/y", transform="yoy_pct"),
        _Series("UNRATE", "unemployment", "labor", "Unemployment rate", "%"),
        _Series("DGS10", "ten_year_yield", "rates", "10Y government yield", "%", max_age_days=14),
    ),
    "EU": (
        _Series(
            "LRHUTTTTEZQ156S",
            "unemployment",
            "labor",
            "Unemployment rate",
            "%",
            note="euro-area aggregate, not a single member state",
        ),
    ),
    "GB": (
        _Series("GBRCPIALLMINMEI", "inflation", "prices", "Inflation", "% y/y", transform="yoy_pct"),
    ),
    "TR": (
        _Series("NGDPRSAXDCTRQ", "gdp_level", "growth", "Real GDP", "mn TRY (SA)", max_age_days=270),
        _Series("NGDPRSAXDCTRQ", "gdp_growth", "growth", "Real GDP growth", "% y/y", transform="yoy_pct", max_age_days=270),
    ),
}

_METHODOLOGY = (
    "COUN combines the latest policy-rate row from BTMM with keyless FRED series normalized "
    "via ECST. Every metric is a live observation or an explicit unavailable row with its "
    "reason; no hard-coded or reference macro value is served. Inflation and real GDP growth "
    "are year-over-year changes computed from the level series. An observation older than its "
    "series limit is flagged stale, keeps its as-of date and does not count as live."
)

_FIELD_DICTIONARY = {
    "metric": "Human-readable country metric.",
    "value": "Latest live value in the displayed unit; null when unavailable.",
    "as_of": "Latest provider observation date.",
    "source_mode": "Provider used for the row, or provider_unavailable.",
    "stale": "True when the latest observation is older than its series limit.",
    "reason": "Why a row has no value or is stale.",
}


async def _fetch_policy(deps: Any, country: str, timeout: Any) -> tuple[dict[str, Any] | None, str | None]:
    try:
        btmm = await BTMMFunction(deps).execute(country=country, timeout=timeout)
    except Exception as exc:
        return None, f"btmm: {exc}"
    rows = btmm.data.get("rows") if isinstance(btmm.data, dict) else None
    candidates = [
        row
        for row in (rows or [])
        if isinstance(row, dict) and row.get("policy_rate") is not None
    ]
    # COUN#4: only a fresh BIS row may drive the live policy rate. BTMM keeps
    # legacy (stale) and undated rows in its output, and rows[0] can be one.
    fresh = [row for row in candidates if row.get("freshness") == "fresh"]
    if fresh:
        return max(fresh, key=lambda row: str(row.get("as_of") or "")), None
    if candidates:
        newest = candidates[0]
        return None, (
            f"btmm: policy-rate row for {country} is not fresh "
            f"(freshness={newest.get('freshness')!r}, as_of={newest.get('as_of')!r}); "
            "not used as live"
        )
    return None, None


def _series_ids(country: str) -> list[str]:
    ids: list[str] = []
    for spec in _LIVE_SERIES.get(country, ()):
        if spec.series_id not in ids:
            ids.append(spec.series_id)
    return ids


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _unknown_country_state(country: str) -> dict[str, Any]:
    """Explicit no-profile state for a country outside the curated set."""
    return {
        "status": "needs_input",
        "reason": (
            f"no curated reference profile for country {country!r}; "
            "no reference values are invented for it"
        ),
        "next_actions": [
            "Choose a curated country: US, EU, GB or TR.",
            "Use live=true for the live BTMM and FRED rows that exist for this country.",
        ],
    }


def _no_live_state(country: str, live: bool, stale_only: bool) -> dict[str, Any]:
    if not live:
        return {
            "status": "needs_input",
            "reason": "live overlay is off (live=false); COUN serves no reference values",
            "next_actions": ["Set live=true to fetch the live BTMM and FRED rows."],
        }
    if stale_only:
        return {
            "status": "stale",
            "reason": (
                f"the only provider observations for {country} are older than their series "
                "limit; they keep their as-of dates and are not treated as live"
            ),
            "next_actions": ["Check the stale rows' as-of dates before relying on them."],
        }
    return {
        "status": "provider_unavailable",
        "reason": (
            f"no live provider returned a value for {country}; COUN serves no reference values"
        ),
        "next_actions": ["Retry later; COUN does not substitute reference values for missing data."],
    }


def _live_flag(params: dict[str, Any]) -> bool:
    """Seed default is live=true; the handler agrees when the flag is omitted."""
    raw = params.get("live_macro")
    if raw is None:
        raw = params.get("live")
    if raw is None:
        return True
    return _truthy(raw)


def _requested_metric_keys(value: Any) -> tuple[set[str], list[str]]:
    if value is None:
        return set(), []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value]
    else:
        items = []
    keys = {item.strip().lower() for item in items if item and item.strip()}
    warnings = [
        f"metric '{key}' is not a COUN metric; ignored"
        for key in sorted(keys)
        if key not in _METRIC_OPTIONS
    ]
    valid = {key for key in keys if key in _METRIC_OPTIONS}
    return valid, warnings


def _filter_by_key(items: list[dict[str, Any]], requested: set[str]) -> list[dict[str, Any]]:
    if not requested:
        return items
    return [item for item in items if item.get("key") in requested]


def _unavailable_row(
    key: str,
    section: str,
    label: str,
    unit: str,
    reason: str,
    series_id: str | None = None,
) -> dict[str, Any]:
    """Explicit no-data row: no value, no as-of, never a placeholder number."""
    return {
        "key": key,
        "section": section,
        "metric": label,
        "value": None,
        "unit": unit,
        "as_of": None,
        "series_id": series_id,
        "source_mode": "provider_unavailable",
        "reason": reason,
    }


def _unavailable_series_row(spec: _Series, reason: str) -> dict[str, Any]:
    return _unavailable_row(
        spec.key, spec.section, spec.label, spec.unit, reason, series_id=spec.series_id
    )


def _gap_reason_for(country: str, live: bool, provider_errors: list[str]) -> Callable[[str], str]:
    btmm_error = next((error for error in provider_errors if error.startswith("btmm:")), None)

    def reason_for(key: str) -> str:
        if not live:
            return "live overlay is off (live=false); COUN serves no reference values"
        if key == "policy_rate":
            return btmm_error or f"BTMM returned no policy-rate row for {country}"
        label = next((m.label for m in _STANDARD_METRICS if m.key == key), key)
        return f"no keyless live provider is wired for {label} in {country}"

    return reason_for


def _gap_rows(
    country: str,
    covered: set[str],
    reason_for: Callable[[str], str],
) -> list[dict[str, Any]]:
    """One explicit unavailable row per uncovered standard slot of a curated country."""
    if country not in _KNOWN_PROFILE_COUNTRIES:
        return []
    return [
        _unavailable_row(metric.key, metric.section, metric.label, metric.unit, reason_for(metric.key))
        for metric in _STANDARD_METRICS
        if metric.key not in covered
    ]


def _series_row(
    spec: _Series,
    payload: Any,
    today: date,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        rows = []
    live_rows = sorted(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("source_mode") in _LIVE_ECST_MODES
            and row.get("date")
            and row.get("value") is not None
        ),
        key=lambda row: str(row["date"]),
    )
    if not live_rows:
        reason = payload.get("reason") if isinstance(payload, dict) else None
        if not isinstance(reason, str) or not reason.strip():
            reason = "no live observations returned"
        return _unavailable_series_row(spec, reason), []

    latest = live_rows[-1]
    as_of = str(latest["date"])[:10]
    try:
        as_of_date = date.fromisoformat(as_of)
    except ValueError:
        return _unavailable_series_row(spec, f"unreadable observation date {as_of!r}"), []

    if spec.transform == "yoy_pct":
        prior = _observation_on(live_rows, _shift_years(as_of_date, -1))
        if prior is None or float(prior["value"]) == 0:
            return (
                _unavailable_series_row(
                    spec,
                    f"no live observation one year before {as_of} to compute a y/y change",
                ),
                [],
            )
        value: Any = round((float(latest["value"]) / float(prior["value"]) - 1.0) * 100.0, 3)
        points: list[dict[str, Any]] = []
    else:
        value = latest.get("value")
        points = [
            {
                "date": row.get("date"),
                "metric": spec.label,
                "value": row.get("value"),
                "unit": _unit_for(spec, row.get("source_mode")),
                "series_id": spec.series_id,
                "source_mode": row.get("source_mode"),
            }
            for row in live_rows
        ]

    age_days = (today - as_of_date).days
    row: dict[str, Any] = {
        "key": spec.key,
        "section": spec.section,
        "metric": spec.label,
        "value": value,
        "unit": _unit_for(spec, latest.get("source_mode")),
        "as_of": as_of,
        "series_id": spec.series_id,
        "source_mode": latest.get("source_mode"),
    }
    if spec.note:
        row["note"] = spec.note
    if age_days > spec.max_age_days:
        row["stale"] = True
        row["reason"] = (
            f"latest observation {as_of} is {age_days} days old; the limit for this series is "
            f"{spec.max_age_days} days. Shown with its as-of date; not treated as live."
        )
    return row, points


def _unit_for(spec: _Series, source_mode: Any) -> str:
    """The unit of the provider that actually served the row."""
    if source_mode == "worldbank" and spec.worldbank_unit:
        return spec.worldbank_unit
    return spec.unit


def _observation_on(rows: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    wanted = target.isoformat()
    for row in rows:
        if str(row.get("date"))[:10] == wanted:
            return row
    return None


def _shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:  # 29 Feb in a non-leap target year
        return value.replace(year=value.year + years, day=28)


def _country_rows(
    country: str,
    profile: dict[str, Any],
    policy_row: dict[str, Any] | None,
    indicators: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge the policy row, provider rows and gap rows into one deduped list.

    ``profile`` carries only explicit unavailable rows here (never values); the
    name is kept for the existing dedup contract.
    """
    # Bug #23 fix: previously this concatenated the reference-profile rows
    # (which always include a static "Policy rate") with a BTMM-sourced
    # "Policy rate" row inserted at position 0 AND with ECST indicator
    # rows. Solution: deduplicate by ``(section, metric)``, keeping the row
    # with the most recent ``as_of`` timestamp and preferring rows that carry
    # an ``as_of`` at all over rows that don't.
    candidates: list[dict[str, Any]] = []
    if policy_row:
        candidates.append({
            "key": "policy_rate",
            "section": "rates",
            "metric": "Policy rate",
            "value": policy_row.get("policy_rate"),
            "unit": "%",
            "as_of": policy_row.get("as_of"),
            "country": country,
            "source_mode": policy_row.get("source") or "BTMM",
        })
    candidates.extend(profile.get("rows") or [])
    candidates.extend(indicators)
    return _deduplicate_country_rows(candidates)


def _deduplicate_country_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate (section, metric) pairs, keeping the freshest row.

    "Freshest" = the row with the latest ``as_of`` ISO date; rows without
    an ``as_of`` are treated as oldest (an explicit gap only wins when
    no live row exists). First seen wins on ties so the BTMM-inserted row
    keeps its leading slot.
    """
    best: dict[tuple[str, str], int] = {}
    out: list[dict[str, Any]] = []
    out_index = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("section") or ""), str(row.get("metric") or ""))
        if not key[1]:
            # Rows with no metric label can't collide — let them pass through.
            out.append(row)
            out_index += 1
            continue
        if key not in best:
            best[key] = out_index
            out.append(row)
            out_index += 1
            continue
        existing_idx = best[key]
        if _row_freshness(row) > _row_freshness(out[existing_idx]):
            out[existing_idx] = row
    return out


def _row_freshness(row: dict[str, Any]) -> str:
    """Sortable freshness key — empty string for rows with no ``as_of``."""
    as_of = row.get("as_of")
    if not as_of:
        return ""
    return str(as_of)


def _country_cards(
    country: str,
    policy_row: dict[str, Any] | None,
    indicators: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    currency = _CURRENCY.get(country)
    if currency:
        cards.append({"key": "currency", "label": "Currency", "value": currency})
    if policy_row:
        cards.append(
            {"key": "policy_rate", "label": "Policy rate", "value": policy_row.get("policy_rate")}
        )
    for row in indicators[:3]:
        cards.append({"key": row.get("key"), "label": row.get("metric"), "value": row.get("value")})
    return cards[:8]


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
