"""World-events tracker helpers for the MEET pane.

Pure, deterministic helpers with no I/O. The MEET function owns provider
calls (the keyless ForexFactory weekly calendar reused from ECO + the
keyless news path) and hands the normalized rows here for:

  * country attribution      — ISO codes, multi-country, currency→ISO,
  * UTC anchoring            — ``when_utc`` parsed from the provider's
                               offset-aware timestamp (never guessed),
  * affected FX pairs        — country → currency → majors (TR→USDTRY/EURTRY),
  * countdown math           — ``seconds_to_event`` / ``age_minutes`` are
                               computed server-side for UI parity,
  * window split             — upcoming ascending / past descending,
  * country index            — every country that appeared on the calendar
                               with its next event + local state,
  * spot flags + alerts      — rate decisions / wars are spot-tracked.

Honesty rules:
  * nothing is invented; rows come from real provider payloads,
  * a row we cannot place in time (unparseable timestamp) is dropped and
    counted, never shown at a guessed time,
  * world headlines carry their actually matched terms in ``matched_terms``
    so a country tag is auditable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Country catalog (ISO 3166-1 alpha-2 -> English name).
#
# Curated "significant" universe: every country the keyless calendar can
# tag plus every country the headline gazetteer knows. Used to build the
# UI's filter index even when the calendar provider is down (the catalog
# itself is static reference data, not an event claim).
# ---------------------------------------------------------------------------

COUNTRY_CATALOG: tuple[tuple[str, str], ...] = (
    ("US", "United States"), ("CA", "Canada"), ("MX", "Mexico"),
    ("BR", "Brazil"), ("AR", "Argentina"), ("CL", "Chile"), ("CO", "Colombia"),
    ("PE", "Peru"), ("VE", "Venezuela"), ("CU", "Cuba"),
    ("GB", "United Kingdom"), ("IE", "Ireland"), ("FR", "France"),
    ("DE", "Germany"), ("IT", "Italy"), ("ES", "Spain"), ("PT", "Portugal"),
    ("NL", "Netherlands"), ("BE", "Belgium"), ("LU", "Luxembourg"),
    ("AT", "Austria"), ("CH", "Switzerland"), ("SE", "Sweden"),
    ("NO", "Norway"), ("DK", "Denmark"), ("FI", "Finland"), ("IS", "Iceland"),
    ("PL", "Poland"), ("CZ", "Czechia"), ("SK", "Slovakia"), ("HU", "Hungary"),
    ("RO", "Romania"), ("BG", "Bulgaria"), ("GR", "Greece"), ("CY", "Cyprus"),
    ("RS", "Serbia"), ("HR", "Croatia"), ("SI", "Slovenia"), ("BA", "Bosnia and Herzegovina"),
    ("AL", "Albania"), ("MK", "North Macedonia"), ("EE", "Estonia"),
    ("LV", "Latvia"), ("LT", "Lithuania"), ("MD", "Moldova"), ("UA", "Ukraine"),
    ("BY", "Belarus"), ("RU", "Russia"), ("GE", "Georgia"), ("AM", "Armenia"),
    ("AZ", "Azerbaijan"), ("TR", "Turkey"), ("IL", "Israel"), ("PS", "Palestine"),
    ("LB", "Lebanon"), ("JO", "Jordan"), ("SY", "Syria"), ("IQ", "Iraq"),
    ("IR", "Iran"), ("SA", "Saudi Arabia"), ("AE", "United Arab Emirates"),
    ("QA", "Qatar"), ("KW", "Kuwait"), ("BH", "Bahrain"), ("OM", "Oman"),
    ("YE", "Yemen"), ("EG", "Egypt"), ("LY", "Libya"), ("TN", "Tunisia"),
    ("DZ", "Algeria"), ("MA", "Morocco"), ("SD", "Sudan"), ("ET", "Ethiopia"),
    ("KE", "Kenya"), ("NG", "Nigeria"), ("GH", "Ghana"), ("ZA", "South Africa"),
    ("IN", "India"), ("PK", "Pakistan"), ("BD", "Bangladesh"), ("LK", "Sri Lanka"),
    ("CN", "China"), ("HK", "Hong Kong"), ("TW", "Taiwan"), ("JP", "Japan"),
    ("KR", "South Korea"), ("KP", "North Korea"), ("MN", "Mongolia"),
    ("KZ", "Kazakhstan"), ("UZ", "Uzbekistan"), ("AF", "Afghanistan"),
    ("TH", "Thailand"), ("VN", "Vietnam"), ("MY", "Malaysia"), ("SG", "Singapore"),
    ("ID", "Indonesia"), ("PH", "Philippines"), ("MM", "Myanmar"),
    ("AU", "Australia"), ("NZ", "New Zealand"),
)

ISO_NAMES: dict[str, str] = dict(COUNTRY_CATALOG)

# The calendar's synthetic euro-area token (not an ISO country but a
# first-class calendar region).
REGION_NAMES: dict[str, str] = {"EU": "Euro Area"}

# ---------------------------------------------------------------------------
# Currency <-> country mapping.
#
# ForexFactory tags its rows by CURRENCY (USD, HUF, ...). The world-events
# layer canonicalizes to ISO codes so country filters are stable.
# ---------------------------------------------------------------------------

CURRENCY_TO_ISO: dict[str, str] = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "CHF": "CH",
    "CAD": "CA", "AUD": "AU", "NZD": "NZ", "CNY": "CN", "CNH": "CN",
    "TRY": "TR", "RUB": "RU", "UAH": "UA", "PLN": "PL", "CZK": "CZ",
    "HUF": "HU", "RON": "RO", "BGN": "BG", "RSD": "RS", "HRK": "HR",
    "SEK": "SE", "NOK": "NO", "DKK": "DK", "ISK": "IS", "GEL": "GE",
    "AMD": "AM", "AZN": "AZ", "ILS": "IL", "SAR": "SA", "AED": "AE",
    "QAR": "QA", "KWD": "KW", "BHD": "BH", "OMR": "OM", "JOD": "JO",
    "EGP": "EG", "TND": "TN", "DZD": "DZ", "MAD": "MA", "ZAR": "ZA",
    "NGN": "NG", "KES": "KE", "GHS": "GH", "ETB": "ET", "INR": "IN",
    "PKR": "PK", "BDT": "BD", "LKR": "LK", "HKD": "HK", "TWD": "TW",
    "KRW": "KR", "MNT": "MN", "KZT": "KZ", "UZS": "UZ", "THB": "TH",
    "VND": "VN", "MYR": "MY", "SGD": "SG", "IDR": "ID", "PHP": "PH",
    "MMK": "MM", "BRL": "BR", "ARS": "AR", "CLP": "CL", "COP": "CO",
    "PEN": "PE", "MXN": "MX",
}

# Currencies whose country mapping is ambiguous in a calendar feed are
# explicitly collapsed onto the region token.
_REGION_CURRENCIES = {"EUR": "EU"}

# ---------------------------------------------------------------------------
# Affected instruments: currency -> quoted majors / index.
# ---------------------------------------------------------------------------

PAIR_MAP: dict[str, tuple[str, ...]] = {
    "USD": ("DXY", "EURUSD", "USDJPY", "GBPUSD", "USDCAD", "AUDUSD", "NZDUSD", "USDCHF", "USDCNH"),
    "EUR": ("EURUSD", "EURGBP", "EURJPY", "EURCHF"),
    "GBP": ("GBPUSD", "EURGBP", "GBPJPY"),
    "JPY": ("USDJPY", "EURJPY", "GBPJPY", "AUDJPY"),
    "CHF": ("USDCHF", "EURCHF"),
    "CAD": ("USDCAD",),
    "AUD": ("AUDUSD", "AUDJPY"),
    "NZD": ("NZDUSD",),
    "CNY": ("USDCNH",),
    "TRY": ("USDTRY", "EURTRY"),
    "INR": ("USDINR",),
    "BRL": ("USDBRL",),
    "MXN": ("USDMXN",),
    "ZAR": ("USDZAR",),
    "SEK": ("USDSEK",),
    "NOK": ("USDNOK",),
    "PLN": ("USDPLN",),
    "HUF": ("USDHUF",),
    "CZK": ("USDCZK",),
    "ILS": ("USDILS",),
    "KRW": ("USDKRW",),
    "SGD": ("USDSGD",),
    "THB": ("USDTHB",),
}

# Countries whose high-impact prints are pinned by default (major markets).
MAJOR_MARKET_ISO: frozenset[str] = frozenset(
    {"US", "EU", "GB", "JP", "CH", "CA", "AU", "NZ", "CN"}
)

# Default lead times (minutes) a spot alert can fire at; the UI lets the
# user toggle these per pane.
DEFAULT_ALERT_LEAD_MINUTES: tuple[int, ...] = (1440, 60, 5)

_IMPACT_ORDER = {"high": 3, "medium": 2, "low": 1, "holiday": 0}

_IMPACT_MAP = {"high": "high", "medium": "medium", "low": "low", "holiday": "holiday"}

# Central-bank / market-moving scheduled decisions (spot-tracked).
_RATE_DECISION_RE = re.compile(
    r"(interest rate decision|rate decision|rate statement|rate announcement"
    r"|fomc statement|fomc economic projections|fomc press conference"
    r"|monetary policy (?:decision|statement|summary)"
    r"|official (?:cash|bank) rate|bank rate|main refinancing|deposit facility"
    r"|interest rate|press conference)",
    re.IGNORECASE,
)

# War / conflict / escalation terms (world headlines are spot-tracked).
_WAR_RE = re.compile(
    r"\b(war|warfare|invasion|invade|airstrikes?|air strikes?|missiles?|drone strikes?"
    r"|offensive|ceasefire|cease-fire|truce|military|troops|soldiers|shelling"
    r"|bombing|bombardment|conflict|escalation|nuclear|sanctions?|mobilization"
    r"|mobilisation|coup|martial law|frontline|front line)\b",
    re.IGNORECASE,
)

# Political / diplomatic terms (world headlines, medium impact).
_POLITICAL_RE = re.compile(
    r"\b(election|elections|referendum|summit|treaty|parliament|president|prime minister"
    r"|sanctions|embargo|protest|protests|diplomat|diplomatic|border|talks|accord)\b",
    re.IGNORECASE,
)

_WORLD_QUERY = (
    "(war OR conflict OR ceasefire OR invasion OR missile OR airstrike OR sanctions"
    " OR election OR summit OR treaty OR coup OR protest OR nuclear OR mobilization"
    " OR shelling OR offensive)"
)


# ---------------------------------------------------------------------------
# Canonicalization helpers
# ---------------------------------------------------------------------------


def canonical_iso(token: Any) -> str:
    """Fold a currency code, ISO code, or region token onto its ISO key."""
    raw = str(token or "").strip().upper()
    if not raw:
        return ""
    if raw in _REGION_CURRENCIES:
        return _REGION_CURRENCIES[raw]
    if raw in ISO_NAMES or raw in REGION_NAMES:
        return raw
    return CURRENCY_TO_ISO.get(raw, "")


def country_name(iso: str) -> str:
    return ISO_NAMES.get(iso) or REGION_NAMES.get(iso) or iso


def currency_for(iso: str) -> str:
    for currency, mapped in CURRENCY_TO_ISO.items():
        if mapped == iso and currency.endswith("_") is False:
            return currency
    return ""


def pairs_for(currencies: Iterable[str]) -> list[str]:
    out: list[str] = []
    for currency in currencies:
        for pair in PAIR_MAP.get(currency, ()):
            if pair not in out:
                out.append(pair)
    return out


def normalize_impact(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return _IMPACT_MAP.get(raw, "low")


def parse_when_utc(value: Any) -> datetime | None:
    """Parse the provider timestamp (offset-aware ISO) into UTC.

    Naive timestamps are treated as UTC (the keyless weekly feed always
    publishes an offset; a naive value would be an upstream anomaly and
    UTC is the least-wrong documented assumption).
    """
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            # GDELT's DOC API uses a compact "20260914T120000Z" stamp.
            try:
                dt = datetime.strptime(raw, "%Y%m%dT%H%M%S%z")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64]


def _row_id(kind: str, when: datetime, isos: list[str], title: str) -> str:
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    who = "-".join(isos) if isos else "zz"
    return f"{kind}:{stamp}:{who}:{_slug(title)}"


# ---------------------------------------------------------------------------
# Economic rows (ForexFactory weekly calendar, reused from ECO)
# ---------------------------------------------------------------------------


def economic_rows(
    calendar_rows: Iterable[Any],
    *,
    now: datetime,
    source: str = "forex_factory",
) -> tuple[list[dict[str, Any]], int]:
    """Normalize calendar rows into world-event rows.

    Returns ``(rows, dropped_no_time)`` — rows without a parseable
    timestamp are dropped and counted (never shown at a guessed time).
    """
    rows: list[dict[str, Any]] = []
    dropped = 0
    seen: set[str] = set()
    for item in calendar_rows:
        if not isinstance(item, dict):
            continue
        title = str(item.get("event") or item.get("title") or "").strip()
        if not title:
            continue
        when = parse_when_utc(item.get("date") or item.get("when_utc") or item.get("datetime"))
        if when is None:
            dropped += 1
            continue
        provider_token = str(item.get("country") or item.get("currency") or "").strip().upper()
        iso = canonical_iso(provider_token)
        isos = [iso] if iso else []
        impact = normalize_impact(item.get("importance") or item.get("impact"))
        currency = currency_for(iso) or (provider_token if provider_token in PAIR_MAP else "")
        currencies = [currency] if currency else []
        seconds = (when - now).total_seconds()
        spot = impact == "high" and bool(_RATE_DECISION_RE.search(title))
        row_id = _row_id("economic", when, isos, title)
        if row_id in seen:
            continue
        seen.add(row_id)
        rows.append({
            "id": row_id,
            "kind": "economic",
            "title": title,
            "countries": isos,
            "country_names": [country_name(i) for i in isos],
            "when_utc": when.isoformat(),
            "impact": impact,
            "currencies": currencies,
            "pairs": pairs_for(currencies),
            "source": source,
            "spot": spot,
            "pinned": spot or (impact == "high" and iso in MAJOR_MARKET_ISO),
            "details": {
                "forecast": item.get("forecast"),
                "previous": item.get("previous"),
                "unit": item.get("unit") or "",
                "provider_country": provider_token or None,
            },
            "seconds_to_event": round(seconds, 1),
            "age_minutes": round(-seconds / 60, 1) if seconds < 0 else None,
        })
    return rows, dropped


# ---------------------------------------------------------------------------
# World rows (keyless headlines tagged with a country gazetteer)
# ---------------------------------------------------------------------------

# Country headline terms. Every catalog name is matched automatically;
# this table adds adjectives, capitals, and short codes for the countries
# that actually dominate wire copy. Terms with <= 3 characters are matched
# case-sensitively (so the English pronoun "us" never tags United States).
COUNTRY_TERMS: dict[str, tuple[str, ...]] = {
    "US": ("US", "U.S.", "united states", "usa", "america", "american", "washington", "white house", "pentagon"),
    "GB": ("UK", "U.K.", "united kingdom", "britain", "british", "england", "london", "westminster"),
    "EU": ("EU", "european union", "eurozone", "euro area", "brussels", "ecb"),
    "TR": ("turkey", "türkiye", "turkiye", "turkish", "ankara", "istanbul", "tcmb"),
    "RU": ("russia", "russian", "moscow", "kremlin", "putin"),
    "UA": ("ukraine", "ukrainian", "kyiv", "kiev", "zelensky"),
    "CN": ("china", "chinese", "beijing", "xi jinping"),
    "TW": ("taiwan", "taipei"),
    "JP": ("japan", "japanese", "tokyo", "boj"),
    "KR": ("south korea", "korean", "seoul"),
    "KP": ("north korea", "pyongyang", "kim jong"),
    "IN": ("india", "indian", "delhi", "modi"),
    "PK": ("pakistan", "pakistani", "islamabad"),
    "IL": ("israel", "israeli", "jerusalem", "tel aviv", "netanyahu"),
    "PS": ("palestinian", "gaza", "west bank", "ramallah"),
    "IR": ("iran", "iranian", "tehran"),
    "SA": ("saudi", "riyadh"),
    "AE": ("emirates", "abu dhabi", "dubai"),
    "QA": ("qatar", "doha"),
    "EG": ("egypt", "egyptian", "cairo"),
    "ZA": ("south africa", "johannesburg", "pretoria"),
    "NG": ("nigeria", "nigerian", "lagos", "abuja"),
    "KE": ("kenya", "nairobi"),
    "BR": ("brazil", "brazilian", "brasilia", "sao paulo"),
    "AR": ("argentina", "argentine", "buenos aires"),
    "MX": ("mexico", "mexican", "mexico city"),
    "CA": ("canada", "canadian", "ottawa", "toronto"),
    "AU": ("australia", "australian", "canberra", "sydney"),
    "NZ": ("new zealand", "wellington", "auckland"),
    "DE": ("germany", "german", "berlin", "bundesbank"),
    "FR": ("france", "french", "paris", "macron"),
    "IT": ("italy", "italian", "rome", "milan"),
    "ES": ("spain", "spanish", "madrid"),
    "NL": ("netherlands", "dutch", "amsterdam", "the hague"),
    "PL": ("poland", "polish", "warsaw"),
    "SE": ("sweden", "swedish", "stockholm"),
    "NO": ("norway", "norwegian", "oslo"),
    "FI": ("finland", "finnish", "helsinki"),
    "CH": ("switzerland", "swiss", "zurich", "geneva"),
    "AT": ("austria", "austrian", "vienna"),
    "BE": ("belgium", "belgian", "brussels summit"),
    "IE": ("ireland", "irish", "dublin"),
    "GR": ("greece", "greek", "athens"),
    "CZ": ("czech", "prague"),
    "HU": ("hungary", "hungarian", "budapest", "orban"),
    "RO": ("romania", "romanian", "bucharest"),
    "RS": ("serbia", "serbian", "belgrade"),
    "BY": ("belarus", "minsk", "lukashenko"),
    "KZ": ("kazakhstan", "astana", "almaty"),
    "AF": ("afghanistan", "afghan", "kabul", "taliban"),
    "SY": ("syria", "syrian", "damascus"),
    "LB": ("lebanon", "lebanese", "beirut"),
    "IQ": ("iraq", "iraqi", "baghdad"),
    "YE": ("yemen", "houthi", "sanaa"),
    "JO": ("jordan", "amman"),
    "TH": ("thailand", "thai", "bangkok"),
    "VN": ("vietnam", "vietnamese", "hanoi"),
    "PH": ("philippines", "filipino", "manila"),
    "ID": ("indonesia", "indonesian", "jakarta"),
    "MY": ("malaysia", "kuala lumpur"),
    "SG": ("singapore"),
    "HK": ("hong kong"),
    "MM": ("myanmar", "burma", "naypyidaw"),
    "ET": ("ethiopia", "ethiopian", "addis ababa"),
    "SD": ("sudan", "khartoum"),
    "LY": ("libya", "libyan", "tripoli"),
    "DZ": ("algeria", "algerian", "algiers"),
    "MA": ("morocco", "moroccan", "rabat"),
    "TN": ("tunisia", "tunisian", "tunis"),
}


def _term_pattern(term: str) -> re.Pattern[str]:
    flags = re.IGNORECASE if len(term) >= 4 else 0
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", flags)


_TERM_PATTERNS: dict[str, list[re.Pattern[str]]] = {}
for _iso, _name in COUNTRY_CATALOG:
    terms = list(COUNTRY_TERMS.get(_iso, ())) + [_name]
    _TERM_PATTERNS[_iso] = [_term_pattern(t) for t in terms]


def match_countries(text: str) -> tuple[list[str], list[str]]:
    """Return ``(isos, matched_terms)`` for a headline.

    Multi-country headlines are supported: one article can legally concern
    several countries, and each one is listed with the exact term that
    matched (auditable attribution).
    """
    haystack = str(text or "")
    if not haystack:
        return [], []
    isos: list[str] = []
    matched: list[str] = []
    for iso, patterns in _TERM_PATTERNS.items():
        for pattern in patterns:
            hit = pattern.search(haystack)
            if hit:
                if iso not in isos:
                    isos.append(iso)
                term = hit.group(0)
                if term not in matched:
                    matched.append(term)
                break
    return isos, matched


def _clean_text(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def world_rows(
    articles: Iterable[Any],
    *,
    now: datetime,
    source: str = "gdelt",
    limit: int = 60,
) -> list[dict[str, Any]]:
    """Normalize headlines into country-tagged world-event rows."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in articles:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title") or item.get("headline") or item.get("name"))
        if not title:
            continue
        summary = _clean_text(item.get("summary") or item.get("description"), 400)
        isos, matched = match_countries(f"{title} {summary}")
        war = bool(_WAR_RE.search(title))
        political = bool(_POLITICAL_RE.search(title))
        impact = "high" if war else ("medium" if political else "low")
        when = parse_when_utc(
            item.get("published_at") or item.get("seendate") or item.get("date")
            or item.get("published") or item.get("datetime")
        )
        undated = when is None
        if when is None:
            when = now
        url = str(item.get("url") or item.get("link") or "").strip()
        row_id = _row_id("world", when, isos, title)
        if row_id in seen:
            continue
        seen.add(row_id)
        seconds = (when - now).total_seconds()
        rows.append({
            "id": row_id,
            "kind": "world",
            "title": title,
            "countries": isos,
            "country_names": [country_name(i) for i in isos],
            "when_utc": when.isoformat(),
            "undated": undated,
            "impact": impact,
            "currencies": [],
            "pairs": [],
            "source": source,
            "spot": war,
            "pinned": war,
            "details": {
                "url": url or None,
                "matched_terms": matched,
                "impact_basis": "headline_keywords",
            },
            "seconds_to_event": round(seconds, 1),
            "age_minutes": round(-seconds / 60, 1) if seconds < 0 else None,
        })
        if len(rows) >= limit:
            break
    return rows


