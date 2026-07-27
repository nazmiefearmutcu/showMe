# showMe — All 11 sub-systems SHIPPED (2026-05-22)

Started: 2026-05-21 (sub-system A spec written).
Completed: 2026-05-22 (sub-system J — final).

| # | Sub-system | Close-out |
|---|---|---|
| A | Multi-exchange portfolio foundation | [SUBSYSTEM_A.md](SUBSYSTEM_A.md) |
| B | Read portfolio aggregation | [SUBSYSTEM_B.md](SUBSYSTEM_B.md) |
| C | Manual trading UI | [SUBSYSTEM_C.md](SUBSYSTEM_C.md) |
| D | Strategy bot runner | [SUBSYSTEM_D.md](SUBSYSTEM_D.md) |
| E | Strategy editor | [SUBSYSTEM_E.md](SUBSYSTEM_E.md) |
| F | Indicator depot | [SUBSYSTEM_F.md](SUBSYSTEM_F.md) |
| G | Template bot library | [SUBSYSTEM_G.md](SUBSYSTEM_G.md) |
| H | Bot supervision | [SUBSYSTEM_H.md](SUBSYSTEM_H.md) |
| I | Cumulative performance | [SUBSYSTEM_I.md](SUBSYSTEM_I.md) |
| J | NL bot dev assistant | [SUBSYSTEM_J.md](SUBSYSTEM_J.md) |
| K | GitHub/HF integrations | [SUBSYSTEM_K.md](SUBSYSTEM_K.md) |

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
