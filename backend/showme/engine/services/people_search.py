"""Live, keyless people search for PEOP via Wikipedia + Wikidata.

The PEOP pane's local SQLite directory only knows what an operator typed in;
on a cold terminal "jensen" answered "No people matched" even though the
Wikimedia public APIs are keyless and reachable. This module turns them into
the pane's row schema:

* candidate discovery — ``en.wikipedia.org/w/api.php?action=query&list=search``
  (a descriptive ``User-Agent`` is required by the Wikimedia policy);
* compact per-candidate summary —
  ``en.wikipedia.org/api/rest_v1/page/summary/<title>`` (description, extract,
  thumbnail, ``wikibase_item``, page timestamp);
* person filter — Wikidata ``P31`` instance-of must contain ``Q5`` (human)
  whenever claims are available. Pages with no Wikidata item/claims fall back
  to a disclosed description-keyword heuristic (``_PERSON_DESCRIPTION_KEYWORDS``
  below) and disambiguation pages are always dropped;
* role / organization / nationality — Wikidata ``P39`` position held →
  ``P106`` occupation (role), ``P108`` employer (organization), ``P27``
  citizenship, with referenced-QID labels resolved in a second batched
  ``wbgetentities`` call. When Wikidata carries no employer statement, an
  explicitly tagged pattern heuristic may derive the organization from the
  summary text (``company_source='summary_pattern'``) so it is never confused
  with a Wikidata statement.

Politeness: every HTTP request START is spaced by
``MIN_REQUEST_INTERVAL_SECONDS`` (~1 req/s across the process), summary
fetches run under a bounded thread pool, and a per-query in-process cache
(5 min success / 45 s failure) keeps repeat searches off the wire. Failures
are surfaced as ``ok=False`` with a reason — this module never fabricates
rows.
"""

from __future__ import annotations

import calendar
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode

LOG = logging.getLogger("showme.people_search")

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

_USER_AGENT = (
    "ShowMeTerminal/1.0 (local research terminal; "
    "https://github.com/nazmiefearmutcu/showme)"
)

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_CACHE_TTL_SECONDS = 300.0
FAILURE_CACHE_TTL_SECONDS = 45.0
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_CANDIDATES = 8
MIN_CANDIDATES = 5
MAX_CONCURRENCY = 4

_Q5_HUMAN = "Q5"
_PROP_INSTANCE_OF = "P31"
_PROP_OCCUPATION = "P106"
_PROP_EMPLOYER = "P108"
_PROP_POSITION = "P39"
_PROP_CITIZENSHIP = "P27"
_PROP_START_TIME = "P580"   # qualifier: start time
_PROP_END_TIME = "P582"     # qualifier: end time

# Disclosed fallback for pages that have no Wikidata claims to check P31
# against. The keywords are matched on word boundaries over the summary
# description + the first 400 chars of the extract.
_PERSON_DESCRIPTION_KEYWORDS = (
    "born",
    "businessman",
    "businesswoman",
    "business executive",
    "business magnate",
    "executive",
    "entrepreneur",
    "investor",
    "banker",
    "economist",
    "politician",
    "diplomat",
    "statesman",
    "lawyer",
    "attorney",
    "judge",
    "actor",
    "actress",
    "filmmaker",
    "film director",
    "producer",
    "screenwriter",
    "singer",
    "musician",
    "rapper",
    "composer",
    "author",
    "writer",
    "journalist",
    "scientist",
    "physicist",
    "chemist",
    "biologist",
    "mathematician",
    "professor",
    "engineer",
    "architect",
    "athlete",
    "footballer",
    "basketball player",
    "baseball player",
    "cricketer",
    "golfer",
    "boxer",
    "cyclist",
    "racing driver",
    "coach",
    "military officer",
    "general",
    "admiral",
    "philanthropist",
    "royal",
    "monarch",
    "nobleman",
    "chief executive",
    "ceo",
    "founder",
    "chairman",
    "chief financial officer",
    "president",
)
_PERSON_KEYWORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _PERSON_DESCRIPTION_KEYWORDS) + r")\b"
)
_BORN_RE = re.compile(r"\(born\s+\d{3,4}\)")

