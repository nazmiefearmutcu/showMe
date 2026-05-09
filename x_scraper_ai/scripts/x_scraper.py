"""
showMe X Scraper - Twitter/X gercek paylasimlari cekme katmani.

3 stratejili scraper: snscrape -> twscrape -> ntscraper (Nitter) fallback chain.
Tum kutuphaneler aktif olanlari secer; konfigurasyonu cevre degiskenleriyle gecer.

Kullanim:
    from x_scraper import XScraper
    s = XScraper()
    posts = s.search("AAPL stock", limit=200, since="2026-04-01")
"""
from __future__ import annotations
import os, time, json, re, html
from dataclasses import dataclass, asdict, field
from typing import Iterable, Optional


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

    def to_dict(self):
        return asdict(self)


def clean_text(t: str) -> str:
    if not isinstance(t, str):
        return ""
    t = html.unescape(t)
    t = re.sub(r"http\S+|www\.\S+", " [URL] ", t)
    t = re.sub(r"@\w+", "@user", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


class XScraper:
    """Onceliklendirilmis scraper - hangisi calisiyorsa kullan."""

    def __init__(self, prefer: str = "auto", max_retries: int = 2):
        self.prefer = prefer
        self.max_retries = max_retries
        self._available = self._detect_backends()

    def _detect_backends(self) -> dict:
        avail = {}
        try:
            import snscrape  # noqa
            avail["snscrape"] = True
        except Exception:
            avail["snscrape"] = False
        try:
            import twscrape  # noqa
            avail["twscrape"] = True
        except Exception:
            avail["twscrape"] = False
        try:
            from ntscraper import Nitter  # noqa
            avail["ntscraper"] = True
        except Exception:
            avail["ntscraper"] = False
        return avail

    def search(self, query: str, limit: int = 100, since: Optional[str] = None,
               until: Optional[str] = None, lang: Optional[str] = None) -> list[Post]:
        order = ["snscrape", "twscrape", "ntscraper"] if self.prefer == "auto" else [self.prefer]
        last_err = None
        for backend in order:
            if not self._available.get(backend):
                continue
            try:
                fn = getattr(self, f"_search_{backend}")
                return fn(query, limit=limit, since=since, until=until, lang=lang)
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise RuntimeError(f"Tum backend'ler basarisiz oldu. Son hata: {last_err}")
        raise RuntimeError("Hicbir scraper backend yuklu degil. pip install snscrape twscrape ntscraper")

    # --- Backend implementasyonlari ---
    def _search_snscrape(self, query, limit, since, until, lang):
        import snscrape.modules.twitter as snstw
        q = query
        if since: q += f" since:{since}"
        if until: q += f" until:{until}"
        if lang:  q += f" lang:{lang}"
        out = []
        for i, t in enumerate(snstw.TwitterSearchScraper(q).get_items()):
            if i >= limit: break
            out.append(Post(
                id=str(t.id), text=clean_text(t.rawContent or t.content),
                user=getattr(t.user, "username", "") if t.user else "",
                date=t.date.isoformat() if t.date else "",
                likes=t.likeCount or 0, retweets=t.retweetCount or 0,
                replies=t.replyCount or 0, url=t.url,
                lang=getattr(t, "lang", "") or "",
            ))
        return out

    def _search_twscrape(self, query, limit, since, until, lang):
        import asyncio
        from twscrape import API
        async def _run():
            api = API()
            await api.pool.login_all()
            q = query
            if since: q += f" since:{since}"
            if until: q += f" until:{until}"
            if lang:  q += f" lang:{lang}"
            out = []
            async for t in api.search(q, limit=limit):
                out.append(Post(
                    id=str(t.id), text=clean_text(t.rawContent),
                    user=t.user.username if t.user else "",
                    date=t.date.isoformat() if t.date else "",
                    likes=t.likeCount or 0, retweets=t.retweetCount or 0,
                    replies=t.replyCount or 0, url=t.url,
                    lang=t.lang or "",
                ))
            return out
        return asyncio.run(_run())

    def _search_ntscraper(self, query, limit, since, until, lang):
        from ntscraper import Nitter
        sc = Nitter(log_level=1, skip_instance_check=False)
        res = sc.get_tweets(query, mode="term", number=limit,
                            since=since, until=until, language=lang)
        out = []
        for t in res.get("tweets", [])[:limit]:
            out.append(Post(
                id=str(t.get("link","").rsplit("/",1)[-1]),
                text=clean_text(t.get("text","")),
                user=t.get("user",{}).get("username",""),
                date=t.get("date",""),
                likes=t.get("stats",{}).get("likes",0),
                retweets=t.get("stats",{}).get("retweets",0),
                replies=t.get("stats",{}).get("comments",0),
                url=t.get("link",""),
                lang=lang or "",
            ))
        return out


def to_jsonl(posts: list[Post], path: str):
    with open(path, "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    s = XScraper()
    posts = s.search(q, limit=10)
    for p in posts:
        print(f"@{p.user} ({p.date}): {p.text[:120]}")
