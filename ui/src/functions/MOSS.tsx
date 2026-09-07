/**
 * MOSS — Most Volatile. Realised-volatility leaderboard across a universe.
 *
 * Global screen (not symbol-bound): the backend ranks the whole universe by
 * annualized realised volatility and returns one rolling-vol history series
 * for the current top symbol. Body: top-symbol sparkline card (design-system
 * Sparkline over the payload history) + ranked leaderboard table (symbol,
 * class, vol %, samples, last close, window) with sort-by-metric chips and a
 * TOP-N cap with a showing-note.
 *
 * Honesty: the backend gates live data behind an explicit `live` flag and the
 * default path returns a synthetic template — the pane always sends
 * `live: true`. When the provider is down the payload arrives as status
 * "provider_unavailable" with a reason, surfaced verbatim (never backfilled).
 * No per-row "change" column is fabricated: the payload carries a history
 * series for the top symbol only.
 */
import { useMemo, useState, type CSSProperties } from "react";
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
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  RowLimitControl,
  SegmentedControl,
} from "./function-controls";
import {
  TOP_N_LIMITS,
  usePersistentOption,
  type TopNLimit,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface MOSSRow {
  symbol?: string | null;
  asset_class?: string | null;
  vol_annualized?: number | null;
  vol?: number | null;
  vol_pct?: number | null;
  samples?: number | null;
  last_close?: number | null;
  start?: string | null;
  end?: string | null;
}

interface MOSSHistoryPoint {
  date?: string | null;
  symbol?: string | null;
  vol?: number | null;
  vol_pct?: number | null;
  window?: number | null;
}

interface MOSSData {
  status?: string;
  rows?: MOSSRow[];
  history?: MOSSHistoryPoint[];
  universe?: string[];
  lookback_days?: number;
  top_symbol?: string;
  live?: boolean;
  methodology?: string;
  reason?: string;
  next_actions?: string[];
}

type SortMetric = "vol" | "samples" | "close";

const DAYS_OPTIONS = [
  { value: 30, label: "30d" },
  { value: 60, label: "60d" },
  { value: 90, label: "90d" },
  { value: 120, label: "120d" },
] as const;
const DAYS_IDS: readonly number[] = DAYS_OPTIONS.map((o) => o.value);

const SORT_OPTIONS: { value: SortMetric; label: string }[] = [
  { value: "vol", label: "Vol" },
  { value: "samples", label: "Samples" },
  { value: "close", label: "Close" },
];

// Backend hard-caps `limit` at 200; we always ask for the full ranking and
// apply the user's TOP-N cap client-side so the showing-note stays honest.
const SERVER_LIMIT = 200;

export function MOSSPane({ code }: FunctionPaneProps) {
  const [days, setDays] = usePersistentOption<number>(
    "showme.moss.days",
    DAYS_IDS,
    90,
  );
  const [topN, setTopN] = usePersistentOption<TopNLimit>(
    "showme.moss.topN",
    TOP_N_LIMITS,
    10,
  );
  const [sort, setSort] = useState<SortMetric>("vol");

  const { state, data, error, refetch } = useFunction<MOSSData>({
    code,
    params: { live: true, days, limit: SERVER_LIMIT },
  });

  const payload = data?.data;
  const rows: MOSSRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const isLive = payload?.live === true;

  const sorted = useMemo(() => {
    const copy = [...rows];
    const metric = (r: MOSSRow): number => {
      if (sort === "samples") return r.samples ?? -1;
      if (sort === "close") return r.last_close ?? -1;
      return r.vol_pct ?? r.vol ?? r.vol_annualized ?? -1;
    };
    copy.sort((a, b) => metric(b) - metric(a));
    return copy;
  }, [rows, sort]);

  const shown = sorted.slice(0, topN);

  const historyValues = useMemo(
    () =>
      (payload?.history ?? [])
        .map((h) => h.vol_pct ?? h.vol)
        .filter((v): v is number => typeof v === "number" && Number.isFinite(v)),
    [payload],
  );
  const topSymbol = payload?.top_symbol ?? "";

  const COLS: DataGridColumn<MOSSRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 130,
        render: (r) => (
          <span style={monoStrongStyle}>{r.symbol ?? "—"}</span>
        ),
      },
      {
        key: "asset_class",
        header: "Class",
        width: 96,
        render: (r) => (
          <span style={monoMutedStyle}>{r.asset_class ?? "—"}</span>
        ),
      },
      {
        key: "vol_pct",
        header: "Vol % (ann.)",
        numeric: true,
        width: 130,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtPct(r.vol_pct)}</span>
        ),
      },
      {
        key: "samples",
        header: "Samples",
        numeric: true,
        width: 100,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.samples, 0)}</span>
        ),
      },
      {
        key: "last_close",
        header: "Last close",
        numeric: true,
        width: 120,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.last_close, 2)}</span>
        ),
      },
      {
        key: "window",
        header: "Window",
        width: 160,
        render: (r) => (
          <span className="u-text-mute">
            {r.start && r.end ? `${r.start} → ${r.end}` : "—"}
          </span>
        ),
      },
    ],
    [],
  );

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
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
      title="No volatility rows returned"
      body={
        payload?.next_actions?.[0] ??
        payload?.reason ??
        "The provider returned no ranked rows."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {historyValues.length > 1 && topSymbol ? (
        <section
          aria-label="Top symbol volatility history"
          style={historyCardStyle}
        >
          <div>
            <div style={historyTitleStyle}>
              Top vol — <span style={monoStrongStyle}>{topSymbol}</span>
            </div>
            <div style={historyMetaStyle}>
              Rolling 20-session annualized volatility · latest{" "}
              {fmtPct(historyValues[historyValues.length - 1])}
            </div>
          </div>
          <Sparkline
            values={historyValues}
            width={180}
            height={40}
            tone="accent"
            ariaLabel={`Rolling volatility history for ${topSymbol}`}
          />
        </section>
      ) : null}
      <DataGrid
        columns={COLS}
        rows={shown}
        rowKey={(r, i) => `${r.symbol ?? ""}-${i}`}
        density="compact"
        ariaLabel="MOSS volatility leaderboard"
      />
      {sorted.length > shown.length && (
        <span className="u-text-mute" style={noteStyle}>
          Showing {shown.length} of {sorted.length} rows (TOP cap).
        </span>
      )}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Most Volatile"
          subtitle={`${rows.length} rows · lookback ${payload?.lookback_days ?? days}d · top ${topSymbol || "—"}`}
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={isLive ? "positive" : "muted"}
                variant="soft"
                withDot={isLive}
              >
                {isLive ? "live" : "reference"}
              </Pill>
              <SegmentedControl
                label="SORT"
                value={sort}
                options={SORT_OPTIONS}
                onChange={(next) => setSort(next as SortMetric)}
              />
              <SegmentedControl
                label="LOOKBACK"
                value={days}
                options={DAYS_OPTIONS}
                onChange={(next) => setDays(next as number)}
              />
              <RowLimitControl
                label="TOP"
                value={topN}
                onChange={(next) => setTopN(next as TopNLimit)}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh volatility ranking"
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
          <StatusSection
            label="universe"
            value={`${payload?.universe?.length ?? 0} symbols`}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="top" value={`TOP ${topN}`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function fmtNum(v: unknown, digits: number): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtPct(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(1)}%`;
}

const noteStyle: CSSProperties = { fontSize: 11 };
const historyCardStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 16,
  padding: "10px 14px",
  border: "1px solid var(--border)",
  borderRadius: 6,
};
const historyTitleStyle: CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: "var(--text-primary)",
};
const historyMetaStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-mute)",
  marginTop: 2,
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
const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
