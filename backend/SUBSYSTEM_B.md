# Sub-system B — Read-only portfolio aggregation (SHIPPED 2026-05-22)

Spec: [docs/superpowers/specs/2026-05-22-read-portfolio-aggregation-design.md](../docs/superpowers/specs/2026-05-22-read-portfolio-aggregation-design.md)
Plan: [docs/superpowers/plans/2026-05-22-read-portfolio-aggregation.md](../docs/superpowers/plans/2026-05-22-read-portfolio-aggregation.md)

## What landed

* `backend/showme/portfolio_aggregate.py` — asyncio fan-out across `factory._DYNAMIC`, 30-second in-process cache, factory-hook subscription so invalidated credentials drop their cache entries.
* `backend/showme/server_routes/portfolio_aggregate.py` — `GET /api/portfolio/aggregate?include_orders=&credential_ids=` returns the unified payload.
* `backend/showme/brokers/factory.py` — `_INVALIDATION_HOOKS` extension point + invocation in `unregister_credential`.
* `ui/src/lib/portfolio-store.ts` — zustand store mirroring exchange-store pattern.
* `ui/src/functions/PORT.tsx` — additive `<AggregateHeader>`, `<SourceFilter>`, `<CredentialGroup>` above the legacy Bloomberg-grade layout. 30s auto-refresh interval.

## Frozen contracts

* Route shape: `{as_of, groups: [{credential_id, exchange_id, account_label, permissions, account, positions, orders, error}], totals: {equity_by_currency, stable_usd_equivalent}}`
* Cache TTL: 30 seconds (in-process)
* Factory hook: `factory._INVALIDATION_HOOKS.append(fn)` is the public extension point
* `usePortfolioStore` UI surface

## Out of scope (next sub-systems)

C (manual trading from PORT), D (bot runner), E (strategy editor), F (indicator depot), G-K.