# Disclosed fallback organization heuristic (only used when Wikidata P108 is
# empty): "CEO of Nvidia", "founder of Microsoft", ... The captured span must
# start with a capital letter so lowercase prose never matches.
_ORG_RE = re.compile(
    r"\b(?:CEO|chief executive(?: officer)?|founder|co-founder|president|"
    r"chair(?:man|woman|person)?|director) of (?:the )?"
    r"([A-Z][A-Za-z0-9&.'-]*(?:[ \t]+[A-Z][A-Za-z0-9&.'-]*){0,3})"
)

_cache_lock = threading.Lock()
_throttle_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_last_request_at = 0.0


def _http_get_json(url: str, timeout: float) -> dict[str, Any]:
    """GET ``url`` as JSON, politely throttled. Raises on non-200."""
    _throttle()
    import httpx

    with httpx.Client(
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as client:
        response = client.get(url)
        if response.status_code != 200:
            raise RuntimeError(
                f"http {response.status_code} from {url.split('?', 1)[0]}"
            )
        data = response.json()
    if not isinstance(data, dict):
        raise TypeError("provider returned a non-object payload")
    return data


def _throttle() -> None:
    """Space live request STARTS (~1 req/s) across the whole process."""
    global _last_request_at
    with _throttle_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        _last_request_at = time.monotonic()


def _wiki_url(params: dict[str, Any]) -> str:
    return f"{WIKI_API}?{urlencode(params)}"


def _wikidata_url(params: dict[str, Any]) -> str:
    return f"{WIKIDATA_API}?{urlencode(params)}"


def _search_candidates(query: str, cap: int) -> list[dict[str, Any]]:
    payload = _http_get_json(
        _wiki_url(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": cap,
                "srnamespace": 0,
                "format": "json",
            }
        ),
        DEFAULT_TIMEOUT_SECONDS,
    )
    hits = ((payload.get("query") or {}).get("search") or [])
    candidates: list[dict[str, Any]] = []
    for rank, hit in enumerate(hits, start=1):
        title = str(hit.get("title") or "").strip()
        if not title:
            continue
        candidates.append(
            {
                "title": title,
                "search_rank": rank,
                "wordcount": int(hit.get("wordcount") or 0),
            }
        )
    return candidates


