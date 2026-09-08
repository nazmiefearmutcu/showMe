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

  const net = summary?.net_sentiment ?? null;
  const read = summary?.label ?? sentimentLabel(net);

  const COLS: DataGridColumn<SOSCRow>[] = useMemo(
    () => [
      {
        key: "platform",
        header: "Outlet / platform",
        width: 260,
        render: (r) => <span style={monoPrimaryStyle}>{r.platform ?? "—"}</span>,
      },
      {
        key: "mentions",
        header: "Mentions",
        numeric: true,
        width: 100,
        render: (r) => <span style={monoStrongStyle}>{fmtInt(r.mentions)}</span>,
      },
      {
        key: "sentiment",
        header: "Mean tone",
        numeric: true,
        width: 110,
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
  ) : isUnavailable ? (
    <Empty
      title="Sentiment provider unavailable"
      body={payload?.reason ?? "GDELT is unreachable — no sentiment is shown rather than a fabricated read."}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : rows.length === 0 ? (
    <Empty
      title="No recent coverage"
      body={`No GDELT articles matched ${effectiveSymbol} in the last ${summary?.window ?? `${days}d`} — nothing is fabricated while coverage is quiet.`}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
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
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.platform ?? "outlet"}-${i}`}
        density="compact"
        ariaLabel="SOSC per-outlet sentiment"
      />
    </div>
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
