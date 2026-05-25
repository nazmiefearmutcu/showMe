# showMe Rebuild — Operator Guide ("What Changed and Why")

**Audience:** the next engineer (or the user) walking into the repo after the rebuild started.
**Tarih:** 2026-05-24

---

## TL;DR — what's different now

| Surface | Before | After |
|---------|--------|-------|
| Function contract | implicit — each pane invented its own envelope; backend returned whatever | explicit — every function declares a `FunctionManifest` (Py + TS, identical schema); backend handlers populate `output_contract.must_have`; frontend derives controls from the manifest |
| Data honesty | `status="ok"` even when payload was synthetic / empty / placeholder | `DataMode` enum: `live_official` / `live_exchange` / `delayed_reference` / `modeled` / `cached_snapshot` / `provider_unavailable` / `not_configured`. The pane header shows the pill, sources list, latency. |
| Production fakery | `FunctionStub` rendered raw JSON for ~111 codes; `TemplateRenderer` layered live payload on mock template; `design-export` panes were a separate parallel render tree | Banned. Test `tests/test_production_fakery_banned.py` ratchets the violation count down. Initial baseline = 8 violations across 4 files. Strict-zero test ready to flip on when count hits 0. |
| Provider layer | ad-hoc httpx calls scattered across handlers, hidden in functools.cache wrappers | `backend/showme/providers/` — 8 adapters (SEC EDGAR, FRED, TreasuryDirect, OpenFIGI, Binance, yfinance, GDELT, RSS) behind one ABC. Each has `auth_state()`, `last_latency_ms()`, `mode()`. Shared `httpx.AsyncClient`. Registered at server startup. |
| Local cache | scattered SQLite + functools.lru | `backend/showme/analytical/` — single DuckDB DB at `<state>/analytical.duckdb` with schemas `cache.*`, `snapshot.*`, `audit.*`, `research.*`. Polars used for transforms. |
| Chart grammar | many panes plotted "row index vs metric" — wrong for correlation (heatmap), GEX (strike ladder), CRVF (tenor curve) | Manifest's `chart_grammar.kind` is the contract. Test `tests/test_chart_grammar.py` enforces appropriate grammars. CORR/PORT_OPT/GEX seeds assert this in semantic tests. |
| UI integration shell | each pane wired everything by hand | `ui/src/manifest/ManifestPane.tsx` — derives header, controls, mode pill, sources strip, warnings, next actions from manifest. Bespoke panes can use `customRenderer` prop and keep their chart while gaining the contract envelope for free. |

---

## Directory map (rebuild additions)

```
backend/showme/
├── manifest/                        # NEW — single source of truth
│   ├── enums.py                     # Category, AssetClass, DataMode, ControlKind, ChartKind
│   ├── spec.py                      # FunctionManifest + 15 supporting pydantic v2 models
│   ├── registry.py                  # ManifestRegistry + REGISTRY singleton + @manifest()
│   └── seeds/
│       ├── __init__.py              # load_seeds() — imports all seeds so they self-register
│       ├── _example_gp.py           # ← retired by gp_seed.py during Wave 1
│       ├── gp_seed.py               # Wave 1 seed: GP
│       ├── hp_seed.py               # ... etc per Wave 1 plan
│       └── (one file per code)
├── providers/                       # NEW — adapter layer
│   ├── base.py                      # ProviderAdapter ABC + DataMode enum + AdapterError
│   ├── _http.py                     # shared httpx.AsyncClient + aclose_shared()
│   ├── registry.py                  # AdapterRegistry + REGISTRY + chain()
│   ├── sec_edgar.py, fred.py, treasury_direct.py, openfigi.py
│   ├── binance.py, yfinance_adapter.py, gdelt.py, rss_news.py
│   ├── seed_register.py             # register_all_adapters() — auto-called on import
│   └── seed_register_batch2.py      # (Binance/yfinance/GDELT/RSS register module)
├── analytical/                      # NEW — DuckDB + Polars local core
│   ├── duck.py                      # DuckPool + connection() + close()
│   ├── frames.py                    # resample_ohlcv, join_asof, rolling_mean, correlation_matrix, ...
│   ├── cache.py                     # cache_key + write/read with TTL
│   ├── snapshots.py                 # pane output snapshots for research
│   └── audit.py                     # state-changing event log
└── server_routes/
    └── manifest.py                  # NEW — GET /api/manifest, GET /api/manifest/{code}

ui/src/
└── manifest/                        # NEW — TS mirror + integration
    ├── types.ts                     # mirror of pydantic schema (string enums, snake_case)
    ├── registry.ts                  # ManifestStore + useManifest(code) + fetchManifests()
    ├── derive-controls.tsx          # FunctionManifest → JSX[]
    ├── derive-renderers.tsx         # FunctionManifest → { chart, table, cards }
    ├── controls/                    # 11 placeholder controls (SymbolPicker, DateRangePicker, ...)
    └── ManifestPane.tsx             # the contract-driven pane wrapper

docs/rebuild/
├── INVENTORY.md                     # every function code, current state, gaps
├── GAP_MATRIX.md                    # production-fakery audit + per-code gap analysis
├── PROVIDER_MATRIX.md               # provider coverage + spec compliance
├── OPERATOR_GUIDE.md                # this file
└── manifests/wave1/                 # markdown design specs (GP, PORT, ECO, GEX, TOP, WATCH, CORR, WIRP)

tests/
├── test_production_fakery_banned.py # baseline scrutinizer; strict-zero ready
├── test_semantic_acceptance.py      # per-code semantic harness (skips if manifest absent)
├── test_chart_grammar.py            # enforces declared grammar matches payload
└── _fakery_baseline.json            # local ceiling — gitignored, regenerated on first run
```

