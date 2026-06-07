# showMe — README Rewrite Design

**Date:** 2026-06-08
**Author:** Nazmi Efe Armutcu (with Claude Code)
**Goal:** Rewrite `README.md` from start to finish so it *genuinely* explains what showMe
is and does, with strong visual design — for a balanced general open-source audience, in English.

---

## 1. Problem with the current README

The current `README.md` (10 KB) is dense and developer-leaning, and has several issues:

1. **The signature feature is never explained.** showMe's defining idea — a *function-code
   terminal* where you type a short code (`GEX`, `FA`, `WIRP`) to open an analyst function —
   is nowhere described. A reader unfamiliar with professional trading terminals has no idea
   what the function codes mean or why they matter.
2. **Internal/stale noise.** A "2026-05-25 rebuild" changelog blockquote, a "Last updated:
   2026-05-25" line, and a "Refactor history" section are maintainer notes, not reader value.
3. **Numbers need verification.** Claims like "141-function engine" and "3 370 symbols" must
   match the actual code (see §3).
4. **No honest positioning.** Nothing states clearly that it is paper-trading, macOS-only,
   and local-first — trust signals that matter for a finance tool.
5. **Over-reliance on one comparison.** "Bloomberg-style" is used as a crutch throughout
   instead of describing the product on its own terms.

## 2. Audience, language, design decisions (confirmed with user)

| Decision | Choice |
| --- | --- |
| **Core framing** | **showMe is introduced as a financial terminal** — a function-driven market workstation. The MIS scanner is **removed from the README entirely**. |
| Primary audience | Balanced general open-source (users *and* developers) |
| Language | English |
| Visual scope | Custom SVG hero banner + existing 4 screenshots + badges + mermaid diagram |
| Structure | Approach A — product-first, progressive depth (`<details>` for heavy dev sections) |

### Identity / framing policy (explicit user instruction)

**The MIS Multi-Indicator Scan is removed from the README completely** — no dedicated section, no
catalog entry, no marquee entry, no scan screenshots, and none of its scan-specific numbers
(3,375 symbols / 12 timeframes / 23 indicators / consensus ranking). It is not mentioned at all.

The README's single, top-level identity is: **a financial terminal you drive by typing function
codes.** There is no "two pillars" framing, no scanner-as-hero framing, and no scanner present.
Other genuine functions that happen to involve screening or heatmaps (e.g. `SECT` sector heatmap,
`ICX` industry explorer) may still appear in the catalog as ordinary functions, but the README is
never built or labelled around "scanning."

### Bloomberg-naming policy (explicit user instruction)

