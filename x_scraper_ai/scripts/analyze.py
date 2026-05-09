"""
showMe X Scraper AI - Analiz orkestrasyonu.

Verilen bir konu/hisse/sorgu icin:
  1) X'te gercek paylasimlari toplar (x_scraper.XScraper)
  2) Multi-task model ile her paylasimi analiz eder (sentiment/emotion/topic)
  3) Toplulastirilmis metrikleri ve dogal dilde gorus ozeti dondurur

CLI kullanim:
    python analyze.py "AAPL" --limit 200 --since 2026-04-01

API kullanim:
    from analyze import ShowMeXAnalyzer
    a = ShowMeXAnalyzer(model_dir="../model/showme_x_v1")
    out = a.analyze_topic("AAPL", limit=200)
"""
from __future__ import annotations
import os, sys, json, statistics, math
from collections import Counter
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from x_scraper import XScraper, Post  # noqa


class ShowMeXAnalyzer:
    """X paylasimlarini cek + AI ile analiz et + toplu metrik uret."""

    def __init__(self, model_dir: str | Path):
        self.model_dir = Path(model_dir)
        self._load_model()
        self.scraper = XScraper()

    def _load_model(self):
        import torch, torch.nn as nn
        from transformers import AutoTokenizer, AutoModel
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir / "tokenizer"))
        self.backbone  = AutoModel.from_pretrained(str(self.model_dir / "backbone"))
        ckpt = torch.load(str(self.model_dir / "heads.pt"), map_location="cpu")
        meta = ckpt["meta"]
        h = self.backbone.config.hidden_size
        self.sent_head = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_sentiment"]))
        self.emo_head  = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_emotion"]))
        self.top_head  = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, meta["n_topic"]))
        self.sent_head.load_state_dict(ckpt["sent_head"])
        self.emo_head.load_state_dict(ckpt["emotion_head"])
        self.top_head.load_state_dict(ckpt["topic_head"])
        self.label_maps = json.load(open(str(self.model_dir / "label_maps.json")))
        for m in [self.backbone, self.sent_head, self.emo_head, self.top_head]:
            m.eval()
        self._torch = torch

    def _label(self, kind: str, idx: int):
        m = self.label_maps.get(kind)
        if not m: return str(idx)
        return m.get(str(idx), m.get(idx, str(idx)))

    def _classify(self, texts: list[str], batch_size: int = 32) -> list[dict]:
        torch = self._torch
        results = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i+batch_size]
            with torch.no_grad():
                enc = self.tokenizer(chunk, truncation=True, padding=True,
                                     max_length=128, return_tensors="pt")
                out = self.backbone(**enc)
                cls = out.last_hidden_state[:, 0]
                s = torch.softmax(self.sent_head(cls), -1)
                e = torch.softmax(self.emo_head(cls), -1)
                t = torch.softmax(self.top_head(cls), -1)
            for j in range(len(chunk)):
                si, ei, ti = int(s[j].argmax()), int(e[j].argmax()), int(t[j].argmax())
                results.append({
                    "sentiment": self._label("sentiment", si),
                    "sentiment_score": float(s[j, si]),
                    "emotion": self._label("emotion", ei),
                    "emotion_score": float(e[j, ei]),
                    "topic": self._label("topic", ti),
                    "topic_score": float(t[j, ti]),
                    "sent_probs": [float(x) for x in s[j].tolist()],
                    "emo_probs":  [float(x) for x in e[j].tolist()],
                })
        return results

    def analyze_topic(self, query: str, limit: int = 200,
                      since: Optional[str] = None, until: Optional[str] = None,
                      lang: Optional[str] = "en") -> dict:
        """Bir konu hakkinda X paylasimlari cek + analiz et + ozet uret."""
        posts = self.scraper.search(query, limit=limit, since=since, until=until, lang=lang)
        if not posts:
            return {"query": query, "post_count": 0, "error": "Hic paylasim bulunamadi."}

        texts = [p.text for p in posts]
        analyses = self._classify(texts)

        # Aggregations
        sent_counts = Counter(a["sentiment"] for a in analyses)
        emo_counts  = Counter(a["emotion"]   for a in analyses)
        top_counts  = Counter(a["topic"]     for a in analyses)

        n = len(analyses)
        sent_pct = {k: round(v/n*100, 1) for k, v in sent_counts.items()}
        emo_pct  = {k: round(v/n*100, 1) for k, v in emo_counts.items()}
        top_pct  = {k: round(v/n*100, 1) for k, v in top_counts.items()}

        # Bullish/bearish skoru: P(positive) - P(negative)
        avg_pos = statistics.mean(a["sent_probs"][2] for a in analyses) if analyses[0]["sent_probs"] else 0
        avg_neg = statistics.mean(a["sent_probs"][0] for a in analyses) if analyses[0]["sent_probs"] else 0
        bullish_score = round((avg_pos - avg_neg), 3)  # -1..+1

        # Dominant emotion + top topic
        dom_sent  = sent_counts.most_common(1)[0][0]
        dom_emo   = emo_counts.most_common(1)[0][0]
        dom_topic = top_counts.most_common(1)[0][0]

        # Engagement ag.
        avg_likes    = statistics.mean(p.likes for p in posts)
        avg_retweets = statistics.mean(p.retweets for p in posts)
        sum_likes    = sum(p.likes for p in posts)
        sum_retweets = sum(p.retweets for p in posts)

        # Confidence agirlikli sentiment - high engagement * confidence
        weighted_pos = sum((p.likes + p.retweets + 1) * a["sent_probs"][2]
                           for p, a in zip(posts, analyses))
        weighted_neg = sum((p.likes + p.retweets + 1) * a["sent_probs"][0]
                           for p, a in zip(posts, analyses))
        weighted_score = round((weighted_pos - weighted_neg) /
                                max(1, sum(p.likes + p.retweets + 1 for p in posts)), 3)

        # Ornek paylasimlar (sentiment basina)
        examples = {}
        for kind in ["positive", "neutral", "negative"]:
            cands = [(p, a) for p, a in zip(posts, analyses) if a["sentiment"] == kind]
            cands.sort(key=lambda x: x[0].likes + x[0].retweets, reverse=True)
            examples[kind] = [{"user": p.user, "text": p.text[:240], "likes": p.likes,
                               "retweets": p.retweets, "url": p.url, "score": a["sentiment_score"]}
                              for p, a in cands[:3]]

        # Dogal dilde ozet (Turkce)
        if bullish_score > 0.15:
            mood = "olumlu"
        elif bullish_score < -0.15:
            mood = "olumsuz"
        else:
            mood = "notr/karisik"

        summary_tr = (
            f"'{query}' icin son {n} paylasimda baskin gorus {mood}. "
            f"Sentiment dagilimi: {sent_pct}. "
            f"Engagement-agirlikli skor: {weighted_score} (-1..+1 araliginda). "
            f"En cok gorulen duygu: {dom_emo}. Baskin tema: {dom_topic}."
        )

        return {
            "query": query,
            "post_count": n,
            "summary_tr": summary_tr,
            "scores": {
                "bullish_score_avg": bullish_score,
                "bullish_score_engagement_weighted": weighted_score,
            },
            "distributions": {
                "sentiment_pct": sent_pct,
                "emotion_pct":   emo_pct,
                "topic_pct":     top_pct,
            },
            "dominant": {
                "sentiment": dom_sent,
                "emotion":   dom_emo,
                "topic":     dom_topic,
            },
            "engagement": {
                "avg_likes": round(avg_likes, 1),
                "avg_retweets": round(avg_retweets, 1),
                "total_likes": sum_likes,
                "total_retweets": sum_retweets,
            },
            "examples": examples,
        }


