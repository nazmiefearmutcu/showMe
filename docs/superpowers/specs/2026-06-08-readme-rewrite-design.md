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
| Primary audience | Balanced general open-source (users *and* developers) |
| Language | English |
| Visual scope | Custom SVG hero banner + existing 4 screenshots + badges + mermaid diagram |
| Structure | Approach A — product-first, progressive depth (`<details>` for heavy dev sections) |

### Bloomberg-naming policy (explicit user instruction)

Reduce Bloomberg references overall, but name Bloomberg **exactly once**, deliberately, in the
positioning line — to communicate what league the project is aiming at. Everywhere else,
describe showMe on its own terms ("a market terminal for macOS", "type a short code to open a
function"), with no "Bloomberg-style" filler.

- ✅ Positioning sentence: "…the kind of professional terminal workflow you'd otherwise pay for
  in a Bloomberg Terminal — open-source, on your own Mac." (one occurrence)
- ❌ No other "Bloomberg" mentions in hero, feature catalog, architecture, etc.

## 3. Verified canonical numbers (single source of truth)

Derived directly from the assembled data structures, **not** raw seed lists.

| Metric | Value | Source |
| --- | --- | --- |
| Symbols scanned | **3,375** (Crypto 381 · Equity 2,461 · ETF 416 · FX 68 · Commodity 32 · Bond 17) | `backend/showme/mis.py` → `MIS_UNIVERSES` |
| Asset classes / markets | **6** | `MIS_UNIVERSES` keys |
| Timeframes | **12** | `MARKET_DEFAULT_TFS` |
| Technical indicators | **23** | `backend/showme/engine/indicators/` (24 files − `base.py`) |
| Function codes | **~138** | grep of `backend/showme/engine/functions/` distinct codes |
| UI languages | **12** | `ui/src/i18n/*.json` |

Note: the function count drifts as functions are added; README will say "**140+ functions**" or
"**~138 functions**" and reference `npm run audit:functions` as the live check, rather than a
brittle exact number. The "3,375" figure is the assembled-universe truth (the old "3 370" was
coincidentally close; the Explore agent's "4,393" was wrong — it summed pre-dedup raw lists).

## 4. Final structure (Approach A)

1. **Hero** — custom SVG banner (terminal-style `showMe` wordmark + tagline), one-line value
   prop, badge row (license · platform · Tauri · Python · React · tests), quick-nav links.
2. **What is showMe?** — honest elevator pitch (3–4 sentences). A market terminal for macOS;
   100% local; no subscription, no broker lock-in. The two core ideas: (a) the MIS multi-asset
   scanner, (b) the function-code terminal. Positioning sentence with the single Bloomberg mention.
3. **Preview** — the 4 existing screenshots (cockpit · MIS scan · function palette · symbol view)
   with honest captions.
4. **Two core ideas** — the "genuinely explains it" section:
   - **MIS — Multi-Indicator Scan:** the ZAK weighting matrix; 3,375 symbols · 6 markets · 12
     timeframes · 23 indicators → a weighted-consensus BUY/SELL ranking. Explain consensus +
     confidence honestly.
   - **The function terminal:** type a short code into the command palette to open a function;
     ~138 functions spanning equities, options, bonds, FX, commodities, macro, news, portfolio.
5. **Function catalog** — table grouped by category with representative codes + one-line
   descriptions, wrapped in `<details>` so it is scannable.
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
"Bloomberg-style" phrasing.

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
- [ ] The function-code terminal concept is clearly explained for a non-expert reader.
- [ ] Bloomberg is named exactly once, in the positioning sentence; no other mentions.
- [ ] "What it is / is NOT" section present and honest (paper trading, macOS ARM64, local, MIT).
- [ ] Hero banner SVG renders on GitHub; all 4 screenshots referenced with honest captions.
- [ ] Heavy dev sections (full catalog, project tree) collapsed behind `<details>`.
- [ ] Stale/internal notes removed.
- [ ] `README.md` renders cleanly on GitHub (valid markdown + mermaid + `<details>` + `<img>`).
