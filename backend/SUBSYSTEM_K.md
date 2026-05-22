# Sub-system K — GitHub/HF integrations (SHIPPED 2026-05-22)

Spec: [docs/superpowers/specs/2026-05-22-github-hf-integrations-design.md](../docs/superpowers/specs/2026-05-22-github-hf-integrations-design.md)
Plan: [docs/superpowers/plans/2026-05-22-github-hf-integrations.md](../docs/superpowers/plans/2026-05-22-github-hf-integrations.md)

## What landed

* GitHub code search (`/api/integrations/github/search`) — thin httpx, 5-min cache, never raises
* HF classify (`/api/integrations/hf/classify`) — reuses XSEN's bundled RoBERTa
* HF explain (`/api/integrations/hf/explain`) — rule-based TR-language strategy summarization

## Frozen contracts

* /api/integrations/github/search, /classify, /explain shapes
* CodeHit + {label, score, top_3} + TR-string explain

## Out of scope

J (NL assistant — consumes K).
