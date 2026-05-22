# Sub-system J — NL bot dev assistant (SHIPPED 2026-05-22 — FINAL)

Spec: [docs/superpowers/specs/2026-05-22-nl-assistant-design.md](../docs/superpowers/specs/2026-05-22-nl-assistant-design.md)
Plan: [docs/superpowers/plans/2026-05-22-nl-assistant.md](../docs/superpowers/plans/2026-05-22-nl-assistant.md)

## What landed

* Rule-based NL→StrategySpec parser (TR + EN phrasings)
* /api/assistant/strategy-from-text + /api/assistant/explain-strategy
* BDA pane: textarea + Generate buttons + result preview + bottom explain panel

## Pattern coverage

* Indicator recognition: 15 F catalog indicators
* Symbol extraction: BTC/USDT format + Bitcoin/Ethereum/Solana keywords
* Timeframe: 1m..1w regex
* Threshold extraction: "N altında" / "N üstünde" / "below N" / "above N"

## Frozen contracts

* /api/assistant routes shape
* parse_request returns (spec | None, notes: list[str])
* Never raises

## Out of scope

* True LLM (RoBERTa is classification only, per K)
* Multi-turn conversation

## ALL 11 SUB-SYSTEMS SHIPPED

A (foundation), B (read portfolio), C (manual trading), D (bot runner),
E (strategy editor), F (indicator depot), G (template bots),
H (bot supervision), I (cumulative performance), J (NL assistant),
K (GitHub/HF integrations).
