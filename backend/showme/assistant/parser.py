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

# Curated map of concepts the parser CANNOT model → human label for the
# honesty note. Each entry is (display_label, [keyword, ...]). Detected
# concepts are echoed back verbatim as "ignored" so the user is never
# misled into thinking a phrase was understood. Keep this list curated and
# every branch tested — do NOT claim to support any of these.
_IGNORED_CONCEPTS: list[tuple[str, tuple[str, ...]]] = [
    ("divergence", ("divergence", "diverjans", "uyumsuzluk")),
    ("stop-loss / take-profit", (
        "stop loss", "stop-loss", "stoploss", "take profit", "take-profit",
        "takeprofit", "kar al", "zarar durdur",
    )),
    ("risk / pozisyon boyutlandırma", (
        "% risk", "per trade", "sizing", "pozisyon büyüklüğü",
        "pozisyon buyuklugu", "kelly", "risk yönetimi", "risk yonetimi",
    )),
    ("trailing stop", ("trailing", "iz süren", "iz suren")),
    ("mum / fiyat formasyonu", (
        "pattern", "engulfing", "breakout", "kırılım", "kirilim",
        "candlestick", "mum formasyonu",
    )),
]

# Word-boundary-sensitive ignored concepts: short tokens (sl/tp/risk/mum)
# that would false-positive as substrings (e.g. "sl" in "alt_close").
# Matched against tokenised words instead of raw substring.
_IGNORED_CONCEPTS_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("stop-loss / take-profit", ("sl", "tp")),
    ("risk / pozisyon boyutlandırma", ("risk",)),
    ("mum / fiyat formasyonu", ("mum",)),
]


def _find_indicator(text_low: str) -> tuple[str, str] | None:
    for keyword, (ind_id, alias) in _KNOWN_INDICATORS.items():
        if keyword in text_low:
            return (ind_id, alias)
    return None


def _all_matched_indicators(text_low: str) -> list[str]:
    """Distinct indicator ids whose keyword appears in the text, in
    keyword-table order. Used to detect multi-indicator sentences where
    only the first is actually wired into the spec."""
    seen: list[str] = []
    for keyword, (ind_id, _alias) in _KNOWN_INDICATORS.items():
        if keyword in text_low and ind_id not in seen:
            seen.append(ind_id)
    return seen


def _detect_ignored(text_low: str) -> list[str]:
    """Return display labels for known-but-UNSUPPORTED concepts present in
    the text. Each label is returned at most once."""
    found: list[str] = []
    for label, keywords in _IGNORED_CONCEPTS:
        if label in found:
            continue
        if any(kw in text_low for kw in keywords):
            found.append(label)
    words = set(re.findall(r"[a-zçğıöşü%]+", text_low))
    for label, tokens in _IGNORED_CONCEPTS_WORDS:
        if label in found:
            continue
        if any(tok in words for tok in tokens):
            found.append(label)
    return found


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
                if word in ("btc", "bitcoin"):
                    symbols.append("BTC/USDT")
                elif word in ("eth", "ethereum"):
                    symbols.append("ETH/USDT")
                elif word in ("sol", "solana"):
                    symbols.append("SOL/USDT")
                elif word == "doge":
                    symbols.append("DOGE/USDT")
                break

    # Timeframe — track whether it was parsed or defaulted so we can be
    # honest about it in the notes (B2).
    tf_match = _TIMEFRAME_RE.search(text)
    timeframe = tf_match.group(1).lower() if tf_match else "1h"
    timeframe_defaulted = tf_match is None

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
        # B3 — two-number EMA fix. Previously the second number ("EMA 20 50")
        # was silently dropped and the long period hardcoded to period*3.
        # Now: ≥2 numbers → use nums[0]/nums[1]; 1 → period + period*3; 0 → 20/60.
        if len(nums) >= 2:
            short_p = int(nums[0])
            long_p = int(nums[1])
            ema_from_input = True
        elif len(nums) == 1:
            short_p = int(nums[0])
            long_p = short_p * 3
            ema_from_input = False
        else:
            short_p = 20
            long_p = 60
            ema_from_input = False
        spec["indicators"] = [
            {"alias": "ema_short", "id": "ema", "params": {"period": short_p}},
            {"alias": "ema_long", "id": "ema", "params": {"period": long_p}},
        ]
        spec["entry_rules"].append({
            "kind": "crosses_above", "left": "ema_short", "right": "ema_long",
        })
        spec["exit_rules"].append({
            "kind": "crosses_below", "left": "ema_short", "right": "ema_long",
        })
        if ema_from_input:
            notes.append(f"EMA({short_p}) ve EMA({long_p}) crossover (her iki periyot da girişten alındı)")
        else:
            notes.append(f"EMA({short_p}) ve EMA({long_p}) crossover (uzun periyot varsayıldı)")

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

    # B2 — honest timeframe note: distinguish parsed vs defaulted.
    if timeframe_defaulted:
        notes.append(f"Timeframe: {timeframe} (varsayılan — belirtilmedi)")
    else:
        notes.append(f"Timeframe: {timeframe}")

    # B2 — disclose the injected position/stop defaults so the user knows
    # they were not requested. Match the actual values in ``spec["position"]``.
    pos = spec["position"]
    notes.append(
        f"Varsayılan: pozisyon {pos['side']}, {pos['sizing_kind']} "
        f"{pos['sizing_value']}, stop-loss %{pos['stop_loss_pct']} (talep edilmedi)"
    )

    # B1 — echo a second indicator that the user mentioned but we did NOT wire
    # in (only the first is used). EMA replaces spec["indicators"] with two EMA
    # legs, so "matched ids" is computed from the original text, not the spec.
    matched_ids = _all_matched_indicators(text_low)
    if len(matched_ids) > 1:
        extra = ", ".join(matched_ids[1:])
        notes.append(
            f"⚠ Yalnızca ilk gösterge ({ind_id}) kullanıldı — diğerleri "
            f"({extra}) yok sayıldı"
        )

    # B1 — echo every known-but-unsupported concept detected in the input.
    for label in _detect_ignored(text_low):
        notes.append(f"⚠ '{label}' desteklenmiyor — yok sayıldı")

    return spec, notes
