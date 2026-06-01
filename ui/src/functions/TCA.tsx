/**
 * TCA — Trade Cost Analysis (post-trade).
 *
 * Bloomberg `TCA<GO>` analogue. Renders the post-trade execution-quality
 * payload from `backend/showme/engine/functions/trade/tca.py`: per-fill
 * slippage vs a live intraday VWAP benchmark, drawn as a centred-zero
 * WATERFALL (adverse fills extend right in --negative, price-improving fills
 * extend left in --positive, scaled to the worst |slippage|). A KPI ribbon
 * summarises avg slippage (bp), total cost ($), notional and worst-fill /
 * implementation-shortfall; a cumulative-cost sparkline tracks how the
 * execution bill accrued across the order; a Fills tab exposes the full
 * child-fill ledger.
 *
 * Real payload (data.data), consumed defensively:
 *   status         "ok" | "empty" | "provider_unavailable"
 *   metadata.data_mode (top-level data.metadata) "live" | "degraded" | "provider_unavailable" | "no_fills"
 *   benchmark      "VWAP" | "TWAP" | "ARRIVAL" | "IMPLEMENTATION_SHORTFALL"
 *   rows[]         order_id, symbol, broker, side, quantity, avg_fill_px,
 *                  benchmark_px, arrival_px, slippage_bps, is_bps,
 *                  opportunity_bps, notional_usd, cost_usd, filled_at,
 *                  benchmark_source
 *   summary        benchmark, fill_count, avg_slippage_bps, avg_is_bps,
 *                  worst_slippage_bps, total_cost_usd
 *   series[]       { label, value }  (value = per-fill slippage_bps)
 *   methodology, field_dictionary, next_actions
 *   (top-level)    warnings[], sources[], elapsed_ms, metadata.data_mode
 *
 * The honest source pill maps data_mode → live/degraded/reference so a
 * VWAP-outage degrade or an empty ledger never masquerades as a clean live
 * audit. Alternate key spellings are accepted so the pane survives engine
 * field drift.
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
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

/* ------------------------------------------------------------------ */
/* tolerant payload accessors                                          */
/* ------------------------------------------------------------------ */
type AnyRec = Record<string, unknown>;

function isRec(v: unknown): v is AnyRec {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function pick(rec: AnyRec, ...keys: string[]): unknown {
  for (const k of keys) {
    const v = rec[k];
    if (v !== undefined && v !== null) return v;
  }
  return undefined;
}
function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v.replace(/[, ]/g, ""));
    if (Number.isFinite(n)) return n;
  }
  return null;
}
function str(v: unknown): string {
  if (v === undefined || v === null) return "";
  return typeof v === "string" ? v : String(v);
}

/* ------------------------------------------------------------------ */
/* formatting                                                          */
/* ------------------------------------------------------------------ */
function fmtBps(v: number | null, sign = true): string {
  if (v === null) return "—";
  const s = sign && v > 0 ? "+" : "";
  return `${s}${v.toFixed(1)} bp`;
}
function fmtMoney(v: number | null): string {
  if (v === null) return "—";
  const a = Math.abs(v);
  const sgn = v < 0 ? "-" : "";
  if (a >= 1e6) return `${sgn}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sgn}$${(a / 1e3).toFixed(2)}K`;
  return `${sgn}$${a.toFixed(2)}`;
}
function fmtPrice(v: number | null): string {
  if (v === null) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}
