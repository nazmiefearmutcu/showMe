"""Spontaneous X (Twitter) scraper for showMe — no API auth, no rate-limit account.

In 2026 every old-school chain (snscrape, twscrape, ntscraper) is either dead
or behind a login wall. This module replaces them with a self-contained chain
that only relies on **public, unauthenticated** endpoints:

1. **DuckDuckGo HTML → syndication CDN** — the workhorse. We hit the
   `html.duckduckgo.com/html/` endpoint with a site-restricted query, parse
   out ``x.com/<user>/status/<id>`` URLs, then fetch each tweet's full text
   from ``cdn.syndication.twimg.com/tweet-result`` (the same CDN every Twitter
   embed uses — no auth, no rate limit account).
2. **Bing HTML mirror** — same flow, different search engine. Used as a
   parallel feed, not a fallback, so a single source going down doesn't
   silence the chain.
3. **r.jina.ai reader proxy** — last-ditch markdown reader that scrapes the
   public X.com search HTML through Jina's free proxy.

Each backend returns the same canonical ``Post`` shape so the analyzer can
treat them uniformly. All HTTP work uses ``httpx`` (already a sidecar dep) so
PyInstaller doesn't need new wheels.
"""
from __future__ import annotations

import html
import logging
import random
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from collections.abc import Iterable
from urllib.parse import quote_plus

import httpx

LOG = logging.getLogger("showme.x_spontaneous")

DEFAULT_TIMEOUT = 15.0
GUEST_TTL_SECONDS = 60 * 25
NITTER_BLACKLIST_SECONDS = 60 * 10

# These match what the public X.com homepage embeds for logged-out visitors.
PUBLIC_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

PUBLIC_NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.tiekoetter.com",
    "https://nitter.unixfox.eu",
    "https://nitter.cz",
    "https://nitter.lucabased.xyz",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)


@dataclass
class Post:
    id: str
    text: str
    user: str
    date: str
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    url: str = ""
    lang: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out.pop("raw", None)
        return out