---

## How to add a new function the right way

Suppose you want to add a real rebuild of `EQS` (equity screener).

1. **Write the design spec.** Add `docs/rebuild/manifests/wave1/EQS.md` following the template at `docs/rebuild/manifests/wave1/README.md`. Lock the inputs, providers, chart grammar, formulas, methodology, semantic tests.

2. **Encode the manifest.** Create `backend/showme/manifest/seeds/eqs_seed.py`:

```python
from showme.manifest.registry import manifest
from showme.manifest.spec import (
    FunctionManifest, InputSpec, ProviderChain, CachingPolicy, OutputContract,
    ChartGrammar, TableSchema, ProvenanceSpec, SemanticTest,
)
from showme.manifest.enums import (
    Category, AssetClass, DataMode, ControlKind, ChartKind,
)

@manifest()
def eqs() -> FunctionManifest:
    return FunctionManifest(
        code="EQS",
        name="Equity Screener",
        category=Category.SCREENING,
        intent="Filter equities by fundamentals, technicals, sector...",
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[...],
        defaults={...},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[DataMode.DELAYED_REFERENCE, DataMode.CACHED_SNAPSHOT],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "results", "filter_summary", "data_mode"],
            rows=True, series=False, cards=True, warnings=True, next_actions=True,
        ),
        ...
    )
```

Then add `from . import eqs_seed  # noqa: F401` to `seeds/__init__.py`'s `load_seeds()`.

3. **Implement the handler.** Build the handler that fills `output_contract.must_have`. Use `providers.REGISTRY.get("yfinance")` to fetch. Use `analytical.write_cache(...)` to persist. Stamp `data_mode` honestly. NEVER return `status=ok` with blank core fields.

4. **Write the pane.** Either:
   - **Default render:** `<ManifestPane code="EQS" />` and the auto-derived controls + default renderer do their job (good for simple table/cards panes).
   - **Bespoke chart:** `<ManifestPane code="EQS" customRenderer={({manifest, payload, ...}) => <MyChart payload={payload} />} />` — header/controls/mode pill/sources/warnings come free from the manifest.

5. **Write the tests.** Add semantic tests matching the manifest's `semantic_tests` array. Use `backend/tests/test_function_eqs.py`. Each named test in the manifest gets a test case in pytest that asserts the same property.

6. **Run the bans.** `pytest tests/test_production_fakery_banned.py` should still pass — the new pane must not import `FunctionStub`/`TemplateRenderer`/`design-export`.

---

## How to drive the fakery baseline to zero

Initial violations (per ban-list test on `2026-05-24`):