function fmtQty(v: number | null): string {
  if (v === null) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
function fmtTime(v: unknown): string {
  const s = str(v);
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/* ------------------------------------------------------------------ */
/* normalized per-fill row                                            */
/* ------------------------------------------------------------------ */
interface FillRow {
  id: string;
  ts: unknown;
  symbol: string;
  broker: string;
  side: string;
  qty: number | null;
  price: number | null;
  benchmark: number | null;
  benchmarkSource: string;
  slipBps: number | null;
  isBps: number | null;
  costUsd: number | null;
  notional: number | null;
}

function normalizeFill(rec: AnyRec, i: number): FillRow {
  const price = num(
    pick(rec, "avg_fill_px", "price", "fill_price", "exec_price", "executed_price"),
  );
  const benchmark = num(
    pick(rec, "benchmark_px", "vwap", "benchmark", "vwap_price", "arrival_px", "arrival"),
  );
  const qty = num(pick(rec, "quantity", "qty", "shares", "size", "filled_qty"));
  const sideRaw = str(pick(rec, "side", "direction")).toUpperCase();
  const isSell = sideRaw.startsWith("S");

  let slipBps = num(pick(rec, "slippage_bps", "slippage_bp", "slippage", "slip_bps", "bps"));
  if (slipBps === null && price !== null && benchmark !== null && benchmark !== 0) {
    // adverse = paid above benchmark on a buy, sold below benchmark on a sell
    const dir = isSell ? -1 : 1;
    slipBps = ((price - benchmark) / benchmark) * 10_000 * dir;
  }

  const notional =
    num(pick(rec, "notional_usd", "notional", "value")) ??
    (price !== null && qty !== null ? price * qty : null);

  let costUsd = num(pick(rec, "cost_usd", "cost", "slippage_cost", "impact_cost"));
  if (costUsd === null && slipBps !== null && notional !== null) {
    costUsd = (slipBps / 10_000) * notional;
  }

  return {
    id: str(pick(rec, "order_id", "id", "trade_id")) || `fill-${i + 1}`,
    ts: pick(rec, "filled_at", "timestamp", "ts", "time"),
    symbol: str(pick(rec, "symbol")) || "—",
    broker: str(pick(rec, "broker", "venue", "exchange")) || "—",
    side: sideRaw || "—",
    qty,
    price,
    benchmark,
    benchmarkSource: str(pick(rec, "benchmark_source")),
    slipBps,
    isBps: num(pick(rec, "is_bps", "implementation_shortfall_bps")),
    costUsd,
    notional,
  };
}

/* ------------------------------------------------------------------ */
/* component                                                          */
/* ------------------------------------------------------------------ */
const VIEWS = ["waterfall", "fills"] as const;
type ViewId = (typeof VIEWS)[number];
const VIEW_IDS = VIEWS.map((v) => v);

const REFRESH_MS = 30_000;

export function TCAPane({ code, symbol }: FunctionPaneProps) {
  const [view, setView] = usePersistentOption<ViewId>(
    "showme.tca-view",
    VIEW_IDS,
    "waterfall",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { benchmark: "VWAP", tick },
  });

  const payload = useMemo<AnyRec>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as AnyRec)
        : {},
    [data?.data],
  );

  const fills = useMemo<FillRow[]>(() => {
    const raw = pick(payload, "rows", "fills");
    const arr = Array.isArray(raw) ? raw : [];
    return arr.map((r, i) => normalizeFill(isRec(r) ? r : {}, i));
  }, [payload]);

  const summary = useMemo<AnyRec>(
    () => (isRec(pick(payload, "summary")) ? (pick(payload, "summary") as AnyRec) : {}),
    [payload],
  );

  /* honest source mode: backend emits status + metadata.data_mode */
  const status = str(pick(payload, "status"));
  const metaMode = str(
    pick(
      isRec(data?.metadata) ? (data?.metadata as AnyRec) : {},
      "data_mode",
    ),
  );
  const dataMode = metaMode || str(pick(payload, "data_mode", "source_mode", "mode"));
  const isDegraded =
    dataMode === "degraded" ||
    dataMode === "provider_unavailable" ||
    status === "provider_unavailable";
  // A status:"ok" payload can still be degraded (e.g. VWAP fell back to arrival
  // price) — only treat it as live when it is NOT degraded, so the honest
  // degradation banner ({!isLive ? …}) actually fires for degraded-but-ok.
  const isLive = (dataMode === "live" || status === "ok") && !isDegraded;
  const benchmark = str(pick(summary, "benchmark")) || str(pick(payload, "benchmark")) || "VWAP";
  const modeLabel = isDegraded ? "degraded" : isLive ? "live" : "reference";

  const methodology = str(pick(payload, "methodology"));
  const warningsList = Array.isArray(data?.warnings) ? data?.warnings : [];
  const sources =
    data?.sources?.join(", ") || str(pick(payload, "source", "provider")) || dataMode || "showMe engine";

  /* summary KPIs (real spellings first, derived fallbacks) */
  const avgSlipBps =
    num(pick(summary, "avg_slippage_bps", "avg_slippage_bp", "avg_slippage")) ??
    (() => {
      const v = fills.map((f) => f.slipBps).filter((x): x is number => x !== null);
      return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
    })();
  const totalCost =
    num(pick(summary, "total_cost_usd", "total_cost", "total_slippage_cost", "cost_usd")) ??
    (() => {
      const v = fills.map((f) => f.costUsd).filter((x): x is number => x !== null);
      return v.length ? v.reduce((a, b) => a + b, 0) : null;
    })();
  const totalNotional =
    num(pick(summary, "total_notional", "total_notional_usd", "gross_notional")) ??
    (() => {
      const v = fills.map((f) => f.notional).filter((x): x is number => x !== null);
      return v.length ? v.reduce((a, b) => a + b, 0) : null;
    })();
  const fillCount =
    num(pick(summary, "fill_count", "n_fills", "count")) ?? fills.length;
  const worstSlip = num(pick(summary, "worst_slippage_bps", "worst_slip_bps"));
  const avgIs = num(pick(summary, "avg_is_bps", "implementation_shortfall_bps", "is_bps"));

  /* cumulative-cost curve: derived from per-fill cost_usd (series[].value is
     per-fill slippage_bps, NOT a running cost — do not mis-read it). */
  const sparkValues = useMemo<number[]>(() => {
    let acc = 0;
    const out: number[] = [];
    for (const f of fills) {
      if (f.costUsd !== null) {
        acc += f.costUsd;
        out.push(acc);
      }
    }
    return out;
  }, [fills]);

  const maxAbsSlip = useMemo(
    () =>
      fills.reduce(
        (m, f) => (f.slipBps !== null ? Math.max(m, Math.abs(f.slipBps)) : m),
        0,
      ) || 1,
    [fills],
  );

  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);

  const cols = useMemo<DataGridColumn<FillRow>[]>(
    () => [
      {
        key: "ts",
        header: "Filled",
        width: 96,
        render: (r) => <span style={monoCell}>{fmtTime(r.ts)}</span>,
      },
      {
        key: "symbol",
        header: "Symbol",
        width: 96,
        render: (r) => <span style={displayNum}>{r.symbol}</span>,
      },
      {
        key: "broker",
        header: "Broker",
        width: 110,
        render: (r) => (
          <Pill tone="muted" variant="soft" withDot={false}>
            {r.broker}
          </Pill>
        ),
      },
      {
        key: "side",
        header: "Side",
        width: 64,
        render: (r) => (
          <Pill
            tone={r.side.startsWith("S") ? "negative" : "positive"}
            variant="soft"
            withDot={false}
          >
            {r.side}
          </Pill>
        ),
      },
      {
        key: "qty",
        header: "Qty",
        numeric: true,
        width: 100,
        render: (r) => <span style={monoCell}>{fmtQty(r.qty)}</span>,
      },
      {
        key: "price",
        header: "Avg Fill",
        numeric: true,
        width: 104,
        render: (r) => <span style={displayNum}>{fmtPrice(r.price)}</span>,
      },
      {
        key: "benchmark",
        header: benchmark,
        numeric: true,
        width: 104,
        render: (r) => <span style={monoCell}>{fmtPrice(r.benchmark)}</span>,
      },
      {
        key: "slipBps",
        header: "Slippage",
        numeric: true,
        width: 116,
        render: (r) =>
          r.slipBps === null ? (
            "—"
          ) : (
            // adverse slippage is bad → negate so the chip reds-out on cost
            <span style={slipCell}>
              <DeltaChip value={-r.slipBps} format="raw" fractionDigits={1} />
              <span style={bpUnit}>bp</span>
            </span>
          ),
      },
      {
        key: "costUsd",
        header: "Cost",
        numeric: true,
        width: 104,
        render: (r) => (
          <span
            style={{
              ...monoCell,
              color:
                r.costUsd === null
                  ? "var(--text-secondary)"
                  : r.costUsd > 0
                    ? "var(--negative)"
                    : "var(--positive)",
            }}
          >
            {fmtMoney(r.costUsd)}
          </span>
        ),
      },
    ],
    [benchmark],
  );

  const isBusy = state === "loading" || state === "idle";
  const isEmpty =
    !isBusy &&
    state !== "error" &&
    fills.length === 0 &&
    (status === "empty" || (avgSlipBps === null && totalCost === null));

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Trade cost analysis"
          subtitle={`${symbol ?? "order"} · ${fills.length} fills · ${benchmark} · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {fills.length} fills
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill
                tone={isDegraded ? "negative" : isLive ? "positive" : "warn"}
                variant="soft"
              >
                {modeLabel}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={[
              { id: "waterfall", label: "Waterfall" },
              { id: "fills", label: "Fills" },
            ]}
            active={view}
            onChange={(id) => setView(id as ViewId)}
          />
        </div>
        <PaneBody>
          {isBusy ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : isEmpty ? (
            <Empty
              title="No fills to analyze"
              body={`No executed fills for ${symbol ?? "this order"}. Run a bot or import orders with fill metadata, then re-run TCA.`}
            />
          ) : (
            <div className="u-grid-gap-14">
              {!isLive ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">
                    {isDegraded ? "Degraded TCA payload" : "Reference TCA payload"}
                  </strong>
                  <span className="u-text-secondary">
                    Data mode is `{dataMode || status || "reference"}` — the live
                    intraday VWAP benchmark fell back to per-fill arrival prices
                    for some or all fills. Treat slippage and cost figures as
                    labelled references, not a clean live execution audit.
                  </span>
                </div>
              ) : null}

              {warningsList.length ? (
                <div style={warningBox}>
                  <strong className="u-text-warn">Provider warnings</strong>
                  <ul style={warningList}>
                    {warningsList.slice(0, 3).map((w, i) => (
                      <li key={i} className="u-text-secondary">
                        {String(w)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {/* KPI ribbon */}
              <section style={kpiGrid} aria-label="TCA KPI ribbon">
                <StatCard
                  label="Avg slippage"
                  value={fmtBps(avgSlipBps)}
                  caption={`AS OF ${utcStamp} UTC · vs ${benchmark}`}
                  tone={
                    avgSlipBps === null
                      ? "neutral"
                      : avgSlipBps > 0
                        ? "negative"
                        : "positive"
                  }
                />
                <StatCard
                  label="Total cost"
                  value={fmtMoney(totalCost)}
                  caption={`${fillCount} fills`}
                  tone={
                    totalCost === null
                      ? "neutral"
                      : totalCost > 0
                        ? "negative"
                        : "positive"
                  }
                  trend={sparkValues}
                />
                <StatCard
                  label="Notional"
                  value={fmtMoney(totalNotional)}
                  caption={symbol ?? "order"}
                  tone="neutral"
                />
                <StatCard
                  label={worstSlip !== null ? "Worst slip" : "Impl. shortfall"}
                  value={
                    worstSlip !== null
                      ? fmtBps(worstSlip)
                      : avgIs !== null
                        ? fmtBps(avgIs)
                        : `${fillCount} fills`
                  }
                  caption={worstSlip !== null ? "single fill" : "vs arrival"}
                  tone={
                    (worstSlip ?? avgIs) === null
                      ? "neutral"
                      : (worstSlip ?? avgIs ?? 0) > 0
                        ? "negative"
                        : "positive"
                  }
                />
              </section>

              {/* cumulative cost sparkline */}
              {sparkValues.length > 1 ? (
                <section style={sparkPanel} aria-label="Cumulative execution cost">
                  <div style={sparkHeader}>
                    <span style={metaLabel}>Cumulative execution cost</span>
                    <span
                      style={{
                        ...monoCell,
                        color:
                          sparkValues[sparkValues.length - 1] > 0
                            ? "var(--negative)"
                            : "var(--positive)",
                        fontWeight: 700,
                      }}
                    >
                      {fmtMoney(sparkValues[sparkValues.length - 1])}
                    </span>
                  </div>
                  <Sparkline
                    values={sparkValues}
                    width={520}
                    height={44}
                    tone={
                      sparkValues[sparkValues.length - 1] > 0 ? "negative" : "positive"
                    }
                  />
                  <div style={sparkCaption}>
                    Running slippage bill accrued across the order, first fill → last.
                  </div>
                </section>
              ) : null}

              {view === "waterfall" ? (
                <section style={methodPanel} aria-label="Per-fill slippage waterfall">
                  <div style={waterfallHeader}>
                    <span style={metaLabel}>Per-fill slippage vs {benchmark}</span>
                    <Pill tone="muted" variant="soft" withDot={false}>
                      bp · centred zero
                    </Pill>
                  </div>
                  {fills.length === 0 ? (
                    <Empty title="No per-fill detail" body="Waterfall unavailable." />
                  ) : (
                    <div style={waterfallList}>
                      {fills.map((f) => {
                        const v = f.slipBps;
                        const adverse = v !== null && v > 0;
                        const pct = v === null ? 0 : (Math.abs(v) / maxAbsSlip) * 50;
                        const tone = adverse ? "var(--negative)" : "var(--positive)";
                        return (
                          <div key={f.id} style={wfRow}>
                            <span style={wfLabel}>
                              {fmtTime(f.ts)} · {f.symbol} · {f.side}
                            </span>
                            <div style={wfTrack} aria-hidden>
                              {v !== null ? (
                                <div
                                  style={{
                                    ...wfBar,
                                    width: `${pct}%`,
                                    background: `linear-gradient(90deg, color-mix(in srgb, ${tone} 55%, transparent), ${tone})`,
                                    ...(adverse ? { left: "50%" } : { right: "50%" }),
                                  }}
                                />
                              ) : null}
                            </div>
                            <span style={{ ...wfValue, color: tone }}>{fmtBps(v)}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </section>
              ) : (
                <DataGrid
                  columns={cols}
                  rows={fills}
                  rowKey={(r, i) => `${r.id}-${i}`}
                  density="compact"
                />
              )}

              <section style={methodPanel}>
                <div style={metaLabel}>Methodology</div>
                <p style={methodText}>
                  {methodology ||
                    "Slippage measured per child fill against the interval VWAP benchmark; positive bp = adverse execution (signed by side). Cost = slippage × notional; the ribbon rolls up the child-fill ledger. TCA is strictly post-trade and read-only."}
                </p>
              </section>
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={sources} />
          <StatusDivider />
          <StatusSection label="benchmark" value={benchmark} />
          <StatusDivider />
          <StatusSection label="fills" value={fills.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="mode" value={dataMode || status || "—"} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* styles                                                             */
/* ------------------------------------------------------------------ */
const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const monoCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const displayNum: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  fontWeight: 600,
};

const slipCell: CSSProperties = {
  display: "inline-flex",
  alignItems: "baseline",
  gap: 4,
  justifyContent: "flex-end",
};

const bpUnit: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.04em",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const sparkPanel: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
  display: "grid",
  gap: 8,
};

const sparkHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const sparkCaption: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.04em",
};

const waterfallHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  marginBottom: 8,
};

const waterfallList: CSSProperties = {
  display: "grid",
  gap: 3,
  maxHeight: 260,
  overflowY: "auto",
};

const wfRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "184px minmax(0, 1fr) 84px",
  alignItems: "center",
  gap: 10,
  fontSize: 11,
  minHeight: 20,
};

const wfLabel: CSSProperties = {
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

const wfTrack: CSSProperties = {
  position: "relative",
  height: 14,
  background:
    "linear-gradient(90deg, transparent calc(50% - 1px), var(--grid-color) 50%, transparent calc(50% + 1px))",
  borderRadius: 2,
};

const wfBar: CSSProperties = {
  position: "absolute",
  top: 2,
  bottom: 2,
  borderRadius: 2,
  transition: "width var(--motion-base)",
};

const wfValue: CSSProperties = {
  textAlign: "right",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 700,
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
  fontSize: 12,
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const warningList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const methodPanel: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: 6,
};

const methodText: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: 12,
};
