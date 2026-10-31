# VCAP source-aware venture capital research

VCAP is one macro research function for country, global, Turkey and crypto series. It preserves each publisher's universe, measurement dates, stage definitions, methodology and revisions. It never sums countries into a world total, adds Turkey/crypto to global totals, splices sources, fills missing values with zero, or extrapolates incomplete years. Startup investment, deals and fund fundraising are separate metrics.

## API

Use `POST /api/fn/VCAP` with a JSON object. `query` is the default action. GET can query/list versions; imports require POST and a GET import returns HTTP 405. There are no path, file-download or URL-fetch parameters. Source URLs in imports are provenance only and are never fetched. Imports are local and are not sent to cloud AI.

```json
{
  "action": "query",
  "scope": "countries",
  "source_ids": ["oecd"],
  "geographies": ["USA"],
  "metric": "investment",
  "stage": "total",
  "frequency": "annual",
  "unit": "USD",
  "start_year": 2007,
  "end_year": 2026,
  "refresh": false,
  "financing_scope": "vc"
}
```

`scope`: `countries|global|turkey|crypto`; `source_ids` and `geographies` accept lists or comma-separated strings. Geography is ISO3, `WORLD` or `TUR_DIASPORA`. Countries excludes aggregate codes; global requires WORLD; Turkey requires TUR/TUR_DIASPORA. Crypto can use explicit company-HQ country series from imports; the direct raises adapter provides WORLD only. Default geography is USA/WORLD/TUR/WORLD respectively. Default sources are OECD/KPMG-PitchBook/startups.watch/DefiLlama respectively. Unknown custom sources must be imported first.

`metric`: `investment|deals|fundraising`; `stage`: `total|seed|early|late`; `frequency`: `annual|quarterly`; `unit`: `USD|PERCENT_GDP|COUNT`. Deals requires COUNT; fundraising requires USD. Years must be integer values (four-digit strings also work for GET), 1900 through current year, start <= end. `refresh` accepts JSON booleans or GET `true|false`. `vintage` is an optional opaque snapshot ID (or `latest`); it pins that source while other selected sources keep their independently latest snapshot. An unknown/mismatched vintage produces input_error before any network request.

`financing_scope`: `vc` (default) or, only for crypto, `all_raises`. The latter means **reported crypto financing (incl token sales)**. It cannot be silently substituted for strict VC. OECD and ordinary imports default to vc; a crypto import can explicitly assign all_raises per dataset or observation.

List versions with `{"action":"versions"}` or `{"action":"versions","source_id":"custom_example"}`. Import with `{"action":"import","dataset":{...}}`. An import returns `snapshot_id`, `imported_snapshot` and `idempotent`, together with the catalogue and complete snapshot history. Importing an empty template creates an empty release, not observations.

The legacy `FunctionResult.data` is the complete VCAP payload. The shared engine also exposes top-level `rows`, `series`, status and metadata; its `payload` projection intentionally excludes rows/status/reason. Read `data` for the complete domain contract. `data.status` uses `ok|empty|input_error|provider_unavailable`; errors preserve source catalogue and snapshot history. A failed source does not discard another source's valid observations.

Payload fields:

- `rows`: source_id, source_name, scope, geography, period, period_start, period_end, frequency, metric, stage, unit, value, status, published_at, retrieved_at, snapshot_id, vintage, methodology_version, geography_basis, date_basis, sector, source_url, coverage_note, financing_scope, methodology and data_mode. Provider flags/multipliers and disclosed-amount counts are retained where available.
- `sources`: complete catalogue, including empty/unavailable sources. Each has scopes/available_scopes, declared metrics/frequencies/stages/units, observed available_metrics/available_frequencies/available_stages/available_units/available_geographies, access_mode, access_status, status, access_notes, research/terms references, lineage, and current release dates when saved. A capability is not a promise of a licensed dataset. Available geography lists come from saved observation rows, never generic codelists.
- `snapshots`: source-specific immutable version history, with snapshot_id/vintage, published_at (nullable), retrieved_at, methodology_version, observation_count and data_mode.
- `available_geographies`: sorted observed codes across currently saved source releases.
- `series`: deterministic source/geography/measurement groups. Each has an id, semantics and chronological `points` with period/start/end/value/status/coverage_note, including explicit nulls. Missing unreported periods are not fabricated.
- `summary`: row/missing/series counts, latest selected period, and `total:null`. `comparison` separates comparable_pairs and blocked_pairs with reasons. Comparability requires identical scope, geography, metric, frequency, stage, unit, sector, geography_basis, date_basis, financing_scope and source methodology. Independent publishers remain side by side; this initial version blocks their normalized percentage gaps. No TTM/annualization is computed.
- `methodology`, optional `reason`, `next_actions`, `warnings` and `cache_note` explain measurement/access/empty/stale states.

`metadata.data_mode` is `official|imported|mixed|unavailable`; official identifies direct publisher data, not a real-time quote or a government endorsement. `cached` and `stale` are explicit. Annual observations/imports pass through the shared envelope as reference data (`live:false`), with source-specific provenance markers. Generic envelope fetched_at is the function execution date, not publication or observation date.

## Import contract (schema_version 1)

