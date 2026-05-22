# Sub-system D — Strategy bot runner (SHIPPED 2026-05-22)

Spec: [docs/superpowers/specs/2026-05-22-bot-runner-design.md](../docs/superpowers/specs/2026-05-22-bot-runner-design.md)
Plan: [docs/superpowers/plans/2026-05-22-bot-runner.md](../docs/superpowers/plans/2026-05-22-bot-runner.md)

## What landed

* BotRecord + SignalEntry models + FS store under $SHOWME_HOME/bots
* OHLCV fetcher via ccxt-backed brokers
* BotRunner asyncio scheduler (one task per enabled bot)
* Lifespan hooks (startup replay, shutdown aclose)
* /api/bots/* — CRUD + enable/disable + signals
* BOT pane — list with status pills + form + signal log

## Safety

* Create forces mode=shadow + enabled=false — explicit escalation required
* Live mode (enable AND PUT) requires both:
  1. Credential with "trade" permission
  2. account_label re-typed in the confirm field
* Adapter-level _require("trade") in CcxtBroker remains the final defense

## Out of scope

H (bot supervision dashboards), I (cumulative performance), G (templates), J (NL assistant).
