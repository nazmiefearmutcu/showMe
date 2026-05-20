/**
 * DVD — Dividends & Splits.
 *
 * Surfaces yfinance corporate-action events. Live toggle drives the backend
 * `live_dividends` flag. Header: live toggle + status pill + refresh.
 * Body: KPI ribbon (last dividend, latest yield-proxy, # dividends, # splits)
 * + action grid with source_mode pill.
 */
import { useMemo, type CSSProperties } from "react";
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

interface DVDRow {
  symbol?: string;
  action_type?: string;
  date?: string | null;
  amount?: number | null;
  source_mode?: string;
  reason?: string;
}

interface DVDData {
  status?: string;
  rows?: DVDRow[];
  history?: DVDRow[];
  dividends?: unknown;
  splits?: unknown;
  actions?: unknown;
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

const LIVE_OPTIONS = [
  { value: "live", label: "Live" },
  { value: "model", label: "Model" },
] as const;
const LIVE_IDS = LIVE_OPTIONS.map((o) => o.value);
type LiveMode = (typeof LIVE_OPTIONS)[number]["value"];

export function DVDPane({ code, symbol }: FunctionPaneProps) {
  const [mode, setMode] = usePersistentOption<LiveMode>(
    "showme.dvd.mode",
    LIVE_IDS,
    "live",
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<DVDData>({
    code,
    symbol: effectiveSymbol,
    params: { live_dividends: mode === "live", live: mode === "live" },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: DVDRow[] = useMemo(
    () => (payload?.rows ?? []) as DVDRow[],
    [payload?.rows],
  );
  const dividendRows = useMemo(
    () => rows.filter((r) => r.action_type === "dividend"),
    [rows],
  );
  const splitRows = useMemo(
    () => rows.filter((r) => r.action_type === "split"),
    [rows],
  );

  const stats = useMemo(() => deriveStats(dividendRows, splitRows), [
    dividendRows,
    splitRows,
  ]);
  const status = payload?.status ?? "—";
  const isLive = state === "ok" && status === "ok";
  const isProviderEmpty =
    rows.length > 0 && rows[0]?.action_type === "provider_unavailable";

  const COLS: DataGridColumn<DVDRow>[] = useMemo(
    () => [
      {
        key: "date",
        header: "Date",
        width: 122,
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {String(r.date ?? "—").slice(0, 10)}
          </span>
        ),
      },
      {
        key: "action_type",
        header: "Type",
        width: 96,
        render: (r) => actionPill(r.action_type),
      },
      {
        key: "amount",
        header: "Amount",
        numeric: true,
        width: 112,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtAmount(r.amount, r.action_type)}</span>
        ),
      },
      {
        key: "delta",
        header: "Δ vs prev",
        numeric: true,
        width: 108,
        render: (r, i) => {
          if (r.action_type !== "dividend") return <span className="u-text-mute">—</span>;
          const list = dividendRows;
          const idx = list.findIndex((x) => x === r);
          if (idx < 0) return <span className="u-text-mute">—</span>;
          const next = list[idx + 1];
          const cur = typeof r.amount === "number" ? r.amount : null;
          const prev = typeof next?.amount === "number" ? next.amount : null;
          if (cur == null || prev == null || prev === 0) {
            return <span className="u-text-mute">—</span>;
          }
          const pct = ((cur - prev) / Math.abs(prev)) * 100;
          return <DeltaChip key={i} value={pct} format="percent" fractionDigits={2} />;
        },
      },
      {
        key: "source_mode",
        header: "Source",
        width: 220,
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={
                r.action_type === "provider_unavailable"
                  ? "warn"
                  : r.source_mode.includes("live")
                    ? "accent"
                    : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {r.source_mode}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [dividendRows],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="DVD needs an equity / ETF ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
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
  ) : rows.length === 0 || isProviderEmpty ? (
    <Empty
      title={isProviderEmpty ? "Provider unavailable" : "No corporate actions"}
      body={
        isProviderEmpty
          ? rows[0]?.reason ?? "yfinance returned no dividend/split rows."
          : "No dividend or split events for this symbol."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="DVD KPI ribbon">
        <StatCard
          label="Last dividend"
          value={fmtAmount(stats.lastDividend, "dividend")}
          caption={stats.lastDividendDate ?? "—"}
          tone="neutral"
          trend={stats.dividendTrend}
        />
        <StatCard
          label="Dividends"
          value={String(dividendRows.length)}
          caption="HISTORICAL ROWS"
          tone="neutral"
        />
        <StatCard
          label="Splits"
          value={String(splitRows.length)}
          caption={
            stats.lastSplit
              ? `LAST ${stats.lastSplit} @ ${stats.lastSplitDate ?? "—"}`
              : "NO SPLITS"
          }
          tone="neutral"
        />
        <StatCard
          label="YoY Δ"
          value={
            stats.yoyDelta != null
              ? `${stats.yoyDelta >= 0 ? "+" : ""}${stats.yoyDelta.toFixed(2)}%`
              : "—"
          }
          caption="LATEST VS 4 PRIOR"
          tone={
            stats.yoyDelta == null
              ? "neutral"
              : stats.yoyDelta >= 0
                ? "positive"
                : "negative"
          }
          trend={stats.dividendTrend}
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.date ?? ""}-${r.action_type ?? ""}-${i}`}
        density="compact"
        ariaLabel="DVD corporate actions"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Dividends & Splits — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${dividendRows.length} div · ${splitRows.length} split`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {dividendRows.length} div
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <SegmentedControl
                label="MODE"
                value={mode}
                options={LIVE_OPTIONS}
                onChange={setMode}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh corporate actions"
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
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="mode" value={mode} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface DVDStats {
  lastDividend: number | null;
  lastDividendDate: string | null;
  lastSplit: number | null;
  lastSplitDate: string | null;
  yoyDelta: number | null;
  dividendTrend: number[];
}

function deriveStats(dividendRows: DVDRow[], splitRows: DVDRow[]): DVDStats {
  const divVals = dividendRows
    .map((r) => (typeof r.amount === "number" ? r.amount : null))
    .filter((v): v is number => v != null && Number.isFinite(v));
  const lastDividend = divVals[0] ?? null;
  const yoy = divVals[4] ?? null;
  const yoyDelta =
    lastDividend != null && yoy && yoy !== 0
      ? ((lastDividend - yoy) / Math.abs(yoy)) * 100
      : null;
  return {
    lastDividend,
    lastDividendDate: dividendRows[0]?.date ?? null,
    lastSplit:
      typeof splitRows[0]?.amount === "number" ? splitRows[0].amount : null,
    lastSplitDate: splitRows[0]?.date ?? null,
    yoyDelta,
    dividendTrend: divVals.slice(0, 22).reverse(),
  };
}

function fmtAmount(v: unknown, kind?: string): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  if (kind === "split") return `${n.toFixed(2)}:1`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
}

function actionPill(action: string | undefined) {
  if (!action) return <span className="u-text-mute">—</span>;
  const tone: "positive" | "accent" | "warn" | "muted" =
    action === "dividend"
      ? "positive"
      : action === "split"
        ? "accent"
        : action === "provider_unavailable"
          ? "warn"
          : "muted";
  return (
    <Pill tone={tone} variant="soft" withDot={false}>
      {action}
    </Pill>
  );
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
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