def clean_text(t: Any) -> str:
    if not isinstance(t, str):
        return ""
    t = html.unescape(t)
    t = re.sub(r"https?://\S+|www\.\S+", " [URL] ", t)
    t = re.sub(r"@\w+", "@user", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _now() -> float:
    return time.monotonic()


_RELATIVE_TIME_RE = re.compile(r"^\s*(\d+)\s*(h|hours?|d|days?|w|weeks?|m|months?|y|years?)\s*$", re.I)


def _parse_filter_time(value: str | None, label: str) -> datetime | None:
    """Parse ``since``/``until`` as ISO date or relative window (24h/7d/30d).

    Unparseable values emit a single warning and return None so the
    filter is skipped (rather than crashing the search).
    """
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Relative form first ("24h", "7d", "30d", "12 hours")
    m = _RELATIVE_TIME_RE.match(raw)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("h"):
            delta_seconds = amount * 3600
        elif unit.startswith("d"):
            delta_seconds = amount * 86400
        elif unit.startswith("w"):
            delta_seconds = amount * 7 * 86400
        elif unit.startswith("mo") or unit == "m":
            delta_seconds = amount * 30 * 86400
        else:
            delta_seconds = amount * 365 * 86400
        return datetime.now(timezone.utc).fromtimestamp(
            time.time() - delta_seconds, tz=timezone.utc
        )
    # ISO date / datetime
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        LOG.warning("x_spontaneous: ignoring unparseable %s=%r", label, value)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_post_date(raw: str) -> datetime | None:
    """Parse a tweet ``created_at`` string in either Twitter's classic format
    or ISO 8601. Returns None on failure (caller treats as "unknown").
    """
    if not raw:
        return None
    text = raw.strip()
    # Twitter classic format: "Wed Oct 10 20:19:24 +0000 2018"
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _filter_posts(
    posts: list["Post"],
    *,
    since_dt: datetime | None,
    until_dt: datetime | None,
    lang: str | None,
) -> list["Post"]:
    """Client-side date / lang filter applied after hydration."""
    if not (since_dt or until_dt or lang):
        return posts
    out: list[Post] = []
    lang_prefix = (lang or "").strip().lower()
    for p in posts:
        if lang_prefix and p.lang and not p.lang.lower().startswith(lang_prefix):
            continue
        if since_dt or until_dt:
            dt = _parse_post_date(p.date)
            if dt is None:
                # Unknown date — keep the post; otherwise we'd silently drop
                # everything when the syndication CDN doesn't ship a date.
                out.append(p)
                continue
            if since_dt and dt < since_dt:
                continue
            if until_dt and dt > until_dt:
                continue
        out.append(p)
    return out


class _GuestTokenCache:
    """Process-wide guest-token cache. Refreshes when the TTL expires."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get(self, client: httpx.Client) -> str | None:
        with self._lock:
            if self._token and _now() < self._expires_at:
                return self._token
            try:
                response = client.post(
                    "https://api.x.com/1.1/guest/activate.json",
                    headers={
                        "Authorization": f"Bearer {PUBLIC_BEARER}",
                        "User-Agent": USER_AGENT,
                    },
                    timeout=DEFAULT_TIMEOUT,
                )
                response.raise_for_status()
                token = response.json().get("guest_token")
                if not token:
                    return None
                self._token = str(token)
                self._expires_at = _now() + GUEST_TTL_SECONDS
                return self._token
            except Exception as exc:  # noqa: BLE001
                LOG.warning("guest-token activation failed: %s", exc)
                self._token = None
                self._expires_at = 0.0
                return None

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0


_GUEST = _GuestTokenCache()


class _NitterPool:
    """Mirror pool with success-priority + failure blacklist."""

    def __init__(self, mirrors: Iterable[str] = PUBLIC_NITTER_INSTANCES) -> None:
        self._lock = threading.Lock()
        self._mirrors = list(mirrors)
        self._blacklist: dict[str, float] = {}
        self._success: dict[str, float] = {}

    def order(self) -> list[str]:
        with self._lock:
            now = _now()
            self._blacklist = {m: t for m, t in self._blacklist.items() if t > now}
            available = [m for m in self._mirrors if m not in self._blacklist]
            random.shuffle(available)
            available.sort(key=lambda m: self._success.get(m, 0.0), reverse=True)
            return available

    def mark_success(self, mirror: str) -> None:
        with self._lock:
            self._success[mirror] = _now()
            self._blacklist.pop(mirror, None)

    def mark_failure(self, mirror: str, ban_seconds: float = NITTER_BLACKLIST_SECONDS) -> None:
        with self._lock:
            self._blacklist[mirror] = _now() + ban_seconds


_NITTER = _NitterPool()


class _SearchEngineThrottle:
    """Per-engine min-interval throttle + small in-process cache.

    SEC-12 hardening:
    * ``max_sleep`` caps each ``wait_slot`` call so a single chip request
      cannot consume the route's 30s timeout sleeping for the throttle —
      if the wait would exceed the cap, the caller is told to fall through
      (``wait_slot`` returns ``False``) instead of blocking.
    * ``ban(engine, seconds)`` lets the caller (typically on HTTP 429)
      tell the throttle to short-circuit future requests for that engine.
      The ban has a 60s floor so even a missing ``Retry-After`` gives the
      remote some breathing room. ``is_banned`` is queried before any
      ``wait_slot`` to avoid pointless sleeps.
    """

    def __init__(
        self,
        min_interval: float = 30.0,
        cache_ttl: float = 1800.0,
        max_sleep: float = 4.0,
    ) -> None:
        self._lock = threading.Lock()
        self._min_interval = min_interval
        self._cache_ttl = cache_ttl
        self._max_sleep = max_sleep
        self._last_call: dict[str, float] = {}
        self._cache: dict[tuple[str, str], tuple[float, list[str]]] = {}
        self._ban_until: dict[str, float] = {}

    def cached(self, engine: str, query: str) -> list[str] | None:
        key = (engine, query)
        with self._lock:
            entry = self._cache.get(key)
            if entry and _now() - entry[0] < self._cache_ttl:
                return list(entry[1])
            return None

    def store(self, engine: str, query: str, ids: list[str]) -> None:
        with self._lock:
            self._cache[(engine, query)] = (_now(), list(ids))

    def is_banned(self, engine: str) -> bool:
        with self._lock:
            return self._ban_until.get(engine, 0.0) > _now()

    def ban(self, engine: str, seconds: float) -> None:
        """Mark ``engine`` as rate-limited for at least ``seconds``.

        60s floor so a missing ``Retry-After`` header still gives the
        remote some breathing room.
        """
        with self._lock:
            self._ban_until[engine] = _now() + max(seconds, 60.0)

    def wait_slot(self, engine: str) -> bool:
        """Honor the min-interval floor; cap the sleep at ``max_sleep``.

        Returns ``True`` if the slot was acquired (sleep ≤ max_sleep),
        ``False`` if the requested wait would have exceeded the cap — in
        which case the caller should fall through to the next backend
        instead of paying the full timeout.
        """
        with self._lock:
            now = _now()
            last = self._last_call.get(engine, 0.0)
            wait = self._min_interval - (now - last)
            sleep_for = min(max(wait, 0.0), self._max_sleep)
            # Bump _last_call now so concurrent callers see the slot taken
            # even though we release the lock during ``time.sleep``.
            self._last_call[engine] = _now() + sleep_for
        if sleep_for > 0:
            time.sleep(sleep_for)
        return wait <= self._max_sleep


_SEARCH_THROTTLE = _SearchEngineThrottle()


def _parse_retry_after(value: str | None, default: float = 300.0) -> float:
    """Parse a Retry-After header (RFC 7231) into seconds; 5min default floor."""
    if not value:
        return default
    try:
        return max(float(value), 60.0)
    except ValueError:
        # Could be an HTTP-date — too rare to support; fall back to default.
        return default


def _syndication_token(tweet_id: str) -> str:
    """Replicate twitter-syndication's deterministic token formula."""
    try:
        tid = int(tweet_id)
    except Exception:
        return "0"
    n = (tid / 1e15) * 0.0006
    return format(n, ".15g").lstrip("0").replace(".", "")


class SpontaneousXScraper:
    """Account-free X scraper.

    Order:
      1. DuckDuckGo HTML → syndication CDN  (primary, most reliable)
      2. Bing HTML → syndication CDN        (parallel feed)
      3. Nitter mirror rotation             (legacy; mostly dead in 2026)
      4. Jina reader proxy                  (last-ditch fallback)
    """

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def __del__(self) -> None:  # pragma: no cover
        try:
            self._client.close()
        except Exception:
            pass

    def diagnostics(self) -> dict[str, Any]:
        # Per FUNC-02 P0: do NOT call _GUEST.get(...) here. /api/x/health
        # was triggering a guest-token POST to api.x.com on every dashboard
        # mount, which 429-rate-limited within minutes. The active backends
        # don't need a guest token; report a static snapshot instead.
        token_snapshot = {
            "token_present": bool(_GUEST._token),
            "expires_at": _GUEST._expires_at,
        }
        return {
            "backends": {
                "brave_syndication": True,
                "ddg_syndication": True,
                "bing_syndication": True,
                "guest_token": token_snapshot["token_present"],
                "nitter_pool_size": len(_NITTER.order()),
                "jina_proxy": True,
            },
            "guest_token_present": token_snapshot["token_present"],
            "guest_token_snapshot": token_snapshot,
            "nitter_mirrors_active": _NITTER.order(),
        }

    def search(
        self,
        query: str,
        limit: int = 100,
        since: str | None = None,
        until: str | None = None,
        lang: str | None = None,
    ) -> list[Post]:
        """Scrape posts matching ``query`` with best-effort date/lang filters.

        Per FUNC-02 P0: ``since`` / ``until`` / ``lang`` were previously
        accepted and silently dropped. Search engines (Brave/DDG/Bing) do
        not reliably honor X's ``since:`` / ``until:`` / ``lang:`` operators,
        so we filter client-side after hydration. ``since`` and ``until``
        accept either ISO date (``2026-05-01``) or relative strings
        (``24h``, ``7d``, ``30d``); unparseable values are ignored with a
        single warning. ``lang`` is matched against ``Post.lang`` prefix.
        """
        full_query = self._normalize_query(query)
        if not full_query:
            return []

        since_dt = _parse_filter_time(since, "since")
        until_dt = _parse_filter_time(until, "until")

        seen_ids: set[str] = set()
        posts: list[Post] = []
        errors: list[str] = []

        for fn in (
            self._search_brave_syndication,
            self._search_ddg_syndication,
            self._search_bing_syndication,
        ):
            if len(posts) >= limit:
                break
            try:
                fresh = fn(full_query, limit=limit - len(posts))
                for p in fresh:
                    if p.id and p.id in seen_ids:
                        continue
                    if p.id:
                        seen_ids.add(p.id)
                    posts.append(p)
                    if len(posts) >= limit:
                        break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fn.__name__}: {exc}")

        if not posts:
            # Fallbacks if every search engine + syndication produced nothing.
            for fn in (self._search_nitter, self._search_jina):
                try:
                    fresh = fn(full_query, limit=limit)
                    if fresh:
                        posts = fresh
                        break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{fn.__name__}: {exc}")

        if posts and (since_dt or until_dt or lang):
            posts = _filter_posts(posts, since_dt=since_dt, until_dt=until_dt, lang=lang)

        if not posts and errors:
            LOG.warning("All X scraper backends failed for %r: %s", query, "; ".join(errors))
        return posts

    # ---- Strategy 1: Brave Search → syndication CDN ----
    def _search_brave_syndication(self, query: str, limit: int) -> list[Post]:
        site_query = self._site_restricted_query(query)
        cached = _SEARCH_THROTTLE.cached("brave", site_query)
        if cached is not None:
            return self._hydrate_via_syndication(cached[: max(limit, 1)])
        if _SEARCH_THROTTLE.is_banned("brave"):
            raise RuntimeError("brave banned (429 cooldown active)")
        if not _SEARCH_THROTTLE.wait_slot("brave"):
            # Throttle wanted to sleep > max_sleep; fall through rather than
            # eat the route's timeout budget.
            raise RuntimeError("brave throttle skipped (fallthrough)")
        url = (
            "https://search.brave.com/search?q="
            + quote_plus(site_query)
            + "&source=web"
        )
        response = self._client.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if response.status_code == 429:
            cooldown = _parse_retry_after(response.headers.get("Retry-After"))
            _SEARCH_THROTTLE.ban("brave", cooldown)
            raise RuntimeError(f"brave http 429 (banned {cooldown:.0f}s)")
        if response.status_code >= 400:
            raise RuntimeError(f"brave http {response.status_code}")
        ids = self._tweet_ids_from_html(response.text)
        if not ids:
            raise RuntimeError("brave returned 0 tweet ids")
        _SEARCH_THROTTLE.store("brave", site_query, ids)
        return self._hydrate_via_syndication(ids[: max(limit, 1)])

    # ---- Strategy 2: DuckDuckGo HTML → syndication CDN ----
    def _search_ddg_syndication(self, query: str, limit: int) -> list[Post]:
        ddg_query = self._site_restricted_query(query)
        cached = _SEARCH_THROTTLE.cached("ddg", ddg_query)
        if cached is not None:
            return self._hydrate_via_syndication(cached[: max(limit, 1)])
        if _SEARCH_THROTTLE.is_banned("ddg"):
            raise RuntimeError("ddg banned (429 cooldown active)")
        if not _SEARCH_THROTTLE.wait_slot("ddg"):
            raise RuntimeError("ddg throttle skipped (fallthrough)")
        url = "https://html.duckduckgo.com/html/"
        response = self._client.post(
            url,
            data={"q": ddg_query},
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        if response.status_code == 429:
            cooldown = _parse_retry_after(response.headers.get("Retry-After"))
            _SEARCH_THROTTLE.ban("ddg", cooldown)
            raise RuntimeError(f"ddg http 429 (banned {cooldown:.0f}s)")
        if response.status_code >= 400:
            raise RuntimeError(f"ddg http {response.status_code}")
        ids = self._tweet_ids_from_html(response.text)
        if not ids:
            raise RuntimeError("ddg returned 0 tweet ids")
        _SEARCH_THROTTLE.store("ddg", ddg_query, ids)
        return self._hydrate_via_syndication(ids[: max(limit, 1)])

    # ---- Strategy 3: Bing → syndication CDN ----
    def _search_bing_syndication(self, query: str, limit: int) -> list[Post]:
        bing_query = self._site_restricted_query(query)
        cached = _SEARCH_THROTTLE.cached("bing", bing_query)
        if cached is not None:
            return self._hydrate_via_syndication(cached[: max(limit, 1)])
        if _SEARCH_THROTTLE.is_banned("bing"):
            raise RuntimeError("bing banned (429 cooldown active)")
        if not _SEARCH_THROTTLE.wait_slot("bing"):
            raise RuntimeError("bing throttle skipped (fallthrough)")
        url = f"https://www.bing.com/search?q={quote_plus(bing_query)}&count=30"
        response = self._client.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        if response.status_code == 429:
            cooldown = _parse_retry_after(response.headers.get("Retry-After"))
            _SEARCH_THROTTLE.ban("bing", cooldown)
            raise RuntimeError(f"bing http 429 (banned {cooldown:.0f}s)")
        if response.status_code >= 400:
            raise RuntimeError(f"bing http {response.status_code}")
        ids = self._tweet_ids_from_html(response.text)
        if not ids:
            raise RuntimeError("bing returned 0 tweet ids")
        _SEARCH_THROTTLE.store("bing", bing_query, ids)
        return self._hydrate_via_syndication(ids[: max(limit, 1)])

    @staticmethod
    def _normalize_query(query: str) -> str:
        text = (query or "").strip()
        if not text:
            return ""
        # Strip any since:/until:/lang: operators so the search engine layer
        # gets a clean ticker / phrase. Date filters are best-effort only.
        text = re.sub(r"\b(?:since|until|lang):\S+", "", text).strip()
        # Drop the cashtag/hashtag OR pattern: search engines hate it and
        # syndication doesn't care which form the tweet uses.
        text = re.sub(r"^\$([A-Za-z]{1,6})\s+OR\s+#\1$", r"\1", text, flags=re.I)
        text = re.sub(r"^\$", "", text)
        return text

    @staticmethod
    def _site_restricted_query(query: str) -> str:
        return f"{query} site:x.com OR site:twitter.com"

    @staticmethod
    def _tweet_ids_from_html(body: str) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(
            r"(?:https?:)?//(?:x|twitter)\.com/[^/?#\"\s]+/status/(\d{6,32})",
            body,
        ):
            tid = match.group(1)
            if tid in seen:
                continue
            seen.add(tid)
            ids.append(tid)
        return ids

    def _hydrate_via_syndication(self, ids: list[str]) -> list[Post]:
        posts: list[Post] = []
        for tid in ids:
            try:
                tok = _syndication_token(tid)
                url = f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token={tok}"
                response = self._client.get(url, headers={"User-Agent": USER_AGENT})
                if response.status_code >= 400:
                    continue
                payload = response.json()
                user = (payload.get("user") or {}).get("screen_name") or ""
                text = clean_text(payload.get("text") or "")
                if not text:
                    continue
                likes = int(payload.get("favorite_count") or 0)
                retweets = int(
                    payload.get("conversation_count")
                    or payload.get("retweet_count")
                    or 0
                )
                created = payload.get("created_at") or ""
                lang = payload.get("lang") or ""
                posts.append(
                    Post(
                        id=str(tid),
                        text=text,
                        user=user,
                        date=created,
                        likes=likes,
                        retweets=retweets,
                        replies=int(payload.get("reply_count") or 0),
                        url=f"https://x.com/{user}/status/{tid}" if user else f"https://x.com/i/status/{tid}",
                        lang=lang,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                LOG.debug("syndication failed for %s: %s", tid, exc)
                continue
        return posts

    # ---- Strategy 3: Nitter HTML mirror rotation (mostly dead in 2026) ----
    def _search_nitter(self, query: str, limit: int) -> list[Post]:
        last_error: str | None = None
        for mirror in _NITTER.order():
            try:
                posts = self._scrape_nitter_mirror(mirror, query=query, limit=limit)
                if posts:
                    _NITTER.mark_success(mirror)
                    return posts
                last_error = f"{mirror}: 0 posts"
                _NITTER.mark_failure(mirror, ban_seconds=300)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{mirror}: {exc}"
                _NITTER.mark_failure(mirror)
                continue
        if last_error:
            raise RuntimeError(last_error)
        return []

    def _scrape_nitter_mirror(self, mirror: str, query: str, limit: int) -> list[Post]:
        url = f"{mirror}/search?f=tweets&q={quote_plus(query)}"
        response = self._client.get(url, headers={"User-Agent": USER_AGENT})
        if response.status_code >= 400:
            raise RuntimeError(f"http {response.status_code}")
        body = response.text
        posts: list[Post] = []
        for match in re.finditer(
            r'<div class="timeline-item[^"]*">(.+?)</div>\s*</div>\s*</div>',
            body,
            flags=re.DOTALL,
        ):
            block = match.group(1)
            text_match = re.search(
                r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>',
                block,
                flags=re.DOTALL,
            )
            user_match = re.search(r'href="/(\w+)"\s+class="username"', block)
            link_match = re.search(r'href="(/[^"]+/status/\d+)[^"]*"', block)
            if not text_match or not user_match or not link_match:
                continue
            text = clean_text(re.sub(r"<[^>]+>", " ", text_match.group(1)))
            user = user_match.group(1)
            link = mirror + link_match.group(1)
            status_id_match = re.search(r"/status/(\d+)", link)
            posts.append(
                Post(
                    id=status_id_match.group(1) if status_id_match else "",
                    text=text,
                    user=user,
                    date="",
                    url=link.replace(mirror, "https://x.com", 1),
                )
            )
            if len(posts) >= limit:
                break
        return posts

    # ---- Strategy 4: r.jina.ai search proxy ----
    def _search_jina(self, query: str, limit: int) -> list[Post]:
        target = f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"
        url = f"https://r.jina.ai/{target}"
        response = self._client.get(url, headers={"User-Agent": USER_AGENT})
        if response.status_code >= 400:
            raise RuntimeError(f"http {response.status_code}")
        text = response.text or ""
        posts: list[Post] = []
        seen: set[str] = set()
        for chunk in re.split(r"\n(?=@\w+\s*[·•])", text):
            chunk = chunk.strip()
            if not chunk or not chunk.startswith("@"):
                continue
            handle_match = re.match(r"@(\w+)\s*[·•]\s*(.+)", chunk)
            if not handle_match:
                continue
            handle = handle_match.group(1)
            body_text = clean_text(handle_match.group(2))
            if not body_text or body_text in seen:
                continue
            seen.add(body_text)
            posts.append(
                Post(
                    id=f"jina-{abs(hash(body_text))%10**12}",
                    text=body_text,
                    user=handle,
                    date="",
                    url=target,
                )
            )
            if len(posts) >= limit:
                break
        return posts


__all__ = ["Post", "SpontaneousXScraper", "clean_text"]
