/**
 * EE — Earnings & Estimates.
 *
 * Historical EPS actual vs consensus + surprise % from Finnhub/yfinance.
 * Header: history segmented control + live mode + status + refresh.
 * Body: KPI ribbon (last actual, last estimate, last surprise %, beat rate)
 * + earnings grid with surprise DeltaChip + source pill.
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

interface EERow {
  symbol?: string;
  period?: string | null;
  date?: string | null;
  actual?: number | null;
  estimate?: number | null;
  surprisePercent?: number | null;
  source_mode?: string;
}

interface EEData {
  status?: string;
  rows?: EERow[];
  earnings?: unknown;
  calendar?: unknown;
  earnings_dates?: unknown;
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

const HISTORY_OPTIONS = [
  { value: 4, label: "4q" },
  { value: 8, label: "8q" },
  { value: 12, label: "12q" },
  { value: 20, label: "20q" },
] as const;
const HISTORY_IDS = HISTORY_OPTIONS.map((o) => o.value);

const LIVE_OPTIONS = [
  { value: "live", label: "Live" },
  { value: "model", label: "Model" },
] as const;
const LIVE_IDS = LIVE_OPTIONS.map((o) => o.value);
type LiveMode = (typeof LIVE_OPTIONS)[number]["value"];

export function EEPane({ code, symbol }: FunctionPaneProps) {
  const [history, setHistory] = usePersistentOption<number>(
    "showme.ee.history",
    HISTORY_IDS,
    8,
  );
  const [mode, setMode] = usePersistentOption<LiveMode>(
    "showme.ee.mode",
    LIVE_IDS,
    "live",
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<EEData>({
    code,
    symbol: effectiveSymbol,
    params: { history, live_earnings: mode === "live", live: mode === "live" },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: EERow[] = useMemo(
    () => (payload?.rows ?? []) as EERow[],
    [payload?.rows],
  );

  const stats = useMemo(() => deriveStats(rows), [rows]);
  const status = payload?.status ?? "—";
  const isLive = state === "ok" && status === "ok";
  const isUnavailable =
    rows.length > 0 &&
    rows[0]?.period === "provider_unavailable";

  const COLS: DataGridColumn<EERow>[] = useMemo(
    () => [
      {
        key: "period",
        header: "Period",
        width: 124,
        render: (r) => (
          <span style={monoPrimaryStyle}>{String(r.period ?? r.date ?? "—").slice(0, 16)}</span>
        ),
      },
      {
        key: "estimate",
        header: "Estimate",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtEps(r.estimate)}</span>
        ),
      },
      {
        key: "actual",
        header: "Actual",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtEps(r.actual)}</span>
        ),
      },
      {
        key: "surprisePercent",
        header: "Surprise",
        numeric: true,
        width: 104,
        render: (r) =>
          typeof r.surprisePercent === "number" &&
          Number.isFinite(r.surprisePercent) ? (
            <DeltaChip value={r.surprisePercent} format="percent" fractionDigits={2} />
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 200,
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={
                r.source_mode.includes("unavailable")
                  ? "warn"
                  : r.source_mode.includes("finnhub") ||
                      r.source_mode.includes("yfinance")
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
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="EE needs an equity ticker." icon="⌖" />
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
  ) : isUnavailable || rows.length === 0 ? (
    <Empty
      title={isUnavailable ? "Provider unavailable" : "No earnings history"}
      body={
        isUnavailable
          ? "Earnings calendar feed is unavailable for this symbol."
          : "Switch mode to live or pick another ticker."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="EE KPI ribbon">
        <StatCard
          label="Last actual"
          value={fmtEps(stats.lastActual)}
          caption={stats.lastPeriod ?? "—"}
          tone="neutral"
          trend={stats.actualTrend}
        />
        <StatCard
          label="Last estimate"
          value={fmtEps(stats.lastEstimate)}
          caption="CONSENSUS"
          tone="neutral"
        />
        <StatCard
          label="Last surprise"
          value={
            stats.lastSurprise != null
              ? `${stats.lastSurprise >= 0 ? "+" : ""}${stats.lastSurprise.toFixed(2)}%`
              : "—"
          }
          caption="vs ESTIMATE"
          tone={
            stats.lastSurprise == null
              ? "neutral"
              : stats.lastSurprise >= 0
                ? "positive"
                : "negative"
          }
          trend={stats.surpriseTrend}
        />
        <StatCard
          label="Beat rate"
          value={
            stats.beatRate != null ? `${(stats.beatRate * 100).toFixed(0)}%` : "—"
          }
          caption={`${stats.beatCount}/${stats.surpriseCount} BEAT`}
          tone={
            stats.beatRate == null
              ? "neutral"
              : stats.beatRate >= 0.5
                ? "positive"
                : "negative"
          }
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.period ?? ""}-${r.date ?? ""}-${i}`}
        density="compact"
        ariaLabel="EE earnings history"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Earnings & Estimates — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${rows.length} quarters`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} q
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <SegmentedControl
                label="HIST"
                value={history}
                options={HISTORY_OPTIONS}
                onChange={setHistory}
              />
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
                title="Refresh earnings"
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
          <StatusSection label="history" value={history} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface EEStats {
  lastActual: number | null;
  lastEstimate: number | null;
  lastSurprise: number | null;
  lastPeriod: string | null;
  beatCount: number;
  surpriseCount: number;
  beatRate: number | null;
  actualTrend: number[];
  surpriseTrend: number[];
}

function deriveStats(rows: EERow[]): EEStats {
  const surpriseList = rows
    .map((r) => (typeof r.surprisePercent === "number" ? r.surprisePercent : null))
    .filter((v): v is number => v != null && Number.isFinite(v));
  const actuals = rows
    .map((r) => (typeof r.actual === "number" ? r.actual : null))
    .filter((v): v is number => v != null && Number.isFinite(v));
  const beatCount = surpriseList.filter((v) => v > 0).length;
  return {
    lastActual: typeof rows[0]?.actual === "number" ? rows[0].actual : null,
    lastEstimate: typeof rows[0]?.estimate === "number" ? rows[0].estimate : null,
    lastSurprise:
      typeof rows[0]?.surprisePercent === "number"
        ? rows[0].surprisePercent
        : null,
    lastPeriod: (rows[0]?.period ?? rows[0]?.date ?? null) as string | null,
    beatCount,
    surpriseCount: surpriseList.length,
    beatRate: surpriseList.length ? beatCount / surpriseList.length : null,
    actualTrend: actuals.slice(0, 22).reverse(),
    surpriseTrend: surpriseList.slice(0, 22).reverse(),
  };
}

function fmtEps(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toFixed(2)}`;
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

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
