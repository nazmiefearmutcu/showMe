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
import { sidecarBaseUrl } from "@/lib/sidecar";
import { confirmAction } from "@/lib/confirm";
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

interface CloseRecord {
  symbol: string;
  asset_class?: string;
  quantity?: number;
  avg_cost?: number;
  exit_price?: number;
  market_value?: number;
  realized_pnl?: number;
  closed_at?: string;
  dry_run?: boolean;
  reason?: string;
}

interface CloseResponse {
  ok: boolean;
  dry_run: boolean;
  record: CloseRecord;
  remaining_positions: number;
  closed_symbols: string[];
}

interface PortData {
  status?: string;
  reason?: string;
  next_actions?: string[];
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

export function PORTPane({ code }: FunctionPaneProps) {
  const { state, data, error, refetch } = useFunction<PortData>({ code });
  const positions = useMemo(() => data?.data?.positions ?? [], [data?.data?.positions]);
  const totals = data?.data?.totals;
  const payloadStatus = data?.status ?? data?.data?.status;
  const [live, setLive] = useState<Record<string, { price: number; ts: number }>>({});
  const [streamStatus, setStreamStatus] = useState<Record<string, StreamStatus>>({});
  const [closePreview, setClosePreview] = useState<CloseResponse | null>(null);
  const [closeError, setCloseError] = useState<string | null>(null);
  const [busySymbol, setBusySymbol] = useState<string | null>(null);

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
    const snapshotMv = totals?.market_value ?? 0;
    if (snapshotMv > 0 && (mv > snapshotMv * 3 || mv < snapshotMv / 3)) {
      return totals;
    }
    return {
      ...totals,
      market_value: mv,
      cost_basis: cost,
      unrealized_pnl: mv - cost,
    };
  }, [enriched, totals, live]);

  const liveCount = Object.values(streamStatus).filter((s) => s === "live").length;
  const hasLiveOverlay = Object.keys(live).length > 0;
  const liveTotalsGuarded = hasLiveOverlay && liveTotals === totals;
  const classBreakdown =
    hasLiveOverlay && !liveTotalsGuarded
      ? aggregateByClass(enriched)
      : data?.data?.by_asset_class ?? aggregateByClass(positions);

  async function previewClose(position: Position) {
    setBusySymbol(position.symbol);
    setCloseError(null);
    try {
      const out = await requestPortfolioClose(position, true);
      setClosePreview(out);
    } catch (err) {
      setCloseError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusySymbol(null);
    }
  }

  async function closePosition(position: Position) {
    const qty = Number(position.quantity) || 0;
    const px = Number(position.last ?? position.avg_cost ?? 0);
    const confirmed = await confirmAction({
      title: `Close ${position.symbol}`,
      body:
        "This removes the local paper position and records a legacy skip marker. " +
        `Quantity ${qty}; exit price ${px}.`,
      primary: "Close position",
      destructive: true,
    });
    if (!confirmed) return;
    setBusySymbol(position.symbol);
    setCloseError(null);
    try {
      const out = await requestPortfolioClose(position, false);
      setClosePreview(out);
      refetch();
    } catch (err) {
      setCloseError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusySymbol(null);
    }
  }

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
        body={
          data?.data?.next_actions?.[0] ??
          "No local positions are attached to this runtime."
        }
        icon="∅"
        action={
          <button type="button" className="btn btn--accent" onClick={() => navigate("/fn/PORT_WHATIF")}>
            Open What-If
          </button>
        }
      />
    ) : (
      <PORTView
        positions={enriched}
        totals={liveTotals}
        byClass={classBreakdown}
        closePreview={closePreview}
        closeError={closeError}
        busySymbol={busySymbol}
        onPreviewClose={previewClose}
        onClosePosition={closePosition}
      />
    );

  return (
    <div className="showme-port showme-port-motion" style={{ padding: 18, height: "100%" }}>
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
              <LoadStatePill state={state} status={payloadStatus} />
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
  closePreview,
  closeError,
  busySymbol,
  onPreviewClose,
  onClosePosition,
}: {
  positions: Position[];
  totals?: PortData["totals"];
  byClass?: Record<string, number>;
  closePreview: CloseResponse | null;
  closeError: string | null;
  busySymbol: string | null;
  onPreviewClose: (position: Position) => void;
  onClosePosition: (position: Position) => void;
}) {
  const cardClasses = byClass ?? aggregateByClass(positions);
  const totalMV = totals?.market_value ?? positions.reduce(
    (s, p) => s + (p.market_value ?? 0), 0,
  );
  const cols = useMemo(
    () => positionColumns({ busySymbol, onPreviewClose, onClosePosition }),
    [busySymbol, onPreviewClose, onClosePosition],
  );
  return (
    <div className="showme-port__view showme-card-reveal" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div
        className="showme-port__kpi-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
        }}
      >
        <Kpi label="Market value" value={fmt$(totalMV)} pulseKey={`mv-${totalMV}`} />
        <Kpi label="Cost basis" value={fmt$(totals?.cost_basis)} pulseKey={`cost-${totals?.cost_basis ?? "na"}`} />
        <Kpi
          label="Unrealized P&L"
          value={<ChangeText value={totals?.unrealized_pnl ?? 0} prefix="$" digits={0} />}
          pulseKey={`pnl-${totals?.unrealized_pnl ?? "na"}`}
        />
        <Kpi label="Cash" value={fmt$(totals?.cash)} pulseKey={`cash-${totals?.cash ?? "na"}`} />
      </div>

      <Card className="showme-port__asset-card showme-card-reveal">
        <CardHeader trailing={`${Object.keys(cardClasses).length} classes`}>
          By asset class
        </CardHeader>
        <CardBody>
          <div
            className="showme-port__asset-grid"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 8,
            }}
          >
            {Object.entries(cardClasses).map(([cls, mv]) => (
              <div
                className="showme-port__class-card showme-card-reveal showme-weight-track"
                key={cls}
                style={{
                  background: "var(--bg-elev-2)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-md)",
                  padding: 10,
                  fontFamily: "JetBrains Mono, monospace",
                  ["--showme-class-share" as string]: `${totalMV > 0 ? Math.max(0, Math.min(1, mv / totalMV)) : 0}`,
                }}
              >
                <span
                  key={`${cls}-${mv}-${totalMV}`}
                  className="showme-port__class-fill showme-weight-fill"
                />
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
                  <span
                    key={`${cls}-mv-${mv}`}
                    className={liveCellClass("neutral")}
                  >
                    {fmt$(mv)}
                  </span>
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

      {closePreview || closeError ? (
        <ClosePreviewPanel preview={closePreview} error={closeError} />
      ) : null}

      <DataGrid
        className="showme-port__grid showme-motion-grid"
        columns={cols}
        rows={positions}
        rowKey={(p) => p.symbol}
        rowClassName={(p, idx) =>
          [
            "showme-motion-grid__row",
            "showme-row-reveal",
            `showme-motion-grid__row--${Math.min(idx, 10)}`,
            p._live_ts ? "showme-motion-grid__row--live" : "",
          ].filter(Boolean).join(" ")
        }
        density="compact"
      />
    </div>
  );
}

function positionColumns({
  busySymbol,
  onPreviewClose,
  onClosePosition,
}: {
  busySymbol: string | null;
  onPreviewClose: (position: Position) => void;
  onClosePosition: (position: Position) => void;
}): DataGridColumn<Position>[] {
  return [
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
      render: (p) =>
        p.last != null ? (
          <span
            key={liveMotionKey(p, "last")}
            className={liveCellClass("neutral")}
          >
            ${p.last.toFixed(2)}
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "market_value",
      header: "MV",
      numeric: true,
      width: 110,
      render: (p) => (
        <span
          key={liveMotionKey(p, "market_value")}
          className={liveCellClass("neutral")}
        >
          {fmt$(p.market_value)}
        </span>
      ),
    },
    {
      key: "unrealized_pnl",
      header: "Unrl P&L",
      numeric: true,
      width: 120,
      render: (p) => (
        <span
          key={liveMotionKey(p, "unrealized_pnl")}
          className={liveCellClass(motionTone(p.unrealized_pnl))}
        >
          <ChangeText value={p.unrealized_pnl ?? 0} prefix="$" digits={0} />
        </span>
      ),
    },
    {
      key: "weight",
      header: "%",
      numeric: true,
      width: 70,
      render: (p) =>
        p.weight != null ? (
          <span
            key={liveMotionKey(p, "weight")}
            className={liveCellClass("neutral", true)}
          >
            {(p.weight * 100).toFixed(1)}%
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "actions",
      header: "Actions",
      width: 154,
      render: (p) => {
        const busy = busySymbol === p.symbol;
        return (
          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => onPreviewClose(p)}
              title="Preview the local paper close order without changing state"
            >
              Preview
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => onClosePosition(p)}
              title="Close this local paper position after confirmation"
            >
              Close
            </button>
          </div>
        );
      },
    },
  ];
}

