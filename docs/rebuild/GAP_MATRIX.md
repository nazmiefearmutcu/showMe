# showMe Gap Matrix

Audit date: 2026-05-24
For the rebuild this is the ban-list and the per-function delta.

---

## Production-Fakery Audit

Files that import a "fakery component" (FunctionStub, TemplateRenderer, or anything from `design-export/*`) in PRODUCTION code paths (excludes `*.test.tsx`):

| Path | Line | Symbol | Verdict |
|------|------|--------|---------|
| `ui/src/shell/Workspace.tsx` | 34-35 | `const FunctionStub = lazy(() => import("@/panes/FunctionStub").then(...))` | BAN in rebuild. Every catalog code without a bespoke pane resolves here. |
| `ui/src/shell/Workspace.tsx` | 37-41 | `const TemplateRenderer = lazy(() => import("@/templates/TemplateRenderer").then(...))` | BAN. Live overlay over hard-coded mock; not used today but still imported. |
| `ui/src/shell/Workspace.tsx` | 45 | `import { hasTemplate } from "@/templates/TemplateRenderer";` | BAN. |
| `ui/src/shell/Workspace.tsx` | 180 | `body = <TemplateRenderer code={code} symbol={symbol} />;` | BAN. |
| `ui/src/shell/Workspace.tsx` | 185 | `body = <FunctionStub leafId={leafId} code={code} symbol={symbol} />;` | BAN. |
| `ui/src/lib/pane-completeness.ts` | 21-24 | `import { DESIGN_BASIC_CODES, DESIGN_PRO_CODES, hasDesignExportComponent } from "@/design-export/showme-design-export";` | BAN the design-export module entirely (kept here only for diagnostics today). |
| `ui/src/lib/pane-completeness.ts` | 25 | `import { listMockCodes, getMockTemplate } from "@/templates/mock-data";` | BAN. |
| `ui/src/lib/pane-completeness.ts` | 26 | `import { listNativeCodes, resolvePane } from "@/functions/registry";` | KEEP (this is the truth source). |
| `ui/src/panes/preferences_pane/index.tsx` | 19 | `import { SettingsDesignExportRenderer } from "@/design-export/showme-design-export";` | LEGITIMATE — Preferences renders the design-export Settings panel as the actual product UI. Rebuild may move this surface inline rather than via design-export, but it is the only honest consumer today. |
| `ui/src/panes/FunctionStub.tsx` | 3 | `export { FunctionStub } from "./function_stub";` | BAN (re-export shim — delete with the rest). |
| `ui/src/panes/function_stub/index.tsx` | (whole file) | `FunctionStub` implementation | BAN — entire `panes/function_stub/` tree. |
| `ui/src/templates/TemplateRenderer.tsx` + `ui/src/templates/mock-data.ts` + `ui/src/templates/registry.ts` + `ui/src/templates/primitives.tsx` + `ui/src/templates/templates.css` | (whole files) | template system | BAN entire `ui/src/templates/` tree. |
| `ui/src/design-export/showme-design-export.tsx` (39024 lines) + `ui/src/design-export/showme-design-export.css` | (whole files) | design-export system | BAN entire `ui/src/design-export/` tree (or migrate `SettingsDesignExportRenderer` into shell first). |
| `ui/src/functions/EQS.tsx` | 153 | comment only ("FunctionStub which already sets `live: true`.") | KEEP (comment), but stale after BAN. |
| `ui/src/functions/registry.tsx` | 3, 8 | comments referencing fallback to FunctionStub | KEEP (comment), update post-rebuild. |
| `ui/src/shell/Sidebar.tsx` | 86 | comment only | KEEP (comment). |
| `ui/src/lib/theme-transition.ts` | 4 | comment only | KEEP (comment). |
| `ui/src/lib/workspace.ts` | 152 | comment only | KEEP (comment). |
| `ui/src/App.tsx` | 125 | comment only | KEEP (comment). |

**Net ban-test count: 13 real production imports across 5 files to be removed before the rebuild is honest.** (Workspace.tsx ×5 references; pane-completeness.ts ×2 imports; preferences_pane uses it legitimately; the stub & template & design-export files themselves are 4 files / N references.)

---

## Functions with significant gaps

