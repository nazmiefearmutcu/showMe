# showMe — Architecture

> Last updated: 2026-05-11 (Round 2C, post-Round-34 monorepo refactor).
> Function/indicator/pane counts are the live values; if they drift, run
> `npm run audit:functions` and update.

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
│  │  React + Vite          │  │  • imports showme.engine.*       │  │
│  │  Tailwind tokens       │  │  • localhost:<discovered_port>   │  │
│  │  zustand store         │  │  • /api/health, /function-index, │  │
│  │  CommandPalette,       │  │    /fn/{code} (current)          │  │
│  │  panes, tray menu      │  └─────────────┬────────────────────┘  │
│  └──────┬─────────────────┘                │                       │
│         │ http://127.0.0.1:<port>          │ regular subpackage    │
│         ▼                                  ▼                       │
│      sidecar HTTP                  backend/showme/engine/          │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

## Why three processes

* **Tauri main (Rust)** — the only process allowed to touch Cocoa APIs.
  Owns native UX: menus, tray, badge, vibrancy, hotkeys, secure enclave.
* **WKWebView (JS)** — pure presentation. Always runs inside Tauri, never as
  a standalone browser tab in production. Falls back to browser-mode for
  designers via `npm run dev`.
* **Python sidecar** — loads the **141-function** bundled ShowMe engine
  (live `/api/function-index`; baseline ≥138). Sidecar dies → Rust restarts
  (3× exp-backoff) → user sees `crashed` pill + NSAlert if all retries fail.

## Bootstrap sequence

1. `Builder::setup` mounts plugins, builds `AppState`, creates the
   `~/Library/Application Support/showMe` layout (`filesystem::ensure_layout`).
2. `sidecar::spawn` shells out to `python3 -m showme.server --port 0`
   (dev) or `MacOS/showme-backend --port 0` (release). It also mints a
   per-boot `SHOWME_AUTH_TOKEN` and exports it to the child + emits
   `sidecar:auth_token` so the renderer can attach `X-ShowMe-Token` to
   every HTTP/WS call (ARCH-05 P2).
3. The sidecar prints `SIDECAR_PORT=<u16>` once uvicorn binds. The shell
   parses that line, stashes the port in `AppState.sidecar_port`, and
   emits `sidecar:port` + `sidecar:status:healthy` to the webview.
4. `tray::install`, `menu::install`, `dock::install`, `shortcuts::register`,
   `deeplink::register`, `window::restore_state` — independent subsystems,
   no ordering constraint.
5. UI: `bootstrapSidecarPort()` → `fetchHealth()` → `fetchFunctionIndex()`.

## Bundled engine

The engine is a **regular Python subpackage** (`from showme.engine.X import Y`)
since the May 2026 unification refactor — no more `sys.path` injection.
Production PyInstaller output bundles `backend/showme/engine/` and
`backend/config/` via the spec at `backend/showme-backend.spec`. The
`SHOWME_ENGINE_PATH` env var is still published for any engine-side code
that needs to find adjacent YAML configs but is no longer prepended to
`sys.path`.

* `backend/showme/engine/indicators/` — 23 first-class indicators (count
  is `*.py` files minus `__init__.py` and `base.py`).
* `backend/showme/engine/functions/` — 141 functions in 14 categories
  (count is the live `/api/function-index` response).
* `ui/src/functions/` — 30 React panes, one per primary function group.
* `/api/function-index` exposes imported capabilities as ShowMe functions.
* Compatibility audits run every listed function against representative
  crypto, equity, FX, commodity, bond and option symbols.

## Failure modes

| Failure                          | Detection                                | Response                                 |
| -------------------------------- | ---------------------------------------- | ---------------------------------------- |
| Sidecar exits ≤ 3 s after boot   | child stdout closes early                | retry exp-backoff 250 / 750 / 2250 ms    |
| Sidecar prints no `SIDECAR_PORT` | line scanner timeout (Round 13)          | mark `crashed`, NSAlert                  |
| Port unreachable                 | UI fetch fails                           | `crashed` pill + retry banner            |
| Window state corrupt             | JSON parse fail in `window::restore_state` | log + ignore, fall back to default size |
| Deep link before main window     | `deeplink::register` checks `get_webview_window` | spawn main window then forward     |
| Rust panic anywhere              | `std::panic::set_hook` in `lib.rs`       | write `<app_data>/logs/crash/panic-<ts>.log` + emit `app:panic` |

## Subsystem files (under `tauri/src/`)

* `sidecar.rs` — child-process supervisor. Single source of truth for
  retry, shutdown, and `SHOWME_AUTH_TOKEN` minting.
* `filesystem.rs` — Application Support tree creator. Idempotent. Verifies
  `~/Library/Logs/showMe` is a symlink to our logs dir and rejects
  pre-existing entries that would let an attacker harvest log lines.
* `tray.rs` / `menu.rs` / `dock.rs` — native chrome.
* `shortcuts.rs` — global hotkeys (⌘⇧S, ⌘⇧K, ⌘⇧A).
* `deeplink.rs` — `showme://` URL routing with strict allow-list parsing
  + `dev/*` verbs disabled in release.
* `biometric.rs` — Touch ID / passcode bridge with single-use HMAC-style
  tokens (5-min TTL) gating privileged Tauri commands.
* `commands.rs` — every `tauri::command` exposed to JS, fronted by
  per-handler token-bucket rate limits in `ipc.rs`.
* `window.rs` — multi-window state persistence, atomic write.
* `ipc.rs` — rate-limit registry + (future) WS re-broadcast helpers.
* `secrets.rs` — Keychain CRUD; sensitive reads gated by biometric token.
* `presets.rs` — layout-preset filesystem store with strict name allow-list.
* `notifications.rs` — UNUserNotificationCenter bridge with severity gate.

## Frontend layering

```
ui/src/
├── main.tsx          ← entry, mount, kill default contextmenu
├── App.tsx           ← shell composition, sidecar bootstrap
├── shell/            ← Titlebar, Sidebar, Statusbar
├── command-palette/  ← ⌘K modal
├── panes/            ← Splash, Welcome, Preferences, FunctionStub (4 today)
├── functions/        ← per-function React components (30 today)
├── lib/
│   ├── tauri.ts      ← façade — silent no-op outside Tauri
│   ├── sidecar.ts    ← typed HTTP client to the Python sidecar
│   └── store.ts      ← zustand singleton store
├── design-system/    ← Round 13+ design tokens + primitives
├── styles/           ← Tailwind layer + tokens.css custom props
└── i18n/             ← 12 dil (Round 24+)
```

Tauri-specific code is isolated to `ui/src/lib/tauri.ts` so designers
can run `npm run dev` in the browser and inspect components without the
Rust toolchain.