function ClosePreviewPanel({
  preview,
  error,
}: {
  preview: CloseResponse | null;
  error: string | null;
}) {
  if (error) {
    return (
      <div className="showme-port__close-panel showme-card-reveal" style={closePanelStyle}>
        <strong style={{ color: "var(--negative)" }}>Close failed</strong>
        <span>{error}</span>
      </div>
    );
  }
  if (!preview) return null;
  const r = preview.record;
  return (
    <div className="showme-port__close-panel showme-card-reveal" style={closePanelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <strong>{preview.dry_run ? "Close preview" : "Position closed"}</strong>
        <span style={{ color: "var(--text-secondary)" }}>
          remaining {preview.remaining_positions}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 10 }}>
        <Kpi label="Symbol" value={r.symbol} />
        <Kpi label="Quantity" value={fmtNum(r.quantity)} />
        <Kpi label="Exit" value={r.exit_price != null ? `$${r.exit_price.toFixed(2)}` : "—"} />
        <Kpi label="Notional" value={fmt$(r.market_value)} />
        <Kpi label="Realized P&L" value={<ChangeText value={r.realized_pnl ?? 0} prefix="$" digits={0} />} />
      </div>
      {preview.dry_run ? (
        <span style={{ color: "var(--text-secondary)" }}>
          Preview is non-destructive. Close requires a confirmation dialog and writes a legacy skip marker.
        </span>
      ) : null}
    </div>
  );
}

