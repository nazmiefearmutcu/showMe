/**
 * SOSC — Social / News Sentiment.
 *
 * Keyless GDELT DOC 2.0 volume+tone blended with the bundled FinBERT
 * headline read into a net sentiment in [-1, +1]. Header: window control
 * (persisted under `showme.sosc.days`) + status pill + refresh. Body:
 * sentiment score cards + per-outlet aggregate table (mentions, mean tone,
 * trend chip). GDELT outages render the backend's honest
 * `provider_unavailable` reason — no fabricated numbers, ever.
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
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { PaneState } from "@/design-system/PaneState";
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

interface SOSCRow {
  platform?: string;
  mentions?: number;
  sentiment?: number;
  trend?: string;
  source_mode?: string;
}

interface SOSCSummary {
  symbol?: string;
  net_sentiment?: number | null;
  label?: string;
  total_mentions?: number;
  gdelt_tone?: number;
  finbert_headline_sentiment?: number | null;
  window?: string;
  outlets?: number;
  source_mode?: string;
}

interface SOSCData {
  status?: string;
  reason?: string;
  rows?: SOSCRow[];
  summary?: SOSCSummary;
  next_actions?: string[];
  methodology?: string;
}

const DAYS_OPTIONS = [
  { value: 1, label: "1d" },
  { value: 3, label: "3d" },
  { value: 7, label: "7d" },
  { value: 14, label: "14d" },
] as const;
const DAYS_IDS = DAYS_OPTIONS.map((o) => o.value);

export function SOSCPane({ code, symbol }: FunctionPaneProps) {
  const [days, setDays] = usePersistentOption<number>(
    "showme.sosc.days",
    DAYS_IDS,
    3,
  );
  const [trendFilter, setTrendFilter] = useState("ALL");
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF", "CRYPTO"]);
  const { state, data, error, refetch } = useFunction<SOSCData>({
    code,
    symbol: effectiveSymbol,
    params: { days },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const summary = payload?.summary;
  const status = payload?.status ?? "—";
  const isUnavailable = status === "provider_unavailable";

  const trends = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      if (row.trend) set.add(row.trend.toLowerCase());
    }
    return ["ALL", ...Array.from(set).sort()];
  }, [rows]);

  const visible = useMemo(
    () =>
      trendFilter === "ALL"
        ? rows
        : rows.filter((r) => (r.trend ?? "").toLowerCase() === trendFilter),
    [rows, trendFilter],
  );

  const net = summary?.net_sentiment ?? null;
  const read = summary?.label ?? sentimentLabel(net);

  const COLS: DataGridColumn<SOSCRow>[] = useMemo(
    () => [
      {
        key: "platform",
        header: "Outlet / platform",
        width: 260,
        sortable: true,
        sortValue: (r) => r.platform ?? "",
        render: (r) => <span style={monoPrimaryStyle}>{r.platform ?? "—"}</span>,
      },
      {
        key: "mentions",
        header: "Mentions",
        numeric: true,
        width: 100,
        sortable: true,
        sortValue: (r) => r.mentions ?? null,
        render: (r) => <span style={monoStrongStyle}>{fmtInt(r.mentions)}</span>,
      },
      {
        key: "sentiment",
        header: "Mean tone",
        numeric: true,
        width: 110,
        sortable: true,
        sortValue: (r) => r.sentiment ?? null,
        render: (r) => (
          <span
            style={{
              ...monoStrongStyle,
              color: toneColor(r.sentiment),
            }}
          >
            {fmtSigned(r.sentiment)}
          </span>
        ),
      },
      {
        key: "trend",
        header: "Trend",
        width: 110,
        sortable: true,
        sortValue: (r) => r.trend ?? "",
        render: (r) =>
          r.trend ? (
            <Pill
              tone={
                r.trend === "bullish"
                  ? "positive"
                  : r.trend === "bearish"
                    ? "negative"
                    : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {r.trend}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="SOSC needs an equity or crypto ticker." icon="⌖" />
  ) : (
    <PaneState
      state={state}
      error={error}
      empty={isUnavailable || rows.length === 0}
      emptyTitle={isUnavailable ? "Sentiment provider unavailable" : "No recent coverage"}
      emptyBody={
        isUnavailable
          ? (payload?.reason ??
            "GDELT is unreachable — no sentiment is shown rather than a fabricated read.")
          : `No GDELT articles matched ${effectiveSymbol} in the last ${summary?.window ?? `${days}d`} — nothing is fabricated while coverage is quiet.`
      }
      emptyIcon={isUnavailable ? "!" : "∅"}
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        <section style={kpiGridStyle} aria-label="SOSC sentiment summary">
          <StatCard
            label="Net sentiment"
            value={fmtSigned(net)}
            caption={`${(summary?.window ?? `${days}d`).toUpperCase()} WINDOW · ${read.toUpperCase()}`}
            tone={sentimentTone(net)}
          />
          <StatCard
            label="Read"
            value={read}
            caption={`SOURCE ${summary?.source_mode ?? "—"}`}
            tone={sentimentTone(net)}
          />
          <StatCard
            label="Articles"
            value={fmtInt(summary?.total_mentions)}
            caption={`${fmtInt(summary?.outlets)} OUTLETS`}
            tone="neutral"
          />
          <StatCard
            label="GDELT tone"
            value={fmtSigned(summary?.gdelt_tone)}
            caption={`FINBERT ${fmtSigned(summary?.finbert_headline_sentiment)}`}
            tone={sentimentTone(summary?.gdelt_tone)}
          />
        </section>
        <div style={chipRowStyle} role="group" aria-label="Trend filter">
          {trends.map((t) => {
            const active = trendFilter === t;
            return (
              <button
                key={t}
                type="button"
                className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
                aria-pressed={active}
                onClick={() => setTrendFilter(t)}
                title={`Filter trend ${t}`}
              >
                {t}
              </button>
            );
          })}
        </div>
        <DataGrid
          columns={COLS}
          rows={visible}
          rowKey={(r, i) => `${r.platform ?? "outlet"}-${i}`}
          density="compact"
          ariaLabel="SOSC per-outlet sentiment"
          defaultSortKey="mentions"
          defaultSortDir="descending"
          empty="No outlets match this trend filter"
        />
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Social Sentiment — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${rows.length} outlets · ${summary?.window ?? `${days}d`} window`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {fmtInt(summary?.total_mentions)} articles
              </Pill>
              <SegmentedControl
                label="WINDOW"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
                title="GDELT lookback window"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Re-scan social sentiment"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="outlets" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="window" value={summary?.window ?? `${days}d`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function sentimentLabel(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v > 0.05 ? "bullish" : v < -0.05 ? "bearish" : "neutral";
}

function sentimentTone(v: number | null | undefined): "positive" | "negative" | "neutral" {
  if (v == null || !Number.isFinite(v)) return "neutral";
  return v > 0.05 ? "positive" : v < -0.05 ? "negative" : "neutral";
}

function toneColor(v: number | null | undefined): string {
  const tone = sentimentTone(v);
  if (tone === "positive") return "var(--positive)";
  if (tone === "negative") return "var(--negative)";
  return "var(--text-primary)";
}

function fmtSigned(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
}

function fmtInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString("en-US");
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const chipRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
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