### GP
- **Current state:** bespoke pane backed by aliased `_execute_price_history_alias` with yfinance, ccxt_failover, coingecko (longest-history race).
- **Gaps:**
  - No symbology hard pin — same `GP AAPL` resolves to yfinance even when the symbol is also tradeable on Binance; user can't force a provider.
  - No fundamentals overlay (revenue, earnings).
  - No event marker overlay (splits/dividends/earnings dates).
  - No comparison overlay (`GP AAPL vs MSFT vs SPY`).
  - Methodology drawer absent (where do the candles come from? which exchange's session?).
  - Real-time tick uses `useLiveQuote` (StreamHub WS→REST hybrid) but the chart's last candle does not visibly stitch the tick onto an in-progress bar.
- **Production-fakery dependency:** none ✓
- **Required for rebuild:** provider toggle, methodology drawer, event markers, compare overlay, tick→candle stitching.

### HP
- **Current state:** bespoke pane mirroring GP with a wider toolbar.
- **Gaps:** same as GP plus:
  - CSV export exists but no PNG / SVG snapshot export.
  - No volume profile (price-by-volume histogram on right axis).
  - Range/Interval matrix has only 7 intervals; intra-day < 1m missing (tick / 5-tick aggregations).
- **Production-fakery dependency:** none ✓
- **Required for rebuild:** parity with GP plus volume profile, chart-snapshot export.

### DES
- **Current state:** bespoke pane; multi-asset profile (yfinance + coingecko for CRYPTO + finnhub augments).
- **Gaps:**
  - No SEC EDGAR latest-filing tile (we have the adapter; DES doesn't consume it).
  - No analyst-consensus mini-tile (ERV/ANR exist; DES ought to summarise them in-pane).
  - Crypto rail OK; equity rail missing GICS sub-industry, beta-versus-SPX.
- **Production-fakery dependency:** none ✓
- **Required for rebuild:** add SEC, ANR, BETA tiles via in-process consensus calls (no external new providers needed).

### FA
- **Current state:** bespoke; sec_edgar standard fundamentals + yfinance.
- **Gaps:**
  - No XBRL fact ladder (we have standard fundamentals only — 30-50 GAAP tags rather than the full XBRL graph).
  - No segment reporting view (geographic / line-of-business).
  - No filing-original-link rail (10-K/10-Q PDF links).
  - No peer-relative charts.
- **Required for rebuild:** full XBRL ingestion, segment reporting, filing links, peer-compare strip.

### WACC
- **Current state:** bespoke; yfinance + fred + damodaran; surface heat grid for β/Rd.
- **Gaps:**
  - Damodaran ERP feed loads ANNUAL spreadsheet; doesn't expose user-edit of ERP override in pane.
  - Tax rate is per-country reference, not editable.
  - No scenario save/recall.
- **Required for rebuild:** add user-override drawer, scenario presets.

### EQS
- **Current state:** bespoke screener; yfinance.
- **Gaps:**
  - Universe is limited to yfinance-discoverable; no custom universe upload.
  - No save-as-watchlist primary action (you have to copy-paste).
  - No multi-factor weighting UI; current screener is purely filter-based.
- **Required for rebuild:** universe upload, persisted screens, factor weights.

### PORT
- **Current state:** bespoke; cross-credential aggregation, real ccxt + portfolio_state.
- **Gaps:**
  - No FX-normalised performance — positions in non-USD show their native PnL, no portfolio-level performance time series.
  - No risk decomposition (factor exposure, sector weight bars).
  - No drawdown-since-inception tile.
- **Required for rebuild:** equity-curve sparkline, factor-attribution mini, drawdown KPI tile.

### SCAN
- **Current state:** bespoke; ZAK-weighted multi-phase scanner.
- **Gaps:**
  - Universe selection is implicit (server-side); user can't pick "scan only my watchlist".
  - No diff vs previous run (which symbols entered / exited the top 50).
- **Required for rebuild:** universe picker, diff column.

### MIS
- **Current state:** bespoke 23-indicator consensus across 12 timeframes; per-market kalibrasyon tab.
- **Gaps:**
  - Indicator weights are hard-coded TBV3 defaults; user can override but cannot persist scan presets.
  - No scheduled-scan / push-alert path; this is interactive-only.
- **Required for rebuild:** scan presets + alert on threshold.

### WATCH
- **Current state:** bespoke; live last price + change + source per row.
- **Gaps:**
  - No grouping (folders / tags) — flat list only.
  - No per-row alert (must go through ALRT to wire one).
- **Required for rebuild:** grouping, inline alert chip.

### TOP / NI / CN
- **Current state:** bespoke; rss + gdelt + finnhub_news.
- **Gaps:**
  - Headline scoring is heuristic; no real sentiment classifier wired (FinBERT is loaded in `sentiment.py` but TOP / NI don't consume it).
  - No de-dup across providers (same Reuters wire appears 3× when finnhub_news + rss + gdelt all carry it).
  - No symbol-extraction NER; relevance scoring relies on string-match.
- **Required for rebuild:** FinBERT sentiment integration, de-dup, NER.

### INSTANT
- **Current state:** bespoke; ETag-aware RSS poller, audio cue.
- **Gaps:**
  - No transcript-from-audio (`audio_line` flag exists, Whisper is in services/transcription.py, never wired).
  - No latency histogram (only `latency_ms` integers).
- **Required for rebuild:** Whisper hookup, latency distribution chart.

### XSEN
- **Current state:** bespoke; auth-free Brave→syndication scrape + bundled `showme_x_v1` (RoBERTa) 3-task heads (sentiment / emotion / topic).
- **Gaps:**
  - The bundled model is showMe's fine-tune, NOT cardiffnlp/twitter-roberta-base-sentiment as the spec asks. Functionally similar but spec-mismatched.
  - Brave scrape is fragile (Cloudflare changes, no Twitter API).
- **Required for rebuild:** swap to cardiffnlp/twitter-roberta-base-sentiment OR document the showme_x_v1 substitution; add a paid X-API alternative.

### GEX
- **Current state:** bespoke; yfinance options chain + Black-Scholes formula.
- **Gaps:** none structural — chart grammar is correct (bar chart of dealer gamma per strike). Limited by yfinance options coverage (US equity only).

### CORR
- **Current state:** bespoke; full Pearson/Spearman/downside; heat grid + summary cards.
- **Gaps:** none structural — the heat grid is correct chart grammar. Could add eigenvalue/PCA decomposition.

### WIRP
- **Current state:** bespoke; **acknowledged "reference rate probability table" — NO live futures adapter is wired**.
- **Gaps:** the entire `cme_fedwatch` adapter exists in the codebase (used by ECO/GMM) but WIRP does not consume it. The pane is honest about the gap but it's still a missing wiring.
- **Required for rebuild:** wire `deps.cme_fedwatch` to WIRP probabilities.

### BTMM / GLCO / WCRS / ECST
- **Current state:** bespoke charts (lightweight-charts) — OK shape.
- **Gaps:** all yfinance-only; no FRED overlay options.

### ALRT
- **Current state:** bespoke; local alert engine + persistence.
- **Gaps:** no push channel (email/sms/desktop notification). `email_service.py` exists, not wired.

### BOT / BOTS / PERF / STRA / TMPL / BDA / INDX / CONN
- **Current state:** all bespoke sub-systems D/E/F/G/H/I/J — well-shaped.
- **Gaps:** none catalog-blocking. Sub-system K (Github code search + HF classify) is present in `engine/services/` but not surfaced as a user pane.

---

## PASSING (bespoke and structurally honest — listed here so the rebuild can preserve the existing UX)

GP, HP, DES, FA, EQS, PORT, SCAN, MIS, WATCH, ALRT, TOP, NI/CN, INSTANT, XSEN, WEI, MOST, MAP, SECT, AGENT, ANR, ASK, BDA, BOT, BOTS, BTMM, BIO, CORR, CONN, DPF, DVD, ECO, ECST, ECFC, EE, EREV, ESG, GEX, GLCO, INDX, OrderTicket, PERF, STRA, TMPL, TRAN, TRQA, TSAR, WACC, WB, WCRS, WETR, WHAL, WIRP (honest about its model fallback).

---

## CATEGORICALLY STUBBED (every one of these is FunctionStub today)

Bonds: CRVF, GC3D, SRSK, TAUC, YAS, CRPR, DDIS, DEBT, ALLQ.
Equities: FTS, FORM4, CACT, HDS, HFS, PIB, SPLC, DCF, DCFS, DDM, BETA, DARK, RV.
FX: FXH, FXFC, FXIP, FRD, OVDV.
Derivatives: OMON, OVME, IVOL, OSA, HVT, GREEKS.
Macro: GMM, REGM, TRDH, COUN.
Commodities: BOIL, BGAS, NGAS, CPF.
Trade/Exec: TCA, EXEC, AIM, FXGO, BBGT, GRAB.
News: AV, EVTS, NSE, NALRT, SOSC.
Screen: ICX, MICRO, FRH, SRCH, FSRC, CSRC, SECF.
Misc: ONCH, POLY, SAT, CDE, LITM, MOSS, CHGS, APPL, BMC, FLY, DINE, MARS, TRA.
Portfolio: ACCT, MGN, LOTS, TLH, PCAS, PVAR, PFA, REBA, RPAR, PORT_OPT, PORT_WHATIF, STRS, GREEKS, BLAK, BTFW, BTUNE, BMTX, MLSIG, PSC.
Comms: MEET, PEOP, BRIEF, READ, TLDR.
API/Dev: BQL, BQUANT, DAPI, FLDS, ISIN, LANG, KEYB, CATALOG.

Total ≈ 111 codes that ONLY work because of `FunctionStub` rendering the raw JSON. Each of these needs a bespoke pane in the rebuild OR an explicit `<MissingPane>` if the function code is intentionally dropped.
