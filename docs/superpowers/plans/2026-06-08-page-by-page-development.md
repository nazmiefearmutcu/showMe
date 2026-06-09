# ShowMe Page-by-Page Development — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **One Ralph iteration = exactly one task (one page) below.**

**Goal:** Bring every page of the ShowMe desktop terminal up to terminal-grade quality — one page per Ralph iteration — fixing deficiencies, improving usability, ensuring data sufficiency, and raising display quality.

**Architecture:** Tauri app; React UI in `ui/`, Python sidecar in `backend/`. Navigation `/fn/{CODE}` resolves through `ui/src/functions/registry.tsx` to a native pane or the `FunctionStub` fallback. Each page-task improves the pane component (`ui/src/functions/{CODE}.tsx`), its backend feed (`backend/showme/engine/functions/{category}/{code}.py` + providers), and its rendering quality.

**Tech Stack:** React + TypeScript + Vite + Zustand (UI); Python + FastAPI-style sidecar (backend); Vitest (UI tests); pytest (backend tests).

---

## Per-Page Procedure (applies to EVERY task below)

Each task is one page. Execute it as a **subagent-driven-development** mini-cycle:

- [ ] **Step 1 — Explore (parallel subagents).** Dispatch 3 read-only subagents on the page; each returns a structured findings list:
  - *UI/UX subagent*: read the pane (`ui/src/functions/{CODE}.tsx` or shell path) + its tests + `PaneChrome`/router usage. Report: states present (loading/error/empty), controls, keyboard/a11y, layout issues, dead/broken UI, missing tests.
  - *Data subagent*: find & read the backend function feeding this code (`rg -l "{code}" backend/showme/engine/functions` and `backend/showme/server_routes`) + its provider(s) in `backend/showme/providers`. Report: is the data real (not stub/mock/empty)? complete? fresh? what fields are missing or hard-coded?
  - *Display-quality subagent*: assess rendering vs. a Bloomberg-grade dark terminal — number/date formatting, table/chart fidelity, density, theming, responsiveness within pane chrome.
- [ ] **Step 2 — Synthesize.** Merge findings into one prioritized deficiency list covering the 4 dimensions: (a) deficiencies/bugs, (b) usability, (c) data sufficiency, (d) display quality.
- [ ] **Step 3 — Implement (TDD).** Smallest correct changes. Write/extend tests first where feasible. Wire real providers where data is insufficient. Add loading/error/empty states. Polish rendering.
- [ ] **Step 4 — Verify.** Run, fix until green:
  - `cd ~/showMe_temp && npm run build:ui`
  - UI tests for the page: `npx vitest run ui/src/functions/{CODE}` (and any touched test) — or `npx vitest run` for the suite if changes are broad.
  - Backend tests if backend touched: `cd backend && .venv/bin/python -m pytest -q` (scope to the touched module when possible).
- [ ] **Step 5 — Review.** Dispatch a `code-reviewer` subagent on the diff (`git diff`); address high-confidence findings.
- [ ] **Step 6 — Commit.** One focused commit: `git add -A && git commit -m "feat({CODE}): <summary of page improvements>"`.
- [ ] **Step 7 — Mark done.** Check this task's box in this file, append a one-line note to `.ralph` progress / `PROGRESS.md`, and advance to the next unchecked task.

**Page Definition of Done:** native pane renders real backend data (or an honest, styled empty state); loading/error/empty states present; terminal-grade formatting & theming; `npm run build:ui` clean; page tests pass; one commit; box checked.

**File-path conventions used below:**
- Pane: `ui/src/functions/{CODE}.tsx` unless a different path is given.
- Backend: locate via `rg -il "{code}" backend/showme/engine/functions backend/showme/server_routes` (functions live under `backend/showme/engine/functions/{category}/{code}.py`).
- Tests: co-located `ui/src/functions/{CODE}.test.tsx` or `ui/src/functions/__tests__/`.

---

## Wave 1 — Core shell & primary workspace

