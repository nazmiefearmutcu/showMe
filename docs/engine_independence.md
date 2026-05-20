# ShowMe Engine Independence

> Last updated: 2026-05-11 (Round 2C, post-Round-34 monorepo refactor).

## Principle

* ShowMe owns its function engine under `backend/showme/engine/`;
  production builds do not depend on any sibling checkout.
* Features that originated elsewhere are exposed as normal ShowMe functions or
  dedicated ShowMe panes, with the same symbol contract as every other
  function.
* Runtime imports resolve through the standard Python import system —
  the engine is a regular `showme.engine` subpackage, no `sys.path`
  injection. (Pre-Round-34 the engine lived at `engine/src` and was
  prepended to `sys.path` by the sidecar; that mode is retired and the
  history table below is **historical**, not current.)
* PyInstaller `--collect-submodules('showme')` bundles the entire
  subpackage tree into the shipped binary; `backend/config/` is added
  via `--add-data` in `backend/showme-backend.spec`.

## Function-by-function migration table

Each row tracks how a backend capability surfaces in the native shell. Filled
in as we ship.

| Backend capability        | showMe surface                          | Round | Notes |
| ------------------------ | --------------------------------------- | ----- | ----- |
| `/`                      | Splash window (current)                 | 12    | Replaced by GoldenLayout in 15. |
| `/symbol/<sym>/DES`      | Function pane `panes/des`               | 14    | First pinned screenshot. |
| `/symbol/<sym>/FA`       | Function pane `panes/fa`                | 14    | |
| `/symbol/<sym>/GP`       | Function pane `panes/gp` (TradingView) | 14    | Lightweight Charts. |
| `/screener/equity`       | Function pane `panes/eqs`               | 14    | DSL editor stays. |
| `/portfolio`             | Function pane `panes/port`              | 14    | |
| `/news`                  | Pane `panes/top` + tray latest          | 16    | |
| `/risk`                  | Pane `panes/risk`                       | 17    | |
| `/stress`, `/pcas`       | Risk lab pane                           | 17    | |
| `/tca`, `/exec`          | Trader's blotter pane                   | 17    | |
| `/jobs`                  | Native preferences pane                 | 18    | NOT a window — Settings. |
| `/latency`               | Status menu (tray dropdown)             | 18    | Not a pane — tray peek. |
| `/settings`              | NSWindow Preferences (Cmd+,)            | 13    | Native pref window. |
| `/auth/login` (passkey)  | Touch ID prompt + Keychain              | 20    | LAContext. |
| `/help`                  | Help menu → web view                    | 23    | Cmd+? overlay. |
| `/api/v1/*`              | Direct sidecar fetch                    | 12    | Path-import mode. |
| `/ws/*`                  | Sidecar websocket → Tauri event re-broadcast | 16 | |
| Static `/static/*`       | Bundled in `src-ui/public`              | 13    | (only the assets we keep). |

## State Import

| Source path                                  | showMe path                                                      | When            |
| ------------------------------------------ | ----------------------------------------------------------------- | --------------- |
| `runtime/portfolio.json`                    | `~/Library/Application Support/showMe/data/sqlite/portfolio.db`  | Round 22 (one-shot importer) |
| `runtime/state.json`                        | read-only mirror, then imported copy                              | Round 22        |
| `runtime/multi_scan_results.json`           | `state/scans/<scan_id>.json` + `scan_runs` SQLite index           | Round 17        |
| `runtime/orders.sqlite`                     | `data/sqlite/orders.sqlite`                                       | Round 17        |
| `runtime/exec_monitor.sqlite`               | `data/sqlite/exec_monitor.sqlite`                                 | Round 17        |
| `runtime/transcripts.sqlite`                | `data/sqlite/transcripts.sqlite`                                  | Round 17        |
| `runtime/people.sqlite`                     | `data/sqlite/people.sqlite`                                       | Round 17        |
| `runtime/tax_lots.sqlite`                   | `data/sqlite/tax_lots.sqlite`                                     | Round 17        |
| `.env` API keys                            | macOS Keychain entries (`app.showme.terminal/<name>`)             | Round 20        |

`docs/round_notes/<round>.md` records the importer command + checksum.

## What we **do not** migrate

* The legacy `_auto_scan_market` cron is replaced by the Scanner Agent (see
  Rapor 2 §7). The ZAK weight matrix is preserved verbatim, the lock /
  atomic-write / saturation logic is reused, only the kripto-specific
  `SKIP_SYMBOLS` is widened to multi-asset.
* `dashboard/templates/*` — wholesale replaced by React components. Each
  template's behavior is captured in `docs/round_notes/<round>.md` so the
  reasoning isn't lost.
* `dashboard/static/css/bloomberg.css` — replaced by `tokens.css`. Color
  decisions copied 1:1 (the Bloomberg-orange is preserved at `#FF7A00`).

## Compatibility Contract

Every function listed by `/api/function-index` (live: 141 functions, baseline
≥138) must execute through `/api/fn/{code}` for crypto, equity, FX,
commodity, bond and option representative symbols. Generated compatibility
reports live under `artifacts/showme-function-audit/<utc-stamp>/`.
