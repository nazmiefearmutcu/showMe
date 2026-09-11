/**
 * HVT — Historical Volatility Trends (realized-vol term structure).
 *
 * Live close-to-close realized volatility from yfinance daily OHLCV:
 * 4 window rows (30/60/90/lookback days) plus a rolling history curve.
 * Header: lookback segmented control (persisted `showme.hvt.days`) +
 * status pill + refresh. Body: KPI ribbon (spot, current 30D RV, history
 * average, observations), the rolling RV curve as an inline-SVG sparkline
 * (design-system `Sparkline`, no chart lib) and the window table.
 *
 * Data honesty: `provider_unavailable` payloads (seeded reference rows)
 * render an explicit empty state — seeded vol values are never shown as
 * if they were measured from real closes. The explicit `reference=true`
 * opt-in template is labeled as such when it comes back.
 */
import { useMemo, type CSSProperties } from "react";
import {
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
import { formatNumberFixed } from "@/lib/format";
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

/* ── payload types ─────────────────────────────────────────────────── */

interface HvtRow {
  metric?: string;
  window_days?: number;
  realized_vol?: number;
  realized_vol_pct?: number;
  samples?: number;
  formula?: string;
}

interface HvtHistoryPoint {
  date?: string;
  vol?: number;
  vol_pct?: number;
  window_days?: number;
}

interface HvtSummary {
  current_realized_vol?: number;
  current_realized_vol_pct?: number;
  observations?: number;
  history_window_days?: number;
}

interface HvtData {
  status?: string;
  reason?: string;
  symbol?: string;
  spot?: number;
  lookback_days?: number;
  rows?: HvtRow[];
  history?: HvtHistoryPoint[];
  summary?: HvtSummary;
  methodology?: string;
}

const DAYS_OPTIONS = [
  { value: 90, label: "90d" },
  { value: 180, label: "180d" },
  { value: 365, label: "1y" },
  { value: 730, label: "2y" },
] as const;
const DAYS_IDS = DAYS_OPTIONS.map((o) => o.value);

/* ── pane ──────────────────────────────────────────────────────────── */

export function HVTPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const [days, setDays] = usePersistentOption<number>(
    "showme.hvt.days",
    DAYS_IDS,
    365,
  );
  const { state, data, error, refetch } = useFunction<HvtData>({
    code,
    symbol: effectiveSymbol,
    params: { days },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: HvtRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const history: HvtHistoryPoint[] = useMemo(() => payload?.history ?? [], [payload]);
  const volSeries = useMemo(
    () =>
      history
        .map((h) => (typeof h.vol_pct === "number" && Number.isFinite(h.vol_pct) ? h.vol_pct : null))
        .filter((v): v is number => v != null),
    [history],
  );
  const currentVol = num(payload?.summary?.current_realized_vol_pct);
  const avgVol = volSeries.length
    ? volSeries.reduce((a, v) => a + v, 0) / volSeries.length
    : null;
  const status = payload?.status ?? "—";
  const isLive = state === "ok" && status === "ok";
  const isReference = status === "reference";

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="HVT needs an equity / ETF with daily history." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8" aria-busy="true">
      <Skeleton height={56} />
      <Skeleton height={96} />
      <Skeleton height={20} width="70%" />
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
  ) : !isLive && !isReference ? (
    // provider_unavailable / empty: the fallback rows are SEEDED values,
    // never real measurements — refuse to render them as data.
    <Empty
      title="Realized-vol history unavailable"
      body={
        payload?.reason ??
        "No daily close history returned for this symbol — realized volatility cannot be measured."
      }
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : rows.length === 0 ? (
    <Empty
      title="No realized-vol windows returned"
      body="The provider returned no usable return window."
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="HVT KPI ribbon">
        <StatCard
          label="Spot"
          value={fmtNum(payload?.spot)}
          caption={`LOOKBACK ${payload?.lookback_days ?? days}D`}
          tone="neutral"
        />
        <StatCard
          label="Current 30D RV"
          value={fmtPct(currentVol)}
          caption={`${payload?.summary?.observations ?? "—"} OBS · WIN ${payload?.summary?.history_window_days ?? "—"}D`}
          tone="neutral"
          trend={trendOf(volSeries)}
        />
        <StatCard
          label="History average RV"
          value={fmtPct(avgVol)}
          caption={`${volSeries.length} ROLLING PTS`}
          tone={currentVol != null && avgVol != null ? (currentVol > avgVol ? "negative" : "positive") : "neutral"}
        />
        <StatCard
          label={longestWindow(rows)?.metric ?? "Long window"}
          value={fmtPct(longestWindow(rows)?.realized_vol_pct)}
          caption={`${longestWindow(rows)?.samples ?? "—"} SAMPLES`}
          tone="neutral"
        />
      </section>

      <section style={sparkCardStyle} aria-label="Rolling realized volatility curve">
        <div style={sparkHeadStyle}>
          <span className="u-text-mute" style={noteTextStyle}>
            ROLLING RV % · {volSeries.length} PTS · {payload?.summary?.history_window_days ?? "—"}D WINDOW
          </span>
          <span style={monoStrongStyle}>{fmtPct(volSeries[volSeries.length - 1])}</span>
        </div>
        <Sparkline
          values={volSeries}
          width={560}
          height={88}
          tone="accent"
          ariaLabel={`Rolling realized volatility, ${volSeries.length} points, current ${fmtPct(volSeries[volSeries.length - 1])}, average ${fmtPct(avgVol)}`}
        />
        <div style={sparkFootStyle}>
          <span className="u-text-mute" style={noteTextStyle}>
            {history[0]?.date ?? "—"}
          </span>
          <span className="u-text-mute" style={noteTextStyle}>
            {history[history.length - 1]?.date ?? "—"}
          </span>
        </div>
      </section>

      <section style={tableWrapStyle} aria-label="Realized volatility windows">
        <table style={tableStyle} aria-label="Volatility term structure">
          <thead>
            <tr>
              {["Window", "Realized vol", "Samples", "Formula"].map((h, i) => (
                <th key={h} style={{ ...thStyle, textAlign: i === 1 || i === 2 ? "right" : "left" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.window_days ?? r.metric} aria-label={`${r.metric}: ${fmtPct(r.realized_vol_pct)}`}>
                <td style={{ ...tdStyle, ...monoStrongStyle }}>
                  {r.metric ?? `${r.window_days}D`}
                </td>
                <td style={tdNumStyle}>{fmtPct(r.realized_vol_pct)}</td>
                <td style={tdNumStyle}>{r.samples ?? "—"}</td>
                <td style={{ ...tdStyle, color: "var(--text-mute)", fontSize: "var(--font-size-2xs)" }}>
                  {r.formula ?? "stdev(daily close returns) * sqrt(252)"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {isReference ? (
          <div style={refNoteStyle} role="status">
            Reference template (deterministic per-symbol seed) — NOT measured
            from live closes.
          </div>
        ) : (
          <div className="u-text-mute" style={noteTextStyle}>
            {payload?.methodology ?? "stdev(daily close-to-close returns) * sqrt(252)"}
          </div>
        )}
      </section>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Historical Volatility — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · 30D RV ${fmtPct(currentVol)} · avg ${fmtPct(avgVol)}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <SegmentedControl
                label="LOOKBACK"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
                title="Lookback window"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh realized volatility"
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
          <StatusSection label="points" value={volSeries.length} tone="accent" />
          <StatusDivider />
          <StatusSection label="lookback" value={`${days}d`} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function longestWindow(rows: HvtRow[]): HvtRow | null {
  let best: HvtRow | null = null;
  for (const r of rows) {
    if (r.window_days != null && (best == null || (r.window_days ?? 0) > (best.window_days ?? 0))) {
      best = r;
    }
  }
  return best;
}

function trendOf(values: number[]): number[] {
  return values.slice(-22);
}

function fmtNum(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  return formatNumberFixed(n, 2);
}

function fmtPct(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  return `${n.toFixed(1)}%`;
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const sparkCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  padding: "10px 12px",
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--bg-raised, transparent)",
};

const sparkHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 12,
};

const sparkFootStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
};

const tableWrapStyle: CSSProperties = { minWidth: 0 };

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  tableLayout: "fixed",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-sm)",
};

const thStyle: CSSProperties = {
  padding: "4px 8px",
  color: "var(--text-mute)",
  fontWeight: 500,
  letterSpacing: "0.06em",
  fontSize: "var(--font-size-xs)",
  textTransform: "uppercase",
  borderBottom: "1px solid var(--border-subtle)",
};

const tdStyle: CSSProperties = {
  padding: "3px 8px",
  color: "var(--text-primary)",
  borderBottom: "1px solid var(--border-subtle)",
};

const tdNumStyle: CSSProperties = {
  ...tdStyle,
  textAlign: "right",
};

const noteTextStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.05em",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const refNoteStyle: CSSProperties = {
  marginTop: 6,
  padding: "5px 8px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-subtle)",
  background: "var(--scrim-low)",
  color: "var(--text-primary)",
  fontSize: "var(--font-size-2xs)",
  fontFamily: "JetBrains Mono, monospace",
};
