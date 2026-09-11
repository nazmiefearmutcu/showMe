/**
 * EREV — Earnings Revisions.
 *
 * Analyst recommendation buckets and revision velocity from Finnhub.
 * Header: status pill + refresh.
 * Body: KPI ribbon (current avg, velocity, analyst count, net upgrade count)
 * + trend grid with score DeltaChip and bucket counts.
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
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface TrendRow {
  period?: string | null;
  score?: number;
  n?: number;
  avg?: number;
  strongBuy?: number;
  buy?: number;
  hold?: number;
  sell?: number;
  strongSell?: number;
}

interface RevisionRow {
  period?: string | null;
  net_pos_change?: number;
  net_neg_change?: number;
  delta_avg?: number;
}

interface EREVData {
  status?: string;
  symbol?: string;
  rows?: TrendRow[];
  trend?: TrendRow[];
  revisions?: RevisionRow[];
  velocity_avg?: number;
  current_score?: TrendRow | null;
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
  reason?: string;
  data_mode?: string;
  warnings?: unknown[];
  next_actions?: string[];
}

export function EREVPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<EREVData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const trend: TrendRow[] = useMemo(
    () =>
      (payload?.trend && payload.trend.length
        ? payload.trend
        : payload?.rows ?? []) as TrendRow[],
    [payload],
  );
  const revisions: RevisionRow[] = useMemo(
    () => (payload?.revisions ?? []) as RevisionRow[],
    [payload?.revisions],
  );
  const trendDescending = useMemo(() => [...trend].reverse(), [trend]);
  const stats = useMemo(
    () => deriveStats(trend, revisions, payload?.velocity_avg),
    [trend, revisions, payload?.velocity_avg],
  );
  const status = payload?.status ?? "—";
  // Honesty: live only when the function AND the shared envelope both say ok
  // AND the payload is not a labelled model/unavailable fallback. The backend
  // no longer fabricates analyst buckets, but the pane must also refuse to
  // claim live if a fallback envelope ever lands here (F6).
  const isLive =
    state === "ok" &&
    status === "ok" &&
    data?.status !== "provider_unavailable" &&
    payload?.data_mode !== "modeled";
  const warnings = useMemo<string[]>(
    () =>
      Array.isArray(payload?.warnings)
        ? payload.warnings.map((w) => String(w)).filter(Boolean)
        : [],
    [payload?.warnings],
  );
  const reasonText =
    typeof payload?.reason === "string" && payload.reason ? payload.reason : null;
  // The backend mirrors the primary provider error into both `reason` and
  // `warnings`; don't print the same sentence twice.
  const extraWarnings = useMemo(
    () => warnings.filter((w) => w !== reasonText),
    [warnings, reasonText],
  );

  const COLS: DataGridColumn<TrendRow>[] = useMemo(
    () => [
      {
        key: "period",
        header: "Period",
        width: 96,
        render: (r) => (
          <span style={monoPrimaryStyle}>{String(r.period ?? "—").slice(0, 16)}</span>
        ),
      },
      {
        key: "avg",
        header: "Avg",
        numeric: true,
        width: 80,
        render: (r) => (
          <span style={monoStrongStyle}>
            {typeof r.avg === "number" && Number.isFinite(r.avg)
              ? r.avg.toFixed(2)
              : "—"}
          </span>
        ),
      },
      {
        key: "delta",
        header: "Δ avg",
        numeric: true,
        width: 100,
        render: (r) => {
          const idx = trend.findIndex((x) => x === r);
          if (idx <= 0) return <span className="u-text-mute">—</span>;
          const prev = trend[idx - 1];
          if (typeof r.avg !== "number" || typeof prev?.avg !== "number") {
            return <span className="u-text-mute">—</span>;
          }
          const delta = r.avg - prev.avg;
          return <DeltaChip value={delta} format="raw" fractionDigits={2} />;
        },
      },
      {
        key: "n",
        header: "n",
        numeric: true,
        width: 60,
        render: (r) => <span style={monoMutedStyle}>{r.n ?? "—"}</span>,
      },
      {
        key: "strongBuy",
        header: "S.Buy",
        numeric: true,
        width: 64,
        render: (r) => <BucketCell tone="positive" v={r.strongBuy} />,
      },
      {
        key: "buy",
        header: "Buy",
        numeric: true,
        width: 56,
        render: (r) => <BucketCell tone="positive" v={r.buy} />,
      },
      {
        key: "hold",
        header: "Hold",
        numeric: true,
        width: 60,
        render: (r) => <BucketCell tone="muted" v={r.hold} />,
      },
      {
        key: "sell",
        header: "Sell",
        numeric: true,
        width: 56,
        render: (r) => <BucketCell tone="negative" v={r.sell} />,
      },
      {
        key: "strongSell",
        header: "S.Sell",
        numeric: true,
        width: 68,
        render: (r) => <BucketCell tone="negative" v={r.strongSell} />,
      },
    ],
    [trend],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="EREV needs an equity ticker." icon="⌖" />
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
  ) : trend.length === 0 ? (
    <Empty
      title={
        payload?.status === "provider_unavailable"
          ? "Provider unavailable"
          : "No revision history"
      }
      body={
        <div style={emptyBodyStyle}>
          <p style={emptyReasonStyle}>
            {reasonText ??
              "Provider returned no recommendation buckets for this symbol."}
          </p>
          {extraWarnings.length > 0 && (
            <ul style={nextActionsStyle}>
              {extraWarnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          {Array.isArray(payload?.next_actions) &&
            payload.next_actions.length > 0 && (
              <ul style={nextActionsStyle}>
                {payload.next_actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            )}
        </div>
      }
      icon={payload?.status === "provider_unavailable" ? "⌀" : "∅"}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="EREV KPI ribbon">
        <StatCard
          label="Current avg"
          value={
            stats.currentAvg != null
              ? `${stats.currentAvg >= 0 ? "+" : ""}${stats.currentAvg.toFixed(2)}`
              : "—"
          }
          caption={stats.currentPeriod ?? "—"}
          tone={
            stats.currentAvg == null
              ? "neutral"
              : stats.currentAvg >= 0
                ? "positive"
                : "negative"
          }
          trend={stats.avgTrend}
        />
        <StatCard
          label="Velocity"
          value={
            stats.velocity != null
              ? `${stats.velocity >= 0 ? "+" : ""}${stats.velocity.toFixed(3)}`
              : "—"
          }
          caption="Δ vs PRIOR PERIOD"
          tone={
            stats.velocity == null
              ? "neutral"
              : stats.velocity >= 0
                ? "positive"
                : "negative"
          }
        />
        <StatCard
          label="Analysts"
          value={String(stats.analystCount ?? "—")}
          caption="LATEST PERIOD"
          tone="neutral"
        />
        <StatCard
          label="Net upgrades"
          value={
            stats.netUpgrades != null
              ? `${stats.netUpgrades >= 0 ? "+" : ""}${stats.netUpgrades}`
              : "—"
          }
          caption={`${stats.netDowngrades ?? 0} DOWN`}
          tone={
            stats.netUpgrades == null
              ? "neutral"
              : stats.netUpgrades >= 0
                ? "positive"
                : "negative"
          }
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={trendDescending}
        rowKey={(r, i) => `${r.period ?? ""}-${i}`}
        density="compact"
        ariaLabel="EREV revision trend"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Earnings Revisions — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${trend.length} periods`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {trend.length} prd
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh revisions"
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
          <StatusSection label="rows" value={trend.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="velocity"
            value={
              stats.velocity != null
                ? `${stats.velocity >= 0 ? "+" : ""}${stats.velocity.toFixed(3)}`
                : "—"
            }
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface EREVStats {
  currentAvg: number | null;
  currentPeriod: string | null;
  velocity: number | null;
  analystCount: number | null;
  netUpgrades: number | null;
  netDowngrades: number | null;
  avgTrend: number[];
}

function deriveStats(
  trend: TrendRow[],
  revisions: RevisionRow[],
  velocityAvg?: number,
): EREVStats {
  const last = trend[trend.length - 1];
  const avgs = trend
    .map((r) => (typeof r.avg === "number" ? r.avg : null))
    .filter((v): v is number => v != null && Number.isFinite(v));
  const lastRev = revisions[revisions.length - 1];
  return {
    currentAvg: typeof last?.avg === "number" ? last.avg : null,
    currentPeriod: last?.period ?? null,
    velocity:
      typeof velocityAvg === "number" && Number.isFinite(velocityAvg)
        ? velocityAvg
        : null,
    analystCount: typeof last?.n === "number" ? last.n : null,
    netUpgrades:
      typeof lastRev?.net_pos_change === "number"
        ? lastRev.net_pos_change
        : null,
    netDowngrades:
      typeof lastRev?.net_neg_change === "number"
        ? lastRev.net_neg_change
        : null,
    avgTrend: avgs.slice(-22),
  };
}

function BucketCell({
  tone,
  v,
}: {
  tone: "positive" | "negative" | "muted";
  v: unknown;
}) {
  if (v == null || !Number.isFinite(Number(v))) {
    return <span className="u-text-mute">—</span>;
  }
  const n = Number(v);
  if (n === 0) return <span style={monoMutedStyle}>0</span>;
  return (
    <span
      style={{
        fontFamily: "JetBrains Mono, monospace",
        fontVariantNumeric: "tabular-nums",
        color:
          tone === "positive"
            ? "var(--positive)"
            : tone === "negative"
              ? "var(--negative)"
              : "var(--text-mute)",
        fontWeight: 600,
      }}
    >
      {n}
    </span>
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

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};

const emptyBodyStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  textAlign: "left",
  maxWidth: 520,
  margin: "0 auto",
};

const emptyReasonStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontSize: "var(--font-size-md)",
  lineHeight: 1.5,
};

const nextActionsStyle: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.6,
};