# ---------------------------------------------------------------------------
# Windows, filtering, index, alerts
# ---------------------------------------------------------------------------


def split_window(
    rows: list[dict[str, Any]],
    *,
    days_ahead: float = 90.0,
    days_back: float = 7.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows into upcoming (ascending) and past (descending).

    Undated headlines (no parseable provider timestamp) land at the top of
    the past list as freshly-arrived wire copy — their publish time is
    unknown and they are flagged ``undated`` instead of being given one.
    """
    ahead_s = days_ahead * 86400
    back_s = days_back * 86400
    upcoming = [
        r for r in rows
        if not r.get("undated") and 0 <= float(r.get("seconds_to_event") or 0) <= ahead_s
    ]
    past = [
        r for r in rows
        if r.get("undated")
        or (
            float(r.get("seconds_to_event") or 0) < 0
            and -float(r.get("seconds_to_event") or 0) <= back_s
        )
    ]
    upcoming.sort(key=lambda r: (str(r.get("when_utc")), -_IMPACT_ORDER.get(str(r.get("impact")), 0)))
    # Past: undated wire copy first (newest arrivals), then dated rows
    # newest -> oldest.
    dated = [r for r in past if not r.get("undated")]
    dated.sort(key=lambda r: str(r.get("when_utc")), reverse=True)
    past = [r for r in past if r.get("undated")] + dated
    return upcoming, past


def _csv(value: Any) -> list[str]:
    if value is None or isinstance(value, (list, tuple, set)):
        parts = list(value or [])
    else:
        parts = str(value).split(",")
    return [str(p).strip() for p in parts if str(p).strip()]


def apply_filters(
    rows: list[dict[str, Any]],
    *,
    countries: Iterable[str] = (),
    kind: str = "all",
    impacts: Iterable[str] = (),
    query: str = "",
    limit: int = 250,
) -> list[dict[str, Any]]:
    wanted_iso = {canonical_iso(c) or c.upper() for c in countries}
    wanted_impact = {str(i).strip().lower() for i in impacts if str(i).strip()}
    kind_key = str(kind or "all").strip().lower() or "all"
    q = str(query or "").strip().lower()
    if kind_key not in {"all", "economic", "world"}:
        kind_key = "all"
    out: list[dict[str, Any]] = []
    for row in rows:
        if kind_key != "all" and row.get("kind") != kind_key:
            continue
        if wanted_iso:
            row_iso = {str(c).upper() for c in (row.get("countries") or [])}
            if not (row_iso & wanted_iso):
                continue
        if wanted_impact and str(row.get("impact") or "").lower() not in wanted_impact:
            continue
        if q:
            hay = " ".join([
                str(row.get("title") or ""),
                " ".join(str(c) for c in (row.get("country_names") or [])),
                " ".join(str(p) for p in (row.get("pairs") or [])),
            ]).lower()
            if q not in hay:
                continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def build_country_index(rows: list[dict[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
    """Aggregate every country that appears in the unfiltered row set."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        for iso in row.get("countries") or []:
            bucket = buckets.setdefault(iso, {
                "iso": iso,
                "name": country_name(iso),
                "upcoming_count": 0,
                "past_count": 0,
                "next_event": None,
            })
            seconds = float(row.get("seconds_to_event") or 0)
            is_past = bool(row.get("undated")) or seconds < 0
            if not is_past:
                bucket["upcoming_count"] += 1
                candidate = bucket["next_event"]
                if candidate is None or seconds < float(candidate.get("seconds_to_event") or 0):
                    bucket["next_event"] = {
                        "id": row.get("id"),
                        "title": row.get("title"),
                        "when_utc": row.get("when_utc"),
                        "impact": row.get("impact"),
                        "seconds_to_event": seconds,
                        "spot": bool(row.get("spot")),
                        "kind": row.get("kind"),
                    }
            else:
                bucket["past_count"] += 1
    index: list[dict[str, Any]] = []
    for bucket in buckets.values():
        next_event = bucket["next_event"]
        if next_event is None:
            state = "quiet"
        else:
            seconds = float(next_event.get("seconds_to_event") or 0)
            if seconds <= 900:
                state = "live"
            elif seconds <= 6 * 3600:
                state = "imminent"
            elif seconds <= 48 * 3600:
                state = "soon"
            else:
                state = "scheduled"
        bucket["state"] = state
        index.append(bucket)
    index.sort(key=lambda b: (
        _STATE_ORDER.get(str(b.get("state")), 9),
        float(((b.get("next_event") or {}).get("seconds_to_event")) or 1e18),
        str(b.get("name")),
    ))
    return index


_STATE_ORDER = {"live": 0, "imminent": 1, "soon": 2, "scheduled": 3, "quiet": 4}


def build_alerts(
    rows: list[dict[str, Any]],
    *,
    lead_minutes: Iterable[int] = DEFAULT_ALERT_LEAD_MINUTES,
) -> list[dict[str, Any]]:
    """Upcoming spot-tracked events the UI can alarm on."""
    leads = sorted({int(m) for m in lead_minutes if int(m) > 0})
    alerts: list[dict[str, Any]] = []
    for row in rows:
        seconds = float(row.get("seconds_to_event") or 0)
        if seconds < 0:
            continue
        is_spot = bool(row.get("spot"))
        is_pinned = bool(row.get("pinned")) and str(row.get("impact")) == "high"
        if not (is_spot or is_pinned):
            continue
        alerts.append({
            "id": row.get("id"),
            "kind": row.get("kind"),
            "title": row.get("title"),
            "when_utc": row.get("when_utc"),
            "seconds_to_event": seconds,
            "countries": row.get("countries") or [],
            "country_names": row.get("country_names") or [],
            "pairs": row.get("pairs") or [],
            "impact": row.get("impact"),
            "spot": is_spot,
            "pinned": is_pinned,
            "source": row.get("source"),
            "lead_minutes": leads,
        })
    alerts.sort(key=lambda a: float(a.get("seconds_to_event") or 0))
    return alerts


def next_high_impact(
    upcoming: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """The nearest upcoming high-impact row — the event the tracker leads to."""
    for row in upcoming:
        if str(row.get("impact")) == "high" and float(row.get("seconds_to_event") or 0) >= 0:
            return {
                "id": row.get("id"),
                "title": row.get("title"),
                "when_utc": row.get("when_utc"),
                "countries": row.get("countries") or [],
                "country_names": row.get("country_names") or [],
                "seconds_to_event": row.get("seconds_to_event"),
                "spot": bool(row.get("spot")),
            }
    return None


def world_query() -> str:
    """GDELT query covering the world-events stream.

    Restricted to English-language wire copy so the country gazetteer can
    tag headlines reliably (the keyless gazetteer is English).
    """
    return _WORLD_QUERY + " sourcelang:english"


def window_meta(
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    days_ahead: float,
    days_back: float,
) -> dict[str, Any]:
    upcoming, past = split_window(rows, days_ahead=days_ahead, days_back=days_back)
    newest_past = past[0]["when_utc"] if past else None
    return {
        "days_ahead": days_ahead,
        "days_back": days_back,
        "upcoming_count": len(upcoming),
        "past_count": len(past),
        "earliest_upcoming_utc": upcoming[0]["when_utc"] if upcoming else None,
        "newest_past_utc": newest_past,
        "next_high_impact": next_high_impact(upcoming, now=now),
        "as_of": now.isoformat(),
    }


__all__ = [
    "COUNTRY_CATALOG",
    "COUNTRY_TERMS",
    "CURRENCY_TO_ISO",
    "DEFAULT_ALERT_LEAD_MINUTES",
    "ISO_NAMES",
    "MAJOR_MARKET_ISO",
    "PAIR_MAP",
    "REGION_NAMES",
    "apply_filters",
    "build_alerts",
    "build_country_index",
    "canonical_iso",
    "country_name",
    "currency_for",
    "economic_rows",
    "match_countries",
    "next_high_impact",
    "normalize_impact",
    "pairs_for",
    "parse_when_utc",
    "split_window",
    "window_meta",
    "world_query",
    "world_rows",
]