# ----- Dogal dil sorgu yorumlayici (basit kural tabanli) -----
def parse_natural_language_request(req: str) -> dict:
    """Kullanicinin '$AAPL hakkinda son 24 saatte bullish mi?' gibi
    sorgusunu parselle: subject + metric + time."""
    req_l = req.lower()
    out = {"raw": req}
    # Subject: $TICKER veya kelimeler
    m = re.search(r"\$([A-Za-z]{1,6})", req)
    if m:
        out["subject"] = m.group(1).upper()
    else:
        # En son onemli kelimeyi dene
        words = re.findall(r"\b[A-Z][A-Z0-9]+\b", req)
        if words: out["subject"] = words[0]
    # Metric
    if any(k in req_l for k in ["bullish", "boga", "yukselis"]):     out["metric"] = "bullish"
    elif any(k in req_l for k in ["bearish", "ayi", "dusus"]):       out["metric"] = "bearish"
    elif any(k in req_l for k in ["duygu", "sentiment", "his"]):     out["metric"] = "sentiment"
    elif any(k in req_l for k in ["panik", "kork", "fear"]):         out["metric"] = "fear"
    elif any(k in req_l for k in ["guven", "umit", "optimism"]):     out["metric"] = "optimism"
    elif any(k in req_l for k in ["ofke", "kizgin", "anger"]):       out["metric"] = "anger"
    else:                                                              out["metric"] = "summary"
    # Time
    if any(k in req_l for k in ["bugun", "today", "24"]):            out["time"] = "1d"
    elif any(k in req_l for k in ["hafta", "week"]):                  out["time"] = "7d"
    elif any(k in req_l for k in ["ay", "month"]):                    out["time"] = "30d"
    else:                                                              out["time"] = "7d"
    return out


import re  # parse_natural_language icin
import datetime as dt

def time_to_since(time_key: str) -> str:
    days = {"1d": 1, "7d": 7, "30d": 30}.get(time_key, 7)
    return (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%d")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("query", help="Konu/hisse/sorgu")
    p.add_argument("--model-dir", default=str(HERE.parent / "model" / "showme_x_v1"))
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--since", default=None)
    p.add_argument("--until", default=None)
    p.add_argument("--lang", default="en")
    p.add_argument("--natural", action="store_true",
                   help="Sorguyu dogal dil olarak yorumla")
    args = p.parse_args()

    a = ShowMeXAnalyzer(model_dir=args.model_dir)

    if args.natural:
        parsed = parse_natural_language_request(args.query)
        print(f"Yorumlanmis sorgu: {parsed}")
        subject = parsed.get("subject", args.query)
        since = time_to_since(parsed.get("time", "7d"))
        result = a.analyze_topic(subject, limit=args.limit, since=since, lang=args.lang)
    else:
        result = a.analyze_topic(args.query, limit=args.limit,
                                 since=args.since, until=args.until, lang=args.lang)
    print(json.dumps(result, ensure_ascii=False, indent=2))
