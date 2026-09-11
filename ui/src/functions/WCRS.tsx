/**
 * WCRS — World currency cross rates.
 *
 * Bloomberg `WCRS<GO>` analogue: matrix of cross rates between G10 +
 * key emerging market currencies. KPI ribbon for top movers, heatmap
 * via the same DS heat tokens, hover-lift rows, methodology rail.
 */
import { useEffect, useMemo, type CSSProperties } from "react";
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
  ResizableChartFrame,
  Skeleton,
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useUtcStamp } from "@/lib/useUtcStamp";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { formatSignedDelta } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface CrossRate {
  base?: string;
  quote?: string;
  pair?: string;
  rate?: number;
  bid?: number;
  ask?: number;
  change?: number;
  change_pct?: number;
  spread_pips?: number;
  ts?: string;
  history?: number[];
}

interface WCRSPayload {
  rows?: CrossRate[];
  surface?: CrossRate[];
  matrix?: Record<string, Record<string, number>>;
  source_mode?: string;
  methodology?: string;
  field_dictionary?: Record<string, string>;
}

const BASES = [
  { id: "USD", label: "USD" },
  { id: "EUR", label: "EUR" },
  { id: "GBP", label: "GBP" },
  { id: "JPY", label: "JPY" },
  { id: "TRY", label: "TRY" },
] as const;
type BaseId = (typeof BASES)[number]["id"];
const BASE_IDS = BASES.map((b) => b.id);

const REFRESH_MS = 30_000;

