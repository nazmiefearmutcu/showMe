/**
 * GC3D — Yield Curve 3D (date × tenor surface).
 *
 * The backend returns a flat surface (date, tenor, tenor_years, yield);
 * the native 2D fallback renders it as a heat-tinted grid: tenors as rows,
 * snapshot dates as columns, each cell tinted by its yield relative to the
 * surface min/max (token-derived accent tints only). Header: look-back
 * days control (persisted `showme.gc3d.days`) + data-mode pill + refresh.
 *
 * Data honesty: without a FRED key the backend serves a labelled
 * yield-curve model template (rolling dates, fixed reference levels) —
 * shown with a prominent MODEL FIXTURE pill + inline notice.
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
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
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

interface GC3DPoint {
  date?: string;
  tenor?: string;
  tenor_years?: number;
  yield?: number;
}

interface GC3DData {
  surface?: GC3DPoint[];
  rows?: GC3DPoint[];
  tenors?: string[];
  dates?: string[];
  summary?: {
    source_mode?: string;
    dates?: number;
    tenors?: number;
    points?: number;
    days?: number;
  };
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

interface GridRow {
  tenor: string;
  tenorYears: number | null;
  values: Record<string, number | null>;
}

const DAYS_OPTIONS = [
  { value: 90, label: "90d" },
  { value: 180, label: "180d" },
  { value: 365, label: "1y" },
  { value: 730, label: "2y" },
] as const;
const DAYS_IDS = DAYS_OPTIONS.map((o) => o.value);

/** Max date columns rendered before downsampling to keep the grid readable. */
const MAX_DATE_COLS = 8;