| Pattern | File:line | Action |
|---------|-----------|--------|
| `ts_dynamic_import_FunctionStub` | `ui/src/shell/Workspace.tsx:35` | Replace with manifest-driven `ManifestPane` lookup |
| `ts_jsx_FunctionStub` | `ui/src/shell/Workspace.tsx:185` | Same |
| `ts_import_TemplateRenderer` | `ui/src/shell/Workspace.tsx:45` | Remove import; template rendering belongs to dev-only |
| `ts_dynamic_import_TemplateRenderer` | `ui/src/shell/Workspace.tsx:38` | Same |
| `ts_jsx_TemplateRenderer` | `ui/src/shell/Workspace.tsx:180` | Same |
| `ts_import_design_export` | `ui/src/panes/preferences_pane/index.tsx:19` | Extract `SettingsDesignExportRenderer` into `ui/src/panes/preferences_pane/SettingsForm.tsx`; remove design-export dep |
| `ts_import_templates_dir` | `ui/src/lib/pane-completeness.ts:25` | Move templates introspection out of production lib into `ui/src/dev/` (dev-only) |
| `py_template_registration` | `backend/showme/server_routes/__init__.py:89` | Move `/api/templates/*` registration behind `if SHOWME_DEV` env gate |

After each fix:
```bash
rm tests/_fakery_baseline.json  # regenerate so the new lower count becomes the ceiling
pytest tests/test_production_fakery_banned.py -v
```

When the count reaches 0, un-skip `tests/test_production_fakery_banned.py::test_no_production_fakery_imports_at_all_STRICT` and that becomes the permanent gate.

---

## Provider environment variables

| Variable | Provider | Required? | Effect when unset |
|----------|----------|-----------|-------------------|
| `FRED_API_KEY` | FRED | yes | `mode()` returns `not_configured`; ECO/ECST/WIRP/BTMM degrade explicitly |
| `OPENFIGI_API_KEY` | OpenFIGI | optional | works with anon quota; with key, higher throughput |
| `SHOWME_AUTH_TOKEN` | sidecar | optional | when set, every `/api/*` (except `/api/health`, `/api/x/health`) requires `X-ShowMe-Token` header |
| `SHOWME_MAX_BODY_BYTES` | sidecar | optional | default 262144 — body-size middleware ceiling |

---

## Lifespan wiring

`backend/showme/server.py::build_app` now:
1. Imports `showme.providers.seed_register` → registers all 8 adapters before lifespan
2. On shutdown calls `aclose_shared()` for the providers' shared `httpx.AsyncClient`
3. On shutdown calls `analytical.close()` for the DuckDB pool (releases the file lock cleanly)

---

## What the rebuild is NOT yet

- Wave 1 implementation panes (the actual rewiring of GP/HP/DES/etc. to use ManifestPane) are scaffolded via manifest seeds but the panes still render via their existing implementations. Wave 1 implementation agents (or subsequent sessions) wrap them in `ManifestPane(customRenderer=...)`.
- Production-fakery baseline > 0. Walk it down per the table above.
- 111 FunctionStub-backed codes still exist. They show raw JSON. They are not in Wave 1; they wait for Wave 2+ rebuilds.
- ASK/AGENT orchestration not redesigned yet.
- TLH/REBA/PORT_WHATIF — real workflows not yet built.
- Whisper + FinBERT not yet wired into TOP/NI/CN/INSTANT — the audit found these models present but unused.

---

## Verification recipe

Every change should be able to run this without surprises:

```bash
# Backend
cd backend && .venv/bin/python -m pytest --no-cov -q

# Frontend
cd ui && npm test -- --run

# Ban-list
cd /Users/nazmi/Desktop/Projeler/proje/showMe && python -m pytest tests/test_production_fakery_banned.py -v

# Full app health
cd backend && .venv/bin/python -m showme.server --port 0 &
# wait for SIDECAR_PORT=... then curl /api/health, /api/manifest, /api/manifest/GP
```

Native deploy still goes through `scripts/build_and_deploy_native.sh` (or the equivalent in `packaging/`) — see `[showMe quality audit FULLY IMPLEMENTED]` memory for the signed-updater contract.