export function WCRSPane({ code }: FunctionPaneProps) {
  const [base, setBase] = usePersistentOption<BaseId>(
    "showme.wcrs-base",
    BASE_IDS,
    "USD",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: {
      bases: base,
      quotes: "USD,EUR,GBP,JPY,TRY,CHF",
      live: true,
    },
  });
  // Poll on the visibility tick without touching the fetch params (R2-F2) —
  // a changing param key would turn every poll into a fresh skeleton load.
  useEffect(() => {
    if (tick === 0) return;
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  const payload = useMemo(
    () =>
      (data?.data && typeof data.data === "object"
        ? data.data
        : {}) as WCRSPayload,
    [data?.data],
  );
  const rows = useMemo(() => {
    const list = normalizeRows(payload);
    return list.filter((r) => {
      const b = r.base?.toUpperCase();
      const q = r.quote?.toUpperCase();
      return b === base || q === base;
    });
  }, [payload, base]);
  const heatmapRows = useMemo(
    () => normalizeRows(payload.surface ?? payload),
    [payload],
  );
  const fieldRows = useMemo(
    () => Object.entries(payload.field_dictionary ?? {}),
    [payload.field_dictionary],
  );
  const stats = useMemo(() => deriveStats(rows, base), [rows, base]);
  const utcStamp = useUtcStamp(tick);
  // Honesty: the green pill may only claim "live" when the backend actually
  // served a live tier — `reference_cross_rate_matrix` is a labelled fallback
  // and must never wear a live badge (envelope warnings carry the detail).
  const warnings = data?.warnings ?? [];
  const sourceMode = payload.source_mode ?? "";
  const isLive = state === "ok" && sourceMode.startsWith("live_");
  const liveLabel = isLive
    ? "live"
    : state === "ok" && sourceMode.startsWith("reference")
      ? "reference"
      : state;

  const cols = useMemo<DataGridColumn<CrossRate>[]>(
    () => [
      {
        key: "pair",
        header: "Pair",
        width: 110,
        render: (r) => {
          const pair = fmtPair(r);
          const navigable = Boolean(r.pair || (r.base && r.quote));
          return (
            <button
              type="button"
              style={navigable ? pairBtnStyle : pairBtnStaticStyle}
              title={navigable ? `Open ${pair} in FXIP` : undefined}
              aria-label={navigable ? `Open ${pair} in FX Info Portal` : undefined}
              disabled={!navigable}
              onClick={() => {
                if (!navigable) return;
                setFocusedTarget("FXIP", pair);
                navigate(`/symbol/${pair}/FXIP`);
              }}
            >
              {pair}
            </button>
          );
        },
      },
      {
        key: "rate",
        header: "Rate",
        numeric: true,
        width: 112,
        render: (r) => (
          <span style={primaryNumStyle}>{fmtRate(r.rate ?? r.bid)}</span>
        ),
      },
      {
        key: "bid",
        header: "Bid",
        numeric: true,
        width: 100,
        render: (r) => <span style={mutedNumStyle}>{fmtRate(r.bid)}</span>,
      },
      {
        key: "ask",
        header: "Ask",
        numeric: true,
        width: 100,
        render: (r) => <span style={mutedNumStyle}>{fmtRate(r.ask)}</span>,
      },
      {
        key: "spread",
        header: "Spread (pips)",
        numeric: true,
        width: 110,
        render: (r) => <span style={mutedNumStyle}>{fmtPips(r)}</span>,
      },
      {
        key: "trend",
        header: "5d",
        width: 78,
        render: (r) => {
          // P2 honesty: real per-row history renders solid + marked
          // data-synthetic="false"; the procedural fallback is de-emphasized
          // and marked synthetic (WEI pattern).
          const real = realHistoryFor(r);
          const series = real ?? syntheticTrendFor(r);
          const chg = realChangePct(r);
          const dir = (chg ?? 0) >= 0 ? "positive" : "negative";
          return (
            <span
              style={real ? sparkRealStyle : synthSparkStyle}
              data-synthetic={real ? "false" : "true"}
              title={
                real ? "Daily close history from the payload" : SYNTH_SPARK_TITLE
              }
            >
              <Sparkline
                values={series}
                width={62}
                height={18}
                tone={dir}
                ariaLabel={
                  real
                    ? "Daily close history"
                    : "Illustrative trend — no real history available"
                }
              />
            </span>
          );
        },
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 96,
        render: (r) => {
          // P2 honesty: a missing change_pct renders the em-dash; the backend
          // used to ship a hardcoded 0.0 placeholder with no underlying
          // series, which is not a real "+0.00%" claim and must not be
          // presented as one.
          const v = realChangePct(r);
          if (v == null) {
            return (
              <span className="u-text-mute" title="No change data in this payload">
                —
              </span>
            );
          }
          return <DeltaChip value={v} format="percent" fractionDigits={2} />;
        },
      },
    ],
    [setFocusedTarget],
  );

  // Envelope warnings name the fallback reason; render them so a degraded
  // matrix cannot be mistaken for a live one.
  const warningBanner =
    warnings.length > 0 ? (
      <div role="status" style={warningStyle} aria-label="Data quality warning">
        {warnings.join(" · ")}
      </div>
    ) : null;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="World currency cross rates"
          subtitle={`${rows.length} pairs · base ${base} · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} fx
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {liveLabel}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={BASES.map((b) => ({ id: b.id, label: b.label }))}
            active={base}
            onChange={(id) => setBase(id as BaseId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty
              title="Function error"
              body={error?.message ?? "—"}
              icon="!"
            />
          ) : rows.length === 0 ? (
            <div className="u-grid-gap-14">
              {warningBanner}
              <Empty
                title="No crosses"
                body={`No WCRS rows for base ${base}. Source mode: ${payload.source_mode ?? "unknown"}.`}
              />
            </div>
          ) : (
            <div className="u-grid-gap-14">
              {warningBanner}
              <KPIRibbon stats={stats} stamp={utcStamp} base={base} />
              <CrossHeatmap rows={heatmapRows} activeBase={base} />
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => fmtPair(r) + i}
                density="compact"
                ariaLabel="WCRS cross rates"
              />
              <div style={twoColLayout}>
                <section style={methodPanel}>
                  <div style={metaLabel}>Methodology</div>
                  <p style={methodText}>
                    {payload.methodology ?? "No methodology returned."}
                  </p>
                  <div style={metaSubLabel}>
                    Source mode ·{" "}
                    <span className="u-text-accent">
                      {payload.source_mode ?? "unknown"}
                    </span>
                  </div>
                </section>
                {fieldRows.length ? (
                  <section style={methodPanel}>
                    <div style={metaLabel}>Field dictionary</div>
                    <div style={fieldGrid}>
                      {fieldRows.map(([key, value]) => (
                        <div key={key} style={fieldRow}>
                          <span className="wcrs-field-key">{key}</span>
                          <span className="u-text-secondary">
                            {value}
                          </span>
                        </div>
                      ))}
                    </div>
                  </section>
                ) : null}
              </div>
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="provider"
            value={
              payload.source_mode ??
              data?.sources?.join(", ") ??
              "showMe engine"
            }
          />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="base" value={base} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface FxStats {
  pairs: number;
  /** Null when the payload carries no real change data (honest em-dash). */
  meanChange: number | null;
  leader?: { pair: string; chg: number };
  laggard?: { pair: string; chg: number };
  trend: number[];
}

function deriveStats(rows: CrossRate[], _base: string): FxStats {
  if (!rows.length) {
    return { pairs: 0, meanChange: null, trend: [] };
  }
  let acc = 0;
  let counted = 0;
  let leader: FxStats["leader"];
  let laggard: FxStats["laggard"];
  const trend: number[] = [];
  for (const r of rows) {
    const v = realChangePct(r);
    if (v == null) continue;
    acc += v;
    counted += 1;
    trend.push(v);
    const pair = fmtPair(r);
    if (!leader || v > leader.chg) leader = { pair, chg: v };
    if (!laggard || v < laggard.chg) laggard = { pair, chg: v };
  }
  return {
    pairs: rows.length,
    meanChange: counted ? acc / counted : null,
    leader,
    laggard,
    trend: trend.slice(-22),
  };
}

function KPIRibbon({
  stats,
  stamp,
  base,
}: {
  stats: FxStats;
  stamp: string;
  base: string;
}) {
  return (
    <section style={kpiGridStyle} aria-label="WCRS KPI ribbon">
      <StatCard
        label={`${base} basket Δ`}
        value={
          stats.meanChange == null
            ? "—"
            : `${stats.meanChange >= 0 ? "+" : ""}${stats.meanChange.toFixed(3)}%`
        }
        caption={
          stats.meanChange == null
            ? `NO CHANGE DATA · ${stats.pairs} pairs`
            : `AS OF ${stamp} UTC · ${stats.pairs} pairs`
        }
        tone={
          stats.meanChange == null
            ? "neutral"
            : stats.meanChange >= 0
              ? "positive"
              : "negative"
        }
        trend={stats.trend}
      />
      <StatCard
        label="Pairs"
        value={String(stats.pairs)}
        caption={`BASE ${base}`}
        tone="neutral"
        trend={stats.trend}
      />
      <StatCard
        label="Leader"
        value={stats.leader?.pair ?? "—"}
        caption={
          stats.leader
            ? `${formatSignedDelta(stats.leader.chg, 3)}%`
            : "—"
        }
        tone="positive"
        trend={stats.trend}
      />
      <StatCard
        label="Laggard"
        value={stats.laggard?.pair ?? "—"}
        caption={
          stats.laggard
            ? `${formatSignedDelta(stats.laggard.chg, 3)}%`
            : "—"
        }
        tone="negative"
        trend={stats.trend}
      />
    </section>
  );
}

function CrossHeatmap({
  rows,
  activeBase,
}: {
  rows: CrossRate[];
  activeBase: string;
}) {
  const filtered = rows.filter((row) => row.base?.toUpperCase() === activeBase);
  if (!filtered.length) return null;
  // P2 honesty: intensity is scaled from REAL change data only; cells without
  // a usable change stay neutral instead of leaning green off a 0 placeholder.
  const max = Math.max(
    ...filtered.map((row) => Math.abs(realChangePct(row) ?? 0)),
    1,
  );
  return (
    <ResizableChartFrame
      storageId={`WCRS.heatmap.${activeBase}`}
      defaultHeight={{ vh: 0.3, max: 340, min: 200 }}
      minHeight={200}
      minWidth={420}
      maxHeight={900}
      style={heatmapPanel}
      ariaLabel="Resize cross-rate heatmap"
    >
      <div style={heatmapHeader}>
        <span style={metaLabel}>Cross-rate heatmap</span>
        <span className="wcrs-corner-meta">
          BASE · {activeBase}
        </span>
      </div>
      <div style={heatmapGrid}>
        {filtered.map((row) => {
          const chg = realChangePct(row);
          const hasChange = chg != null;
          const intensity = hasChange
            ? Math.min(0.6, Math.max(0.12, Math.abs(chg) / max))
            : 0;
          const tone = (chg ?? 0) >= 0 ? "var(--positive)" : "var(--negative)";
          const bg =
            row.base === row.quote || !hasChange
              ? "var(--surface-2)"
              : `color-mix(in srgb, ${tone} ${(intensity * 100).toFixed(0)}%, transparent)`;
          return (
            <div
              key={`${row.base}-${row.quote}`}
              style={{ ...heatCell, background: bg }}
            >
              <span style={heatCellQuote}>{row.quote}</span>
              <strong style={heatCellRate}>
                {fmtRate(row.rate ?? row.bid)}
              </strong>
              {hasChange ? (
                <span
                  style={{
                    fontSize: "var(--font-size-2xs)",
                    color: (chg as number) >= 0 ? "var(--positive)" : "var(--negative)",
                    fontFamily: "JetBrains Mono, monospace",
                  }}
                >
                  {(chg as number) >= 0 ? "+" : ""}
                  {(chg as number).toFixed(2)}%
                </span>
              ) : null}
            </div>
          );
        })}
      </div>
    </ResizableChartFrame>
  );
}

const SYNTH_SPARK_TITLE = "Illustrative trend — no real history available";

/**
 * P2 honesty: the real per-row series, when the payload ships one. Returns
 * null when the row carries no usable history so the caller can fall back to
 * the explicitly-marked synthetic line instead.
 */
function realHistoryFor(r: CrossRate): number[] | null {
  if (Array.isArray(r.history) && r.history.length >= 4) {
    return r.history.slice(-12);
  }
  return null;
}

/** Procedural stand-in — only ever rendered de-emphasized + data-synthetic. */
function syntheticTrendFor(r: CrossRate): number[] {
  const seed = `${r.base ?? ""}${r.quote ?? ""}`;
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 1009;
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < 12; i++) {
    const x = Math.sin((i + h) * 0.55) * 5 + Math.cos((i * 0.31 + h) * 0.95) * 3.5;
    v = Math.max(20, Math.min(80, v + x * 0.5));
    out.push(v);
  }
  return out;
}

/**
 * P2 honesty: a finite change_pct is real data. The backend used to ship a
 * hardcoded 0.0 placeholder when no real daily change existed — a zero with
 * no supporting history series is not a meaningful "+0.00%" claim and is
 * treated as missing (honest em-dash) instead.
 */
function realChangePct(r: CrossRate): number | null {
  const v = r.change_pct;
  if (v == null || !Number.isFinite(v)) return null;
  if (v === 0 && realHistoryFor(r) == null) return null;
  return v;
}

function normalizeRows(payload: unknown): CrossRate[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as CrossRate[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.pairs ?? o.rates ?? o.rows ?? o.items ?? null;
    if (Array.isArray(items)) return items as CrossRate[];
    const matrix = o.matrix ?? (looksLikeMatrix(o) ? o : null);
    if (matrix && typeof matrix === "object") {
      const out: CrossRate[] = [];
      for (const [base, qs] of Object.entries(
        matrix as Record<string, unknown>,
      )) {
        if (qs && typeof qs === "object") {
          for (const [quote, rate] of Object.entries(
            qs as Record<string, unknown>,
          )) {
            if (typeof rate === "number") out.push({ base, quote, rate });
          }
        }
      }
      return out;
    }
  }
  return [];
}

function looksLikeMatrix(value: Record<string, unknown>): boolean {
  return Object.entries(value).some(
    ([key, row]) =>
      /^[A-Z]{3}$/.test(key) &&
      row != null &&
      typeof row === "object" &&
      Object.values(row as Record<string, unknown>).some(
        (item) => typeof item === "number",
      ),
  );
}

function fmtPair(r: CrossRate): string {
  if (r.pair) return r.pair;
  if (r.base && r.quote) return `${r.base}${r.quote}`;
  return "—";
}

function fmtRate(v: number | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const dp = Math.abs(v) > 20 ? 2 : 4;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}

function fmtPips(r: CrossRate): string {
  // Backend ships JPY-aware spread_pips (JPY quote = pip factor 100, else
  // 10000). Render that field when present; the local fallback mirrors the
  // same pip factor so USDJPY is never shown 100x wide.
  if (typeof r.spread_pips === "number" && Number.isFinite(r.spread_pips)) {
    return r.spread_pips.toFixed(1);
  }
  if (r.bid == null || r.ask == null) return "—";
  const spread = r.ask - r.bid;
  const pipFactor = (r.quote ?? "").toUpperCase() === "JPY" ? 100 : 10000;
  return Math.abs(spread * pipFactor).toFixed(1);
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

// P2 honesty — a real history series renders solid; the procedural fallback
// is de-emphasized so it cannot masquerade as real history.
const sparkRealStyle: CSSProperties = {
  display: "inline-flex",
};

const synthSparkStyle: CSSProperties = {
  display: "inline-flex",
  opacity: 0.4,
  filter: "saturate(0.6)",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const twoColLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1.1fr) minmax(280px, 0.9fr)",
  gap: 12,
  alignItems: "start",
};

const pairBtnStyle: CSSProperties = {
  background: "transparent",
  border: "none",
  color: "var(--accent)",
  cursor: "pointer",
  font: "inherit",
  padding: 0,
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  letterSpacing: "0.02em",
  transition: "transform var(--motion-base)",
};

const pairBtnStaticStyle: CSSProperties = {
  ...pairBtnStyle,
  cursor: "default",
};

const warningStyle: CSSProperties = {
  border: "1px solid var(--warning, var(--text-mute))",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  padding: "6px 8px",
  fontFamily: "JetBrains Mono, monospace",
};

const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  fontWeight: 600,
};

const mutedNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: 6,
};

const metaSubLabel: CSSProperties = {
  marginTop: 8,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
};

const heatmapPanel: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
};

const heatmapHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  padding: "12px 12px 6px 12px",
  flexShrink: 0,
};

const heatmapGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(96px, 1fr))",
  gap: 8,
  padding: "0 12px 12px 12px",
  flex: "1 1 0",
  minHeight: 0,
  alignContent: "start",
  overflow: "auto",
};

const heatCell: CSSProperties = {
  minHeight: 64,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: 8,
  display: "grid",
  gap: 2,
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  transition: "transform var(--motion-base), border-color var(--motion-base)",
};

const heatCellQuote: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
};

const heatCellRate: CSSProperties = {
  fontSize: "var(--font-size-lg)",
  color: "var(--text-display)",
  fontWeight: 600,
};

const methodPanel: CSSProperties = {
  display: "grid",
  gap: 4,
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
};

const methodText: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: "var(--font-size-md)",
};

const fieldGrid: CSSProperties = {
  display: "grid",
  gap: 6,
};

const fieldRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(120px, 0.35fr) 1fr",
  gap: 10,
  fontSize: "var(--font-size-md)",
  color: "var(--text-secondary)",
  paddingBottom: 4,
  borderBottom: "1px solid var(--border-row)",
};