- [x] **Task 1: HOME — Overview.** Pane: `ui/src/panes/Welcome.tsx` (+ `Welcome.test.tsx`, `Welcome.cascade.test.tsx`, `Welcome.sentiment.test.tsx`). Backend: market snapshot/sentiment feeds. Focus: first-screen impact, live tiles, navigation affordances.
- [x] **Task 2: WATCH — Live Watchlist.** Pane: `ui/src/functions/WATCH.tsx`. Backend: quotes/streaming provider. Focus: live updates, add/remove symbols, sparkline/quote density, empty state.
- [x] **Task 3: PORT — Portfolio.** Pane: `ui/src/functions/PORT.tsx`. Backend: portfolio aggregation. Focus: holdings table, P&L, real broker/positions data sufficiency.
- [x] **Task 4: WEI — Macro Monitor.** Pane: `ui/src/functions/WEI.tsx`. Backend: world indices/macro. Focus: index grid completeness, freshness, formatting.
- [x] **Task 5: NI — News Desk (CN alias = Company News).** Pane: `ui/src/functions/NI.tsx`. Backend: `backend/showme/engine/functions/news/`. Focus: real headlines, filtering, readable list, empty/error states.
- [x] **Task 6: SCAN — All Functions.** Pane: `ui/src/functions/SCAN.tsx`. Backend: function index. Focus: discoverability, search, categories, launch affordances. _(Note: SCAN is actually a TRADING SCANNER, not a function catalog — improved as such; function discovery lives in the Command Palette.)_
- [x] **Task 7: MIS — Multi Indicator Scan.** Pane: `ui/src/functions/MIS.tsx`. Backend: indicators engine (`backend/showme/indicators`). Focus: multi-indicator results, real scans, result density.
- [x] **Task 8: PREF — Settings.** Pane: `ui/src/panes/Preferences.tsx` (+ `ui/src/panes/__tests__/`). Focus: every setting wired & persisted, language/theme, sane defaults, layout.

## Wave 2 — Featured quick analytics

- [x] **Task 9: GEX — Gamma Exposure.** Pane: `ui/src/functions/GEX.tsx`. Backend: `backend/showme/engine/functions/derivative/gex.py`. Focus: gamma profile chart, strikes data sufficiency, dealer-positioning display.
- [x] **Task 10: FA — Financial Analysis.** Pane: `ui/src/functions/FA.tsx`. Backend: fundamentals provider (SEC EDGAR). Focus: statements, ratios, real filings data, table quality.
- [x] **Task 11: DES — Description.** Pane: `ui/src/functions/DES.tsx`. Backend: company/instrument description. Focus: profile completeness, formatting.
- [x] **Task 12: BTMM — Rates Environment.** Pane: `ui/src/functions/BTMM.tsx`. Backend: `backend/showme/engine/functions/macro/btmm.py`. Focus: rates/curve display, freshness.
- [x] **Task 13: MOST — Most Active.** Pane: `ui/src/functions/MOST.tsx`. Backend: movers provider. Focus: real most-active data, ranking table, refresh.

## Wave 3 — Trading & automation tools

- [x] **Task 14: INSTANT — Trade Ticket (Instant Squawk Line).** Pane: `ui/src/functions/INSTANT.tsx`. Backend: `backend/showme/engine/functions/trade/`. Focus: ticket UX, order fields, validation, squawk feed.
- [x] **Task 15: ALRT — Alerts.** Pane: `ui/src/functions/ALRT.tsx`. Backend: `backend/showme/engine/functions/misc/alrt.py`. Focus: create/manage alerts, persistence, trigger display.
- [x] **Task 16: STRA — Strategy Editor.** Pane: `ui/src/functions/STRA.tsx`. Backend: `backend/showme/strategies`. Focus: editor UX, rule building, save/load, validation.
- [x] **Task 17: TMPL — Strategy Templates.** Pane: `ui/src/functions/TMPL.tsx`. Backend: `backend/showme/templates`. Focus: template library, preview, instantiate.
- [x] **Task 18: BOT — Bot Manager.** Pane: `ui/src/functions/BOT.tsx`. Backend: `backend/showme/bots`. Focus: bot list, start/stop, status display.
- [x] **Task 19: BOTS — Bot Supervision.** Pane: `ui/src/functions/BOTS.tsx`. Backend: `backend/showme/bots`. Focus: supervision view, health/metrics, controls.
- [x] **Task 20: PERF — Performance.** Pane: `ui/src/functions/PERF.tsx`. Backend: performance/leaderboard. Focus: cumulative perf charts, real metrics, leaderboard table.
- [x] **Task 21: BDA — Bot Dev Assistant.** Pane: `ui/src/functions/BDA.tsx`. Backend: `backend/showme/assistant`. Focus: NL→strategy parsing, explanation output quality.
- [x] **Task 22: INDX — Indicator Index.** Pane: `ui/src/functions/INDX.tsx`. Backend: `backend/showme/indicators`. Focus: indicator depot, search, descriptions, params.
- [x] **Task 23: CONN — Connect Exchange.** Pane: `ui/src/functions/CONN.tsx`. Backend: `backend/showme/brokers`/`integrations`. Focus: connection flow, status, key handling UX (no secrets logged).
- [x] **Task 24: TXNS — Trade Blotter.** Pane: `ui/src/functions/TXNS.tsx`. Backend: transactions/fills. Focus: blotter table, real fills, filtering, export.

