/**
 * HVT — Historical volatility trends (options-family redesign 2026-09-12).
 *
 * One screen, one job: the realized-vol term structure. Primary visual is
 * the rolling-RV sparkline built ONLY from the real `history[]` series, with
 * the window table as the single DataGrid (sort + keyboard + CSV). Probe
 * evidence (sidecar 2026-09-12, raw: options-redesign/raw/hvt-*.json):
 *
 *   rows[]    { metric, window_days, realized_vol, realized_vol_pct,
 *               samples, formula }
 *   history[] { date, vol, vol_pct, window_days }        (real when live)
 *   summary   { current_realized_vol, current_realized_vol_pct,
 *               observations, history_window_days }
 *
 * Honesty: `provider_unavailable` payloads ship SEEDED reference rows — this
 * pane refuses to render them and shows the empty branch with the provider
 * reason instead. The explicit `reference=true` template is renderable but
 * labeled once (mode pill + one grid note). Removed decoration: KPI mini
 * trend spark, duplicate spark/footer point counts, duplicate lookback
 * labels, the constant Formula column, and the second text block under the
 * grid (methodology XOR reference note, never both).
 */
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  PaneState,
  Pill,
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import { formatNumberFixed } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

/* ── payload types ─────────────────────────────────────────────────── */

interface HvtRow {
  metric?: string;
  window_days?: number;
  realized_vol?: number;
  realized_vol_pct?: number;
  samples?: number;
  formula?: string;
}

interface HvtHistoryPoint {
  date?: string;
  vol?: number;
  vol_pct?: number;
  window_days?: number;
}

interface HvtSummary {
  current_realized_vol?: number;
  current_realized_vol_pct?: number;
  observations?: number;
  history_window_days?: number;
}

interface HvtData {
  status?: string;
  reason?: string;
  symbol?: string;
  spot?: number;
  lookback_days?: number;
  rows?: HvtRow[];
  history?: HvtHistoryPoint[];
  summary?: HvtSummary;
  methodology?: string;
}

const DAYS_OPTIONS = [
  { value: 90, label: "90d" },
  { value: 180, label: "180d" },
  { value: 365, label: "1y" },
  { value: 730, label: "2y" },
] as const;
const DAYS_IDS = DAYS_OPTIONS.map((o) => o.value);

const DEFAULT_FORMULA = "stdev(daily close returns) * sqrt(252)";

/* ── helpers ───────────────────────────────────────────────────────── */