Reduce Bloomberg references overall, but name Bloomberg **exactly once**, deliberately, in the
positioning line — to communicate what league the project is aiming at. Everywhere else,
describe showMe on its own terms ("a market terminal for macOS", "type a short code to open a
function"), with no "Bloomberg-style" filler.

- ✅ Positioning sentence: "…the kind of professional terminal workflow you'd otherwise pay for
  in a Bloomberg Terminal — open-source, on your own Mac." (one occurrence)
- ❌ No other "Bloomberg" mentions in hero, feature catalog, architecture, etc.

## 3. Verified canonical numbers (single source of truth)

Derived directly from the code, **not** raw seed lists.

Terminal-level identity numbers (the only numbers the README leads with):

| Metric | Value | Source |
| --- | --- | --- |
| Function codes | **~138** | grep of `backend/showme/engine/functions/` distinct codes |
| Asset classes covered | **6** (equities, options, bonds, FX, commodities, crypto) | engine function folders: `equity` · `derivative` · `bond` · `fx` · `commodity` + crypto coverage |
| Function categories | **14** | `backend/showme/engine/functions/` subfolders |
| UI languages | **12** | `ui/src/i18n/*.json` |

Note: the function count drifts as functions are added; README will say "**140+ functions**" or
"**~138 functions**" and reference `npm run audit:functions` as the live check, rather than a
brittle exact number.

**Excluded numbers (scanner-specific, do NOT use anywhere):** 3,375 symbols, 12 timeframes,
23 indicators, consensus/ZAK ranking — all tied to the removed MIS scanner.

## 4. Final structure (Approach A)

1. **Hero** — custom SVG banner (terminal-style `showMe` wordmark + tagline), one-line value
   prop ("**a financial terminal for macOS**"), badge row (license · platform · Tauri · Python ·
   React · tests), quick-nav links.
2. **What is showMe?** — honest elevator pitch (3–4 sentences), framed as **a financial
   terminal**: a local, open-source market workstation you drive by typing short *function codes*.
   ~138 functions span equities, options, bonds, FX, commodities, macro, news, and portfolio.
   100% local; no subscription, no broker lock-in. Positioning sentence with the single Bloomberg
   mention. **No "scanner" framing here.**
3. **Preview** — **3** existing screenshots only: cockpit · function palette · symbol view, with
   honest captions. **The two MIS scan screenshots (`02-mis-scan.png`, `04-mis-scan.png`) are NOT
   used.** Lead with cockpit + function palette (the terminal identity).
4. **How the terminal works** — the single "genuinely explains it" section, all about the
   function-code model:
   - The command palette: type a code → a function opens. Explain the mental model for a reader
     who has never used a professional terminal.
   - A curated **marquee grid of ~12 representative function codes** *inline* (not collapsed),
     each with a one-line gloss, chosen to show breadth across categories — e.g. `FA` financials,
     `GEX` gamma exposure, `WIRP` rate-hike odds, `ESG` scores, `CORR` correlation matrix,
     `PORT` portfolio analytics, `ECO` economic calendar, `YAS` yield & spread, `OMON` option
     monitor, `DCF` discounted cash flow, `GMM` global macro movers, `BRIEF` daily briefing.
   - **`MIS` is NOT in this grid.** No scan/consensus language anywhere in this section.
5. **Full function catalog** — the *complete* table grouped by category (equities · options ·
   bonds · FX · commodities · macro · news · portfolio · screen · trade · misc) with codes +
   one-line descriptions, wrapped in `<details>`. **`MIS` is omitted from the catalog.** Other
   screen-category functions (`SECT`, `ICX`, `MAP`, `MICRO`, `FRH`) may remain as ordinary
   functions, but the category is labelled neutrally (e.g. "Screen") — never "scanner."
6. **Honest by design** — the real differentiator:
   - data-mode pill + strict-zero gate (live vs modeled-data transparency; shows
     `PROVIDER_UNAVAILABLE` instead of fake data).
   - **What showMe is / is NOT** — paper trading (not a live broker by default), macOS ARM64,
     local-only, MIT, no warranty.
7. **Architecture** — keep the existing mermaid diagram (Tauri shell · React UI · FastAPI
   sidecar + engine) with brief prose.
8. **Tech stack** — compact table (Tauri 2/Rust · React 18/Vite/Tailwind/zustand · FastAPI/
   Python 3.11+ · PyInstaller · DuckDB/Polars).
9. **Data sources** — yfinance · Binance · FRED · SEC EDGAR · GDELT · OpenFIGI · Treasury ·
   CME-FedWatch math, etc. Most are keyless/live; note which need keys.
10. **AI features (opt-in)** — FinBERT sentiment · Whisper transcription · X sentiment · LLM
    assistant. Explicitly opt-in; state what each requires (API key / local model).
11. **Get started** — Download (link to GitHub Releases v0.1.1), Quickstart (dev), browser-mode
    (no Rust toolchain), build-from-source, production build (sign/notarize).
12. **Project layout** — the directory tree, wrapped in `<details>`.
13. **Development & testing** — test/lint/audit commands; link CONTRIBUTING.md, SECURITY.md.
14. **License + footer** — MIT, author, repo.

### Removed from current README

"2026-05-25 rebuild" blockquote · "Last updated" line · "Refactor history" section · scattered
"Bloomberg-style" phrasing · **the entire MIS / Multi-Indicator Scan feature** (its screenshots,
its 3,375-symbol / 12-TF / 23-indicator numbers, and the "what's moving together" scan pitch in
the current hero tagline).

## 5. Hero banner (new asset)

- Format: **SVG** committed to `docs/assets/hero.svg` (retina-crisp, no external dependency,
  renders inline on GitHub via `<img>`).
- Direction: terminal aesthetic — monospace `showMe` wordmark, accent orange `#dc5721`
  (the existing shell brand color), dark terminal background with a subtle sector heat-strip /
  candlestick motif and the tagline. Width ~1200px, ~ 2.5:1 ratio.
- Fallback: `alt` text describing the banner for accessibility.

## 6. Out of scope

- No code changes (README + one SVG asset only).
- No new screenshots / GIF (existing 4 screenshots reused).
- No translation of the README (English only; the *app* remains 12-language).
- No CI/release changes.

## 7. Acceptance criteria

- [ ] Every numeric claim matches §3 (or uses the soft "140+/~138 + audit command" form).
- [ ] showMe is introduced as **a financial terminal** (function-code workstation) in the hero
      and the "What is" section — this is the single top-level identity.
- [ ] The function-code terminal concept is clearly explained for a non-expert reader.
- [ ] **The MIS scanner is removed entirely:** the string "MIS" and the words scan/scanner/
      consensus/ZAK do not appear; no scan screenshots; no 3,375 / 12-timeframe / 23-indicator
      numbers; no section built around scanning.
- [ ] A curated marquee grid of ~12 representative function codes (excluding MIS) appears inline.
- [ ] Bloomberg is named exactly once, in the positioning sentence; no other mentions.
- [ ] "What it is / is NOT" section present and honest (paper trading, macOS ARM64, local, MIT).
- [ ] Hero banner SVG renders on GitHub; all 4 screenshots referenced with honest captions.
- [ ] Heavy dev sections (full catalog, project tree) collapsed behind `<details>`.
- [ ] Stale/internal notes removed.
- [ ] `README.md` renders cleanly on GitHub (valid markdown + mermaid + `<details>` + `<img>`).
