"""Rule-based NL → StrategySpec parser.

Sub-system J. NOT a real LLM — pattern matching on common TR+EN phrasings.
Returns a partial StrategySpec dict + notes, never raises.
"""
from __future__ import annotations

import re
from typing import Any


_KNOWN_INDICATORS = {
    "rsi": ("rsi", "rsi14"),
    "macd": ("macd", "macd"),
    "ema": ("ema", "ema20"),
    "sma": ("sma", "sma20"),
    "bollinger": ("bollinger_bands", "bb"),
    "stochastic": ("stochastic", "stoch"),
    "stoch": ("stochastic", "stoch"),
    "atr": ("atr", "atr14"),
    "adx": ("adx", "adx14"),
    "cci": ("cci", "cci20"),
    "obv": ("obv", "obv"),
    "williams": ("williams_r", "willr"),
    "vwap": ("vwap", "vwap"),
    "ichimoku": ("ichimoku", "kijun"),
    "psar": ("parabolic_sar", "psar"),
    "kdj": ("kdj", "kdj"),
}

_SYMBOL_RE = re.compile(r"\b([A-Z]{2,8}/[A-Z]{2,8})\b")
_TIMEFRAME_RE = re.compile(r"\b(1m|5m|15m|30m|1h|2h|4h|6h|1d|1w)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _find_indicator(text_low: str) -> tuple[str, str] | None:
    for keyword, (ind_id, alias) in _KNOWN_INDICATORS.items():
        if keyword in text_low:
            return (ind_id, alias)
    return None


def _extract_numbers(s: str) -> list[float]:
    return [float(m) for m in _NUMBER_RE.findall(s)]


def _number_near(text: str, text_low: str, patterns: list[str]) -> float | None:
    """Find a number near any of ``patterns`` in ``text_low``.

    The number can be on either side of the keyword (TR: "30 altında",
    EN: "below 30"). We pick whichever number is closest to the keyword
    in character distance.
    """
    for pat in patterns:
        idx = text_low.find(pat)
        if idx < 0:
            continue
        pat_end = idx + len(pat)
        # Find all number positions in the source text.
        best: tuple[int, float] | None = None  # (distance, value)
        for m in _NUMBER_RE.finditer(text):
            n_start, n_end = m.span()
            if n_end <= idx:
                dist = idx - n_end
            elif n_start >= pat_end:
                dist = n_start - pat_end
            else:
                dist = 0
            if best is None or dist < best[0]:
                best = (dist, float(m.group(1)))
        if best is not None:
            return best[1]
    return None


def parse_request(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse a natural-language strategy request.

    Returns (spec_dict, notes). spec_dict is None when no indicator
    is recognised. Notes always populated with guidance.
    """
    notes: list[str] = []
    if not text or not text.strip():
        return None, ["Boş istek. Bir indikatör adı (RSI, MACD, EMA, ...) + koşullar yaz."]
    text_low = text.lower()

    ind = _find_indicator(text_low)
    if ind is None:
        return None, [
            "Tanınan bir indikatör bulunamadı. Mesajına şu indikatörlerden birini ekle:",
            "RSI, MACD, EMA, SMA, Bollinger, Stochastic, ATR, ADX, CCI, OBV, Williams, VWAP, Ichimoku, PSAR, KDJ",
        ]
    ind_id, alias = ind

    # Symbol
    symbols: list[str] = []
    for m in _SYMBOL_RE.findall(text):
        symbols.append(m)
    if not symbols:
        for word in ("btc", "eth", "sol", "doge", "bitcoin", "ethereum", "solana"):
            if word in text_low:
                if word in ("btc", "bitcoin"): symbols.append("BTC/USDT")
                elif word in ("eth", "ethereum"): symbols.append("ETH/USDT")
                elif word in ("sol", "solana"): symbols.append("SOL/USDT")
                elif word == "doge": symbols.append("DOGE/USDT")
                break

    # Timeframe
    tf_match = _TIMEFRAME_RE.search(text)
    timeframe = tf_match.group(1).lower() if tf_match else "1h"

    # Build base spec
    spec: dict[str, Any] = {
        "name": f"NL: {ind_id}",
        "description": text[:200],
        "timeframe": timeframe,
        "indicators": [{"alias": alias, "id": ind_id, "params": {}}],
        "entry_rules": [],
        "entry_logic": "all",
        "exit_rules": [],
        "exit_logic": "any",
        "position": {"side": "long", "sizing_kind": "fixed_quote",
                     "sizing_value": 100, "stop_loss_pct": 2.0},
    }
    if symbols:
        spec["asset_filter"] = {"symbols": symbols}

    # Threshold extraction for momentum indicators
    nums = _extract_numbers(text)
    # Patterns: "RSI X altında" / "RSI X üstünde" / "above X" / "below X" / "<X" / ">X"
    below_patterns = ["altında", "altinda", "below", "under", " < ", "altında al", "düşünce"]
    above_patterns = ["üstünde", "ustunde", "above", "over", " > ", "üstünde sat", "geçince"]

    # Try to find numbers near "below"/"above" keywords. TR phrasing
    # ("30 altında") puts the number BEFORE the keyword; EN ("below 30")
    # puts it AFTER. `_number_near` accepts either side.
    entry_threshold = _number_near(text, text_low, below_patterns)
    exit_threshold = _number_near(text, text_low, above_patterns)

    # Indicator-specific defaults
    if ind_id == "rsi":
        if entry_threshold is None and exit_threshold is None and nums:
            # Just numbers — assume oversold/overbought
            if len(nums) >= 2:
                entry_threshold = min(nums[0], nums[1])
                exit_threshold = max(nums[0], nums[1])
        spec["indicators"][0]["params"] = {"period": 14}
        if entry_threshold is not None:
            spec["entry_rules"].append({
                "kind": "crosses_below", "left": alias,
                "right": f"literal:{entry_threshold}",
            })
            notes.append(f"Entry: {alias} {entry_threshold} altına düşünce")
        if exit_threshold is not None:
            spec["exit_rules"].append({
                "kind": "crosses_above", "left": alias,
                "right": f"literal:{exit_threshold}",
            })
            notes.append(f"Exit: {alias} {exit_threshold} üstüne çıkınca")
        if not spec["entry_rules"]:
            # Provide a default suggestion
            spec["entry_rules"].append({
                "kind": "crosses_below", "left": alias, "right": "literal:30",
            })
            spec["exit_rules"].append({
                "kind": "crosses_above", "left": alias, "right": "literal:70",
            })
            notes.append("Eşik bulunamadı — varsayılan 30/70 kullanıldı")

    elif ind_id == "macd":
        spec["indicators"][0]["params"] = {
            "fast_period": 12, "slow_period": 26, "signal_period": 9,
        }
        spec["entry_rules"].append({
            "kind": "crosses_above", "left": alias, "right": "literal:0",
        })
        spec["exit_rules"].append({
            "kind": "crosses_below", "left": alias, "right": "literal:0",
        })
        notes.append("MACD sıfır çizgisi cross — klasik trend giriş/çıkış")

    elif ind_id == "ema":
        period = int(nums[0]) if nums else 20
        spec["indicators"] = [
            {"alias": "ema_short", "id": "ema", "params": {"period": period}},
            {"alias": "ema_long", "id": "ema", "params": {"period": period * 3}},
        ]
        spec["entry_rules"].append({
            "kind": "crosses_above", "left": "ema_short", "right": "ema_long",
        })
        spec["exit_rules"].append({
            "kind": "crosses_below", "left": "ema_short", "right": "ema_long",
        })
        notes.append(f"EMA({period}) ve EMA({period*3}) crossover")

    else:
        # Generic: just use the indicator without strong rules
        spec["entry_rules"].append({
            "kind": "greater_than", "left": "close", "right": alias,
        })
        spec["exit_rules"].append({
            "kind": "less_than", "left": "close", "right": alias,
        })
        notes.append(f"Genel kalıp: close > {alias} ile alım, < ile çıkış — STRA panelinde özelleştir")

    notes.insert(0, f"Tanınan indikatör: {ind_id} (alias={alias})")
    if symbols:
        notes.append(f"Tanınan sembol(ler): {', '.join(symbols)}")
    notes.append(f"Timeframe: {timeframe}")

    return spec, notes