def _fetch_one_summary(candidate: dict[str, Any]) -> dict[str, Any] | None:
    title = candidate["title"]
    url = WIKI_SUMMARY + quote(title.replace(" ", "_"), safe="")
    try:
        summary = _http_get_json(url, DEFAULT_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — a single dead page must not sink the search
        LOG.info("wikipedia summary fetch failed for %s: %s", title, exc)
        return None
    return {**candidate, "summary": summary}


def _fetch_summaries(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        fetched = list(pool.map(_fetch_one_summary, candidates))
    return [row for row in fetched if row is not None]


def _claim_qids(entity: dict[str, Any] | None, prop: str) -> list[str]:
    """All non-deprecated object values of ``prop``, in provider order."""
    if not entity:
        return []
    out: list[str] = []
    for claim in entity.get("claims", {}).get(prop, []) or []:
        if claim.get("rank") == "deprecated":
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("id"):
            out.append(str(value["id"]))
    return out


_TIME_RE = re.compile(r"^([+-]?)(\d{4,})-(\d{2})-(\d{2})")


def _parse_wikidata_time(raw: Any, *, end: bool) -> datetime | None:
    """Parse a Wikidata time value such as ``+2026-08-31T00:00:00Z``.

    Wikidata writes ``00`` for an unknown month or day. An end time is then
    taken as the latest possible date and a start time as the earliest, so
    that an uncertain boundary never makes a claim look current by accident.
    """
    match = _TIME_RE.match(str(raw or "").strip())
    if not match:
        return None
    sign, year_text, month_text, day_text = match.groups()
    year = int(year_text) * (-1 if sign == "-" else 1)
    month = int(month_text)
    day = int(day_text)
    if year < 1:
        return None
    if month == 0:
        month = 12 if end else 1
    if day == 0:
        day = calendar.monthrange(year, month)[1] if end else 1
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def _qualifier_time(claim: dict[str, Any], prop: str, *, end: bool) -> tuple[bool, datetime | None]:
    """Return ``(present, parsed)`` for a time qualifier.

    ``novalue`` means the qualifier is explicitly absent and returns ``(False, None)``.
    ``somevalue`` means the qualifier exists but its date is unknown and returns
    ``(True, None)``: callers treat that as present-but-unparseable, never as absent.
    """
    snaks = (claim.get("qualifiers") or {}).get(prop) or []
    for snak in snaks:
        if not isinstance(snak, dict):
            continue
        snaktype = snak.get("snaktype")
        if snaktype == "somevalue":
            return True, None
        if snaktype != "value":
            continue
        value = (snak.get("datavalue") or {}).get("value")
        raw = value.get("time") if isinstance(value, dict) else None
        return True, _parse_wikidata_time(raw, end=end)
    return False, None


def _claim_is_current(claim: dict[str, Any], moment: datetime) -> bool:
    """A claim is current when its end time (P582) has not passed and its start (P580) has begun.

    A present qualifier whose date cannot be parsed (including Wikidata's
    'unknown value') is treated as not provably current and excluded, so an
    ambiguous qualifier cannot produce a false current role. An absent qualifier
    (no P580 / P582 at all, or 'no value') places no constraint.
    """
    has_end, end = _qualifier_time(claim, _PROP_END_TIME, end=True)
    if has_end and (end is None or end <= moment):
        return False
    has_start, start = _qualifier_time(claim, _PROP_START_TIME, end=False)
    if has_start and (start is None or start > moment):
        return False
    return True


def _current_claim_qids(
    entity: dict[str, Any] | None, prop: str, *, now: datetime | None = None
) -> list[str]:
    """Object values of ``prop`` whose qualifiers say they are current, best first.

    Ordering: ``preferred`` rank first, then the most recent start time (P580),
    then provider order. Ended claims (P582 in the past) are dropped, which is
    what stops a former CEO from being reported as the current one.
    """
    if not entity:
        return []
    moment = now or datetime.now(timezone.utc)
    ranked: list[tuple[tuple[int, float], str]] = []
    for claim in entity.get("claims", {}).get(prop, []) or []:
        if not isinstance(claim, dict) or claim.get("rank") == "deprecated":
            continue
        if not _claim_is_current(claim, moment):
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if not (isinstance(value, dict) and value.get("id")):
            continue
        _, start = _qualifier_time(claim, _PROP_START_TIME, end=False)
        start_key = -start.timestamp() if start is not None else float("inf")
        preferred = 0 if claim.get("rank") == "preferred" else 1
        ranked.append(((preferred, start_key), str(value["id"])))
    ranked.sort(key=lambda item: item[0])
    out: list[str] = []
    for _, qid in ranked:
        if qid not in out:
            out.append(qid)
    return out


def _fetch_entities(qids: list[str]) -> dict[str, dict[str, Any]]:
    if not qids:
        return {}
    payload = _http_get_json(
        _wikidata_url(
            {
                "action": "wbgetentities",
                "ids": "|".join(qids[:50]),
                "props": "claims|labels",
                "languages": "en",
                "format": "json",
            }
        ),
        DEFAULT_TIMEOUT_SECONDS,
    )
    entities = payload.get("entities") or {}
    return {
        qid: ent
        for qid, ent in entities.items()
        if isinstance(ent, dict) and "missing" not in ent
    }


def _fetch_referenced_labels(
    entities: dict[str, dict[str, Any]],
) -> dict[str, str]:
    labels: dict[str, str] = {}
    for qid, ent in entities.items():
        label = ((ent.get("labels") or {}).get("en") or {}).get("value")
        if label:
            labels[qid] = str(label)
    referenced: set[str] = set()
    for ent in entities.values():
        for prop in (
            _PROP_POSITION,
            _PROP_OCCUPATION,
            _PROP_EMPLOYER,
            _PROP_CITIZENSHIP,
        ):
            referenced.update(_current_claim_qids(ent, prop))
    wanted = sorted(q for q in referenced if q not in labels)
    for start in range(0, len(wanted), 50):
        chunk = wanted[start : start + 50]
        payload = _http_get_json(
            _wikidata_url(
                {
                    "action": "wbgetentities",
                    "ids": "|".join(chunk),
                    "props": "labels",
                    "languages": "en",
                    "format": "json",
                }
            ),
            DEFAULT_TIMEOUT_SECONDS,
        )
        for qid, ent in (payload.get("entities") or {}).items():
            if not isinstance(ent, dict):
                continue
            label = ((ent.get("labels") or {}).get("en") or {}).get("value")
            if label:
                labels[qid] = str(label)
    return labels


def _description_looks_like_person(summary: dict[str, Any]) -> bool:
    description = str(summary.get("description") or "")
    extract = str(summary.get("extract") or "")[:400]
    haystack = f"{description} {extract}"
    if _BORN_RE.search(haystack):
        return True
    return bool(_PERSON_KEYWORD_RE.search(haystack))


def _is_person(
    summary: dict[str, Any], entity: dict[str, Any] | None
) -> bool:
    if str(summary.get("type") or "").strip().lower() == "disambiguation":
        return False
    p31 = _claim_qids(entity, _PROP_INSTANCE_OF)
    if p31:
        return _Q5_HUMAN in p31
    return _description_looks_like_person(summary)


def _organization_from_text(text: str) -> str | None:
    match = _ORG_RE.search(text)
    if not match:
        return None
    org = match.group(1).strip(" .,;:'\"")
    return org or None


def _matched_tokens(query: str, text: str) -> int:
    tokens = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 1]
    haystack = text.lower()
    return sum(1 for token in tokens if token in haystack)


def _labels_for(
    entity: dict[str, Any] | None, prop: str, labels: dict[str, str]
) -> list[str]:
    out: list[str] = []
    for qid in _current_claim_qids(entity, prop):
        label = labels.get(qid) or qid
        if label not in out:
            out.append(label)
    return out


def _map_item(
    candidate: dict[str, Any],
    entity: dict[str, Any] | None,
    labels: dict[str, str],
    query: str,
) -> dict[str, Any]:
    summary = candidate["summary"]
    title = str(summary.get("title") or candidate["title"]).strip()
    qid = str(summary.get("wikibase_item") or "") or None
    description = str(summary.get("description") or "").strip()
    extract = str(summary.get("extract") or "").strip()

    positions = _labels_for(entity, _PROP_POSITION, labels)
    occupations = _labels_for(entity, _PROP_OCCUPATION, labels)
    employers = _labels_for(entity, _PROP_EMPLOYER, labels)
    citizenships = _labels_for(entity, _PROP_CITIZENSHIP, labels)

    role = positions[0] if positions else ", ".join(occupations[:2])
    if not role:
        role = description or None
    # When the only employer claims have ended, the summary text names a former
    # employer; it must not be read back as the current company.
    employer_ended = not employers and bool(_claim_qids(entity, _PROP_EMPLOYER))
    company = employers[0] if employers else (
        None if employer_ended else _organization_from_text(f"{description}\n{extract}")
    )
    company_source = (
        "wikidata:P108" if employers else ("summary_pattern" if company else None)
    )
    page_url = (
        ((summary.get("content_urls") or {}).get("desktop") or {}).get("page")
        or (f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}")
    )
    thumbnail = ((summary.get("thumbnail") or {}) or {}).get("source")

    return {
        "full_name": title,
        "wikidata_label": labels.get(qid) if qid else None,
        "role": role,
        "company": company,
        "company_source": company_source,
        "description": description or None,
        "summary": extract[:280] or None,
        "bio": extract[:600] or None,
        "nationality": " / ".join(citizenships) or None,
        "thumbnail": thumbnail,
        "profile_url": page_url,
        "wikidata_id": qid,
        "source": "wikipedia",
        "source_url": page_url,
        "source_date": summary.get("timestamp"),
        "contact_status": "public_profile_only",
        "match_score": _matched_tokens(query, f"{title} {description}"),
        "search_rank": candidate["search_rank"],
        "_wordcount": candidate["wordcount"],
    }


def _rank_key(item: dict[str, Any]) -> tuple[int, int, int]:
    # Person-likeness filtering already ran; rank by query-token coverage,
    # then article depth (a transparent prominence proxy), then the live
    # Wikipedia relevance order as the tie-breaker.
    return (-int(item["match_score"]), -int(item["_wordcount"]), int(item["search_rank"]))


def _fetch_people(query: str, *, limit: int) -> dict[str, Any]:
    sources: list[str] = []
    try:
        cap = min(max(limit, MIN_CANDIDATES), MAX_CANDIDATES)
        hits = _search_candidates(query, cap)
        if not hits:
            return {"ok": True, "items": [], "sources": ["wikipedia"], "reason": None}
        candidates = _fetch_summaries(hits)
        if not candidates:
            raise RuntimeError("every wikipedia summary fetch failed")
        sources.append("wikipedia")
        entities = _fetch_entities(
            [c["summary"].get("wikibase_item") for c in candidates if c["summary"].get("wikibase_item")]
        )
        if entities:
            sources.append("wikidata")
        labels = _fetch_referenced_labels(entities)
        items: list[dict[str, Any]] = []
        for candidate in candidates:
            qid = candidate["summary"].get("wikibase_item")
            entity = entities.get(str(qid)) if qid else None
            if not _is_person(candidate["summary"], entity):
                continue
            items.append(_map_item(candidate, entity, labels, query))
        items.sort(key=_rank_key)
        public = [
            {k: v for k, v in item.items() if not k.startswith("_")} for item in items
        ]
        return {"ok": True, "items": public, "sources": sources, "reason": None}
    except Exception as exc:  # noqa: BLE001 — surfaced honestly, never faked
        LOG.info("people search failed for %r: %s", query, exc)
        return {
            "ok": False,
            "items": [],
            "sources": [],
            "reason": f"wikipedia/wikidata: {exc}",
        }


def search_people(query: str, *, limit: int = 25) -> dict[str, Any]:
    """Search Wikipedia/Wikidata for people.

    Returns ``{"ok", "items", "sources", "reason"}``. Cache-first (5 min
    success / 45 s failure); the returned ``items`` list is sliced to
    ``limit`` without touching the cached pool.
    """
    q = str(query or "").strip()
    bounded = max(1, int(limit or 1))
    if len(q) < 2:
        return {"ok": True, "items": [], "sources": [], "reason": None}
    key = q.lower()
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
    if entry is not None and entry[0] > now:
        result = entry[1]
        return {**result, "items": list(result.get("items") or [])[:bounded]}

    result = _fetch_people(q, limit=bounded)
    ttl = DEFAULT_CACHE_TTL_SECONDS if result["ok"] else FAILURE_CACHE_TTL_SECONDS
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl, result)
    return {**result, "items": list(result.get("items") or [])[:bounded]}


def clear_cache() -> None:
    """Test/ops hook — drop every cached response."""
    with _cache_lock:
        _cache.clear()


__all__ = [
    "DEFAULT_CACHE_TTL_SECONDS",
    "MAX_CANDIDATES",
    "MIN_REQUEST_INTERVAL_SECONDS",
    "clear_cache",
    "search_people",
]
