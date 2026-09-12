/**
 * ONCH — On-chain vitals (Bitcoin network dashboard).
 *
 * Global pane (not symbol-bound): mempool fee market, projected mempool
 * blocks, hashrate / difficulty epoch progress, plus companion market
 * context (dominance, total cap, 24h volume). Body: vitals StatCard ribbon
 * (from the payload cards) + projected-mempool-block bar chart (inline SVG)
 * + compact metric table (metric, value, source, context).
 *
 * Honesty: the backend marks this feed data_mode "delayed_reference" even
 * when live — the pane shows that mode verbatim instead of claiming
 * "live_official". The auto-refresh control polls the sidecar on an
 * interval (15/30/60s) only while the pane is mounted; "Off" is the
 * default. Provider outages arrive as status "provider_unavailable" with
 * warnings — surfaced verbatim, never backfilled with synthetic vitals.
 */
import { useEffect, useMemo, useRef, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  ProgressBar,
  Skeleton,
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

interface ONCHRow {
  metric?: string | null;
  value?: string | null;
  unit?: string | null;
  source?: string | null;
  context?: string | null;
}

interface ONCHSeriesPoint {
  bucket?: string | null;
  count?: number | null;
}

interface ONCHCard {
  label?: string | null;
  value?: unknown;
}

interface ONCHData {
  status?: string;
  data_mode?: string;
  chain?: string;
  rows?: ONCHRow[];
  series?: ONCHSeriesPoint[];
  cards?: ONCHCard[];
  summary?: string;
  methodology?: string;
  reason?: string;
  next_actions?: string[];
}

const REFRESH_OPTIONS = [
  { value: 0, label: "Off" },
  { value: 15, label: "15s" },
  { value: 30, label: "30s" },
  { value: 60, label: "60s" },
] as const;
const REFRESH_IDS: readonly number[] = REFRESH_OPTIONS.map((o) => o.value);

export function ONCHPane({ code }: FunctionPaneProps) {
  const [refreshSec, setRefreshSec] = usePersistentOption<number>(
    "showme.onch.refresh",
    REFRESH_IDS,
    0,
  );

  const { state, data, error, refetch } = useFunction<ONCHData>({ code });

  // Auto-refresh: `refetch` is recreated every render, so keep the latest
  // one in a ref and let the interval read through it — the interval itself
  // is (re)armed only when the cadence changes, and cleared on unmount or
  // cadence change (same ref + clearInterval idiom as MIS).
  const refetchRef = useRef(refetch);
  useEffect(() => {
    refetchRef.current = refetch;
  }, [refetch]);
  useEffect(() => {
    if (!refreshSec) return;
    const id = setInterval(() => refetchRef.current(), refreshSec * 1000);
    return () => clearInterval(id);
  }, [refreshSec]);

  const payload = data?.data;
  const rows: ONCHRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const cards: ONCHCard[] = useMemo(() => payload?.cards ?? [], [payload]);
  const series: ONCHSeriesPoint[] = useMemo(
    () => payload?.series ?? [],
    [payload],
  );
  const status = payload?.status ?? "—";
  const dataMode = payload?.data_mode ?? status;

  const COLS: DataGridColumn<ONCHRow>[] = useMemo(
    () => [
      {
        key: "metric",
        header: "Metric",
        width: 180,
        render: (r) => (
          <span style={monoStrongStyle}>{r.metric ?? "—"}</span>
        ),
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 140,
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {r.value ?? "—"}
            {r.unit ? (
              <span style={unitStyle}> {r.unit}</span>
            ) : null}
          </span>
        ),
      },
      {
        key: "source",
        header: "Source",
        width: 120,
        render: (r) =>
          r.source ? (
            <Pill tone="muted" variant="soft" withDot={false}>
              {r.source}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "context",
        header: "Context",
        width: 320,
        render: (r) => (
          <span className="u-text-mute">{r.context ?? "—"}</span>
        ),
      },
    ],
    [],
  );

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={72} />
      <Skeleton height={96} />
      <Skeleton height={20} />
      <Skeleton height={20} width="85%" />
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
  ) : rows.length === 0 ? (
    <Empty
      title="No on-chain vitals returned"
      body={
        payload?.next_actions?.[0] ??
        payload?.reason ??
        "The upstream providers returned no vitals."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {payload?.summary ? (
        <span className="u-text-mute" style={summaryStyle}>
          {payload.summary}
        </span>
      ) : null}
      {cards.length > 0 && (
        <section style={kpiGridStyle} aria-label="ONCH vitals cards">
          {cards.map((c, i) => (
            <StatCard
              key={c.label ?? i}
              label={c.label ?? "—"}
              value={typeof c.value === "string" ? c.value : "—"}
              tone="neutral"
            />
          ))}
        </section>
      )}
      <DifficultyEpochProgress rows={rows} />
      {series.length > 0 && <MempoolBars series={series} />}
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.metric ?? ""}-${i}`}
        density="compact"
        ariaLabel="ONCH on-chain metrics"
        // Lane B4: metric values are display strings with mixed units
        // (sat/vB, EH/s, %), so numeric sorting would be dishonest —
        // alphabetical metric ordering is the neutral default.
        defaultSortKey="metric"
        defaultSortDir="ascending"
        keyboardNavigable
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="On-chain Vitals — Bitcoin"
          subtitle={`${payload?.chain ?? "BTC"} · ${rows.length} metrics · as of ${
            (data?.asOf ?? "").slice(0, 10) || "—"
          }`}
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={
                  dataMode === "live_official"
                    ? "positive"
                    : dataMode === "delayed_reference"
                      ? "warn"
                      : "muted"
                }
                variant="soft"
              >
                {dataMode}
              </Pill>
              {refreshSec > 0 && (
                <Pill tone="accent" variant="soft" withDot>
                  {`auto ${refreshSec}s`}
                </Pill>
              )}
              <SegmentedControl
                label="AUTO"
                value={refreshSec}
                options={REFRESH_OPTIONS}
                onChange={(next) => setRefreshSec(next as number)}
                title="Auto-refresh cadence"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh on-chain vitals"
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
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="mode" value={dataMode} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="auto"
            value={refreshSec > 0 ? `${refreshSec}s` : "off"}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * Difficulty-epoch progress. mempool.space's difficulty-adjustment payload
 * supplies `progressPercent` / `remainingBlocks`, which the backend folds
 * into the "Difficulty Change" row's context string (onch.py:200-203); we
 * parse that verbatim display string — no re-derivation, no invented
 * numbers. Unparsable context renders an honest note instead of a bar.
 */
function difficultyEpochFromRows(
  rows: ONCHRow[],
): { progressPercent: number; remainingBlocks: number } | null {
  const row = rows.find((r) => r.metric === "Difficulty Change");
  if (!row?.context) return null;
  const match = /([\d.]+)% through epoch,\s*([\d,]+) blocks left/.exec(
    row.context,
  );
  if (!match) return null;
  const progressPercent = Number(match[1]);
  const remainingBlocks = Number(match[2].replace(/,/g, ""));
  if (!Number.isFinite(progressPercent) || !Number.isFinite(remainingBlocks)) {
    return null;
  }
  return { progressPercent, remainingBlocks };
}

function DifficultyEpochProgress({ rows }: { rows: ONCHRow[] }) {
  const hasRow = rows.some((r) => r.metric === "Difficulty Change");
  if (!hasRow) return null;
  const epoch = difficultyEpochFromRows(rows);
  if (!epoch) {
    return (
      <span className="u-text-mute" style={epochNoteStyle}>
        Difficulty epoch progress unavailable in this snapshot.
      </span>
    );
  }
  return (
    <section aria-label="Difficulty epoch progress" style={epochPanelStyle}>
      <div style={epochHeadStyle}>
        <span style={chartTitleStyle}>Difficulty epoch</span>
        <span className="u-text-mute" style={epochMetaStyle}>
          {`${Math.round(epoch.progressPercent)}% through epoch · ${epoch.remainingBlocks.toLocaleString("en-US")} blocks remaining`}
        </span>
      </div>
      <ProgressBar
        value={epoch.progressPercent}
        height={12}
        label={`${epoch.progressPercent.toFixed(1)}%`}
        ariaLabel={`Difficulty epoch ${epoch.progressPercent.toFixed(1)} percent complete, ${epoch.remainingBlocks} blocks remaining`}
      />
    </section>
  );
}

/**
 * Projected mempool blocks — inline SVG bars, one per upcoming block
 * bucket ("Block +1" … "+N"), transaction count above each bar.
 */
function MempoolBars({ series }: { series: ONCHSeriesPoint[] }) {
  const points = series.filter(
    (s): s is ONCHSeriesPoint & { count: number } =>
      typeof s.count === "number" && Number.isFinite(s.count),
  );
  if (!points.length) {
    return (
      <span className="u-text-mute">No projected mempool blocks returned.</span>
    );
  }
  const max = points.reduce((m, p) => Math.max(m, p.count), 0) || 1;
  const slot = 56;
  const barW = 34;
  const height = 88;
  const width = points.length * slot;
  return (
    <div>
      <div style={chartTitleStyle}>Projected mempool blocks (tx per block)</div>
      <svg
        role="img"
        aria-label={`Projected mempool blocks, ${points.length} buckets, busiest ${
          points.reduce((m, p) => (p.count > m.count ? p : m), points[0]).bucket ?? ""
        } with ${max} tx`}
        width={width}
        height={height + 22}
        style={{ maxWidth: "100%" }}
      >
        {points.map((p, i) => {
          const h = Math.max(2, (p.count / max) * height);
          const x = i * slot + (slot - barW) / 2;
          return (
            <g key={p.bucket ?? i}>
              <title>{`${p.bucket ?? "—"}: ${p.count.toLocaleString("en-US")} tx`}</title>
              <rect
                x={x}
                y={height - h}
                width={barW}
                height={h}
                rx={2}
                fill="var(--accent)"
              />
              <text
                x={x + barW / 2}
                y={height + 14}
                textAnchor="middle"
                fontSize={9}
                fill="var(--text-mute)"
                style={{ fontFamily: "JetBrains Mono, monospace" }}
              >
                {(p.bucket ?? "").replace("Block ", "")}
              </text>
              <text
                x={x + barW / 2}
                y={height - h - 3}
                textAnchor="middle"
                fontSize={9}
                fill="var(--text-secondary)"
                style={{ fontFamily: "JetBrains Mono, monospace" }}
              >
                {p.count >= 10000
                  ? `${(p.count / 1000).toFixed(0)}k`
                  : p.count.toLocaleString("en-US")}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

const summaryStyle: CSSProperties = { fontSize: "var(--font-size-md)" };
const epochPanelStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "8px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-2)",
};
const epochHeadStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 8,
  flexWrap: "wrap",
};
const epochMetaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
};
const epochNoteStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
};
const chartTitleStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-mute)",
  marginBottom: 4,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};
const unitStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
};
const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};
const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};
const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};
