/**
 * EXEC — Execution Monitor.
 *
 * Slice-by-slice VWAP/TWAP execution plan built against live intraday bars
 * (backend drives the real algo schedulers over Binance/Yahoo 5m OHLCV).
 * Header: algo / side / slices / horizon / parent-size controls (all
 * persisted under `showme.exec.*`) + status pill + refresh. Body: pace +
 * implementation-shortfall headline cards, then the per-slice TCA table —
 * each slice maps to a real market bar with its interval-VWAP benchmark,
 * slippage bps (tone-tinted) and side-signed IS bps.
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

interface EXECRow {
  slice_idx?: number;
  offset_s?: number;
  ts_ms?: number | null;
  qty?: number;
  cum_qty?: number;
  bar_close?: number | null;
  interval_vwap?: number | null;
  benchmark_px?: number | null;
  slip_bps?: number | null;
  is_bps?: number | null;
  pace_pct?: number | null;
}

interface EXECOrder {
  parent_id?: string;
  side?: string;
  algo?: string;
  target_qty?: number;
  filled_qty?: number;
  avg_fill_px?: number | null;
  arrival_price?: number | null;
  pace_pct?: number | null;
  status?: string;
}

interface EXECData {
  status?: string;
  reason?: string;
  symbol?: string;
  algo?: string;
  interval?: string;
  rows?: EXECRow[];
  orders?: EXECOrder[];
  cards?: {
    avg_is_bps?: number | null;
    worst_slippage_bps?: number | null;
    data_mode?: string;
    as_of?: number | null;
  };
}

const ALGO_OPTIONS = [
  { value: "TWAP", label: "TWAP" },
  { value: "VWAP", label: "VWAP" },
  { value: "ICEBERG", label: "ICE" },
  { value: "SNIPER", label: "SNPR" },
] as const;
const ALGO_IDS = ALGO_OPTIONS.map((o) => o.value);

const SIDE_OPTIONS = [
  { value: "BUY", label: "BUY" },
  { value: "SELL", label: "SELL" },
] as const;
const SIDE_IDS = SIDE_OPTIONS.map((o) => o.value);

const SLICES_OPTIONS = [
  { value: 6, label: "6" },
  { value: 12, label: "12" },
  { value: 24, label: "24" },
] as const;
const SLICES_IDS = SLICES_OPTIONS.map((o) => o.value);

const HORIZON_OPTIONS = [
  { value: 300, label: "5m" },
  { value: 900, label: "15m" },
  { value: 1800, label: "30m" },
  { value: 3600, label: "1h" },
] as const;
const HORIZON_IDS = HORIZON_OPTIONS.map((o) => o.value);

const QTY_OPTIONS = [
  { value: 100, label: "100" },
  { value: 500, label: "500" },
  { value: 1000, label: "1k" },
  { value: 5000, label: "5k" },
] as const;
const QTY_IDS = QTY_OPTIONS.map((o) => o.value);

export function EXECPane({ code, symbol }: FunctionPaneProps) {
  const [algo, setAlgo] = usePersistentOption<string>("showme.exec.algo", ALGO_IDS, "TWAP");
  const [side, setSide] = usePersistentOption<string>("showme.exec.side", SIDE_IDS, "BUY");
  const [slices, setSlices] = usePersistentOption<number>("showme.exec.slices", SLICES_IDS, 12);
  const [horizon, setHorizon] = usePersistentOption<number>(
    "showme.exec.horizon",
    HORIZON_IDS,
    900,
  );
  const [qty, setQty] = usePersistentOption<number>("showme.exec.qty", QTY_IDS, 100);

  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "CRYPTO"]);
  const { state, data, error, refetch } = useFunction<EXECData>({
    code,
    symbol: effectiveSymbol,
    params: {
      action: "plan",
      algo,
      side,
      slices,
      horizon_seconds: horizon,
      target_qty: qty,
    },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: EXECRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const order = payload?.orders?.[0];
  const cards = payload?.cards;
  const status = payload?.status ?? "—";

  const COLS: DataGridColumn<EXECRow>[] = useMemo(
    () => [
      {
        key: "slice_idx",
        header: "#",
        width: 44,
        render: (r) => <span style={monoMutedStyle}>{r.slice_idx ?? "—"}</span>,
      },
      {
        key: "ts_ms",
        header: "Window (UTC)",
        width: 116,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtHm(r.ts_ms)}</span>
        ),
      },
      {
        key: "qty",
        header: "Qty",
        numeric: true,
        width: 96,
        render: (r) => <span style={monoStrongStyle}>{fmtNum(r.qty, 2)}</span>,
      },
      {
        key: "benchmark_px",
        header: "Benchmark VWAP",
        numeric: true,
        width: 140,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtNum(r.benchmark_px, 2)}</span>
        ),
      },
      {
        key: "bar_close",
        header: "Bar close",
        numeric: true,
        width: 108,
        render: (r) => <span style={monoMutedStyle}>{fmtNum(r.bar_close, 2)}</span>,
      },
      {
        key: "slip_bps",
        header: "Slip bps",
        numeric: true,
        width: 100,
        render: (r) => (
          <span style={{ ...monoStrongStyle, color: bpsColor(r.slip_bps, side, false) }}>
            {fmtBps(r.slip_bps)}
          </span>
        ),
      },
      {
        key: "is_bps",
        header: "IS bps",
        numeric: true,
        width: 96,
        render: (r) => (
          <span style={{ ...monoMutedStyle, color: bpsColor(r.is_bps, side, true) }}>
            {fmtBps(r.is_bps)}
          </span>
        ),
      },
      {
        key: "pace_pct",
        header: "Pace",
        numeric: true,
        width: 88,
        render: (r) => <span style={monoMutedStyle}>{fmtPct(r.pace_pct)}</span>,
      },
    ],
    [side],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="EXEC needs a tradable symbol to plan against." icon="⌖" />
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
  ) : rows.length === 0 ? (
    <Empty
      title="No execution plan"
      body={
        payload?.reason ??
        "No intraday bars available for this symbol — the planner refuses to fabricate slices."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="EXEC headline">
        <StatCard
          label="Avg IS"
          value={fmtBps(cards?.avg_is_bps)}
          caption={`AVG IMPLEMENTATION SHORTFALL · ${order?.algo ?? payload?.algo ?? algo}`}
          tone={bpsTone(cards?.avg_is_bps, side, true)}
        />
        <StatCard
          label="Worst slip"
          value={fmtBps(cards?.worst_slippage_bps)}
          caption="WORST SLICE VS INTERVAL VWAP"
          tone={bpsTone(cards?.worst_slippage_bps, side, false)}
        />
        <StatCard
          label="Target / parent"
          value={fmtNum(order?.target_qty ?? qty, 0)}
          caption={`${side} · ${slices} SLICES · ${labelForHorizon(horizon)}`}
          tone="neutral"
        />
        <StatCard
          label="Final pace"
          value={fmtPct(rows[rows.length - 1]?.pace_pct)}
          caption={`ARRIVAL ${fmtNum(order?.arrival_price, 2)} → AVG FILL ${fmtNum(order?.avg_fill_px, 2)}`}
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `slice-${r.slice_idx ?? i}`}
        density="compact"
        ariaLabel="EXEC slice plan"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Execution Monitor — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${payload?.algo ?? algo} · ${slices}×${labelForHorizon(horizon)} · ${payload?.interval ?? "5m"} bars`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} slices
              </Pill>
              <LoadStatePill state={state} status={status} />
              <SegmentedControl
                label="ALGO"
                value={algo}
                options={ALGO_OPTIONS}
                onChange={setAlgo}
              />
              <SegmentedControl
                label="SIDE"
                value={side}
                options={SIDE_OPTIONS}
                onChange={setSide}
              />
              <SegmentedControl
                label="SLICES"
                value={slices}
                options={SLICES_OPTIONS}
                onChange={setSlices}
              />
              <SegmentedControl
                label="HORIZON"
                value={horizon}
                options={HORIZON_OPTIONS}
                onChange={setHorizon}
              />
              <SegmentedControl
                label="QTY"
                value={qty}
                options={QTY_OPTIONS}
                onChange={setQty}
              />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Rebuild execution plan"
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
          <StatusSection label="slices" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="parent" value={order?.parent_id ?? "—"} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function labelForHorizon(seconds: number): string {
  const opt = HORIZON_OPTIONS.find((o) => o.value === seconds);
  return opt?.label ?? `${seconds}s`;
}

/**
 * EXEC bps semantics (backend trade/exec.py):
 *  - ``is_bps`` is side-signed implementation-shortfall COST: positive means
 *    the slice executed worse than arrival (paid more on BUY, sold lower on
 *    SELL) — negative is a favourable fill on both sides.
 *  - ``slip_bps`` is the raw close-vs-benchmark move, NOT side-signed:
 *    positive = close above the interval VWAP, which is a cost on BUY but a
 *    favourable print on SELL — so the SELL side flips the sign for colour.
 */
function bpsColor(
  v: number | null | undefined,
  side: string,
  sideSigned: boolean,
): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-mute)";
  const cost = sideSigned ? v : side.toUpperCase() === "SELL" ? -v : v;
  return cost > 0 ? "var(--negative)" : "var(--positive)";
}

function bpsTone(
  v: number | null | undefined,
  side: string,
  sideSigned: boolean,
): "neutral" | "positive" | "negative" {
  if (v == null || !Number.isFinite(v)) return "neutral";
  const cost = sideSigned ? v : side.toUpperCase() === "SELL" ? -v : v;
  return cost > 0 ? "negative" : "positive";
}

function fmtHm(tsMs: number | null | undefined): string {
  if (tsMs == null || !Number.isFinite(tsMs)) return "—";
  const d = new Date(tsMs);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function fmtNum(v: number | null | undefined, digits: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return formatNumberFixed(v, digits);
}

function fmtBps(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(1)}%`;
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
