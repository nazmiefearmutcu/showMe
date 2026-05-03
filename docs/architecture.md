# showMe — Architecture

## Process model

```
┌──────────────────────────── showMe.app ────────────────────────────┐
│                                                                    │
│  ┌─────────── Tauri main (Rust) ───────────┐                       │
│  │  • lifecycle, NSMenuBar, NSStatusItem,  │                       │
│  │    NSDockTile, deep links, hotkeys,     │                       │
│  │    LocalAuthentication bridge           │                       │
│  │  • spawn / supervise sidecar            │                       │
│  └─────────┬─────────────────┬─────────────┘                       │
│            │ tauri::invoke   │ subprocess (stdin/stdout)           │
│            ▼                 ▼                                     │
│  ┌──── WKWebView (UI) ────┐  ┌── Python sidecar (FastAPI) ──────┐  │
│  │  React + Vite          │  │  • imports bundled engine src.*  │  │
│  │  Tailwind tokens       │  │  • localhost:<discovered_port>   │  │
│  │  zustand store         │  │  • /api/health, /function-index, │  │
│  │  CommandPalette,       │  │    /proxy/* (round-12 stand-in)  │  │
│  │  panes, tray menu      │  └─────────────┬────────────────────┘  │
│  └──────┬─────────────────┘                │                       │
│         │ http://127.0.0.1:<port>          │ pip-installed         │
│         ▼                                  ▼                       │
│      sidecar HTTP                     ./engine/src                 │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

## Why three processes

* **Tauri main (Rust)** — the only process allowed to touch Cocoa APIs.
  Owns native UX: menus, tray, badge, vibrancy, hotkeys, secure enclave.
* **WKWebView (JS)** — pure presentation. Always runs inside Tauri, never as
  a standalone browser tab in production. Falls back to browser-mode for
  designers via `npm run dev`.
* **Python sidecar** — loads the 138-function bundled ShowMe engine. Sidecar
  dies → Rust restarts (3× exp-backoff) → user sees `crashed` pill + NSAlert
  if all retries fail.

## Bootstrap sequence

1. `Builder::setup` mounts plugins, builds `AppState`, creates the
   `~/Library/Application Support/showMe` layout (`filesystem::ensure_layout`).
2. `sidecar::spawn` shells out to `python3 -m showme.server --port 0`
   (dev) or `MacOS/showme-backend --port 0` (release).
3. The sidecar prints `SIDECAR_PORT=<u16>` once uvicorn binds. The shell
   parses that line, stashes the port in `AppState.sidecar_port`, and
   emits `sidecar:port` + `sidecar:status:healthy` to the webview.
4. `tray::install`, `menu::install`, `dock::install`, `shortcuts::register`,
   `deeplink::register`, `window::restore_state` — independent subsystems,
   no ordering constraint.
5. UI: `bootstrapSidecarPort()` → `fetchHealth()` → `fetchFunctionIndex()`.

## Bundled Engine

The sidecar prepends `SHOWME_ENGINE_PATH` (default `./engine`) to `sys.path`
before `import src.services...`. Source builds and packaged builds use the
same contract:

* `engine/src` and `engine/config` are part of the ShowMe project.
* Production PyInstaller output bundles those directories with `--add-data`.
* `/api/function-index` exposes imported capabilities as ShowMe functions.
* Compatibility audits run every listed function against representative
  crypto, equity, FX, and commodity symbols.

## Failure modes

| Failure                          | Detection                                | Response                                 |
| -------------------------------- | ---------------------------------------- | ---------------------------------------- |
| Sidecar exits ≤ 3 s after boot   | child stdout closes early                | retry exp-backoff 250 / 750 / 2250 ms    |
| Sidecar prints no `SIDECAR_PORT` | line scanner timeout (Round 13)          | mark `crashed`, NSAlert                  |
| Port unreachable                 | UI fetch fails                           | `crashed` pill + retry banner            |
| Window state corrupt             | JSON parse fail in `window::restore_state` | ignore, fall back to default size      |
| Deep link before main window     | `deeplink::register` checks `get_webview_window` | spawn main window then forward     |

## Subsystem files

* `sidecar.rs` — child-process supervisor. Single-source-of-truth for retry
  & shutdown logic.
* `filesystem.rs` — Application Support tree creator. Idempotent.
* `tray.rs` / `menu.rs` / `dock.rs` — native chrome.
* `shortcuts.rs` — global hotkeys (⌘⇧S, ⌘⇧K, ⌘⇧A).
* `deeplink.rs` — `showme://` URL routing.
* `biometric.rs` — Touch ID stub (round 20 wires LAContext).
* `commands.rs` — every `tauri::command` exposed to JS.
* `window.rs` — multi-window state persistence.
* `ipc.rs` — helpers for the JS ↔ sidecar HTTP path.

## Frontend layering

```
src-ui/src/
├── main.tsx          ← entry, mount, kill default contextmenu
├── App.tsx           ← shell composition, sidecar bootstrap
├── shell/            ← Titlebar, Sidebar, Statusbar
├── command-palette/  ← ⌘K modal
├── panes/            ← Splash today, GoldenLayout panes Round 15+
├── functions/        ← per-function React components (Round 14+)
├── lib/
│   ├── tauri.ts      ← façade — silent no-op outside Tauri
│   ├── sidecar.ts    ← typed HTTP client to the Python sidecar
│   └── store.ts      ← zustand singleton store
├── design-system/    ← Round 13 design tokens + primitives
├── styles/           ← Tailwind layer + tokens.css custom props
└── i18n/             ← 12 dil (Round 24+)
```

Tauri-specific code is isolated to `src-ui/src/lib/tauri.ts` so designers
can run `npm run dev` in the browser and inspect components without the
Rust toolchain.
