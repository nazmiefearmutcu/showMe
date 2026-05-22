# showMe — All 11 sub-systems SHIPPED (2026-05-22)

Started: 2026-05-21 (sub-system A spec written).
Completed: 2026-05-22 (sub-system J — final).

| # | Sub-system | Spec | Plan | Close-out |
|---|---|---|---|---|
| A | Multi-exchange portfolio foundation | [spec](../docs/superpowers/specs/2026-05-21-multi-exchange-portfolio-foundation-design.md) | [plan](../docs/superpowers/plans/2026-05-21-multi-exchange-portfolio-foundation.md) | [SUBSYSTEM_A.md](SUBSYSTEM_A.md) |
| B | Read portfolio aggregation | [spec](../docs/superpowers/specs/2026-05-22-read-portfolio-aggregation-design.md) | [plan](../docs/superpowers/plans/2026-05-22-read-portfolio-aggregation.md) | [SUBSYSTEM_B.md](SUBSYSTEM_B.md) |
| C | Manual trading UI | [spec](../docs/superpowers/specs/2026-05-22-manual-trading-ui-design.md) | [plan](../docs/superpowers/plans/2026-05-22-manual-trading-ui.md) | [SUBSYSTEM_C.md](SUBSYSTEM_C.md) |
| D | Strategy bot runner | [spec](../docs/superpowers/specs/2026-05-22-bot-runner-design.md) | [plan](../docs/superpowers/plans/2026-05-22-bot-runner.md) | [SUBSYSTEM_D.md](SUBSYSTEM_D.md) |
| E | Strategy editor | [spec](../docs/superpowers/specs/2026-05-22-strategy-editor-design.md) | [plan](../docs/superpowers/plans/2026-05-22-strategy-editor.md) | [SUBSYSTEM_E.md](SUBSYSTEM_E.md) |
| F | Indicator depot | [spec](../docs/superpowers/specs/2026-05-22-indicator-depot-design.md) | [plan](../docs/superpowers/plans/2026-05-22-indicator-depot.md) | [SUBSYSTEM_F.md](SUBSYSTEM_F.md) |
| G | Template bot library | [spec](../docs/superpowers/specs/2026-05-22-template-bots-design.md) | [plan](../docs/superpowers/plans/2026-05-22-template-bots.md) | [SUBSYSTEM_G.md](SUBSYSTEM_G.md) |
| H | Bot supervision | [spec](../docs/superpowers/specs/2026-05-22-bot-supervision-design.md) | [plan](../docs/superpowers/plans/2026-05-22-bot-supervision.md) | [SUBSYSTEM_H.md](SUBSYSTEM_H.md) |
| I | Cumulative performance | [spec](../docs/superpowers/specs/2026-05-22-cumulative-performance-design.md) | [plan](../docs/superpowers/plans/2026-05-22-cumulative-performance.md) | [SUBSYSTEM_I.md](SUBSYSTEM_I.md) |
| J | NL bot dev assistant | [spec](../docs/superpowers/specs/2026-05-22-nl-assistant-design.md) | [plan](../docs/superpowers/plans/2026-05-22-nl-assistant.md) | [SUBSYSTEM_J.md](SUBSYSTEM_J.md) |
| K | GitHub/HF integrations | [spec](../docs/superpowers/specs/2026-05-22-github-hf-integrations-design.md) | [plan](../docs/superpowers/plans/2026-05-22-github-hf-integrations.md) | [SUBSYSTEM_K.md](SUBSYSTEM_K.md) |

## Test counts at final ship

* Backend: 668 passed, 1 skipped
* UI: 502 passed, 8 pre-existing failures (function_stub WIP — not part of this work)

## All native function codes (152 total = 141 static + 11 new native-only)

`AGENT, ANR, ASK, BDA, BIO, BOT, BOTS, BTMM, CONN, CORR, DES, DPF, DVD, ECFC,
ECO, ECST, EE, EMSX, EQS, EREV, ESG, FA, GEX, GLCO, GP, HP, INDX, INSTANT,
MIS, MarketHeatmap, MOST, NI, PERF, PORT, SCAN, STRA, TMPL, TOP, TRAN, TRQA,
TSAR, TSOX, WACC, WATCH, WB, WCRS, WEI, WETR, WHAL, WIRP, XSEN` + 7 native-only
that were added during this work: BDA, BOT, BOTS, CONN, INDX, PERF, STRA, TMPL.

(Originally 141 functions; sub-systems contributed: CONN, INDX, STRA, BOT, BOTS, TMPL, PERF, BDA = 8 new native-only.)