export function GC3DPane({ code, symbol }: FunctionPaneProps) {
  const [days, setDays] = usePersistentOption<number>(
    "showme.gc3d.days",
    DAYS_IDS,
    365,
  );
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "BOND"]);
  const { state, data, error, refetch } = useFunction<GC3DData>({
    code,
    symbol: effectiveSymbol,
    params: { days },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const surface: GC3DPoint[] = useMemo(
    () =>
      payload?.surface && payload.surface.length
        ? payload.surface
        : payload?.rows ?? [],
    [payload],
  );
  const summary = payload?.summary;
  const sourceMode = summary?.source_mode ?? "yield_curve_model";
  const isModelFixture = sourceMode !== "fred";

  const grid = useMemo(() => buildGrid(surface, payload), [surface, payload]);

  const COLS: DataGridColumn<GridRow>[] = useMemo(() => {
    const tenorCol: DataGridColumn<GridRow> = {
      key: "tenor",
      header: "Tenor",
      width: 92,
      render: (r) => (
        <span style={monoStrongStyle}>
          {r.tenor}
          {r.tenorYears != null ? (
            <span style={monoMutedStyle}> · {fmtYears(r.tenorYears)}y</span>
          ) : null}
        </span>
      ),
    };
    const dateCols = grid.displayDates.map((date) => ({
      key: date,
      header: date.slice(5),
      numeric: true,
      render: (r: GridRow) => (
        <HeatCell
          value={r.values[date] ?? null}
          min={grid.min}
          max={grid.max}
          title={r.values[date] != null ? `${r.tenor} ${date}` : `${r.tenor} ${date} (no data)`}
        />
      ),
    }));
    return [tenorCol, ...dateCols];
  }, [grid]);

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={20} />
        <Skeleton height={20} />
        <Skeleton height={20} width="80%" />
      </div>
    ) : state === "error" ? (
      <Empty
        title="Function error"
        body={error?.message ?? "—"}
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : surface.length === 0 || grid.tenors.length === 0 ? (
      <Empty
        title="No surface returned"
        body="The backend returned no date-by-tenor points — retry or widen the look-back window."
        icon="∅"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        {isModelFixture ? (
          <div role="note" style={noticeStyle}>
            <strong>Curve template.</strong> No FRED key is configured, so the
            backend served its labelled yield-curve fixture (rolling dates,
            fixed reference levels) — NOT live Treasury observations.
          </div>
        ) : null}
        <section style={kpiGridStyle} aria-label="GC3D surface stats">
          <StatCard
            label="Snapshots"
            value={String(grid.dates.length)}
            caption={`LOOK-BACK ${summary?.days ?? days}D`}
            tone="neutral"
          />
          <StatCard
            label="Tenors"
            value={String(grid.tenors.length)}
            caption={`${grid.tenors[0] ?? "—"} → ${grid.tenors[grid.tenors.length - 1] ?? "—"}`}
            tone="neutral"
          />
          <StatCard
            label="Yield range"
            value={`${grid.min.toFixed(3)}–${grid.max.toFixed(3)}%`}
            caption={`TINT = RELATIVE LEVEL`}
            tone="neutral"
          />
          <StatCard
            label="Points"
            value={String(summary?.points ?? surface.length)}
            caption={`MODE ${sourceMode.toUpperCase()}`}
            tone="neutral"
          />
        </section>
        <div>
          <div style={gridTitleStyle}>
            date × tenor surface (yield %, accent tint = level vs range)
          </div>
          <DataGrid
            columns={COLS}
            rows={grid.rows}
            rowKey={(r) => r.tenor}
            density="compact"
            ariaLabel="GC3D date-by-tenor surface"
          />
          {grid.dates.length > grid.displayDates.length ? (
            <div style={captionStyle}>
              showing {grid.displayDates.length} of {grid.dates.length}{" "}
              snapshot dates (downsampled for readability)
            </div>
          ) : null}
        </div>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Yield Curve Surface — ${summary?.tenors ?? grid.tenors.length}×${summary?.dates ?? grid.dates.length}`}
          subtitle={`${effectiveSymbol || "—"} · ${surface.length} points`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {surface.length} pts
              </Pill>
              <Pill
                tone={isModelFixture ? "warn" : "positive"}
                variant="soft"
                withDot={!isModelFixture}
              >
                {isModelFixture ? "model fixture" : "FRED live"}
              </Pill>
              <SegmentedControl
                label="LOOK-BACK"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
              />
              <LoadStatePill state={state} status={sourceMode} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh yield surface"
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
          <StatusSection label="mode" value={sourceMode} />
          <StatusDivider />
          <StatusSection label="points" value={surface.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="days" value={days} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── grid assembly ─────────────────────────────────────────────────── */

interface Grid {
  tenors: string[];
  dates: string[];
  displayDates: string[];
  rows: GridRow[];
  min: number;
  max: number;
}

function buildGrid(
  surface: GC3DPoint[],
  payload: GC3DData | undefined,
): Grid {
  const tenorYears = new Map<string, number>();
  for (const p of surface) {
    if (p.tenor && typeof p.tenor_years === "number") {
      tenorYears.set(p.tenor, p.tenor_years);
    }
  }
  const tenors = payload?.tenors?.length
    ? [...payload.tenors]
    : [...tenorYears.keys()];
  tenors.sort(
    (a, b) => (tenorYears.get(a) ?? 0) - (tenorYears.get(b) ?? 0),
  );
  const dateSet = new Set<string>();
  const valueMap = new Map<string, number>();
  const yields: number[] = [];
  for (const p of surface) {
    if (!p.date || !p.tenor || typeof p.yield !== "number") continue;
    dateSet.add(p.date);
    valueMap.set(`${p.date}|${p.tenor}`, p.yield);
    yields.push(p.yield);
  }
  const dates = payload?.dates?.length ? [...payload.dates] : [...dateSet].sort();
  dates.sort();
  const min = yields.length ? Math.min(...yields) : 0;
  const max = yields.length ? Math.max(...yields) : 0;

  const rows: GridRow[] = tenors.map((tenor) => {
    const values: Record<string, number | null> = {};
    for (const date of dates) {
      values[date] = valueMap.get(`${date}|${tenor}`) ?? null;
    }
    return { tenor, tenorYears: tenorYears.get(tenor) ?? null, values };
  });

  return { tenors, dates, displayDates: downsample(dates, MAX_DATE_COLS), rows, min, max };
}

/** Keep the first/last and evenly-spaced subset when there are too many columns. */
function downsample(items: string[], max: number): string[] {
  if (items.length <= max) return items;
  const out: string[] = [];
  for (let i = 0; i < max; i += 1) {
    const idx = Math.round((i * (items.length - 1)) / (max - 1));
    out.push(items[idx]);
  }
  return [...new Set(out)];
}

/* ── heat cell ─────────────────────────────────────────────────────── */

function HeatCell({
  value,
  min,
  max,
  title,
}: {
  value: number | null;
  min: number;
  max: number;
  title: string;
}) {
  if (value == null || !Number.isFinite(value)) {
    return (
      <span style={heatWrapStyle} title={title}>
        <span style={heatTextStyle}>—</span>
      </span>
    );
  }
  const span = max - min;
  const norm = span > 0 ? (value - min) / span : 0.5;
  return (
    <span style={heatWrapStyle} title={`${title}: ${value.toFixed(3)}%`}>
      <span
        aria-hidden="true"
        style={{ ...heatFillStyle, opacity: 0.06 + 0.34 * norm }}
      />
      <span style={heatTextStyle}>{value.toFixed(3)}</span>
    </span>
  );
}

/* ── formatting ────────────────────────────────────────────────────── */

function fmtYears(v: number): string {
  return v < 1 ? v.toFixed(2) : String(v);
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 12,
  color: "var(--text-primary)",
};

const gridTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  letterSpacing: "0.05em",
  marginBottom: 6,
};

const captionStyle: CSSProperties = {
  marginTop: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
};

const heatWrapStyle: CSSProperties = {
  position: "relative",
  display: "flex",
  justifyContent: "flex-end",
  padding: "1px 4px",
  borderRadius: 3,
  overflow: "hidden",
};

const heatFillStyle: CSSProperties = {
  position: "absolute",
  inset: 0,
  background: "var(--accent)",
};

const heatTextStyle: CSSProperties = {
  position: "relative",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 11,
  color: "var(--text-primary)",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
