# Wave 1 Manifest Design Specs

These are the canonical design specifications for Wave 1 functions. Each spec is the source of truth for:
- The Python `FunctionManifest` registered in `backend/showme/manifest/seeds/`
- The pane implementation in `ui/src/functions/{CODE}.tsx`
- The semantic tests in `tests/test_function_{code}.py` and `ui/src/functions/{CODE}.test.tsx`

## Wave 1 scope

**Market data core:**
- [GP](GP.md) — Generic Price Chart (candle/line with overlays + studies)
- [HP](HP.md) — Historical Price (table + linked chart + export)
- [DES](DES.md) — Security Description (identifiers, sector taxonomy, corporate actions context)
- [FA](FA.md) — Financial Analysis (statements + common-size + growth + cash conversion)
- [WATCH](WATCH.md) — Operator-grade watchlist with alerts
- [TOP](TOP.md) — Top news with dedupe + freshness + market-impact scoring
- [CN](CN.md) — Company news with relevance filtering
- [QUOTE](QUOTE.md) — Real-time quote service infrastructure

**Portfolio & risk:**
- [PORT](PORT.md) — Canonical portfolio workspace
- [ACCT](ACCT.md) — Account-level truth
- [CORR](CORR.md) — Correlation heatmap with horizon/method
- [PORT_OPT](PORT_OPT.md) — PyPortfolioOpt-backed efficient frontier
- [BLAK](BLAK.md) — Black-Litterman with priors/views/tau

**Macro & rates:**
- [ECO](ECO.md) — Economic event calendar
- [ECST](ECST.md) — Economic series explorer with vintages
- [WIRP](WIRP.md) — World interest rate probabilities (cut/hold/hike)
- [BTMM](BTMM.md) — Monetary policy regime view

**Derivatives:**
- [GEX](GEX.md) — Gamma exposure strike ladder + walls
- [IVOL](IVOL.md) — Implied volatility surface heatmap
- [OMON](OMON.md) — Option chain with model controls
- [OVDV](OVDV.md) — OTC vol surface
- [HVT](HVT.md) — Historical (realized) volatility table

## Spec template

Each spec follows this structure:

```
# {CODE} — {Full Display Name}

**Category:** {category}
**Asset classes:** {list}
**Professional intent:** {one sentence}

## Inputs
| Name | Label | Control | Required | Default | Range/Options | Description |

## Provider chain
- Primary: {adapter}
- Fallbacks: [{adapter},...]
- Acceptable modes: [{mode},...]

## Output contract
- `must_have`: [{field names}]
- Has rows: yes/no
- Has series: yes/no
- Has cards: yes/no

## Chart grammar (if applicable)
- Kind: {chart_kind}
- X axis: {type/unit/label}
- Y axis: {type/unit/label}
- Panes: [{name/series_kind/height_pct}]
- Overlays: yes/no
- Compare: yes/no

## Table schema (if applicable)
| Column | Label | Kind | Unit | Format |

## Card schema (if applicable)
| Slot | Label | Kind | Unit |

## Methodology
{paragraph explaining how the function computes / surfaces what it does}

## Formulas
| Name | Expression | Variables |

## Field dictionary
| Field | Unit | Description | Source |

## Provenance requirements
- Source list: required
- As-of: required
- Latency ms: required (live mode)

## Alerting (if applicable)
- Conditions: [...]
- Delivery: [...]

## Semantic tests
1. **{name}** — {what it proves}, given inputs `{...}`, asserts `[...]`
```
