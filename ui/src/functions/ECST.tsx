/**
 * ECST — Economic statistics.
 *
 * Single FRED-series time-series viewer. Header SegmentedControl picks the
 * series_id (CPIAUCSL / GDPC1 / UNRATE / DGS10 / DGS2) and an optional
 * compare series (`compare_with`); body shows a KPI ribbon from the
 * backend's `cards` array, a Sparkline of the value path across ascending
 * dates (a dual indexed overlay when a compare series is active), and a
 * dense DataGrid of (date, value, source).
 */
import { useMemo, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const SERIES = [
  { value: "CPIAUCSL", label: "CPI" },
  { value: "GDPC1", label: "GDP" },
  { value: "UNRATE", label: "UNRATE" },
  { value: "DGS10", label: "10Y" },
  { value: "DGS2", label: "2Y" },
] as const;
const SERIES_IDS = SERIES.map((s) => s.value);

// `compare_with` is the backend's exact param (ecst.py:33). "off" = no
// compare series sent; every other value is a FRED series id.
const COMPARE_OFF = "off";
const COMPARE_OPTIONS: { value: string; label: string; title: string }[] = [
  { value: COMPARE_OFF, label: "—", title: "No compare series" },
  ...SERIES.map((s) => ({
    value: s.value,
    label: s.label,
    title: `Compare with ${s.label} (${s.value})`,
  })),
];
const COMPARE_IDS = COMPARE_OPTIONS.map((o) => o.value);

interface EcstRow {
  date?: string;
  series_id?: string;
  series_name?: string;
  value?: number | string | null;
  unit?: string;
  frequency?: string;
  source_mode?: string;
  compare_value?: number | string | null;
}

interface EcstCard {
  label?: string;
  value?: number | string | null;
}

interface EcstPayload {
  series_id?: string;
  series_name?: string;
  unit?: string;
  frequency?: string;
  rows?: EcstRow[];
  history?: EcstRow[];
  cards?: EcstCard[];
  methodology?: string;
  field_dictionary?: Record<string, string>;
  source_mode?: string;
  compare_series_id?: string;
  compare_series_name?: string;
  compare_source_mode?: string;
}

export function ECSTPane({ code }: FunctionPaneProps) {
  const [seriesId, setSeriesId] = usePersistentOption(
    "showme.ecst.series",
    SERIES_IDS,
    "CPIAUCSL",
  );
  const [compareWith, setCompareWith] = usePersistentOption<string>(
    "showme.ecst.compare",
    COMPARE_IDS,
    COMPARE_OFF,
  );

  const params = useMemo(
    () => ({
      series_id: seriesId,
      ...(compareWith !== COMPARE_OFF ? { compare_with: compareWith } : {}),
    }),
    [seriesId, compareWith],
  );

  const { state, data, error, refetch } = useFunction<EcstPayload>({
    code,
    params,
  });

  const payload = data?.data ?? {};
  const rows = useMemo<EcstRow[]>(
    () => normalizeRows(payload.rows ?? payload.history),
    [payload.rows, payload.history],
  );

  // Ascending dates so the sparkline reads left-to-right oldest→newest.
  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const ta = new Date(String(a.date ?? "")).getTime();
      const tb = new Date(String(b.date ?? "")).getTime();
      if (Number.isNaN(ta) || Number.isNaN(tb)) return 0;
      return ta - tb;
    });
  }, [rows]);

  const cards = useMemo<EcstCard[]>(
    () => (Array.isArray(payload.cards) ? payload.cards : []),
    [payload.cards],
  );
  const values = useMemo(
    () =>
      sortedRows
        .map((r) => numeric(r.value))
        .filter((v): v is number => v != null),
    [sortedRows],
  );

  const unit = payload.unit ?? rows[0]?.unit ?? "";
  const frequency = payload.frequency ?? rows[0]?.frequency ?? "—";
  const seriesName = payload.series_name ?? seriesId;
  const sourceMode = payload.source_mode ?? data?.sources?.[0] ?? "—";
  const compareName = payload.compare_series_name ?? null;
  const compareMode = payload.compare_source_mode ?? null;
  // The backend only emits compare fields when the pane sent `compare_with`,
  // so the payload is the source of truth for what is on screen.
  const compareActive = payload.compare_series_id != null;

  // Paired (date, value, compare_value) observations for the overlay —
  // only rows carrying BOTH values, so the two lines share one x-axis.
  const comparePairs = useMemo(() => {
    if (!compareActive) return [];
    const pairs: { date: string; value: number; compare: number }[] = [];
    for (const row of sortedRows) {
      const v = numeric(row.value);
      const c = numeric(row.compare_value);
      if (v == null || c == null) continue;
      pairs.push({
        date: String(row.date ?? "").slice(0, 10),
        value: v,
        compare: c,
      });
    }
    return pairs;
  }, [sortedRows, compareActive]);

  const trend = useMemo(() => deriveTrendTone(values), [values]);
  // F4 fix (A1-ECST-M): the backend can serve the labelled
  // `macro_series_baseline` fallback; a green "live" pill over it contradicts
  // the muted source pill next to it. Only real providers are live.
  const LIVE_SOURCE_MODES = new Set(["fred", "worldbank"]);
  const isLive = state === "ok" && LIVE_SOURCE_MODES.has(sourceMode);

  const COLS: DataGridColumn<EcstRow>[] = useMemo(
    () => [
      {
        key: "date",
        header: "Date",
        width: 124,
        render: (row) => (
          <span style={dateCellStyle}>{String(row.date ?? "—").slice(0, 10)}</span>
        ),
      },
      {
        key: "value",
        header: "Value",
        width: 160,
        numeric: true,
        render: (row) => {
          const n = numeric(row.value);
          if (n == null) return <span style={primaryNumStyle}>—</span>;
          return (
            <span style={primaryNumStyle}>
              {n.toLocaleString("en-US", { maximumFractionDigits: 4 })}
              {unit ? <span style={unitStyle}> {unit}</span> : null}
            </span>
          );
        },
      },
      {
        key: "source_mode",
        header: "Source",
        width: 220,
        render: (row) => (
          <Pill
            tone={row.source_mode === "fred" ? "positive" : "muted"}
            variant="soft"
            withDot={false}
          >
            {row.source_mode ?? "—"}
          </Pill>
        ),
      },
    ],
    [unit],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Economic statistics"
          subtitle={`${seriesId} · ${frequency} · last ${sortedRows.length} obs`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {unit || "—"}
              </Pill>
              <Pill tone="muted" variant="soft" withDot={false}>
                {frequency}
              </Pill>
              <Pill
                tone={LIVE_SOURCE_MODES.has(sourceMode) ? "positive" : "muted"}
                variant="soft"
                withDot={false}
              >
                {sourceMode}
              </Pill>
              <span data-testid="ecst-mode-pill">
                <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                  {isLive ? "live" : state === "ok" ? "reference" : state}
                </Pill>
              </span>
              {compareActive ? (
                <span data-testid="ecst-compare-pill">
                  <Pill
                    tone={
                      compareMode === "macro_series_baseline" ? "warn" : "muted"
                    }
                    variant="soft"
                    withDot={false}
                  >
                    {`vs ${compareName ?? compareWith}${
                      compareMode === "macro_series_baseline"
                        ? " · baseline"
                        : ""
                    }`}
                  </Pill>
                </span>
              ) : null}
              <SegmentedControl
                label="SERIES"
                value={seriesId}
                options={SERIES}
                onChange={setSeriesId}
              />
              <SegmentedControl
                label="COMPARE"
                value={compareWith}
                options={COMPARE_OPTIONS}
                onChange={(next) => setCompareWith(next)}
                title="Compare with another series"
              />
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh series"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <div className="u-grid-gap-12">
              <Skeleton height={88} />
              <Skeleton height={120} />
              <Skeleton height={200} />
            </div>
          ) : state === "error" ? (
            <Empty
              title="Series load failed"
              body={error?.message ?? "—"}
              icon="!"
              action={
                <button onClick={refetch} className="btn btn--accent">
                  Retry
                </button>
              }
            />
          ) : sortedRows.length === 0 ? (
            <Empty
              title="No observations"
              body={`${seriesId} returned no rows.`}
              action={
                <button onClick={refetch} className="btn">
                  Refresh
                </button>
              }
            />
          ) : (
            <div className="u-grid-gap-14">
              <KPIRibbon cards={cards} seriesId={seriesId} frequency={frequency} />
              {comparePairs.length >= 2 ? (
                <CompareOverlay
                  seriesName={seriesName}
                  compareName={compareName ?? compareWith}
                  pairs={comparePairs}
                  compareMode={compareMode}
                />
              ) : (
                <SeriesChart
                  values={values}
                  seriesName={seriesName}
                  tone={trend.tone}
                  summary={trend.summary}
                />
              )}
              <DataGrid
                columns={COLS}
                rows={sortedRows}
                rowKey={(row, i) => `${row.date ?? ""}-${i}`}
                density="compact"
                ariaLabel="ECST observations"
              />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || sourceMode}
          />
          <StatusDivider />
          <StatusSection label="series" value={seriesId} tone="accent" />
          <StatusDivider />
          <StatusSection label="frequency" value={frequency} />
          <StatusDivider />
          <StatusSection label="rows" value={sortedRows.length} />
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

function KPIRibbon({
  cards,
  seriesId,
  frequency,
}: {
  cards: EcstCard[];
  seriesId: string;
  frequency: string;
}) {
  if (cards.length === 0) {
    return (
      <section style={kpiGridStyle} aria-label="ECST KPI ribbon">
        <StatCard
          label="Series"
          value={seriesId}
          caption={frequency}
          tone="neutral"
        />
      </section>
    );
  }
  return (
    <section style={kpiGridStyle} aria-label="ECST KPI ribbon">
      {cards.map((card, i) => {
        const n = numeric(card.value);
        return (
          <StatCard
            key={`${card.label ?? "card"}-${i}`}
            label={card.label ?? "—"}
            value={
              n == null
                ? card.value == null || card.value === ""
                  ? "—"
                  : String(card.value)
                : n.toLocaleString("en-US", { maximumFractionDigits: 4 })
            }
            caption={frequency}
            tone="neutral"
          />
        );
      })}
    </section>
  );
}

function SeriesChart({
  values,
  seriesName,
  tone,
  summary,
}: {
  values: number[];
  seriesName: string;
  tone: "positive" | "negative" | "neutral";
  summary: string;
}) {
  if (values.length < 2) {
    return (
      <div style={chartFrameStyle}>
        <div style={chartHeaderStyle}>
          <span style={chartTitleStyle}>{seriesName}</span>
          <span style={chartHintStyle}>need ≥2 obs to draw a line</span>
        </div>
      </div>
    );
  }
  return (
    <div style={chartFrameStyle}>
      <div style={chartHeaderStyle}>
        <span style={chartTitleStyle}>{seriesName}</span>
        <span style={chartHintStyle}>{summary}</span>
      </div>
      <div style={chartCanvasStyle} aria-label="value sparkline">
        <Sparkline
          values={values}
          width={920}
          height={140}
          tone={tone === "neutral" ? "accent" : tone}
          ariaLabel={`${seriesName} trend`}
        />
      </div>
    </div>
  );
}

/**
 * Dual-series overlay for `compare_with`. Both series are indexed to 100 at
 * the first paired observation so a level series (CPI ~311) and a rate
 * series (10Y ~4.2) share one honest scale; the legend states the rebasing
 * explicitly. A baseline compare series is labelled as such — never drawn
 * as if it were a live provider feed.
 */
function CompareOverlay({
  seriesName,
  compareName,
  pairs,
  compareMode,
}: {
  seriesName: string;
  compareName: string;
  pairs: { date: string; value: number; compare: number }[];
  compareMode: string | null;
}) {
  const WIDTH = 920;
  const HEIGHT = 140;
  const PAD = 6;

  const chart = useMemo(() => {
    if (pairs.length < 2) return null;
    const baseV = pairs[0].value;
    const baseC = pairs[0].compare;
    if (!baseV || !baseC) return null;
    const indexedV = pairs.map((p) => (p.value / baseV) * 100);
    const indexedC = pairs.map((p) => (p.compare / baseC) * 100);
    let min = indexedV[0];
    let max = indexedV[0];
    for (const v of indexedV) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
    for (const v of indexedC) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
    const span = max - min || 1;
    const step = (WIDTH - PAD * 2) / (pairs.length - 1);
    const toPath = (series: number[]) =>
      series
        .map((v, i) => {
          const x = PAD + i * step;
          const y = HEIGHT - PAD - ((v - min) / span) * (HEIGHT - PAD * 2);
          return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" ");
    return {
      pathV: toPath(indexedV),
      pathC: toPath(indexedC),
      min,
      max,
    };
  }, [pairs]);

  if (!chart) {
    return (
      <div style={chartFrameStyle}>
        <div style={chartHeaderStyle}>
          <span style={chartTitleStyle}>
            {seriesName} vs {compareName}
          </span>
          <span style={chartHintStyle}>
            compare series returned no overlapping observations
          </span>
        </div>
      </div>
    );
  }

  const baseline = compareMode === "macro_series_baseline";
  const firstDate = pairs[0]?.date || "—";

  return (
    <div style={chartFrameStyle}>
      <div style={chartHeaderStyle}>
        <span style={chartTitleStyle}>
          {seriesName} vs {compareName}
        </span>
        <span style={chartHintStyle}>
          {`${pairs.length} paired obs · both indexed to 100 at ${firstDate}`}
          {baseline ? " · compare: labelled baseline (not live)" : ""}
        </span>
      </div>
      <div style={chartCanvasStyle}>
        <svg
          width="100%"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`${seriesName} versus ${compareName}, both indexed to 100 at ${firstDate}`}
          preserveAspectRatio="none"
          style={{ display: "block", width: "100%", height: HEIGHT }}
        >
          <path
            d={chart.pathV}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
          <path
            d={chart.pathC}
            fill="none"
            stroke="var(--accent-2, var(--accent))"
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="5 3"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
      <div style={compareLegendStyle}>
        <span style={legendItemStyle}>
          <span
            aria-hidden
            style={{ ...legendDotStyle, background: "var(--accent)" }}
          />
          {seriesName}
        </span>
        <span style={legendItemStyle}>
          <span
            aria-hidden
            style={{
              ...legendDotStyle,
              background: "var(--accent-2, var(--accent))",
            }}
          />
          {compareName}
          {baseline ? " (baseline)" : ""}
        </span>
        <span style={chartHintStyle}>
          {`index 100 = ${pairs[0].value.toLocaleString("en-US", { maximumFractionDigits: 4 })} / ${pairs[0].compare.toLocaleString("en-US", { maximumFractionDigits: 4 })}`}
        </span>
      </div>
    </div>
  );
}

function deriveTrendTone(values: number[]): {
  tone: "positive" | "negative" | "neutral";
  summary: string;
} {  if (values.length < 2) {
    return { tone: "neutral", summary: "no trend" };
  }
  const first = values[0];
  const last = values[values.length - 1];
  const diff = last - first;
  const pct = first !== 0 ? (diff / Math.abs(first)) * 100 : 0;
  const tone: "positive" | "negative" | "neutral" =
    diff > 0 ? "positive" : diff < 0 ? "negative" : "neutral";
  const sign = diff > 0 ? "+" : "";
  const summary = `${values.length} obs · Δ ${sign}${diff.toLocaleString("en-US", { maximumFractionDigits: 2 })} (${sign}${pct.toFixed(2)}%)`;
  return { tone, summary };
}

function normalizeRows(payload: unknown): EcstRow[] {
  if (Array.isArray(payload)) {
    return payload.filter((item): item is EcstRow => typeof item === "object" && item !== null);
  }
  return [];
}

function numeric(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const n = Number(value.replace(/[%,]/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
};

const chartFrameStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
};

const chartHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const chartTitleStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  fontWeight: 600,
  color: "var(--text-primary)",
  letterSpacing: "0.02em",
};

const chartHintStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
};

const chartCanvasStyle: CSSProperties = {
  width: "100%",
  display: "flex",
  alignItems: "stretch",
  justifyContent: "stretch",
};

const dateCellStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
  display: "inline-flex",
  alignItems: "baseline",
  gap: 4,
};

const unitStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const compareLegendStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  flexWrap: "wrap",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-secondary)",
};

const legendItemStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const legendDotStyle: CSSProperties = {
  width: 8,
  height: 3,
  borderRadius: 2,
  display: "inline-block",
};
