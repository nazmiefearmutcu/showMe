# Sub-system H — Bot supervision (SHIPPED 2026-05-22)

Spec: [docs/superpowers/specs/2026-05-22-bot-supervision-design.md](../docs/superpowers/specs/2026-05-22-bot-supervision-design.md)
Plan: [docs/superpowers/plans/2026-05-22-bot-supervision.md](../docs/superpowers/plans/2026-05-22-bot-supervision.md)

## What landed

* GET /api/bots/feed — merged signal log across all bots, newest first, capped 500
* BOTS pane with KPI strip + per-bot table + unified signal feed
* 10-second auto-refresh

## Frozen contracts

* /api/bots/feed shape
* useBotsSupervisionStore

## Out of scope

I (cumulative performance), J (NL assistant), K (integrations).
