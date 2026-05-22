# Bot dev assistant (Sub-system J) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Rule-based NL→StrategySpec parser + BDA pane.

---

## Tasks

### Task J1: parser + routes + UI store + BDA pane

**Files to create:**
- `backend/showme/assistant/__init__.py` (empty)
- `backend/showme/assistant/parser.py`
- `backend/showme/server_routes/assistant.py`
- `backend/tests/test_assistant_parser.py`
- `backend/tests/test_assistant_route.py`
- `ui/src/lib/assistant-store.ts` + test
- `ui/src/functions/BDA.tsx` + test

**Files to modify:**
- `backend/showme/server_routes/__init__.py` — `assistant` alphabetical (between `ask` and `bots`)
- `ui/src/functions/registry.tsx` + `registry.test.tsx` (154→155, NATIVE_ONLY += "BDA")
- `ui/src/shell/Sidebar.tsx` (BDA after PERF in TOOL_ITEMS)

### Backend — `backend/showme/assistant/parser.py`

```python
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

    entry_threshold: float | None = None
    exit_threshold: float | None = None

    # Try to find: "ind below N" or "ind altında N"
    for pat in below_patterns:
        if pat in text_low:
            # find a number after the pattern
            idx = text_low.find(pat)
            tail = text[idx:]
            tnums = _extract_numbers(tail)
            if tnums:
                entry_threshold = tnums[0]
                break
    for pat in above_patterns:
        if pat in text_low:
            idx = text_low.find(pat)
            tail = text[idx:]
            tnums = _extract_numbers(tail)
            if tnums:
                exit_threshold = tnums[0]
                break

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
```

### Backend — `backend/showme/server_routes/assistant.py`

```python
"""Routes: /api/assistant/* — NL→spec parsing + explain delegation."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, FastAPI, HTTPException
from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.post("/api/assistant/strategy-from-text")
    async def strategy_from_text(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.assistant.parser import parse_request
        from showme.strategies.spec import StrategySpec
        from showme.strategies.store import StrategyStore

        text = (payload or {}).get("text") or ""
        save = bool((payload or {}).get("save", False))
        if not text.strip():
            raise HTTPException(400, detail="text is required")

        spec_dict, notes = parse_request(text)
        if spec_dict is None:
            return {"spec": None, "notes": notes, "saved_id": None}

        try:
            spec = StrategySpec(**spec_dict)
        except Exception as exc:  # noqa: BLE001
            return {"spec": spec_dict, "notes": notes + [f"validation failed: {exc}"],
                    "saved_id": None}

        saved_id = None
        if save:
            saved = StrategyStore.fresh().save(spec)
            saved_id = saved.id

        return {
            "spec": spec.model_dump(),
            "notes": notes,
            "saved_id": saved_id,
        }

    @router.post("/api/assistant/explain-strategy")
    async def explain_strategy(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.integrations.hf import explain
        from showme.strategies.store import StrategyStore, UnknownStrategy

        sid = (payload or {}).get("strategy_id")
        if not sid:
            raise HTTPException(400, detail="strategy_id is required")
        try:
            spec = StrategyStore.fresh().get(sid)
        except UnknownStrategy:
            raise HTTPException(404, detail=f"unknown strategy: {sid}")
        return {"explanation": explain(spec.model_dump())}

    app.include_router(router)
```

### Tests

`backend/tests/test_assistant_parser.py`:
- parse_request empty → notes
- parse_request "RSI 30 altında, 70 üstünde" → spec with rsi + crosses_below 30 + crosses_above 70
- parse_request "MACD trend" → spec with macd crosses_above 0
- parse_request "EMA 20 strategy on BTC/USDT 4h" → spec with ema indicators, BTC/USDT, 4h
- parse_request "bilinmeyen şey" → (None, notes)
- parse_request "RSI 4h" → fallback to 30/70 defaults

`backend/tests/test_assistant_route.py`:
- POST strategy-from-text empty → 400
- POST strategy-from-text "RSI 30 altında" → spec returned
- POST strategy-from-text with save=true → saved_id set + appears in /api/strategies
- POST explain-strategy 400 without strategy_id
- POST explain-strategy 404 on unknown
- POST explain-strategy with real id → explanation string

### UI

`ui/src/lib/assistant-store.ts`:
```typescript
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface StrategyFromTextResult {
  spec: Record<string, unknown> | null;
  notes: string[];
  saved_id: string | null;
}

interface AssistantStoreShape {
  text: string;
  result: StrategyFromTextResult | null;
  explanation: string | null;
  loading: boolean;
  error: string | null;
  setText: (t: string) => void;
  generate: (save?: boolean) => Promise<StrategyFromTextResult | null>;
  explainStrategy: (id: string) => Promise<string | null>;
}

export const useAssistantStore = create<AssistantStoreShape>((set, get) => ({
  text: "", result: null, explanation: null, loading: false, error: null,
  setText: (t) => set({ text: t }),
  generate: async (save = false) => {
    set({ loading: true, error: null });
    try {
      const r = await sidecarFetch<StrategyFromTextResult>(
        "/api/assistant/strategy-from-text",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: get().text, save }),
        },
      );
      set({ result: r, loading: false });
      return r;
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },
  explainStrategy: async (id) => {
    set({ loading: true, error: null });
    try {
      const r = await sidecarFetch<{ explanation: string }>(
        "/api/assistant/explain-strategy",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ strategy_id: id }),
        },
      );
      set({ explanation: r.explanation, loading: false });
      return r.explanation;
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },
}));
```

`ui/src/lib/assistant-store.test.ts`: 3-4 tests (setText, generate POSTs, explain POSTs, error path).

`ui/src/functions/BDA.tsx`:
- Top half: textarea + "Strateji öner" + "Strateji öner + kaydet" buttons + result preview (notes + JSON preview).
- Bottom half: strategy dropdown (from strategy-store) + "Açıkla" button + explanation pane.

`ui/src/functions/BDA.test.tsx`: 3-4 tests (textarea binding, generate triggers store action, result rendering).

### Registry/Sidebar
Bump 154→155. Add BDA to TOOL_ITEMS after PERF.

### Task J2: Native rebuild + close-out

Tests; build; deploy; live smoke for `POST /api/assistant/strategy-from-text` with `text="RSI 30 altında, 70 üstünde"`; screenshot; memory `showme_subsystem_j.md`; `backend/SUBSYSTEM_J.md`.