See [empty JSON template](vcap-template.json) and [empty CSV header](vcap-template.csv). The API accepts JSON datasets; the pane can convert the documented CSV rows to this same dataset object. Repeat metadata columns for every observation in a CSV file; all rows must agree on dataset metadata. CSV is not fetched or parsed by the backend.

Required dataset metadata:

- `schema_version`: integer 1; `source_id`: lowercase slug (1–64, letters/digits/underscore/hyphen, beginning with a letter), one catalogue ID or a custom slug. `source_name` is required for custom sources; known publisher names are canonical.
- `source_url`: HTTPS reference without username/password or control/whitespace characters. It is provenance only.
- `published_at`: valid ISO date or datetime, normalized to UTC (a date/naive datetime uses UTC); `methodology` and `methodology_version`: nonempty text.
- `geography_basis`: `company_hq|fund_manager|source_defined`; `date_basis`: `announced|closed|source_defined`; `sector`: `all|crypto|web3|source_defined`.
- `observations`: array of at most 10,000 entries. Each requires scope, geography, period (`YYYY` or `YYYY-Q1` through `YYYY-Q4`), metric, stage, unit, value, status (`reported|provisional|missing`); optional coverage_note and financing_scope. Frequency and date bounds derive from period. Monetary value is nonnegative finite **USD**, not millions; percent GDP is percent (0.5 means 0.5%); counts are nonnegative integers. JSON booleans/number strings/NaN/infinity are rejected. Missing requires null, and null requires missing. Explicit zero is valid. Percent >100, fractional counts, duplicate period/group keys and incompatible metric/unit/scope/geography combinations fail the whole import. Period years are 1900–2100; queries restrict to current year.

Unknown fields are ignored; semantic fields are never guessed. The dataset is validated before one SQLite transaction. The normalized dataset's UTF-8 JSON must be <=2,000,000 bytes; the HTTP VCAP POST request has a separate 2,100,000-byte cap for its envelope. Ordinary endpoints keep their existing limit, and chunked requests remain rejected. Identical normalized content is idempotent. Snapshots cannot be overwritten; content changes create new IDs. Latest means newest publication date, then retrieval date, then deterministic content ID. An older publication imported later does not replace a newer one. There is no application reset/delete endpoint.

## Sources and configuration

`SHOWME_VCAP_DIR` isolates all VCAP SQLite data (`snapshots.sqlite3`). Default Windows location is `%LOCALAPPDATA%/ShowMe/vcap`; other platforms use `$XDG_DATA_HOME/showme/vcap` or `~/.local/share/showme/vcap`. Every backend test points this variable at a test-owned temporary directory. No other application data is reset.

- **OECD:** fixed HTTPS CSV, OECD.SDD.TPS,DSD_VC@DF_VC_INV,1.0, annual VC_INV_MKT, USD_EXC/PT_B1GQ, stages _T/SEED/START/LATER. UNIT_MULT applies to both units: current USD is ×1,000,000; GDP is multiplier 0 and already percent. Missing values, original flags and stage/unit codes are preserved. Country coverage comes only from CSV observations; live verification on 31 October 2026 observed 37 countries and no TUR/WORLD. The non-production dataflow and country-stage comparability caveats are disclosed (KOR/NZL/RUS/ZAF). The CSV provides no publication date: published_at is null. HTTP Last-Modified was older than some data and is only transport metadata. The automatic bulk cache lasts 24 hours, explicit refresh has a 60-second cooldown, requests are single-flight per source/store across threads, size capped at 8 MB, connect timeout 5s/read timeout 15s with a 30s streaming deadline. HTTP redirects are not followed. Network failures retain an explicitly stale immutable release. See [API guidance](https://www.oecd.org/en/data/insights/data-explainers/2024/11/Api-best-practices-and-recommendations.html) and [data terms](https://www.oecd.org/en/about/terms-conditions.html).
- **DefiLlama:** optional existing `SHOWME_DEFILLAMA_API_KEY`, fixed Pro raises endpoint. No credential/subscription is created. The key/keyed URL and raw upstream exception are never returned or logged. Documented [official SDK](https://github.com/DefiLlama/api-sdk/blob/f0d43119c746dda0c1ad8460c37ac9e00e8e5161/src/types/ecosystem.ts) provides announced raises with amounts in millions USD, but no investment-instrument or company-HQ classification. Therefore only all_raises is automated. A Series A/seed round name does not establish equity VC. Investment is the sum of disclosed announcement amounts with coverage counts; it remains null when none are disclosed. Deals includes undisclosed amounts and counts announcements, not unique companies. Exact duplicate records are removed. No empty year/quarter is invented. Fund fundraising/geographic/stage queries are unsupported. Strict VC requires a classified owned/licensed import. Same cache/timeout/size/cooldown rules apply. Consult [Pro documentation](https://api-docs.defillama.com/) for access/terms.
- **KPMG/PitchBook, Crunchbase, CB Insights, Dealroom, startups.watch, Galaxy:** catalogue research/terms links plus validated local import of owned/licensed series. No invented API, report scrape or copied restricted dataset is included. KPMG/PitchBook lineage, startups.watch retrospective revisions and diaspora boundaries, and Galaxy's crypto investment/fund fundraising distinction remain visible in the catalogue.
- **Custom:** complete metadata and user-controlled source slug; never an inferred source or an assumed redistribution license.

No purchase, vendor account, cloud upload, prediction, confidence score or synthetic fallback is part of VCAP.
