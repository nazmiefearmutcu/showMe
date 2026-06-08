# ShowMe — Page-by-Page Development Campaign (Design)

**Date:** 2026-06-08
**Status:** Approved (user pre-approved before presentation)
**Driver:** Ralph Loop (`/ralph-loop:ralph-loop`), one page per iteration
**Per-iteration engine:** subagent-driven-development (full multi-aspect analysis per page)

## Goal

Develop **every page** of the ShowMe desktop terminal, one page per Ralph
iteration, in priority order. For each page, in a single iteration:

1. **Fix deficiencies** — missing native pane, broken states, bugs, dead controls.
2. **Increase usability** — keyboard/nav, empty/loading/error states, a11y, layout polish.
3. **Assess data sufficiency** — is the backend feeding this page enough real data?
   If insufficient, make it sufficient (wire real providers, fill gaps).
4. **Ensure display quality** — are the user-side renderings adequate and high quality
   (tables, charts, formatting, density, dark-terminal aesthetic)?

When **all pages** are developed, open a single question: *"Should I end the Ralph loop?"*

## Architecture context (why "page" = "function pane")

- ShowMe is a Tauri desktop app: React UI in `ui/`, Python sidecar in `backend/`.
- Navigation is `/fn/{CODE}`. A code resolves through `ui/src/functions/registry.tsx`:
  - **Native pane** (bespoke React component) if registered in `PANES`, **or**
  - **`FunctionStub`** fallback → hits `/api/fn/{code}` and renders the raw payload.
- "Improve a page" therefore means, per code: ensure a high-quality native pane exists,
  its backend feed (`backend/showme/engine/functions/...` + providers) returns real,
  sufficient data, and the rendering is terminal-grade.
- Shell pages live in `ui/src/panes/` (Welcome=HOME, Preferences=Settings) and
  `ui/src/shell/` (Sidebar, Workspace, Statusbar, etc.).

## Per-iteration procedure (the loop body)

Each Ralph iteration handles **exactly one** page via subagent-driven-development:

1. **Explore (parallel subagents)** — fully analyze the page from every aspect:
   - *UI/UX subagent*: the pane component, its states, controls, a11y, tests.
   - *Data subagent*: the backend function + provider(s) feeding it; is the data real,
     complete, fresh? What's stubbed/empty/mocked?
   - *Display-quality subagent*: rendering fidelity vs. a Bloomberg-grade terminal.
2. **Synthesize** — merge findings into a concrete, prioritized deficiency list for that page.
3. **Implement (TDD)** — fix deficiencies + usability + data + display, smallest correct
   changes, tests first where feasible.
4. **Verify** — `npm run build:ui`, run the page's unit tests, lint/typecheck; fix until green.
5. **Review** — a code-reviewer subagent checks the diff; address high-confidence findings.
6. **Commit** — one focused commit per page: `feat(<CODE>): <summary>`.
7. **Mark done** — check the page off in the backlog (`PROGRESS.md` / plan), advance.

## Page backlog (development order, 64 pages)

Order = user visibility/importance first, long-tail analytics last. The
PortfolioAnalytics family (20 codes) shares one pane → one iteration.

### Wave 1 — Core shell & primary workspace (8)
1. HOME — Overview (Welcome.tsx)
2. WATCH — Live Watchlist
3. PORT — Portfolio
4. WEI — Macro Monitor
5. NI — News Desk (CN = Company News alias)
6. SCAN — All Functions
7. MIS — Multi Indicator Scan
8. PREF — Settings (Preferences.tsx)

### Wave 2 — Featured quick analytics (5)
9. GEX — Gamma Exposure
10. FA — Financial Analysis
11. DES — Description
12. BTMM — Rates Environment
13. MOST — Most Active

### Wave 3 — Trading & automation tools (11)
14. INSTANT — Trade Ticket (Instant Squawk Line)
15. ALRT — Alerts
16. STRA — Strategy Editor
17. TMPL — Strategy Templates
18. BOT — Bot Manager
19. BOTS — Bot Supervision
20. PERF — Performance
21. BDA — Bot Dev Assistant
22. INDX — Indicator Index
23. CONN — Connect Exchange
24. TXNS — Trade Blotter

### Wave 4 — Research / AI / market-structure (7)
25. AGENT — Symbol Agent
26. ASK — Ask
27. XSEN — X Sentiment AI
28. CORR — Correlation
29. MAP — Market Heatmap (SECT alias)
30. TOP — Top Movers
31. ECO — Economic Calendar

### Wave 5 — Portfolio analytics family — one pane, 20 codes (1)
32. PORTX — PortfolioAnalyticsPane
    (ACCT, BLAK, BMTX, BTFW, BTUNE, LOTS, MARS, MGN, MLSIG, PCAS, PFA,
     PORT_OPT, PORT_WHATIF, PSC, PVAR, REBA, RPAR, STRS, TLH, TRA)

### Wave 6 — Long-tail bespoke analytics (32, alphabetical by code)
33. AIM  34. ANR  35. BIO  36. CRPR  37. DEBT  38. DPF  39. DVD  40. ECFC
41. ECST 42. EE  43. EMSX 44. EQS  45. EREV 46. ESG  47. GLCO 48. GP
49. HP   50. IVOL 51. MICRO 52. OVDV 53. POLY 54. SAT  55. TCA  56. TRQA
57. TSAR 58. TSOX 59. WACC 60. WB   61. WCRS 62. WETR 63. WHAL 64. WIRP

## Definition of done (per page)

- Native pane renders real backend data (no placeholder/empty unless genuinely no data,
  and then an honest, well-designed empty state).
- Loading + error + empty states all present and styled.
- Display is terminal-grade: correct number formatting, sensible density, dark theme,
  responsive within the pane chrome.
- `npm run build:ui` clean; page's tests pass; new tests cover the changes.
- One commit per page; backlog entry checked off.

## Definition of done (campaign)

All 64 backlog entries checked off → ask the user: **"Should I end the Ralph loop?"**
Do not self-terminate the loop; wait for the user's decision.

## Non-goals

- No rebrand / no new top-level features beyond the existing page set.
- No backend rewrites beyond what a page's data sufficiency requires.
- No unrelated refactors; stay scoped to the page under development each iteration.
