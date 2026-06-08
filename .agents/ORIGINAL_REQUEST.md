# Original User Request

## Initial Request — 2026-06-06T12:37:36+03:00

Systematic improvement of all 141+ backend functions and 30 UI components in the `showMe` trading terminal to ensure robust data flows, UI compatibility, a dedicated data pool inspection panel, and enhanced capabilities exceeding basic claims.

Working directory: /Users/nazmi/Desktop/Projeler/proje/showMe
Integrity mode: development

## Requirements

### R1. Robust Real-World Data Flows
All functions registered in the system (141+ codes) must use real data adapters (yfinance, FRED, CCXT, DuckDB analytics, etc.) or correct analytical calculations. They must not rely on simple static placeholders or mock templates in production mode. Banned mock or fake production files must be strictly avoided.

### R2. Dynamic UI Compatibility
All UI components must adapt to and correctly display all metrics returned by the backend data contract. The interface must dynamically format and scale according to the incoming data structure, avoiding layout shift or data compatibility crashes.

### R3. Data Pool Inspection Panel
Every function interface must provide a dedicated feature, pane, or modal to view and inspect the raw underlying data (JSON payload or structured table) of the function's output.

### R4. Value-Added Capabilities (Exceeding Basic Claim)
Every function must go beyond its basic minimum claim. For example, if a function claims to compute a metric, it should also present related context such as historical trend analysis, multi-asset comparisons, statistical distributions, or threshold alerts.

### R5. Audit and Validation Integrity
The project's function audit (`npm run audit:functions`) and unit/E2E test suites must pass 100% green. All panel headers must correctly surface the manifest status (`📜 M`), honest `DataMode` pills, source names, and warning counts.

## Acceptance Criteria

### Function Audit & Test Performance
- [ ] Running `npm run audit:functions` results in 0 errors and contains no `FAIL_STATUSES` (e.g. `input_error`, `calc_error`) or banned sentinels (e.g. `"No rows"`, `"No ratios"`, `"undefined"`, `"NaN"`).
- [ ] Running `npm run test` (including pytest and vitest suites) finishes with 100% green status.

### UI Data Inspection & Visual Integrity
- [ ] Every active function page in the UI renders a clickable inspection/data-pool button that displays the raw backend payload in a formatted JSON tree or interactive table.
- [ ] Every pane shows a valid, honest `DataMode` pill (such as `live_official`, `live_exchange`, `delayed_reference`) and displays at least one authentic source provenance name.
- [ ] All dynamic data feeds are styled correctly, utilizing modern typography and smooth visual feedback without rendering fallback or mock stubs in production.