## Wave 4 — Research / AI / market-structure

- [x] **Task 25: AGENT — Symbol Agent.** Pane: `ui/src/functions/AGENT.tsx`. Backend: `backend/showme/agents`. Focus: ranked function set per symbol, relevance, display.
- [x] **Task 26: ASK — Ask.** Pane: `ui/src/functions/ASK.tsx`. Backend: assistant/research. Focus: query UX, answer rendering, function-backed citations.
- [x] **Task 27: XSEN — X Sentiment AI.** Pane: `ui/src/functions/XSEN.tsx`. Backend: `x_scraper_ai`/news. Focus: sentiment feed real data, scoring display, freshness.
- [x] **Task 28: CORR — Correlation.** Pane: `ui/src/functions/CORR.tsx`. Backend: correlation compute. Focus: correlation matrix/heatmap, symbol selection, real series.
- [ ] **Task 29: MAP — Market Heatmap (SECT alias).** Pane: `ui/src/functions/MarketHeatmap.tsx`. Backend: sector/market data. Focus: heatmap fidelity, sizing/coloring, real constituents.
- [ ] **Task 30: TOP — Top Movers.** Pane: `ui/src/functions/TOP.tsx`. Backend: movers. Focus: gainers/losers, real data, ranking quality.
- [ ] **Task 31: ECO — Economic Calendar.** Pane: `ui/src/functions/ECO.tsx`. Backend: `backend/showme/engine/functions/macro/eco.py`. Focus: events calendar, real schedule, importance/actual/forecast.

## Wave 5 — Portfolio analytics family (one pane, 20 codes)

- [ ] **Task 32: PORTX — Portfolio Analytics.** Pane: `ui/src/functions/PortfolioAnalytics.tsx`. Codes: ACCT, BLAK, BMTX, BTFW, BTUNE, LOTS, MARS, MGN, MLSIG, PCAS, PFA, PORT_OPT, PORT_WHATIF, PSC, PVAR, REBA, RPAR, STRS, TLH, TRA. Backend: portfolio analytics. Focus: each code's view renders the right analytic with real data; verify the shared pane branches correctly per code; tables/charts terminal-grade.

## Wave 6 — Long-tail bespoke analytics (alphabetical by code)

