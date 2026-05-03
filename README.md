# showMe

Native macOS Apple Silicon market cockpit powered by ShowMe's bundled Python
function engine (141 indexed functions, 14 categories). The OS shell and view
layer stay thin; function routing, defaults, provider handling, audit, and
payload quality gates live in Python.

## Layout

```
showMe/
├── src-tauri/   Thin macOS shell: app lifecycle, tray, menubar, deep links
├── src-py/      Python runtime: FastAPI, function routing, quality audit
├── src-ui/      Thin presentation layer: views, controls, layout
├── engine/      Python function engine source/config
├── packaging/   build / sign / notarize / dmg config
└── docs/        architecture, ui_standards, coder_log, engine_independence
```

The app is self-contained: production builds bundle `engine/src` and
`engine/config` into the Python sidecar. `SHOWME_ENGINE_PATH` exists only as a
developer override for testing a different engine tree.

## Quickstart

```bash
# 1 — install front-end deps once
cd src-ui && npm install && cd ..

# 2 — install sidecar deps
cd src-py && python3 -m pip install -e ".[dev]" && cd ..

# 3 — run dev (Tauri spawns sidecar + UI together)
npm run tauri:dev
```

Without the Rust toolchain you can still inspect the UI in browser-mode:

```bash
# in two terminals:
cd src-py && python3 -m showme.server --port 8765
cd src-ui && npm run dev    # http://localhost:5173
```

## Production build

```bash
bash packaging/build_sidecar.sh         # PyInstaller universal2 backend
npm run tauri:build                     # bundles .app + .dmg
APPLE_SIGNING_IDENTITY="Developer ID Application: ..." \
  bash packaging/sign.sh
APPLE_ID=... APPLE_TEAM_ID=... APPLE_APP_SPECIFIC_PASSWORD=... \
  bash packaging/notarize.sh
```

## Quality status

Run the Python function quality audit against a live runtime before handing the
app to a user:

```bash
python3 scripts/audit_functions.py --port 8765 --timeout 18
```

The audit is asset-aware: it tests each function with a compatible crypto,
equity, FX, commodity, bond, or standalone option profile instead of forcing a
single symbol into every function.

## Runtime protocol

The macOS shell discovers the Python runtime port from a single stdout line:
```
SIDECAR_PORT=<u16>
```
Lifecycle: 3× restart with exponential backoff (250 / 750 / 2250 ms), then
fatal alert. SIGTERM → 5 s grace → SIGKILL on quit.

## Native conventions

- Custom titlebar (`Overlay`, hidden title) + macOS traffic lights.
- `app-region: drag` on titlebar; everything `.interactive` opts out.
- NSVisualEffect vibrancy via `windowEffects: ["sidebar","underWindowBackground"]`.
- `~/Library/Application Support/showMe` for state; `~/Library/Logs/showMe`
  symlink for Console.app streaming.
- API keys in macOS Keychain.