function Kpi({
  label,
  value,
  pulseKey,
}: {
  label: string;
  value: React.ReactNode;
  pulseKey?: string | number;
}) {
  return (
    <div
      className="showme-port__kpi showme-card-reveal"
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
        key={pulseKey}
        className="showme-port__kpi-value"
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

function liveMotionKey(position: Position, key: keyof Position): string {
  const stamp = Number(position._live_ts ?? 0);
  const raw = position[key];
  const value = typeof raw === "number" ? raw : String(raw ?? "na");
  return `${position.symbol}-${String(key)}-${stamp}-${value}`;
}

function motionTone(value: unknown): "positive" | "negative" | "neutral" {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n) || n === 0) return "neutral";
  return n > 0 ? "positive" : "negative";
}

function liveCellClass(tone: "positive" | "negative" | "neutral", compact = false): string {
  const direction =
    tone === "positive" ? "up" : tone === "negative" ? "down" : "changed";
  return [
    "showme-live-value",
    "showme-live-cell",
    "is-showme-updated",
    compact ? "showme-live-value--compact" : "",
    `showme-live-value--${tone}`,
    `showme-live-cell--${direction}`,
  ].filter(Boolean).join(" ");
}

function aggregateByClass(positions: Position[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of positions) {
    const key = p.asset_class ?? "OTHER";
    out[key] = (out[key] ?? 0) + (p.market_value ?? 0);
  }
  return out;
}

function fmtNum(n?: number) {
  return n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

async function requestPortfolioClose(position: Position, dryRun: boolean): Promise<CloseResponse> {
  const exit = Number(position.last ?? position.avg_cost ?? 0);
  const res = await fetch(`${sidecarBaseUrl()}/api/portfolio/positions/${encodeURIComponent(position.symbol)}/close`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      dry_run: dryRun,
      exit_price: Number.isFinite(exit) && exit > 0 ? exit : undefined,
      reason: dryRun ? "ui_preview" : "ui_close",
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as CloseResponse;
}

const closePanelStyle: React.CSSProperties = {
  display: "grid",
  gap: 10,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--bg-elev-2)",
};
