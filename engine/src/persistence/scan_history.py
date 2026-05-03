"""Rolling auto-scan history (last 10 scans, ≤24 h old) — cumulative scoring.

Persists to runtime/scan_history.json. Hot-reloaded on every read; written
atomically on append.

Each scan entry: {timestamp: ISO UTC, results: [...top10 cross_ranked dict...]}
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("persistence.scan_history")

DEFAULT_PATH = "runtime/scan_history.json"
MAX_SCANS = 10
MAX_AGE_HOURS = 24


class ScanHistoryStore:
    """Maintains the last MAX_SCANS scans (≤ MAX_AGE_HOURS old) for cumulative scoring."""

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._scans: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._scans = []
            return
        try:
            data = json.loads(self.path.read_text())
            scans = data.get("scans", []) if isinstance(data, dict) else []
            self._scans = self._prune(scans)
        except Exception as e:
            logger.warning(f"scan_history load failed: {e}")
            self._scans = []

    def _save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"scans": self._scans}, default=str, indent=2))
            tmp.replace(self.path)
        except Exception as e:
            logger.warning(f"scan_history save failed: {e}")

    @staticmethod
    def _prune(scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop scans older than MAX_AGE_HOURS, keep at most MAX_SCANS most recent."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
        valid: list[dict[str, Any]] = []
        for s in scans:
            ts = s.get("timestamp")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    valid.append(s)
            except Exception:
                continue
        valid.sort(key=lambda s: s["timestamp"], reverse=True)
        return valid[:MAX_SCANS]

    def append(self, results: list[dict[str, Any]], timestamp: str | None = None) -> None:
        """Add a scan to the history. Timestamp defaults to now (UTC)."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        # Trim per-scan results to keep storage bounded — top 50 is plenty
        trimmed = [
            {
                "symbol": r.get("symbol"),
                "net_nss": float(r.get("net_nss", r.get("total_nss", 0)) or 0),
                "buy_nss": float(r.get("buy_nss", 0) or 0),
                "sell_nss": float(r.get("sell_nss", 0) or 0),
                "dominant_dir": r.get("dominant_dir", "N/A"),
                "count": int(r.get("count", 0) or 0),
                "best_conf": int(r.get("best_conf", 0) or 0),
                "price": float(r.get("price", 0) or 0),
            }
            for r in (results or [])[:50]
        ]
        with self._lock:
            self._scans.insert(0, {"timestamp": ts, "results": trimmed})
            self._scans = self._prune(self._scans)
            self._save()

    def get_scans(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._scans)

    def saturation(self) -> dict[str, int]:
        """Return {filled, max} where filled is non-stale scans count."""
        with self._lock:
            return {"filled": len(self._scans), "max": MAX_SCANS}

    def is_full(self) -> bool:
        with self._lock:
            return len(self._scans) >= MAX_SCANS

    def cumulative_ranking(self, top_n: int = 10) -> list[dict[str, Any]]:
        """Sum each coin's net_nss across all stored scans.

        Coins not appearing in a scan contribute 0 for that scan. Returns top N
        sorted by total_score descending.
        """
        with self._lock:
            scans = list(self._scans)

        if not scans:
            return []

        agg: dict[str, dict[str, Any]] = {}
        for s in scans:
            for r in s.get("results", []):
                sym = r.get("symbol")
                if not sym:
                    continue
                if sym not in agg:
                    agg[sym] = {
                        "symbol": sym,
                        "total_score": 0.0,
                        "buy_score_sum": 0.0,
                        "sell_score_sum": 0.0,
                        "appearances": 0,
                        "best_conf": 0,
                        "last_price": 0.0,
                        "dir_counts": {"BUY": 0, "SELL": 0, "N/A": 0},
                    }
                a = agg[sym]
                # signed contribution: BUY → positive, SELL → negative
                # so a coin appearing 5x BUY ranks above one with mixed directions
                signed = float(r.get("net_nss", 0))
                dom = r.get("dominant_dir", "N/A")
                if dom == "SELL":
                    signed = -abs(signed)
                else:
                    signed = abs(signed)
                a["total_score"] += signed
                a["buy_score_sum"] += float(r.get("buy_nss", 0) or 0)
                a["sell_score_sum"] += float(r.get("sell_nss", 0) or 0)
                a["appearances"] += 1
                bc = int(r.get("best_conf", 0) or 0)
                if bc > a["best_conf"]:
                    a["best_conf"] = bc
                last_p = float(r.get("price", 0) or 0)
                if last_p > 0:
                    a["last_price"] = last_p
                a["dir_counts"][dom if dom in a["dir_counts"] else "N/A"] += 1

        # Final fields
        ranked: list[dict[str, Any]] = []
        for sym, a in agg.items():
            counts = a["dir_counts"]
            if counts["BUY"] > counts["SELL"]:
                dom = "BUY"
            elif counts["SELL"] > counts["BUY"]:
                dom = "SELL"
            else:
                dom = counts.get("N/A", 0) and "N/A" or "BUY"
            avg = a["total_score"] / max(1, a["appearances"])
            ranked.append({
                "symbol": sym,
                "total_score": round(a["total_score"], 2),
                "abs_total_score": round(abs(a["total_score"]), 2),
                "appearances": a["appearances"],
                "max_appearances": len(scans),
                "avg_score": round(avg, 2),
                "best_conf": a["best_conf"],
                "last_price": a["last_price"],
                "dominant_dir": dom,
            })

        # Sort by absolute total score descending — direction doesn't matter for ranking
        ranked.sort(key=lambda x: x["abs_total_score"], reverse=True)
        return ranked[:top_n]

    def clear(self) -> None:
        with self._lock:
            self._scans = []
            self._save()
