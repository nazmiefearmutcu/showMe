/**
 * ECST — Economic statistics.
 *
 * Single FRED-series time-series viewer. Header SegmentedControl picks the
 * series_id (CPIAUCSL / GDPC1 / UNRATE / DGS10 / DGS2); body shows a KPI
 * ribbon from the backend's `cards` array, a Sparkline of the value path
 * across ascending dates, and a dense DataGrid of (date, value, source).
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

interface EcstRow {
  date?: string;
  series_id?: string;
  series_name?: string;
  value?: number | string | null;
  unit?: string;
  frequency?: string;
  source_mode?: string;
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
}

export function ECSTPane({ code }: FunctionPaneProps) {
  const [seriesId, setSeriesId] = usePersistentOption(
    "showme.ecst.series",
    SERIES_IDS,
    "CPIAUCSL",
  );

  const { state, data, error, refetch } = useFunction<EcstPayload>({
    code,
    params: { series_id: seriesId },
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

  const trend = useMemo(() => deriveTrendTone(values), [values]);
  const isLive = state === "ok";

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
              {n.toLocaleString(undefined, { maximumFractionDigits: 4 })}
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
                tone={sourceMode === "fred" ? "positive" : "muted"}
                variant="soft"
                withDot={false}
              >
                {sourceMode}
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : state}
              </Pill>
              <SegmentedControl
                label="SERIES"
                value={seriesId}
                options={SERIES}
                onChange={setSeriesId}
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
              <SeriesChart
                values={values}
                seriesName={seriesName}
                tone={trend.tone}
                summary={trend.summary}
              />
              <DataGrid
                columns={COLS}
                rows={sortedRows}
                rowKey={(row, i) => `${row.date ?? ""}-${i}`}
                density="compact"
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
                : n.toLocaleString(undefined, { maximumFractionDigits: 4 })
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

function deriveTrendTone(values: number[]): {
  tone: "positive" | "negative" | "neutral";
  summary: string;
} {
  if (values.length < 2) {
    return { tone: "neutral", summary: "no trend" };
  }
  const first = values[0];
  const last = values[values.length - 1];
  const diff = last - first;
  const pct = first !== 0 ? (diff / Math.abs(first)) * 100 : 0;
  const tone: "positive" | "negative" | "neutral" =
    diff > 0 ? "positive" : diff < 0 ? "negative" : "neutral";
  const sign = diff > 0 ? "+" : "";
  const summary = `${values.length} obs · Δ ${sign}${diff.toLocaleString(undefined, { maximumFractionDigits: 2 })} (${sign}${pct.toFixed(2)}%)`;
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
  fontSize: 12,
  fontWeight: 600,
  color: "var(--text-primary)",
  letterSpacing: "0.02em",
};

const chartHintStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
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
  fontSize: 10,
  color: "var(--text-mute)",
};
