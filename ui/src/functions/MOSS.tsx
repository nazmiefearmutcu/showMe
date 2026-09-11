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
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Sparkline,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { PaneState } from "@/design-system/PaneState";
import { compareGridValues } from "@/design-system/DataGrid";
import { formatNumberFixed } from "@/lib/format";
import { navigate } from "@/lib/router";
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

type SortDir = "ascending" | "descending";

const DAYS_OPTIONS = [
  { value: 30, label: "30d" },
  { value: 60, label: "60d" },
  { value: 90, label: "90d" },
  { value: 120, label: "120d" },
] as const;
const DAYS_IDS: readonly number[] = DAYS_OPTIONS.map((o) => o.value);

// Backend hard-caps `limit` at 200; we always ask for the full ranking and
// apply the user's TOP-N cap client-side so the showing-note stays honest.
const SERVER_LIMIT = 200;

function metricFor(r: MOSSRow, key: string): unknown {
  if (key === "samples") return r.samples ?? null;
  if (key === "last_close") return r.last_close ?? null;
  if (key === "symbol") return r.symbol ?? null;
  if (key === "asset_class") return r.asset_class ?? null;
  return r.vol_pct ?? r.vol ?? r.vol_annualized ?? null;
}

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
  const [sortBy, setSortBy] = useState<string | null>("vol_pct");
  const [sortDir, setSortDir] = useState<SortDir>("descending");

  const { state, data, error, refetch } = useFunction<MOSSData>({
    code,
    params: { live: true, days, limit: SERVER_LIMIT },
  });

  const payload = data?.data;
  const rows: MOSSRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const isLive = payload?.live === true;

  const onSort = (key: string) => {
    if (sortBy !== key) {
      setSortBy(key);
      setSortDir("descending");
    } else if (sortDir === "descending") {
      setSortDir("ascending");
    } else {
      setSortBy(null);
    }
  };

  const sorted = useMemo(() => {
    if (!sortBy) return rows;
    const mul = sortDir === "ascending" ? 1 : -1;
    return [...rows]
      .map((row, index) => ({ row, index }))
      .sort((a, b) => {
        const av = metricFor(a.row, sortBy);
        const bv = metricFor(b.row, sortBy);
        if (av == null && bv == null) return a.index - b.index;
        // Nullish values sink regardless of direction (matches DataGrid).
        if (av == null) return 1;
        if (bv == null) return -1;
        const cmp = compareGridValues(av, bv);
        if (cmp !== 0) return mul * cmp;
        return a.index - b.index;
      })
      .map((entry) => entry.row);
  }, [rows, sortBy, sortDir]);

  const shown = sorted.slice(0, topN);

  const historyValues = useMemo(
    () =>
      (payload?.history ?? [])
        .map((h) => h.vol_pct ?? h.vol)
        .filter((v): v is number => typeof v === "number" && Number.isFinite(v)),
    [payload],
  );
  const topSymbol = payload?.top_symbol ?? "";
  // F14: never hardcode the rolling window — the payload carries it per point.
  const historyWindow = (payload?.history?.[0] as { window?: number } | undefined)?.window;

  const COLS: DataGridColumn<MOSSRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 130,
        sortable: true,
        render: (r) => (
          <button
            type="button"
            className="scan-symbol"
            title="Open DES"
            aria-label={`Open ${r.symbol ?? "symbol"} in DES`}
            onClick={() => {
              if (r.symbol) navigate(`/symbol/${r.symbol}/DES`);
            }}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && r.symbol) {
                e.preventDefault();
                navigate(`/symbol/${r.symbol}/DES`);
              }
            }}
          >
            {r.symbol ?? "—"}
          </button>
        ),
      },
      {
        key: "asset_class",
        header: "Class",
        width: 96,
        sortable: true,
        render: (r) => (
          <span style={monoMutedStyle}>{r.asset_class ?? "—"}</span>
        ),
      },
      {
        key: "vol_pct",
        header: "Vol % (ann.)",
        numeric: true,
        width: 130,
        sortable: true,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtPct(r.vol_pct)}</span>
        ),
      },
      {
        key: "samples",
        header: "Samples",
        numeric: true,
        width: 100,
        sortable: true,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.samples, 0)}</span>
        ),
      },
      {
        key: "last_close",
        header: "Last close",
        numeric: true,
        width: 120,
        sortable: true,
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

  const body = (
    <PaneState
      state={state}
      error={error}
      empty={rows.length === 0}
      emptyTitle="No volatility rows returned"
      emptyBody={
        payload?.next_actions?.[0] ??
        payload?.reason ??
        "The provider returned no ranked rows."
      }
      onRetry={refetch}
    >
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
                Rolling {historyWindow ? `${historyWindow}-session ` : ""}annualized volatility · latest{" "}
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
          sortBy={sortBy ?? undefined}
          sortDir={sortBy ? sortDir : "none"}
          onSort={onSort}
        />
        {sorted.length > shown.length && (
          <span className="u-text-mute" style={noteStyle}>
            Showing {shown.length} of {sorted.length} rows (TOP cap).
          </span>
        )}
      </div>
    </PaneState>
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
  return formatNumberFixed(n, digits);
}

function fmtPct(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(1)}%`;
}

const noteStyle: CSSProperties = { fontSize: "var(--font-size-sm)" };
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
  fontSize: "var(--font-size-lg)",
  fontWeight: 600,
  color: "var(--text-primary)",
};
const historyMetaStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
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