- [ ] **Task 33: AIM.** Pane: `ui/src/functions/AIM.tsx`. Backend via `rg -il aim backend/showme/engine/functions`.
- [ ] **Task 34: ANR.** Pane: `ui/src/functions/ANR.tsx` (+ `anr_pane/`). Backend: analyst recommendations.
- [ ] **Task 35: BIO.** Pane: `ui/src/functions/BIO.tsx`. Backend via `rg -il bio backend/showme/engine/functions`.
- [ ] **Task 36: CRPR.** Pane: `ui/src/functions/CRPR.tsx`. Backend: crypto price (CoinGecko/Binance).
- [ ] **Task 37: DEBT.** Pane: `ui/src/functions/DEBT.tsx`. Backend: Treasury/debt.
- [ ] **Task 38: DPF.** Pane: `ui/src/functions/DPF.tsx`. Backend via `rg -il dpf backend/showme/engine/functions`.
- [ ] **Task 39: DVD.** Pane: `ui/src/functions/DVD.tsx`. Backend: dividends.
- [ ] **Task 40: ECFC.** Pane: `ui/src/functions/ECFC.tsx`. Backend: `backend/showme/engine/functions/macro/ecfc.py`.
- [ ] **Task 41: ECST.** Pane: `ui/src/functions/ECST.tsx`. Backend: `backend/showme/engine/functions/macro/ecst.py`.
- [ ] **Task 42: EE.** Pane: `ui/src/functions/EE.tsx`. Backend: earnings estimates.
- [ ] **Task 43: EMSX.** Pane: `ui/src/functions/EMSX.tsx`. Backend: execution.
- [ ] **Task 44: EQS.** Pane: `ui/src/functions/EQS.tsx`. Backend: equity screen.
- [ ] **Task 45: EREV.** Pane: `ui/src/functions/EREV.tsx`. Backend: earnings revisions.
- [ ] **Task 46: ESG.** Pane: `ui/src/functions/ESG.tsx`. Backend: ESG scores.
- [ ] **Task 47: GLCO.** Pane: `ui/src/functions/GLCO.tsx`. Backend: global commodities.
- [ ] **Task 48: GP.** Pane: `ui/src/functions/GP.tsx`. Backend: price chart.
- [ ] **Task 49: HP.** Pane: `ui/src/functions/HP.tsx`. Backend: historical prices.
- [ ] **Task 50: IVOL.** Pane: `ui/src/functions/IVOL.tsx`. Backend: implied vol.
- [ ] **Task 51: MICRO.** Pane: `ui/src/functions/MICRO.tsx`. Backend: market microstructure.
- [ ] **Task 52: OVDV.** Pane: `ui/src/functions/OVDV.tsx`. Backend: options vol surface (`derivative/`).
- [ ] **Task 53: POLY.** Pane: `ui/src/functions/POLY.tsx`. Backend: `backend/showme/engine/functions/misc/poly.py` (Polymarket).
- [ ] **Task 54: SAT.** Pane: `ui/src/functions/SAT.tsx`. Backend: `backend/showme/engine/functions/misc/sat.py` (NASA-GIBS).
- [ ] **Task 55: TCA.** Pane: `ui/src/functions/TCA.tsx`. Backend: `backend/showme/engine/functions/trade/tca.py`.
- [ ] **Task 56: TRQA.** Pane: `ui/src/functions/TRQA.tsx`. Backend: `backend/showme/engine/functions/news/trqa.py`.
- [ ] **Task 57: TSAR.** Pane: `ui/src/functions/TSAR.tsx`. Backend via `rg -il tsar backend/showme/engine/functions`.
- [ ] **Task 58: TSOX.** Pane: `ui/src/functions/TSOX.tsx`. Backend via `rg -il tsox backend/showme/engine/functions`.
- [ ] **Task 59: WACC.** Pane: `ui/src/functions/WACC.tsx`. Backend: cost of capital.
- [ ] **Task 60: WB.** Pane: `ui/src/functions/WB.tsx`. Backend: `backend/showme/engine/functions/bond/wb.py` (World Bank).
- [ ] **Task 61: WCRS.** Pane: `ui/src/functions/WCRS.tsx`. Backend: relative strength.
- [ ] **Task 62: WETR.** Pane: `ui/src/functions/WETR.tsx`. Backend: weather/commodity.
- [ ] **Task 63: WHAL.** Pane: `ui/src/functions/WHAL.tsx`. Backend: `backend/showme/engine/functions/misc/whal.py` (whale/on-chain).
- [ ] **Task 64: WIRP.** Pane: `ui/src/functions/WIRP.tsx`. Backend: `backend/showme/engine/functions/macro/wirp.py` (rate probabilities).

---

## Task 65: Campaign completion gate

- [ ] **Step 1:** Confirm Tasks 1–64 are all checked.
- [ ] **Step 2:** Run the full suite once: `cd ~/showMe_temp && npm run build:ui && npx vitest run` and `cd backend && .venv/bin/python -m pytest -q`. Fix any regressions.
- [ ] **Step 3:** Ask the user (single question, via AskUserQuestion): **"All 64 pages developed. Should I end the Ralph loop?"** Do NOT self-terminate the loop — wait for the user's decision.

---

## Self-Review notes

- **Spec coverage:** All 64 pages from the spec backlog are represented as Tasks 1–64 in the same order; the 4 dimensions are encoded in the Per-Page Procedure (Steps 1–3) and Page DoD; the completion gate (ask to end loop) is Task 65. ✓
- **No placeholders:** The Per-Page Procedure carries the exact, repeated steps & commands so every task is self-contained without restating them 64×; page-specific identity (code, pane path, backend locator, focus) is given per task. ✓
- **Consistency:** Pane paths follow `ui/src/functions/{CODE}.tsx` (verified for sample); shell pages use explicit paths; backend located via `rg` since the code→file map is by category. ✓
