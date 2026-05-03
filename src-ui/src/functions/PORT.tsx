/**
 * PORT — Comprehensive portfolio analytics.
 *
 * Round-14 view focuses on the position table + headline KPIs (notional,
 * unrealized P&L, top-asset weights). Round-17 layers on stress / VaR /
 * factor exposure tabs.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { subscribeQuote, type StreamStatus } from "@/lib/stream";
import { navigate } from "@/lib/router";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface Position {
  symbol: string;
  asset_class?: string;
  quantity?: number;
  avg_cost?: number;
  last?: number;
  market_value?: number;
  unrealized_pnl?: number;
  weight?: number;
  currency?: string;
  [key: string]: unknown;
}

interface PortData {
  positions?: Position[];
  totals?: {
    market_value?: number;
    cost_basis?: number;
    unrealized_pnl?: number;
    cash?: number;
    n_positions?: number;
  };
  by_asset_class?: Record<string, number>;
  by_currency?: Record<string, number>;
  [key: string]: unknown;
}

const fmt$ = (n?: number) => {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
};

const COLS: DataGridColumn<Position>[] = [
  {
    key: "symbol",
    header: "Symbol",
    width: 100,
    render: (p) => (
      <button
        type="button"
        onClick={() => navigate(`/symbol/${p.symbol}/DES`)}
        style={{
          background: "transparent",
          border: "none",
          color: "var(--accent)",
          font: "inherit",
          padding: 0,
          cursor: "default",
        }}
      >
        {p.symbol}
      </button>
    ),
  },
  { key: "asset_class", header: "Class", width: 90 },
  { key: "quantity", header: "Qty", numeric: true, width: 90 },
  {
    key: "avg_cost",
    header: "Avg cost",
    numeric: true,
    width: 100,
    render: (p) => (p.avg_cost != null ? `$${p.avg_cost.toFixed(2)}` : "—"),
  },
  {
    key: "last",
    header: "Last",
    numeric: true,
    width: 100,
    render: (p) => (p.last != null ? `$${p.last.toFixed(2)}` : "—"),
  },
  {
    key: "market_value",
    header: "MV",
    numeric: true,
    width: 110,
    render: (p) => fmt$(p.market_value),
  },
  {
    key: "unrealized_pnl",
    header: "Unrl P&L",
    numeric: true,
    width: 120,
    render: (p) => <ChangeText value={p.unrealized_pnl ?? 0} prefix="$" digits={0} />,
  },
  {
    key: "weight",
    header: "%",
    numeric: true,
    width: 70,
    render: (p) =>
      p.weight != null ? `${(p.weight * 100).toFixed(1)}%` : "—",
  },
];

export function PORTPane({ code }: FunctionPaneProps) {
  const { state, data, error, refetch } = useFunction<PortData>({ code });
  const positions = useMemo(() => data?.data?.positions ?? [], [data?.data?.positions]);
  const totals = data?.data?.totals;
  const [live, setLive] = useState<Record<string, { price: number; ts: number }>>({});
  const [streamStatus, setStreamStatus] = useState<Record<string, StreamStatus>>({});

  // Round 30 — Subscribe each position to the WS stream so MV / P&L
  // update sub-second. Re-runs whenever the underlying position list
  // mutates (close / reopen).
  useEffect(() => {
    if (positions.length === 0) return;
    const handles = positions
      .map((p) => p.symbol)
      .filter((s, idx, all) => !!s && all.indexOf(s) === idx)
      .map((sym) =>
        subscribeQuote(sym, {
          onTick: (tick) =>
            setLive((m) => ({ ...m, [sym]: { price: tick.price, ts: tick.ts * 1000 } })),
          onStatus: (status) =>
            setStreamStatus((s) => ({ ...s, [sym]: status })),
        }),
      );
    return () => {
      for (const h of handles) h.close();
    };
  }, [positions]);

  const enriched = useMemo<Position[]>(() => {
    const overlaid = positions.map((p) => {
      const tick = live[p.symbol];
      if (!tick) return p;
      const last = tick.price;
      const qty = Number(p.quantity) || 0;
      const cost = Number(p.avg_cost) || 0;
      const market_value = qty * last;
      const unrealized_pnl = market_value - qty * cost;
      return {
        ...p,
        last,
        market_value,
        unrealized_pnl,
        _live_ts: tick.ts,
      };
    });
    const total = totals?.market_value ?? overlaid.reduce(
      (s, p) => s + (Number(p.market_value) || 0), 0,
    );
    return overlaid.map((p) => ({
      ...p,
      weight: total > 0 ? (Number(p.market_value) || 0) / total : undefined,
    }));
  }, [positions, totals, live]);

  const liveTotals = useMemo(() => {
    if (Object.keys(live).length === 0) return totals;
    const mv = enriched.reduce((s, p) => s + (Number(p.market_value) || 0), 0);
    const cost = enriched.reduce(
      (s, p) => s + (Number(p.quantity) || 0) * (Number(p.avg_cost) || 0),
      0,
    );
    return {
      ...totals,
      market_value: mv,
      cost_basis: cost,
      unrealized_pnl: mv - cost,
    };
  }, [enriched, totals, live]);

  const liveCount = Object.values(streamStatus).filter((s) => s === "live").length;

  const body =
    state === "loading" || state === "idle" ? (
      <div style={{ display: "grid", gap: 8 }}>
        <Skeleton height={20} width="40%" />
        <Skeleton height={14} />
        <Skeleton height={14} width="80%" />
        <Skeleton height={120} />
      </div>
    ) : state === "error" ? (
      <Empty
        title="Function error"
        body={error?.message ?? "—"}
        icon="!"
        action={
          <button onClick={refetch} className="btn">Retry</button>
        }
      />
    ) : enriched.length === 0 ? (
      <Empty
        title="Empty portfolio"
        body="No positions on file. Add holdings via /portfolio (ShowMe) or open a PORT WHAT-IF (Round 17)."
        icon="∅"
      />
    ) : (
      <PORTView
        positions={enriched}
        totals={liveTotals}
        byClass={data?.data?.by_asset_class}
      />
    );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Portfolio"
          subtitle={`${positions.length} position(s)`}
          trailing={
            <FunctionControlGroup>
              {liveTotals?.market_value != null ? (
                <Pill
                  tone={(liveTotals.unrealized_pnl ?? 0) >= 0 ? "positive" : "negative"}
                  withDot={liveCount > 0}
                >
                  MV {fmt$(liveTotals.market_value)}
                </Pill>
              ) : null}
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
          <span>
            ws · {liveCount}/{positions.length} live
          </span>
          {data?.warnings?.length ? <span>{data.warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PORTView({
  positions,
  totals,
  byClass,
}: {
  positions: Position[];
  totals?: PortData["totals"];
  byClass?: Record<string, number>;
}) {
  const cardClasses = byClass ?? aggregateByClass(positions);
  const totalMV = totals?.market_value ?? positions.reduce(
    (s, p) => s + (p.market_value ?? 0), 0,
  );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
        }}
      >
        <Kpi label="Market value" value={fmt$(totalMV)} />
        <Kpi label="Cost basis" value={fmt$(totals?.cost_basis)} />
        <Kpi
          label="Unrealized P&L"
          value={<ChangeText value={totals?.unrealized_pnl ?? 0} prefix="$" digits={0} />}
        />
        <Kpi label="Cash" value={fmt$(totals?.cash)} />
      </div>

      <Card>
        <CardHeader trailing={`${Object.keys(cardClasses).length} classes`}>
          By asset class
        </CardHeader>
        <CardBody>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 8,
            }}
          >
            {Object.entries(cardClasses).map(([cls, mv]) => (
              <div
                key={cls}
                style={{
                  background: "var(--bg-elev-2)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-md)",
                  padding: 10,
                  fontFamily: "JetBrains Mono, monospace",
                }}
              >
                <div
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-mute)",
                  }}
                >
                  {cls}
                </div>
                <div style={{ fontSize: 14, color: "var(--text-primary)" }}>
                  {fmt$(mv)}
                </div>
                {totalMV > 0 && (
                  <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                    {((mv / totalMV) * 100).toFixed(1)}%
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardBody>
      </Card>

      <DataGrid columns={COLS} rows={positions} rowKey={(p) => p.symbol} density="compact" />
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      style={{
        background: "var(--bg-elev-2)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        padding: 12,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: "var(--text-mute)",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 17,
          color: "var(--text-primary)",
          fontFamily: "JetBrains Mono, monospace",
          marginTop: 4,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function aggregateByClass(positions: Position[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of positions) {
    const key = p.asset_class ?? "OTHER";
    out[key] = (out[key] ?? 0) + (p.market_value ?? 0);
  }
  return out;
}
