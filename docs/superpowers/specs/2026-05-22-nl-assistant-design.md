# Bot dev assistant (Sub-system J)

**Date:** 2026-05-22
**Depends on:** E (StrategySpec + store), F (indicator catalog), K (HF classify + explain)
**Status:** Design — auto-approved per `feedback_decisive`

## 1. Goal

Natural-language to strategy. User types "RSI 30 altında alım, 70 üstünde satım yap" and the assistant returns a saved StrategySpec they can edit in STRA. Bidirectional with K's `explain`: user can also paste a strategy id and get a TR-language summary back.

Per the user's original ask: "(bot editleme ekranı yine de özgün olacak çünkü bütün indikatörlerin her biri için hazırda bir suggest edilen strateji olacak)" — J's NL flow complements G's templates and E's editor.

## 2. Approach

**Rule-based NL → spec parser** in v1. Not a real LLM (text-generation models too heavy per K's analysis). Pattern matching handles the most common phrasings:

* "RSI [N altında|N üstünde]" → rsi indicator + threshold rule
* "MACD [yukarı|aşağı] kesince" → macd cross rule
* "EMA(N) [yukarı|aşağı] EMA(M)" → ema crossover
* Symbol + timeframe extracted from common patterns
* If no recognized indicator → return error with helpful hints

Bidirectionally exposes K's `explain` for the user's existing strategies.

## 3. Components

### 3.1 Backend

* `backend/showme/assistant/__init__.py` (empty)
* `backend/showme/assistant/parser.py` — `parse_request(text) → (StrategySpec | None, list[str] notes)`. Pattern matching with TR + EN keywords.
* `backend/showme/server_routes/assistant.py`:
  * `POST /api/assistant/strategy-from-text` — body `{text, save?: bool}` returns `{spec, notes, saved_id?}`
  * `POST /api/assistant/explain-strategy` — body `{strategy_id}` returns `{explanation}` (delegates to K)

### 3.2 UI

* `ui/src/lib/assistant-store.ts` — text input state, last result.
* `ui/src/functions/BDA.tsx` — Bot Dev Assistant:
  * Big textarea for user prompt.
  * "Strateji öner" button → POST /assistant/strategy-from-text.
  * Result preview: parsed spec rendered as JSON + notes list.
  * "Kaydet" button (uses K's save flag).
  * "Açıkla" panel: dropdown of existing strategies + Explain button → shows TR summary.

## 4. Acceptance criteria

* J1. `parse_request("RSI 30 altında al, 70 üstünde sat")` returns a valid StrategySpec with rsi indicator + crosses_below + crosses_above rules.
* J2. `parse_request` returns `(None, notes)` with helpful guidance when no indicator recognized.
* J3. `POST /api/assistant/strategy-from-text` with `save=true` actually persists to the strategies store.
* J4. `POST /api/assistant/explain-strategy` returns the rule-based summary.
* J5. BDA pane renders + Generate → preview flow works.
* J6. Backend + UI tests green; native build deployed.

## 5. Out of scope

* True conversational LLM (defer; out of scope per K's analysis)
* Multi-turn dialogue history
* Conversational refinement ("change the period to 21")
* Voice input
* Confidence scores on parse output
