/**
 * BTMM — central-bank policy-rate monitor.
 *
 * Dedicated native pane for the BIS CBPOL-backed policy-rate matrix. KPI
 * ribbon for hike/cut/hold tally, full-width policy-rate history chart,
 * sparkline column, sectioned filter strip, hover-lift rows.
 */
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import {
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  ResizableChartFrame,
  Skeleton,
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { maxOf, minOf } from "@/lib/maxOf";
import { formatPercent, formatNumber, formatMissing } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface BTMMRow {
  country_code?: string;
  bis_ref_area?: string;
  country?: string;
  central_bank?: string;
  currency?: string;
  region?: string;
  policy_rate?: number;
  as_of?: string;
  previous_rate?: number | null;
  previous_date?: string | null;
  change_bp?: number | null;
  last_move?: "hike" | "cut" | "hold" | string;
  trend_3m_bp?: number | null;
  history?: Array<{ date?: string; policy_rate?: number; country_code?: string }>;
  source?: string;
}

interface BTMMSummary {
  rows?: number;
  universe?: number;
  average_policy_rate?: number | null;
  max_policy_rate?: number | null;
  min_policy_rate?: number | null;
  hikes?: number;
  cuts?: number;
  holds?: number;
  largest_last_move?: BTMMRow | null;
}

interface BTMMPayload {
  country?: string;
  region?: string;
  rows: BTMMRow[];
  summary?: BTMMSummary;
  as_of?: string;
  stale_seconds?: number | null;
}

const COUNTRIES = [
  { value: "ALL", label: "All" },
  { value: "US", label: "US" },
  { value: "EU", label: "EU" },
  { value: "GB", label: "UK" },
  { value: "JP", label: "JP" },
  { value: "TR", label: "TR" },
] as const;
type CountryId = (typeof COUNTRIES)[number]["value"];
const COUNTRY_IDS = COUNTRIES.map((c) => c.value) as CountryId[];

const REGIONS = [
  { value: "all", label: "All" },
  { value: "g10", label: "G10" },
  { value: "em", label: "EM" },
  { value: "americas", label: "Americas" },
  { value: "europe", label: "Europe" },
  { value: "asia_pacific", label: "APAC" },
  { value: "mea", label: "MEA" },
] as const;
type RegionId = (typeof REGIONS)[number]["value"];
const REGION_IDS = REGIONS.map((r) => r.value) as RegionId[];

const COLS: DataGridColumn<BTMMRow>[] = [
  {
    key: "country",
    header: "Country",
    width: 168,
    render: (row) => (
      <span style={countryCellStyle}>
        <span style={countryCodeStyle}>{row.country_code ?? "—"}</span>
        <span style={countryNameStyle}>
          {row.country ?? row.bis_ref_area ?? "—"}
        </span>
      </span>
    ),
  },
  {
    key: "central_bank",
    header: "Central bank",
    width: 220,
    render: (row) => (
      <span className="u-text-secondary">
        {row.central_bank ?? "—"}
      </span>
    ),
  },
  {
    key: "currency",
    header: "Ccy",
    width: 64,
    render: (row) =>
      row.currency ? (
        <Pill tone="muted" variant="soft" withDot={false}>
          {row.currency}
        </Pill>
      ) : (
        "—"
      ),
  },
  {
    key: "policy_rate",
    header: "Rate",
    numeric: true,
    width: 96,
    render: (row) => (
      <span className="terminal-grid-numeric" style={primaryNumStyle}>
        {fmtPct(row.policy_rate)}
      </span>
    ),
  },
  {
    key: "trend",
    // P2.6: clarify the ambiguous "12m" header for hover/AT.
    header: (
      <span title="12-month policy-rate trend (real history only)">12m</span>
    ),
    width: 84,
    render: (row) => {
      const series = realTrendSeries(row);
      // P1.1: no fabricated trend. With < 4 real observations show a muted
      // em-dash placeholder (data-synthetic) instead of a procedural line.
      if (series.length < 4) {
        return (
          <span
            className="btmm-spark btmm-spark--empty"
            data-synthetic="true"
            aria-label="insufficient history for a trend"
            title="Insufficient history — no trend available"
          >
            {formatMissing}
          </span>
        );
      }
      // Fixed-income convention is inverted vs equities: a rate CUT (negative
      // bp) is "easing"/bullish → green/positive; a HIKE (positive bp) is
      // tightening → red/negative. A 0-bp / null "hold" carries no direction,
      // so it is NEUTRAL (gray) — consistent with bpDirection(0) → "flat".
      const bpVal = row.trend_3m_bp ?? row.change_bp ?? null;
      const dir: "negative" | "positive" | "neutral" =
        bpVal == null || bpVal === 0 ? "neutral" : bpVal > 0 ? "negative" : "positive";
      return (
        <span className="btmm-spark" data-synthetic="false">
          <Sparkline
            values={series}
            width={64}
            height={18}
            tone={dir}
            ariaLabel={`${row.country_code ?? "policy rate"} 12-month trend`}
          />
        </span>
      );
    },
  },
  {
    key: "change_bp",
    header: "Last move",
    numeric: true,
    width: 138,
    render: (row) => (
      <span className="u-inline-flex u-items-center u-gap-6 terminal-grid-numeric">
        {movePill(row.last_move)}
        {row.change_bp == null ? (
          formatMissing
        ) : (
          <DeltaChip
            value={row.change_bp}
            // INVERTED fixed-income convention: a HIKE (positive bp) tightens
            // policy → red/down; a CUT (negative bp) eases → green/up. This is
            // the opposite of the equity default (positive=green), so we drive
            // `direction` explicitly to keep the column consistent with the
            // hike/cut pill, KPI tilt, and sparkline tone.
            direction={bpDirection(row.change_bp)}
            format="raw"
            fractionDigits={0}
            ariaLabel={`change ${row.change_bp} basis points`}
          />
        )}
      </span>
    ),
  },
  {
    key: "trend_3m_bp",
    header: "3M bp",
    numeric: true,
    width: 92,
    render: (row) =>
      row.trend_3m_bp == null ? (
        formatMissing
      ) : (
        <span className="terminal-grid-numeric">
          {/* INVERTED convention — see "change_bp" above. */}
          <DeltaChip
            value={row.trend_3m_bp}
            direction={bpDirection(row.trend_3m_bp)}
            format="raw"
            fractionDigits={0}
          />
        </span>
      ),
  },
  {
    key: "as_of",
    // P2.6: clarify what "As of" dates.
    header: (
      <span title="Date of the latest BIS CBPOL observation for this rate">
        As of
      </span>
    ),
    width: 100,
    render: (row) => (
      <span className="terminal-grid-numeric" style={mutedNumStyle}>
        {row.as_of ?? formatMissing}
      </span>
    ),
  },
  {
    key: "source",
    header: "Source",
    width: 110,
    render: (row) => (
      <Pill tone="muted" variant="soft" withDot={false}>
        {row.source ?? "—"}
      </Pill>
    ),
  },
];

export function BTMMPane({ code }: FunctionPaneProps) {
  const [country, setCountry] = usePersistentOption<CountryId>(
    "showme.btmm-country",
    COUNTRY_IDS,
    "ALL",
  );
  const [region, setRegion] = usePersistentOption<RegionId>(
    "showme.btmm-region",
    REGION_IDS,
    "all",
  );

  const { state, data, error, refetch } = useFunction<BTMMPayload>({
    code,
    params: { country, region, limit: 80 },
  });
  const payload = useMemo(() => normalizePayload(data?.data), [data]);
  const rawRows = payload.rows;
  const [search, setSearch] = useState("");
  const rows = useMemo(() => filterRows(rawRows, search), [rawRows, search]);
  const summary = payload.summary;
  const largestMove = summary?.largest_last_move;
  const chartRow = rows[0] ?? rawRows[0];
  // Wall-clock when the UI last polled (sticky to `data` so it doesn't
  // tick every render). Replaces the old single stamp.
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [data]);
  // Bug #24 fix: surface the BIS data freshness as its own stamp. Previously
  // the header pill said `HH:MM UTC` from `new Date()` which made a 24-day
  // old fallback look freshly polled. We now display both.
  const dataAsOf = payload.as_of ?? null;
  // P1.2: the backend flips `sources` to ["local fallback"] (and stamps every
  // row's `source`) when it served the hardcoded snapshot. That is the clean
  // frontend signal — no backend change needed.
  const isFallback =
    (data?.sources?.some((s) => s.toLowerCase().includes("fallback")) ?? false) ||
    rawRows.some((r) => String(r.source ?? "").toLowerCase().includes("fallback"));
  // P1.3 / P2.6: freshness honesty. "live" used to mean "the fetch succeeded"
  // even when serving a 6h cache or a 24-day-old fallback. Reflect REAL
  // freshness from `stale_seconds` (server-computed age of the freshest
  // observation in scope) so a clearly-stale snapshot reads "stale", not "live".
  const staleSeconds = payload.stale_seconds ?? null;
  // The backend `warnings` array is general-purpose; an informational warning
  // (not about freshness) must NOT flip the pill to "stale". Only treat
  // warnings that actually signal staleness/fallback as a freshness signal.
  const hasFreshnessWarning = (data?.warnings ?? []).some((w) =>
    /stale|fallback|outdated|unavailable/i.test(String(w)),
  );
  const isStale =
    isFallback ||
    hasFreshnessWarning ||
    (staleSeconds != null && staleSeconds > 24 * 3600);
  const isLive = state === "ok" && !isStale;
  const freshnessLabel = state !== "ok" ? "warn" : isLive ? "live" : "stale";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Central-bank monitor"
          subtitle={`${rows.length}/${summary?.universe ?? rows.length} rates · ${country} · ${regionLabel(region)}`}
          help={<BTMMHelp />}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} cb
              </Pill>
              <span data-testid="btmm-poll-stamp">
                <Pill tone="muted" variant="soft" withDot={false}>
                  Last poll {utcStamp} UTC
                </Pill>
              </span>
              <span data-testid="btmm-data-stamp">
                <Pill
                  tone={dataAsOf ? "accent" : "muted"}
                  variant="soft"
                  withDot={false}
                >
                  Data as of {dataAsOf ?? "—"}
                </Pill>
              </span>
              <span
                data-testid="btmm-live-pill"
                title={
                  state === "error"
                    ? "Policy-rate data could not be loaded"
                    : isLive
                      ? "Freshest BIS observation is current"
                      : isFallback
                        ? "Serving a stored fallback snapshot"
                        : "Serving a cached / stale snapshot"
                }
              >
                <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                  {freshnessLabel}
                </Pill>
              </span>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh policy-rate matrix"
              />
            </FunctionControlGroup>
          }
        />
        <div style={filterBarStyle}>
          <FunctionControlGroup>
            <label htmlFor="btmm-search" style={searchLabelStyle}>
              Search
              <input
                id="btmm-search"
                type="search"
                aria-label="Search central banks by country, bank, or currency"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="country, bank, ccy"
                className="btmm-search-input"
                style={searchInputStyle}
              />
            </label>
            <SegmentedControl
              label="COUNTRY"
              value={country}
              options={COUNTRIES}
              onChange={(next) => {
                setCountry(next);
                if (next !== "ALL") setRegion("all");
              }}
              disabled={state === "loading"}
            />
            <SegmentedControl
              label="REGION"
              value={region}
              options={REGIONS}
              onChange={(next) => {
                setRegion(next);
                if (next !== "all") setCountry("ALL");
              }}
              disabled={state === "loading"}
            />
          </FunctionControlGroup>
        </div>
        <PaneBody
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 14,
            minHeight: 0,
          }}
        >
          {state === "loading" || state === "idle" ? (
            <Skeleton height={340} />
          ) : state === "error" ? (
            <Empty
              title="BTMM failed"
              body={error?.message ?? "Policy-rate data could not be loaded."}
              icon="!"
              action={
                <button onClick={refetch} className="btn">
                  Retry
                </button>
              }
            />
          ) : rows.length === 0 ? (
            <Empty
              title="No matching central banks"
              body="Change the country or region filter."
            />
          ) : (
            <>
              {isFallback ? (
                <div
                  role="status"
                  aria-live="polite"
                  data-testid="btmm-fallback-banner"
                  className="btmm-fallback-banner"
                >
                  <span className="btmm-fallback-banner__dot" aria-hidden />
                  <strong>Stored fallback snapshot</strong>
                  <span className="u-text-secondary">
                    Central-bank feed unavailable — showing a stored snapshot
                    {dataAsOf ? ` from ${dataAsOf}` : ""}. Rates may be stale.
                  </span>
                </div>
              ) : null}
              <KPIRibbon
                summary={summary}
                largestMove={largestMove}
                stamp={utcStamp}
              />
              <PolicyRateHistory row={chartRow} />
              <DataGrid
                columns={COLS}
                rows={rows}
                rowKey={(row, index) =>
                  `${row.country_code ?? row.bis_ref_area ?? "row"}-${index}`
                }
                density="compact"
              />
              {data?.warnings?.length ? (
                <div style={warnStyle}>
                  <strong className="u-text-warn">warning</strong>
                  <span className="u-text-secondary">
                    {data.warnings.join(" | ")}
                  </span>
                </div>
              ) : null}
            </>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="provider"
            value={data?.sources?.join(", ") || "BIS CBPOL"}
          />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="filter" value={`${country}/${region}`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function KPIRibbon({
  summary,
  largestMove,
  stamp,
}: {
  summary?: BTMMSummary;
  largestMove?: BTMMRow | null;
  stamp: string;
}) {
  const hikes = summary?.hikes ?? 0;
  const cuts = summary?.cuts ?? 0;
  const holds = summary?.holds ?? 0;
  const tilt = hikes - cuts;
  return (
    <section style={kpiGridStyle} aria-label="BTMM KPI ribbon">
      <StatCard
        label="Avg policy rate"
        value={fmtPct(summary?.average_policy_rate)}
        caption={`AS OF ${stamp} UTC · ${summary?.rows ?? 0} cb`}
        tone="neutral"
        trend={[]}
      />
      <StatCard
        label="Range"
        value={`${fmtPct(summary?.min_policy_rate)} – ${fmtPct(summary?.max_policy_rate)}`}
        caption="MIN – MAX"
        tone="neutral"
        trend={[]}
      />
      <StatCard
        label="Tilt (H − C)"
        value={`${tilt >= 0 ? "+" : ""}${tilt}`}
        caption={`${hikes}H · ${cuts}C · ${holds}HO`}
        // P2.6: the bare "H − C" label is opaque; the info marker spells out
        // that tilt = number of hikes minus number of cuts across the universe.
        rightSlot={
          <span
            className="btmm-info"
            title="Tilt = hikes minus cuts across the visible central banks. Positive = net tightening (red); negative = net easing (green)."
            aria-label="Tilt is hikes minus cuts across the visible central banks"
          >
            ⓘ
          </span>
        }
        tone={tilt > 0 ? "negative" : tilt < 0 ? "positive" : "neutral"}
        trend={[]}
      />
      <StatCard
        label="Largest move"
        value={
          largestMove
            ? `${largestMove.country_code ?? "—"} ${fmtBp(largestMove.change_bp)}`
            : "—"
        }
        caption={largestMove?.central_bank ? truncate(largestMove.central_bank, 22) : "—"}
        tone={
          largestMove?.change_bp == null
            ? "neutral"
            : (largestMove.change_bp ?? 0) >= 0
              ? "negative"
              : "positive"
        }
        trend={[]}
      />
    </section>
  );
}

function PolicyRateHistory({ row }: { row?: BTMMRow }) {
  const points = (row?.history ?? []).filter(
    (point) => typeof point.policy_rate === "number" && point.date,
  );
  if (points.length < 2) return null;
  const values = points.map((point) => Number(point.policy_rate));
  // UA-HIGH-12: stack-safe.
  const min = minOf(values);
  const max = maxOf(values);
  const span = max - min || 1;
  const width = 720;
  const height = 132;
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * width;
      const y =
        height -
        ((Number(point.policy_rate) - min) / span) * (height - 24) -
        12;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const areaPath = `${path} L${width},${height} L0,${height} Z`;
  const latest = points[points.length - 1];
  const first = points[0];
  // P2.4: text alternative for the raw <svg> so screen readers get country +
  // date range + min/max instead of an unlabelled graphic.
  const chartAriaLabel =
    `${row?.country_code ?? "Policy rate"} policy-rate history, ` +
    `${first?.date ?? "?"} to ${latest?.date ?? "?"}, ` +
    `min ${fmtPct(min)}, max ${fmtPct(max)}`;
  return (
    <ResizableChartFrame
      storageId={`BTMM.policy-rate.${row?.country_code ?? "default"}`}
      defaultHeight={{ vh: 0.24, max: 260, min: 160 }}
      minHeight={160}
      minWidth={420}
      maxHeight={620}
      style={chartPanelStyle}
      ariaLabel="Resize policy-rate chart"
    >
      <div style={chartHeaderStyle}>
        <div className="u-flex u-flex-col u-gap-2">
          <span style={metaLabel}>{row?.country_code ?? "—"} · policy-rate history</span>
          <strong style={chartLatestStyle}>{fmtPct(latest?.policy_rate)}</strong>
        </div>
        <div style={chartCaptionRow}>
          <Pill tone="muted" variant="soft" withDot={false}>
            {points.length} obs
          </Pill>
          <Pill tone="accent" variant="soft" withDot={false}>
            {latest?.date}
          </Pill>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={chartAriaLabel}
        style={{ width: "100%", flex: "1 1 0", minHeight: 0, minWidth: 0 }}
      >
        <defs>
          <linearGradient id="btmm-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.32" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line
          x1="0"
          y1={height - 12}
          x2={width}
          y2={height - 12}
          stroke="var(--border-subtle)"
        />
        <line x1="0" y1="12" x2={width} y2="12" stroke="var(--border-row)" />
        <path d={areaPath} fill="url(#btmm-area)" />
        <path
          d={path}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.2"
          vectorEffect="non-scaling-stroke"
          strokeLinecap="round"
        />
      </svg>
      <div style={chartFooterStyle}>
        <span>min · {fmtPct(min)}</span>
        <span>max · {fmtPct(max)}</span>
        <span>span · {(max - min).toFixed(2)} pp</span>
      </div>
    </ResizableChartFrame>
  );
}

// P1.1 data-honesty: only return a series when we have a REAL trend. The old
// implementation fabricated a deterministic pseudo-random walk for rows with
// < 4 observations and rendered it as a plain sparkline — a fake line shown as
// data. We now return at least 2 real points or nothing; the caller renders a
// muted "insufficient history" placeholder instead of a synthetic curve.
function realTrendSeries(row: BTMMRow): number[] {
  const values = (row.history ?? [])
    .filter((p) => typeof p.policy_rate === "number")
    .map((p) => Number(p.policy_rate))
    .slice(-12);
  return values.length >= 4 ? values : [];
}

function filterRows(rows: BTMMRow[], search: string): BTMMRow[] {
  const needle = search.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((row) =>
    [
      row.country_code,
      row.bis_ref_area,
      row.country,
      row.central_bank,
      row.currency,
      row.region,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
}

function BTMMHelp() {
  return (
    <div className="u-grid-gap-8">
      <strong
        style={{
          color: "var(--accent)",
          fontFamily: "JetBrains Mono, monospace",
        }}
      >
        BTMM · Central-bank monitor
      </strong>
      <span className="u-text-secondary">
        Country buttons isolate one policy-rate series. Region buttons switch to
        a central-bank universe such as G10, EM, Europe, Americas, APAC, or MEA.
      </span>
      <span className="u-text-secondary">
        Rate is the latest BIS CBPOL daily value. Last move compares the latest
        rate with the previous different rate; 3M bp compares with the value
        roughly 90 calendar days earlier.
      </span>
      <span className="u-text-mute">
        Use Refresh to re-query the backend. The backend caches BIS data for six
        hours and shows a warning if it has to fall back.
      </span>
    </div>
  );
}

function normalizePayload(payload: BTMMPayload | unknown): BTMMPayload {
  if (payload && typeof payload === "object") {
    const obj = payload as Record<string, unknown>;
    const rows = Array.isArray(obj.rows) ? (obj.rows as BTMMRow[]) : [];
    return {
      country: typeof obj.country === "string" ? obj.country : undefined,
      region: typeof obj.region === "string" ? obj.region : undefined,
      rows,
      summary:
        obj.summary && typeof obj.summary === "object"
          ? (obj.summary as BTMMSummary)
          : undefined,
      // Bug #24 fix: thread the data-freshness envelope through so the
      // header can render "Data as of <as_of>" instead of fabricating a
      // wall-clock stamp.
      as_of: typeof obj.as_of === "string" ? obj.as_of : undefined,
      stale_seconds:
        typeof obj.stale_seconds === "number" ? obj.stale_seconds : null,
    };
  }
  return { rows: [] };
}

// P3.7: rates/yields share format.ts's `formatPercent` (already-percent
// contract, fixed 2dp) so the columns never jitter. The previous bespoke
// `fmtPct` allowed 2–4 decimals which made the Rate column shift width as
// magnitudes changed; `fmtPctCompact` duplicated the 2dp variant.
function fmtPct(value: number | null | undefined): string {
  return formatPercent(value, { digits: 2 });
}

// bps: format.ts has no "+12bp" unit helper, so this stays a thin local wrapper
// — but it reuses the shared `formatMissing`/`formatNumber` sentinel + locale
// so sign + unit are consistent with the rest of the dashboard.
function fmtBp(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return formatMissing;
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, 0)}bp`;
}

// INVERTED fixed-income convention: a hike (positive bp) is tightening
// (bearish → "down"/red), a cut (negative bp) is easing (bullish → "up"/green).
// DeltaChip defaults to the equity mapping (positive=green), so BTMM passes
// `direction` explicitly everywhere a bps delta is shown.
function bpDirection(bp: number): "up" | "down" | "flat" {
  if (bp > 0) return "down";
  if (bp < 0) return "up";
  return "flat";
}

function movePill(move: BTMMRow["last_move"]): ReactNode {
  const normalized = String(move ?? "hold").toLowerCase();
  const tone: "negative" | "positive" | "muted" =
    normalized === "hike"
      ? "negative"
      : normalized === "cut"
        ? "positive"
        : "muted";
  return (
    <Pill tone={tone} variant="soft" withDot={false}>
      {normalized}
    </Pill>
  );
}

function regionLabel(region: RegionId): string {
  return REGIONS.find((item) => item.value === region)?.label ?? region;
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const filterBarStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const searchLabelStyle: CSSProperties = {
  display: "grid",
  gap: 3,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
};

const searchInputStyle: CSSProperties = {
  minWidth: 200,
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  padding: "6px 8px",
  font: "inherit",
  textTransform: "none",
  letterSpacing: 0,
  transition: "border-color var(--motion-base)",
};

const countryCellStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "baseline",
  gap: 8,
};

const countryCodeStyle: CSSProperties = {
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 700,
  fontSize: 12,
  letterSpacing: "0.06em",
};

const countryNameStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: 12,
};

const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  fontWeight: 600,
};

const mutedNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const chartPanelStyle: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  position: "relative",
  display: "flex",
  flexDirection: "column",
};

const chartHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 12,
  padding: "12px 12px 4px 12px",
  flexShrink: 0,
};

const chartLatestStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 22,
  color: "var(--text-display)",
  fontWeight: 600,
  letterSpacing: "-0.01em",
};

const chartCaptionRow: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const chartFooterStyle: CSSProperties = {
  display: "flex",
  gap: 18,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  padding: "6px 12px 10px 12px",
  flexShrink: 0,
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const warnStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  background: "var(--warn-soft)",
  display: "grid",
  gap: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};
