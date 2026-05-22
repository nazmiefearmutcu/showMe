# Sub-system E — Strategy editor (SHIPPED 2026-05-22)

Spec: [docs/superpowers/specs/2026-05-22-strategy-editor-design.md](../docs/superpowers/specs/2026-05-22-strategy-editor-design.md)
Plan: [docs/superpowers/plans/2026-05-22-strategy-editor.md](../docs/superpowers/plans/2026-05-22-strategy-editor.md)

## What landed

* StrategySpec pydantic models + JSON roundtrip + catalog validation
* FS store under `$SHOWME_HOME/strategies/{id}.json` with created_at preservation
* Compute engine for 15 F indicators (pandas/numpy, NaN-tolerant)
* evaluate() state machine emitting entry/exit events
* /api/strategies CRUD + /preview (seeded random walk for v1)
* STRA pane — list + form + Save + Preview + Delete
* Frozen contracts documented in memory

## Out of scope

D (bot runner uses E specs), G (templates extend E), J (NL assistant generates E specs).
