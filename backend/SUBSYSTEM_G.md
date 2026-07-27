# Sub-system G — Template bot library (SHIPPED 2026-05-22)

## What landed

* 12 hand-curated templates with TR NL explanations + math + applicability
* Catalog loader mirrors F's pattern
* /api/templates list + detail + instantiate (creates a real StrategySpec)
* TMPL pane — grid + detail + Use button → modal → strategy created

## Frozen contracts

* TemplateEntry.id stable lookup
* spec_template = StrategySpec subset (id/timestamps stripped at instantiate)
* Routes: /api/templates, /api/templates/{id}, /api/templates/{id}/instantiate
* Instantiate body: `{name?: str, symbol?: str}`

## Out of scope

H (bot supervision), I (cumulative performance), J (NL assistant), K (integrations).
