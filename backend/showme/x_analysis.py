"""showMe X Sentiment AI — sidecar-side singleton + analysis orchestration.

Wraps the trained ``showme_x_v1`` model (RoBERTa-base + 3 task heads: sentiment,
emotion, topic) and the spontaneous account-free scraper into a single
process-wide singleton:

* Model loads lazily on the first analyze call (cold start ~2 sec, ~500 MB
  RAM). Sidecar boot is unaffected.
* All inference runs under one ``threading.Lock`` so concurrent FastAPI
  requests don't corrupt the shared backbone.
* Aggregations (sentiment/emotion/topic distribution, bullish score, examples)
  follow the contract in ``x_scraper_ai/scripts/analyze.py`` so anything that
  consumed the standalone CLI keeps working.
* ``analyze_topic_as_instant_events`` returns the same shape as the SQLite
  fallback in ``instant_line.py`` so high-impact tweets can be merged into the
  INSTANT feed without a second adapter.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import statistics
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Iterable

from showme.x_spontaneous import Post, SpontaneousXScraper, clean_text

LOG = logging.getLogger("showme.x_analysis")

DEFAULT_LIMIT = 120
MAX_LIMIT = 500
DEFAULT_LANG = "en"

# Below this many real posts the classifier output is statistical noise —
# 2 neutral tweets shouldn't be enough to declare "bullish" with any
# confidence. Returning {"verdict": "insufficient_data"} lets the UI render
# a "not enough data" empty-state rather than a misleading verdict.
# See SHOWME_BUGHUNT 2026-05-24 Bug #6. Tunable via env for ops/tests.
MIN_POSTS_FOR_VERDICT = max(
    1, int(os.environ.get("SHOWME_X_MIN_POSTS_FOR_VERDICT", "5"))
)

INSTANT_SOURCE_ID = "x_sentiment"
INSTANT_SOURCE_NAME = "X Social Sentiment"
INSTANT_SOURCE_CATEGORY = "social"
INSTANT_SOURCE_REGION = "global"


def _candidate_model_dirs() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            return
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    override = os.environ.get("SHOWME_X_MODEL_DIR")
    if override:
        add(Path(override))

    here = Path(__file__).resolve().parent
    add(here / "data" / "x_model" / "showme_x_v1")
    add(here / "x_model" / "showme_x_v1")

    parents = list(here.parents)
    for parent in parents[:6]:
        add(parent / "x_scraper_ai" / "model" / "showme_x_v1")
        add(parent / "model" / "showme_x_v1")

    home = Path.home()
    add(home / "Library" / "Application Support" / "showMe" / "models" / "showme_x_v1")
    add(home / "Desktop" / "Projeler" / "proje" / "showMe" / "x_scraper_ai" / "model" / "showme_x_v1")

    return candidates


def find_model_dir() -> Path | None:
    for candidate in _candidate_model_dirs():
        if (candidate / "tokenizer").is_dir() and (candidate / "heads.pt").exists():
            return candidate
    return None


class XAnalyzer:
    """Process-wide singleton wrapping the trained model + spontaneous scraper."""

    _instance: "XAnalyzer | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._loaded = False
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._model_dir: Path | None = None
        self._tokenizer = None
        self._backbone = None
        self._sent_head = None
        self._emo_head = None
        self._top_head = None
        self._label_maps: dict[str, dict[str, str]] = {}
        self._device = "cpu"
        self._torch = None
        self._scraper = SpontaneousXScraper()
        self._load_error: str | None = None

    @classmethod
    def instance(cls) -> "XAnalyzer":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---- Model lifecycle ----
    def health(self) -> dict[str, Any]:
        model_dir = find_model_dir()
        return {
            "ok": model_dir is not None,
            "model_loaded": self._loaded,
            "model_dir": str(model_dir) if model_dir else None,
            "load_error": self._load_error,
            "scraper": self._scraper.diagnostics(),
        }

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            try:
                model_dir = find_model_dir()
                if model_dir is None:
                    raise FileNotFoundError(
                        "X sentiment model not found. Set SHOWME_X_MODEL_DIR or place the bundle "
                        "under ~/Library/Application Support/showMe/models/showme_x_v1/."
                    )
                import torch  # type: ignore[import-not-found]
                import torch.nn as nn  # type: ignore[import-not-found]
                from transformers import AutoModel, AutoTokenizer  # type: ignore[import-not-found]

                self._torch = torch
                self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir / "tokenizer"))
                self._backbone = AutoModel.from_pretrained(str(model_dir / "backbone"))
                # weights_only=False: checkpoint["meta"] is a plain dict, not a tensor.
                # torch>=2.6 flipped the default to True, which raises UnpicklingError on
                # non-tensor pickled state. The file path is resolved through find_model_dir()
                # which only accepts the signed bundle directory shipped with the app
                # (or SHOWME_X_MODEL_DIR set by the operator), so we trust the source.
                checkpoint = torch.load(
                    str(model_dir / "heads.pt"),
                    map_location="cpu",
                    weights_only=False,
                )
                meta = checkpoint["meta"]
                hidden = self._backbone.config.hidden_size
                self._sent_head = nn.Sequential(
                    nn.Dropout(0.1),
                    nn.Linear(hidden, meta["n_sentiment"]),
                )
                self._emo_head = nn.Sequential(
                    nn.Dropout(0.1),
                    nn.Linear(hidden, meta["n_emotion"]),
                )
                self._top_head = nn.Sequential(
                    nn.Dropout(0.1),
                    nn.Linear(hidden, meta["n_topic"]),
                )
                self._sent_head.load_state_dict(checkpoint["sent_head"])
                self._emo_head.load_state_dict(checkpoint["emotion_head"])
                self._top_head.load_state_dict(checkpoint["topic_head"])
                with open(model_dir / "label_maps.json", "r", encoding="utf-8") as fh:
                    self._label_maps = json.load(fh)
                if torch.backends.mps.is_available():
                    self._device = "mps"
                elif torch.cuda.is_available():
                    self._device = "cuda"
                for module in (
                    self._backbone,
                    self._sent_head,
                    self._emo_head,
                    self._top_head,
                ):
                    module.to(self._device)
                    module.eval()
                self._model_dir = model_dir
                self._loaded = True
                self._load_error = None
                LOG.info("XAnalyzer loaded from %s on %s", model_dir, self._device)
            except Exception as exc:  # noqa: BLE001
                self._load_error = str(exc)
                LOG.exception("XAnalyzer load failed")
                raise

    # ---- Classification ----
    def classify(self, texts: Iterable[str], batch_size: int = 32) -> list[dict[str, Any]]:
        cleaned = [clean_text(t) for t in texts]
        cleaned = [t for t in cleaned if t]
        if not cleaned:
            return []
        self._ensure_loaded()
        torch = self._torch
        results: list[dict[str, Any]] = []
        with self._infer_lock:
            for start in range(0, len(cleaned), batch_size):
                chunk = cleaned[start : start + batch_size]
                with torch.no_grad():
                    enc = self._tokenizer(
                        chunk,
                        truncation=True,
                        padding=True,
                        max_length=128,
                        return_tensors="pt",
                    )
                    if self._device != "cpu":
                        enc = {k: v.to(self._device) for k, v in enc.items()}
                    out = self._backbone(**enc)
                    cls = out.last_hidden_state[:, 0]
                    sent = torch.softmax(self._sent_head(cls), dim=-1).cpu()
                    emo = torch.softmax(self._emo_head(cls), dim=-1).cpu()
                    topic = torch.softmax(self._top_head(cls), dim=-1).cpu()
                for j, text in enumerate(chunk):
                    si = int(sent[j].argmax())
                    ei = int(emo[j].argmax())
                    ti = int(topic[j].argmax())
                    results.append(
                        {
                            "text": text,
                            "sentiment": self._label("sentiment", si),
                            "sentiment_score": float(sent[j, si]),
                            "sentiment_probs": [float(p) for p in sent[j].tolist()],
                            "emotion": self._label("emotion", ei),
                            "emotion_score": float(emo[j, ei]),
                            "emotion_probs": [float(p) for p in emo[j].tolist()],
                            "topic": self._label("topic", ti),
                            "topic_score": float(topic[j, ti]),
                        }
                    )
        return results

    def _label(self, kind: str, idx: int) -> str:
        labels = self._label_maps.get(kind) or {}
        return labels.get(str(idx), labels.get(idx, str(idx)))  # type: ignore[arg-type]

    def label_options(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for kind, labels in self._label_maps.items():
            try:
                ordered = sorted(labels.items(), key=lambda kv: int(kv[0]))
                out[kind] = [str(value) for _, value in ordered]
            except Exception:
                out[kind] = list(labels.values())
        return out

    # ---- High-level orchestration ----
    def analyze_topic(
        self,
        query: str,
        limit: int = DEFAULT_LIMIT,
        since: str | None = None,
        until: str | None = None,
        lang: str | None = DEFAULT_LANG,
    ) -> dict[str, Any]:
        bounded = max(1, min(int(limit), MAX_LIMIT))
        started = time.monotonic()
        # Strip exchange-specific suffixes that don't appear on X.
        # "ETHUSDT" → search "ETH"; "AAPL" stays "AAPL"; free-text untouched.
        scraper_query = self._scrape_query(query)
        posts = self._scraper.search(
            query=scraper_query,
            limit=bounded,
            since=since,
            until=until,
            lang=lang,
        )
        scrape_seconds = time.monotonic() - started
        if not posts:
            return {
                "query": query,
                "post_count": 0,
                "scrape_seconds": round(scrape_seconds, 2),
                "warning": "no posts returned by any scraper backend",
                "scraper": self._scraper.diagnostics(),
            }
        # Bug #6 guard: below MIN_POSTS_FOR_VERDICT real posts the
        # classifier output is noise. Return an explicit insufficient_data
        # verdict so the UI doesn't declare "bullish" off 2 neutral tweets.
        if len(posts) < MIN_POSTS_FOR_VERDICT:
            return {
                "query": query,
                "post_count": len(posts),
                "scrape_seconds": round(scrape_seconds, 2),
                "verdict": "insufficient_data",
                "mood": "insufficient_data",
                "scores": {
                    "bullish_score_avg": 0.0,
                    "bullish_score_engagement_weighted": 0.0,
                    "confidence": 0.0,
                },
                "warning": (
                    f"only {len(posts)} post(s) scraped — need at least "
                    f"{MIN_POSTS_FOR_VERDICT} for a reliable verdict"
                ),
                "posts_seen": len(posts),
                "min_posts_for_verdict": MIN_POSTS_FOR_VERDICT,
                "scraper": self._scraper.diagnostics(),
            }
        analyses = self.classify([post.text for post in posts])
        if not analyses:
            return {
                "query": query,
                "post_count": 0,
                "scrape_seconds": round(scrape_seconds, 2),
                "warning": "scraper returned posts but classifier produced no rows",
            }
        return self._aggregate(query, posts, analyses, scrape_seconds, lang=lang)

    def _aggregate(
        self,
        query: str,
        posts: list[Post],
        analyses: list[dict[str, Any]],
        scrape_seconds: float,
        *,
        lang: str | None = None,
    ) -> dict[str, Any]:
        # The scraper may have de-duplicated empty texts so re-align by text.
        text_to_analysis: dict[str, dict[str, Any]] = {}
        for analysis in analyses:
            text_to_analysis.setdefault(analysis["text"], analysis)
        paired: list[tuple[Post, dict[str, Any]]] = []
        for post in posts:
            cleaned = clean_text(post.text)
            analysis = text_to_analysis.get(cleaned)
            if analysis:
                paired.append((post, analysis))
        if not paired:
            return {
                "query": query,
                "post_count": 0,
                "scrape_seconds": round(scrape_seconds, 2),
                "warning": "no post survived classifier alignment",
            }

        n = len(paired)
        sentiment_counts = Counter(a["sentiment"] for _, a in paired)
        emotion_counts = Counter(a["emotion"] for _, a in paired)
        topic_counts = Counter(a["topic"] for _, a in paired)

        sentiment_pct = {k: round(v / n * 100, 1) for k, v in sentiment_counts.items()}
        emotion_pct = {k: round(v / n * 100, 1) for k, v in emotion_counts.items()}
        topic_pct = {k: round(v / n * 100, 1) for k, v in topic_counts.items()}

        labels = self._label_maps.get("sentiment") or {}
        # Per FUNC-02 P0: the previous fallback computed
        # ``len(next(iter(labels.values()), "")) - 1``, which is the length of
        # the first label *value* string (e.g. len("negative")-1 = 7) and
        # raises IndexError when sentiment_probs has fewer than 8 classes.
        # Use the highest integer key as the fallback for "positive" and the
        # lowest for "negative" so a label rename doesn't kill the aggregator.
        positive_idx = next(
            (int(k) for k, v in labels.items() if str(v).lower() in {"positive", "bullish", "pos"}),
            max((int(k) for k in labels.keys()), default=0),
        )
        negative_idx = next(
            (int(k) for k, v in labels.items() if str(v).lower() in {"negative", "bearish", "neg"}),
            min((int(k) for k in labels.keys()), default=0),
        )

        avg_pos = statistics.mean(a["sentiment_probs"][positive_idx] for _, a in paired)
        avg_neg = statistics.mean(a["sentiment_probs"][negative_idx] for _, a in paired)
        bullish_score = round(avg_pos - avg_neg, 3)

        engagement_total = sum(p.likes + p.retweets + 1 for p, _ in paired)
        weighted_pos = sum(
            (p.likes + p.retweets + 1) * a["sentiment_probs"][positive_idx] for p, a in paired
        )
        weighted_neg = sum(
            (p.likes + p.retweets + 1) * a["sentiment_probs"][negative_idx] for p, a in paired
        )
        weighted_score = round(
            (weighted_pos - weighted_neg) / max(1, engagement_total),
            3,
        )

        confidence = round(
            (
                statistics.mean(a["sentiment_score"] for _, a in paired) * 0.6
                + min(1.0, math.log10(max(2, n)) / 2.5) * 0.4
            ),
            3,
        )

        if bullish_score > 0.18:
            mood = "bullish"
            mood_tr = "olumlu / boğa"
            mood_en = "bullish"
        elif bullish_score < -0.18:
            mood = "bearish"
            mood_tr = "olumsuz / ayı"
            mood_en = "bearish"
        else:
            mood = "mixed"
            mood_tr = "kararsız / nötr"
            mood_en = "mixed"

        examples: dict[str, list[dict[str, Any]]] = {}
        for kind in {a["sentiment"] for _, a in paired}:
            cands = [(p, a) for p, a in paired if a["sentiment"] == kind]
            cands.sort(key=lambda pa: pa[0].likes + pa[0].retweets, reverse=True)
            examples[kind] = [
                {
                    "user": p.user,
                    "text": p.text[:280],
                    "likes": p.likes,
                    "retweets": p.retweets,
                    "url": p.url,
                    "score": round(a["sentiment_score"], 3),
                    "emotion": a["emotion"],
                    "topic": a["topic"],
                    "date": p.date,
                }
                for p, a in cands[:3]
            ]

        avg_likes = statistics.mean(p.likes for p, _ in paired)
        avg_retweets = statistics.mean(p.retweets for p, _ in paired)

        dominant = {
            "sentiment": sentiment_counts.most_common(1)[0][0],
            "emotion": emotion_counts.most_common(1)[0][0],
            "topic": topic_counts.most_common(1)[0][0],
        }

        summary_tr = (
            f"'{query}' için son {n} paylaşımda baskın görüş {mood_tr}. "
            f"Sentiment dağılımı: {sentiment_pct}. "
            f"Engagement-ağırlıklı skor: {weighted_score} (-1..+1 aralığında). "
            f"En çok görülen duygu: {dominant['emotion']}. Baskın tema: {dominant['topic']}. "
            f"Güven: {confidence}."
        )
        # Per FUNC-02 P2/UI-INT-05: when caller asks lang="en" the UI
        # expects an English summary. Build it in parallel and let the
        # caller pick via the new ``summary`` key.
        summary_en = (
            f"For '{query}', the dominant view across the latest {n} posts is {mood_en}. "
            f"Sentiment distribution: {sentiment_pct}. "
            f"Engagement-weighted score: {weighted_score} (range -1..+1). "
            f"Most common emotion: {dominant['emotion']}. Dominant topic: {dominant['topic']}. "
            f"Confidence: {confidence}."
        )
        lang_normalized = (lang or "tr").strip().lower()
        summary = summary_en if lang_normalized.startswith("en") else summary_tr

        return {
            "query": query,
            "post_count": n,
            "scrape_seconds": round(scrape_seconds, 2),
            # Honest freshness marker: the wall-clock instant THIS response was
            # served / analysis completed. The underlying search-engine tweet-ID
            # list may itself be cached up to ~30 min (see x_spontaneous.py
            # cache_ttl) — `fetched_at` is the served time, NOT a guarantee that
            # every post is brand new. `scrape_seconds` above is processing
            # duration (scrape + classify), not data age.
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "device": self._device,
            "model_dir": str(self._model_dir) if self._model_dir else None,
            "summary": summary,
            "summary_tr": summary_tr,
            "summary_en": summary_en,
            "mood": mood,
            "scores": {
                "bullish_score_avg": bullish_score,
                "bullish_score_engagement_weighted": weighted_score,
                "confidence": confidence,
            },
            "distributions": {
                "sentiment_pct": sentiment_pct,
                "emotion_pct": emotion_pct,
                "topic_pct": topic_pct,
            },
            "dominant": dominant,
            "engagement": {
                "avg_likes": round(avg_likes, 1),
                "avg_retweets": round(avg_retweets, 1),
                "total_likes": sum(p.likes for p, _ in paired),
                "total_retweets": sum(p.retweets for p, _ in paired),
            },
            "examples": examples,
        }

    # ---- Symbol-level helpers (used by DES/TOP/NI/CN chips) ----
    def symbol_chip(
        self,
        symbol: str,
        limit: int = 60,
        since: str | None = None,
        lang: str | None = DEFAULT_LANG,
    ) -> dict[str, Any]:
        query = self._symbol_query(symbol)
        analysis = self.analyze_topic(query=query, limit=limit, since=since, lang=lang)
        # Bug #6: insufficient_data shape lacks summary_tr/distributions/etc.,
        # so handle it the same way as post_count==0 — chip stays non-ok.
        if analysis.get("post_count", 0) == 0 or analysis.get("verdict") == "insufficient_data":
            return {
                "symbol": symbol,
                "ok": False,
                "post_count": analysis.get("post_count", 0),
                "warning": analysis.get("warning") or "no posts",
                "verdict": analysis.get("verdict"),
            }
        return {
            "symbol": symbol,
            "ok": True,
            "post_count": analysis["post_count"],
            "mood": analysis["mood"],
            "summary_tr": analysis["summary_tr"],
            "bullish_score": analysis["scores"]["bullish_score_engagement_weighted"],
            "confidence": analysis["scores"]["confidence"],
            "dominant": analysis["dominant"],
            "distributions": analysis["distributions"],
            "examples": analysis["examples"],
        }

    @staticmethod
    def _symbol_query(symbol: str) -> str:
        sym = (symbol or "").strip().upper()
        if not sym:
            return ""
        # Plain ticker query: search engines + syndication match all forms
        # (cashtag, hashtag, bare). Operator-heavy queries fail in Brave/DDG.
        if re.match(r"^[A-Z]{1,6}$", sym):
            return sym
        if sym.endswith("USDT"):
            return sym[:-4]
        if sym.endswith("USD"):
            return sym[:-3]
        return sym

    @staticmethod
    def _scrape_query(query: str) -> str:
        """Normalize a free-form analyze_topic query the same way symbol_chip
        normalizes a ticker — strips USDT/USD suffixes, plain-text otherwise.
        """
        text = (query or "").strip()
        if not text:
            return ""
        # Single-token queries that look like an exchange-suffixed pair
        if re.fullmatch(r"[A-Za-z]{1,6}(?:USDT|USD)", text):
            return XAnalyzer._symbol_query(text)
        return text

    # ---- Instant feed mapping ----
    def analyze_topic_as_instant_events(
        self,
        symbol: str | None = None,
        query: str | None = None,
        limit: int = 60,
        since: str | None = None,
        lang: str | None = DEFAULT_LANG,
    ) -> dict[str, Any]:
        if not query:
            query = self._symbol_query(symbol or "")
        if not query:
            return {"ok": False, "events": [], "warning": "query required"}
        result = self.analyze_topic(query=query, limit=limit, since=since, lang=lang)
        # Bug #6: an insufficient_data verdict has no examples / summary so it
        # cannot produce INSTANT events. Treat the same as zero-post path.
        if result.get("post_count", 0) == 0 or result.get("verdict") == "insufficient_data":
            return {
                "ok": False,
                "events": [],
                "warning": result.get("warning") or "no posts",
                "summary_tr": result.get("summary_tr"),
                "verdict": result.get("verdict"),
            }

        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        now = datetime.now(timezone.utc)
        examples = result.get("examples") or {}

        # The aggregate examples already include the highest-engagement tweet
        # per sentiment bucket; promoting them straight to the INSTANT feed
        # keeps the cross-pane signal-to-noise ratio reasonable.
        for sentiment_label, items in examples.items():
            for item in items:
                key = item.get("url") or item.get("text") or ""
                if not key or key in seen:
                    continue
                seen.add(key)
                score = item.get("score") or 0.0
                priority = _instant_priority_score(sentiment_label, score, item)
                label = _instant_priority_label(priority)
                events.append(
                    {
                        "id": None,
                        "dedupe_key": _dedupe_key(item, sentiment_label, query),
                        "source_id": INSTANT_SOURCE_ID,
                        "source_name": INSTANT_SOURCE_NAME,
                        "source_category": INSTANT_SOURCE_CATEGORY,
                        "source_region": INSTANT_SOURCE_REGION,
                        "official_url": "https://x.com/search?q=" + query,
                        "title": (
                            f"@{item.get('user') or 'x'} · "
                            f"{sentiment_label} · {item.get('emotion','')}"
                        ),
                        "link": item.get("url") or "https://x.com/" + (item.get("user") or ""),
                        "summary": item.get("text", ""),
                        "generated_summary": (
                            f"{INSTANT_SOURCE_NAME} for {query}: {sentiment_label} "
                            f"(score {round(score, 2)}, emotion {item.get('emotion','?')})."
                        ),
                        "priority_score": priority,
                        "priority_label": label,
                        "matched_keywords": [k for k in [symbol, item.get("topic")] if k],
                        "calendar_window": None,
                        "published_at": item.get("date") or now.isoformat(),
                        "fetched_at": now.isoformat(),
                        "latency_seconds": None,
                        "metadata": {
                            "kind": "x_sentiment_example",
                            "sentiment": sentiment_label,
                            "topic": item.get("topic"),
                            "engagement": (item.get("likes", 0) or 0) + (item.get("retweets", 0) or 0),
                            "query": query,
                        },
                    }
                )

        # Always also emit one "summary" event so the feed shows the rolling mood.
        weighted = result.get("scores", {}).get("bullish_score_engagement_weighted") or 0.0
        priority = _instant_priority_score(result.get("mood", "mixed"), abs(weighted), {})
        events.append(
            {
                "id": None,
                "dedupe_key": f"x-summary::{query}",
                "source_id": INSTANT_SOURCE_ID,
                "source_name": INSTANT_SOURCE_NAME,
                "source_category": INSTANT_SOURCE_CATEGORY,
                "source_region": INSTANT_SOURCE_REGION,
                "official_url": "https://x.com/search?q=" + query,
                "title": (
                    f"X mood for {symbol or query}: "
                    f"{result.get('mood', 'mixed')} ({weighted:+.2f})"
                ),
                "link": "https://x.com/search?q=" + query,
                "summary": result.get("summary_tr", ""),
                "generated_summary": result.get("summary_tr", ""),
                "priority_score": priority,
                "priority_label": _instant_priority_label(priority),
                "matched_keywords": [symbol] if symbol else [],
                "calendar_window": None,
                "published_at": now.isoformat(),
                "fetched_at": now.isoformat(),
                "latency_seconds": result.get("scrape_seconds"),
                "metadata": {
                    "kind": "x_sentiment_summary",
                    "post_count": result.get("post_count"),
                    "distributions": result.get("distributions"),
                    "dominant": result.get("dominant"),
                    "query": query,
                },
            }
        )
        events.sort(key=lambda e: e.get("priority_score") or 0, reverse=True)
        return {
            "ok": True,
            "events": events,
            "transport": "x_sentiment",
            "warning": result.get("warning"),
        }


def _instant_priority_score(sentiment: str, score: float, item: dict[str, Any]) -> int:
    label = (sentiment or "").lower()
    base = 50
    if label in {"positive", "bullish"}:
        base = 70
    elif label in {"negative", "bearish"}:
        base = 78  # bad news travels faster
    elif label in {"neutral", "mixed"}:
        base = 45
    base += int(min(20, max(0, abs(score) * 25)))
    engagement = (item.get("likes") or 0) + (item.get("retweets") or 0)
    if engagement > 1000:
        base += 6
    elif engagement > 200:
        base += 3
    return max(0, min(100, base))


def _instant_priority_label(score: int) -> str:
    if score >= 75:
        return "breaking"
    if score >= 58:
        return "watch"
    if score >= 40:
        return "low"
    return "mute"


def _dedupe_key(item: dict[str, Any], sentiment: str, query: str) -> str:
    base = item.get("url") or item.get("text") or ""
    return f"x::{sentiment}::{query}::{abs(hash(base)) % 10**12}"


__all__ = ["XAnalyzer", "find_model_dir"]
