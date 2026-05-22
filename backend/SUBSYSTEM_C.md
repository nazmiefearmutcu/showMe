# Sub-system C — Manual trading UI (SHIPPED 2026-05-22)

Spec: [docs/superpowers/specs/2026-05-22-manual-trading-ui-design.md](../docs/superpowers/specs/2026-05-22-manual-trading-ui-design.md)
Plan: [docs/superpowers/plans/2026-05-22-manual-trading-ui.md](../docs/superpowers/plans/2026-05-22-manual-trading-ui.md)

## What landed

* `ui/src/lib/trading-store.ts` — zustand store wrapping POST /api/broker/orders + DELETE
* `ui/src/functions/OrderTicket.tsx` — inline form + ConfirmModal
* `ui/src/functions/PORT.tsx` — additive: OrderTicket + per-position Close + per-order Cancel

## Safety

* Backend POST /api/broker/orders already enforced trade permission via CcxtBroker._require("trade") (HTTP 403)
* trading-store confirmation modal requires account_label re-type
* Form rendering itself is gated by `g.permissions.includes("trade")` so read-only credentials don't see writes at all

## Out of scope

D-K (bot runner, strategy editor, indicators, templates, supervision, performance, NL assistant, integrations).