function num(v: unknown): number | null {
  // null/undefined/"" must stay missing — Number(null) === 0 would render a
  // fake "0.0%" for a payload that never measured the value.
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmtNum(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  return formatNumberFixed(n, 2);
}

function fmtPct(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  return `${n.toFixed(1)}%`;
}

interface SeriesPoint {
  value: number;
  date?: string;
}

function seriesStats(history: HvtHistoryPoint[]): {
  min: SeriesPoint | null;
  max: SeriesPoint | null;
  avg: number | null;
  count: number;
} {
  let min: SeriesPoint | null = null;
  let max: SeriesPoint | null = null;
  let sum = 0;
  let count = 0;
  for (const point of history) {
    const value = num(point.vol_pct);
    if (value == null) continue;
    sum += value;
    count += 1;
    if (!min || value < min.value) min = { value, date: point.date };
    if (!max || value > max.value) max = { value, date: point.date };
  }
  return { min, max, avg: count ? sum / count : null, count };
}

/**
 * Measure a container's rendered width so the pixel-width kit `Sparkline`
 * fills its card (FIX R2-#2: a hard-coded 560px drew the rolling-RV curve in
 * ~38% of the card, the right half staying dead). No deps; falls back to the
 * previous fixed width when layout is unavailable (jsdom / hidden pane).
 */
function useMeasuredWidth<T extends HTMLElement>(
  fallback: number,
): [(node: T | null) => void, number] {
  const [width, setWidth] = useState(fallback);
  const roRef = useRef<ResizeObserver | null>(null);
  // Callback ref: the measured node is conditionally rendered (only when the
  // series exists), so a mount-time effect would measure nothing and never
  // retry. Attach the observer the moment the node attaches.
  const setRef = useCallback((node: T | null) => {
    roRef.current?.disconnect();
    roRef.current = null;
    if (!node) return;
    const measure = () => {
      const next = Math.round(node.getBoundingClientRect().width);
      if (next > 0) setWidth(next);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    roRef.current = ro;
  }, []);
  // No teardown effect: under StrictMode's double-mount React does not
  // re-invoke callback refs, so an effect cleanup would disconnect the
  // observer permanently (R3-N1). `setRef(null)` disconnects on unmount.
  return [setRef, width];
}

/* ── pane ──────────────────────────────────────────────────────────── */

export function HVTPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const [days, setDays] = usePersistentOption<number>(
    "showme.hvt.days",
    DAYS_IDS,
    365,
  );
  const { state, data, error, refetch } = useFunction<HvtData>({
    code,
    symbol: effectiveSymbol,
    params: { days },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: HvtRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const history: HvtHistoryPoint[] = useMemo(
    () => payload?.history ?? [],
    [payload],
  );
  const volSeries = useMemo(
    () =>
      history
        .map((point) => num(point.vol_pct))
        .filter((value): value is number => value != null),
    [history],
  );
  const stats = useMemo(() => seriesStats(history), [history]);
  const [sparkRef, sparkWidth] = useMeasuredWidth<HTMLDivElement>(560);
  const currentVol = num(payload?.summary?.current_realized_vol_pct);
  const observations = payload?.summary?.observations;
  const windowDays = num(payload?.summary?.history_window_days) ?? 30;
  const status = payload?.status;
  const isLive = status === "ok";
  const isReference = status === "reference";
  const providerDown = status === "provider_unavailable";
  // The mode (live/reference) is stated exactly once — by the header mode
  // pill. The load-state pill + footer carry the CALL status only, so a
  // reference payload does not repeat its label three times.
  const loadStatus = isLive || isReference ? "ok" : status;
  const hasData = (isLive || isReference) && rows.length > 0;
  const lastDate = history[history.length - 1]?.date;

  const columns = useMemo<DataGridColumn<HvtRow>[]>(
    () => [
      {
        key: "metric",
        header: "Window",
        width: 150,
        sortable: true,
        sortValue: (row) => row.window_days ?? 0,
        render: (row) => (
          <span style={MONO_STRONG}>
            {row.metric ?? (row.window_days ? `${row.window_days}D` : "—")}
          </span>
        ),
      },
      {
        key: "realized_vol_pct",
        header: "Realized vol",
        numeric: true,
        width: 116,
        sortable: true,
        render: (row) => (
          <span style={MONO_STRONG}>{fmtPct(row.realized_vol_pct)}</span>
        ),
      },
      {
        key: "samples",
        header: "Samples",
        numeric: true,
        width: 92,
        sortable: true,
        render: (row) => (
          <span style={MONO_MUTED}>{row.samples ?? "—"}</span>
        ),
      },
    ],
    [],
  );

  const csvColumns = useMemo<GridCsvColumn<HvtRow>[]>(
    () => [
      {
        key: "metric",
        header: "Window",
        value: (row) => row.metric ?? (row.window_days ? `${row.window_days}D` : ""),
      },
      {
        key: "realized_vol_pct",
        header: "Realized vol (%)",
        value: (row) => row.realized_vol_pct ?? "",
      },
      { key: "samples", header: "Samples", value: (row) => row.samples ?? "" },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, rows);
    downloadGridCsv(
      gridCsvFilename(`hvt-${effectiveSymbol || "windows"}`),
      csv,
    );
  };

  const subtitle = [
    payload?.spot != null ? `spot ${fmtNum(payload.spot)}` : null,
    lastDate ? `as of ${lastDate}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const body = !effectiveSymbol ? (
    <Empty
      title="Pick a symbol"
      body="HVT needs an equity / ETF with daily history."
      icon="⌖"
    />
  ) : (
    <PaneState
      state={state}
      error={error}
      empty={!hasData}
      emptyTitle={
        providerDown
          ? "Realized-vol history unavailable"
          : "No realized-vol windows returned"
      }
      emptyBody={
        providerDown
          ? (payload?.reason ??
            "No daily close history returned for this symbol — realized volatility cannot be measured.")
          : "The provider returned no usable return window."
      }
      emptyIcon="∅"
      onRetry={refetch}
      loadingRows={5}
    >
      <section style={KPI_GRID} aria-label="HVT KPI ribbon">
        <StatCard
          label="Current 30D RV"
          value={fmtPct(currentVol)}
          caption={`${observations ?? "—"} obs`}
          tone="neutral"
        />
        <StatCard
          label="History average"
          value={fmtPct(stats.avg)}
          caption={`${stats.count} rolling points`}
          tone="neutral"
        />
        <StatCard
          label="History min"
          value={fmtPct(stats.min?.value)}
          caption={stats.min?.date ?? "—"}
          tone="neutral"
        />
        <StatCard
          label="History max"
          value={fmtPct(stats.max?.value)}
          caption={stats.max?.date ?? "—"}
          tone="neutral"
        />
      </section>

      <section
        className="hvt-spark"
        style={SPARK_CARD}
        aria-label="Rolling realized volatility curve"
      >
        <div style={SPARK_HEAD}>
          <span className="u-text-mute" style={META}>
            Rolling RV · {windowDays}D window
          </span>
        </div>
        {volSeries.length > 1 ? (
          <div ref={sparkRef} style={MEASURE_WRAP} data-testid="hvt-spark-measure">
            <Sparkline
              values={volSeries}
              width={sparkWidth}
              height={88}
              tone="accent"
              ariaLabel={`Rolling realized volatility, ${volSeries.length} points, last ${fmtPct(volSeries[volSeries.length - 1])}`}
            />
          </div>
        ) : (
          <div className="u-text-mute" style={META}>
            No rolling history returned.
          </div>
        )}
        <div style={SPARK_FOOT}>
          <span className="u-text-mute" style={META}>
            {history[0]?.date ?? "—"}
          </span>
          <span className="u-text-mute" style={META}>
            {lastDate ?? "—"}
          </span>
        </div>
      </section>

      <section style={TABLE_WRAP} aria-label="Realized volatility windows">
        <DataGrid
          columns={columns}
          rows={rows}
          rowKey={(row, index) =>
            `${row.window_days ?? row.metric ?? "row"}-${index}`
          }
          density="compact"
          ariaLabel="Volatility term structure"
          defaultSortKey="metric"
          defaultSortDir="ascending"
          keyboardNavigable
        />
        {isReference ? (
          <div style={REF_NOTE} role="status" data-testid="hvt-ref-note">
            Reference template (deterministic per-symbol seed) — NOT measured
            from live closes.
          </div>
        ) : (
          <div className="u-text-mute" style={NOTE}>
            {payload?.methodology ?? DEFAULT_FORMULA}
          </div>
        )}
      </section>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Historical volatility — ${effectiveSymbol || ""}`}
          subtitle={subtitle || "waiting for daily closes"}
          trailing={
            <FunctionControlGroup>
              {isLive ? (
                <Pill tone="positive" variant="soft">
                  live
                </Pill>
              ) : isReference ? (
                <Pill tone="warn" variant="soft">
                  reference
                </Pill>
              ) : null}
              <SegmentedControl
                label="LOOKBACK"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
                title="Lookback window"
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={rows.length === 0}
                title="Download CSV"
                aria-label={`Download ${rows.length} realized-vol windows as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={loadStatus} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh realized volatility"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={loadStatus ?? "—"} />
          <StatusDivider />
          <StatusSection label="windows" value={rows.length} tone="accent" />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const KPI_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const SPARK_CARD: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  padding: "10px 12px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--scrim-low)",
};

const SPARK_HEAD: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 12,
};

const SPARK_FOOT: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
};

/** Full-width wrapper measured for the responsive sparkline (FIX R2-#2). */
const MEASURE_WRAP: CSSProperties = {
  width: "100%",
  minWidth: 0,
};

const TABLE_WRAP: CSSProperties = { minWidth: 0 };

const META: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  fontFamily: "var(--font-mono)",
  letterSpacing: "0.05em",
};

const NOTE: CSSProperties = {
  marginTop: 6,
  fontSize: "var(--font-size-2xs)",
  fontFamily: "var(--font-mono)",
  color: "var(--text-mute)",
};

const REF_NOTE: CSSProperties = {
  ...NOTE,
  padding: "5px 8px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--scrim-low)",
  color: "var(--text-primary)",
};

const MONO_STRONG: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const MONO_MUTED: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

export default HVTPane;
