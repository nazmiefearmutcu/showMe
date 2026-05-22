/**
 * PORT — Bloomberg-grade portfolio analytics.
 *
 * Round-redesign: KPI ribbon (StatCard) + asset-class progress strip + dense
 * position table with DeltaChip P&L pills, accent symbol links, weight
 * progress fills, and ghost action buttons. All colors token-driven.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  ChangeText,
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
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { subscribeQuote, type StreamStatus } from "@/lib/stream";
import { navigate } from "@/lib/router";
import { sidecarFetch } from "@/lib/sidecar";
import { confirmAction } from "@/lib/confirm";
import { formatCurrency } from "@/lib/format";
import { usePortfolioStore, type PortfolioGroup } from "@/lib/portfolio-store";
import { useExchangeStore } from "@/lib/exchange-store";
import { useTradingStore } from "@/lib/trading-store";
import { OrderTicket } from "./OrderTicket";
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

// Compact, sign-correct USD formatter. Sign comes BEFORE the symbol so
// negatives render as "-$1.50B" not "$-1.50B". See ui/src/lib/format.ts.
const fmt$ = (n?: number) => formatCurrency(n, { compact: true });

// Stable seeded micro-trend for KPI sparklines until tick history is wired.
function makeTrend(seed: number, n = 16): number[] {
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < n; i++) {
    const x = Math.sin((i + seed) * 0.7) * 6 + Math.cos((i * 0.3 + seed) * 1.1) * 4;
    v = Math.max(20, Math.min(80, v + x * 0.6));
    out.push(v);
  }
  return out;
}

function AggregateHeader() {
  const totals = usePortfolioStore((s) => s.totals);
  const lastFetched = usePortfolioStore((s) => s.lastFetchedAt);
  const load = usePortfolioStore((s) => s.loadPortfolio);
  const groups = usePortfolioStore((s) => s.groups);
  const errors = groups.filter((g) => g.error).length;
  return (
    <div style={{ display: "flex", gap: 24, alignItems: "center", padding: "8px 16px",
                  borderBottom: "1px solid var(--border-1)" }}>
      <div>
        <div style={{ fontSize: 10, color: "var(--fg-2)" }}>Toplam (USD stable eq.)</div>
        <div style={{ fontSize: 22, fontWeight: 600 }}>
          ${(totals.stable_usd_equivalent ?? 0).toLocaleString()}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: "var(--fg-2)" }}>Bağlantı</div>
        <div>{groups.length}</div>
      </div>
      {errors > 0 && (
        <div style={{ color: "var(--accent-err)" }}>Hata: {errors}</div>
      )}
      <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--fg-2)" }}>
        {lastFetched ? `Son: ${new Date(lastFetched).toLocaleTimeString()}` : ""}
      </div>
      <button onClick={() => load()}>Yenile</button>
    </div>
  );
}

function SourceFilter() {
  const credentials = useExchangeStore((s) => s.credentials);
  const selected = usePortfolioStore((s) => s.selectedCredentialIds);
  const setSel = usePortfolioStore((s) => s.setSelectedCredentialIds);
  if (credentials.length === 0) return null;
  const isAll = selected === null;
  const toggle = (id: string) => () => {
    if (isAll) {
      setSel([id]);
    } else {
      const cur = new Set(selected);
      if (cur.has(id)) cur.delete(id); else cur.add(id);
      setSel(cur.size === credentials.length || cur.size === 0 ? null : Array.from(cur));
    }
  };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "6px 16px" }}>
      <button onClick={() => setSel(null)} aria-pressed={isAll}
              style={{ opacity: isAll ? 1 : 0.55 }}>Hepsi</button>
      {credentials.map((c) => {
        const active = isAll || selected?.includes(c.id);
        return (
          <button key={c.id} onClick={toggle(c.id)} aria-pressed={!!active}
                  style={{ opacity: active ? 1 : 0.55, fontSize: 11 }}>
            {c.exchange_id}:{c.account_label}
          </button>
        );
      })}
    </div>
  );
}

function CredentialGroup({ g }: { g: PortfolioGroup }) {
  if (g.error) {
    return (
      <div style={{ padding: 12, borderBottom: "1px solid var(--border-1)" }}>
        <strong>{g.exchange_id}:{g.account_label}</strong>
        <div style={{ color: "var(--accent-err)" }}>{g.error}</div>
      </div>
    );
  }
  return (
    <div style={{ padding: 12, borderBottom: "1px solid var(--border-1)" }}>
      <div style={{ display: "flex", gap: 16 }}>
        <strong>{g.exchange_id}:{g.account_label}</strong>
        {g.account && (
          <span>
            {g.account.equity.toFixed(2)} {g.account.currency}
            <span style={{ color: "var(--fg-2)" }}> ({g.account.cash.toFixed(2)} cash)</span>
          </span>
        )}
      </div>
      {g.positions.length > 0 && (
        <table style={{ width: "100%", marginTop: 6, fontSize: 12 }}>
          <thead>
            <tr style={{ color: "var(--fg-2)" }}>
              <th align="left">Symbol</th><th align="right">Qty</th>
              <th align="right">Entry</th><th align="right">Mark</th>
              <th align="right">PnL</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {g.positions.map((p, i) => (
              <tr key={`${p.symbol}-${i}`}>
                <td>{p.symbol}</td>
                <td align="right">{p.quantity}</td>
                <td align="right">{p.entry_price ?? "-"}</td>
                <td align="right">{p.current_price ?? "-"}</td>
                <td align="right" style={{
                  color: (p.unrealized_pnl ?? 0) >= 0 ? "var(--accent-ok)" : "var(--accent-err)",
                }}>
                  {(p.unrealized_pnl ?? 0).toFixed(2)}
                </td>
                <td align="right">
                  {g.permissions.includes("trade") && (
                    <button
                      onClick={() => useTradingStore.getState().closePosition(
                        `${g.exchange_id}:${g.credential_id}`,
                        p.symbol,
                        (p.side as "buy" | "sell"),
                        p.quantity,
                        g.account_label,
                      )}
                    >
                      Close
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {g.orders.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary>Açık emirler ({g.orders.length})</summary>
          <table style={{ width: "100%", fontSize: 12, marginTop: 4 }}>
            <thead>
              <tr style={{ color: "var(--fg-2)" }}>
                <th align="left">Symbol</th><th>Side</th><th align="right">Qty</th>
                <th align="right">Type</th><th align="right">Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {(g.orders as Array<Record<string, unknown>>).map((o, i) => (
                <tr key={String(o.id ?? i)}>
                  <td>{String(o.symbol ?? "-")}</td>
                  <td>{String(o.side ?? "-")}</td>
                  <td align="right">{String(o.quantity ?? "-")}</td>
                  <td align="right">{String(o.order_type ?? "-")}</td>
                  <td align="right">{String(o.status ?? "-")}</td>
                  <td align="right">
                    {g.permissions.includes("trade") && (
                      <button
                        onClick={() => useTradingStore.getState().cancelOrder(
                          `${g.exchange_id}:${g.credential_id}`,
                          String(o.id ?? ""),
                        )}
                      >
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {g.permissions.includes("trade") && (
        <OrderTicket
          credentialId={g.credential_id}
          brokerName={`${g.exchange_id}:${g.credential_id}`}
          accountLabel={g.account_label}
        />
      )}
    </div>
  );
}

export function PORTPane({ code }: FunctionPaneProps) {
  const portfolioGroups = usePortfolioStore((s) => s.groups);
  const credentialsCount = useExchangeStore((s) => s.credentials.length);
  const loadPortfolio = usePortfolioStore((s) => s.loadPortfolio);
  const loadCredentials = useExchangeStore((s) => s.loadCredentials);

  useEffect(() => {
    loadCredentials();
    loadPortfolio();
    const t = setInterval(() => loadPortfolio(), 30_000);
    return () => clearInterval(t);
  }, [loadPortfolio, loadCredentials]);

  const hasAnyCredential = credentialsCount > 0;
  const aggregateSection = !hasAnyCredential ? (
    <div style={{ padding: 24, color: "var(--fg-2)" }}>
      Bağlı borsa yok. <strong>Connect Exchange</strong> üzerinden bir bağlantı ekle
      (/CONN), portföyün burada görünsün.
    </div>
  ) : (
    <>
      <AggregateHeader />
      <SourceFilter />
      {portfolioGroups.map((g) => (
        <CredentialGroup key={g.credential_id} g={g} />
      ))}
    </>
  );

  const { state, data, error, refetch } = useFunction<PortData>({ code });
  const positions = useMemo(() => data?.data?.positions ?? [], [data?.data?.positions]);
  const totals = data?.data?.totals;
  const payloadStatus = data?.status ?? data?.data?.status;
  const [live, setLive] = useState<Record<string, { price: number; ts: number }>>({});
  const [streamStatus, setStreamStatus] = useState<Record<string, StreamStatus>>({});
  const [closePreview, setClosePreview] = useState<CloseResponse | null>(null);
  const [closeError, setCloseError] = useState<string | null>(null);
  const [busySymbol, setBusySymbol] = useState<string | null>(null);

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

  const utcNow = new Date().toISOString().slice(11, 16);
  const pnlValue = liveTotals?.unrealized_pnl ?? 0;
  const pnlTone: "positive" | "negative" | "neutral" =
    pnlValue > 0 ? "positive" : pnlValue < 0 ? "negative" : "neutral";
  const pnlPct =
    liveTotals?.cost_basis && liveTotals.cost_basis !== 0
      ? (pnlValue / Math.abs(liveTotals.cost_basis)) * 100
      : null;
  const positionCount = liveTotals?.n_positions ?? positions.length;
  const liveProvider = data?.sources?.[0] ?? "—";

  const body =
    state === "loading" || state === "idle" ? (
      <div className="skeleton-stack">
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
        utcNow={utcNow}
        pnlTone={pnlTone}
        pnlPct={pnlPct}
        onPreviewClose={previewClose}
        onClosePosition={closePosition}
      />
    );

  return (
    <div className="showme-port showme-port-motion port-pane-host">
      {aggregateSection}
      <h2 className="u-sr-only">{code} — Portfolio</h2>
      <Pane>
        <PaneHeader
          code={code}
          title="Portfolio"
          subtitle={`${positions.length} position(s) · ${liveProvider}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {positionCount} pos
              </Pill>
              <Pill
                tone={liveCount > 0 ? "positive" : "muted"}
                variant="soft"
                withDot={liveCount > 0}
              >
                {liveCount > 0 ? `LIVE · ${liveCount}` : "OFFLINE"}
              </Pill>
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
  utcNow,
  pnlTone,
  pnlPct,
  onPreviewClose,
  onClosePosition,
}: {
  positions: Position[];
  totals?: PortData["totals"];
  byClass?: Record<string, number>;
  closePreview: CloseResponse | null;
  closeError: string | null;
  busySymbol: string | null;
  utcNow: string;
  pnlTone: "positive" | "negative" | "neutral";
  pnlPct: number | null;
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
    <div className="showme-port__view showme-card-reveal port-view">
      <h3 className="u-sr-only">Portfolio KPI ribbon</h3>
      {/* Top KPI ribbon — Bloomberg-grade 4-stat strip */}
      <div className="showme-port__kpi-grid port-kpi-grid">
        <StatCard
          label="Market value"
          value={fmt$(totalMV)}
          caption={`AS OF ${utcNow} UTC`}
          trend={makeTrend(7)}
          tone="neutral"
        />
        <StatCard
          label="Cost basis"
          value={fmt$(totals?.cost_basis)}
          caption={`AS OF ${utcNow} UTC`}
          trend={makeTrend(13)}
          tone="neutral"
        />
        <StatCard
          label="Unrealized P&L"
          value={<ChangeText value={totals?.unrealized_pnl ?? 0} prefix="$" digits={0} />}
          caption={`AS OF ${utcNow} UTC`}
          delta={pnlPct ?? undefined}
          deltaFormat="percent"
          trend={makeTrend(21)}
          tone={pnlTone}
        />
        <StatCard
          label="Cash"
          value={fmt$(totals?.cash)}
          caption={`AS OF ${utcNow} UTC`}
          trend={makeTrend(29)}
          tone="neutral"
        />
      </div>

      {/* Asset class progress strip */}
      <Card className="showme-port__asset-card showme-card-reveal" variant="elev-2">
        <CardHeader
          trailing={
            <Pill tone="accent" variant="soft" withDot={false}>
              {Object.keys(cardClasses).length} classes
            </Pill>
          }
        >
          <h3 className="welcome-grid__sub-h3">By asset class</h3>
        </CardHeader>
        <CardBody>
          <div className="showme-port__asset-grid port-asset-grid">
            {Object.entries(cardClasses).map(([cls, mv]) => (
              <AssetClassCard key={cls} cls={cls} mv={mv} totalMV={totalMV} />
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

function AssetClassCard({
  cls,
  mv,
  totalMV,
}: {
  cls: string;
  mv: number;
  totalMV: number;
}) {
  const share = totalMV > 0 ? Math.max(0, Math.min(1, mv / totalMV)) : 0;
  const pct = share * 100;
  return (
    <div className="showme-port__class-card showme-card-reveal port-class-card">
      <span
        aria-hidden
        className="port-class-card__bg"
        style={{ ["--u-pct" as string]: `${pct}%` }}
      />
      <div className="port-class-card__caption">{cls}</div>
      <div className="port-class-card__value">
        <span
          key={`${cls}-mv-${mv}`}
          className={liveCellClass("neutral")}
        >
          {fmt$(mv)}
        </span>
      </div>
      {totalMV > 0 && (
        <div className="port-class-card__share">{pct.toFixed(1)}%</div>
      )}
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
          className="u-symbol-link"
        >
          {p.symbol}
        </button>
      ),
    },
    {
      key: "asset_class",
      header: "Class",
      width: 86,
      render: (p) =>
        p.asset_class ? (
          <Pill tone="muted" variant="soft" withDot={false}>
            {p.asset_class}
          </Pill>
        ) : (
          "—"
        ),
    },
    {
      key: "quantity",
      header: "Qty",
      numeric: true,
      width: 90,
      render: (p) => (p.quantity != null ? fmtNum(p.quantity) : "—"),
    },
    {
      key: "avg_cost",
      header: "Avg cost",
      numeric: true,
      width: 96,
      render: (p) => (p.avg_cost != null ? `$${p.avg_cost.toFixed(2)}` : "—"),
    },
    {
      key: "last",
      header: "Last",
      numeric: true,
      width: 96,
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
      width: 122,
      render: (p) => {
        const v = p.unrealized_pnl;
        if (v == null || !Number.isFinite(v))
          return <span className="u-text-mute">—</span>;
        return (
          <span key={liveMotionKey(p, "unrealized_pnl")}>
            <DeltaChip value={v} format="currency" fractionDigits={0} />
          </span>
        );
      },
    },
    {
      key: "weight",
      header: "%",
      numeric: true,
      width: 88,
      render: (p) => <WeightFill pct={p.weight != null ? p.weight * 100 : null} />,
    },
    {
      key: "actions",
      header: "Actions",
      width: 154,
      render: (p) => {
        const busy = busySymbol === p.symbol;
        return (
          <div className="port-action-row">
            <button
              type="button"
              className="btn btn--ghost port-action-btn"
              disabled={busy}
              onClick={() => onPreviewClose(p)}
              title="Preview the local paper close order without changing state"
            >
              Preview
            </button>
            <button
              type="button"
              className="btn btn--ghost port-action-btn"
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

function WeightFill({ pct }: { pct: number | null }) {
  if (pct == null || !Number.isFinite(pct))
    return <span className="u-text-mute">—</span>;
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <span className="port-weight">
      <span
        aria-hidden
        className="port-weight__track"
        style={{ ["--u-empty" as string]: `${100 - clamped}%` }}
      />
      <span className="port-weight__label">{clamped.toFixed(1)}%</span>
    </span>
  );
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
      <div className="showme-port__close-panel showme-card-reveal port-close-panel">
        <div className="port-close-panel__head port-close-panel__head--error">
          <strong>Close failed</strong>
        </div>
        <span>{error}</span>
      </div>
    );
  }
  if (!preview) return null;
  const r = preview.record;
  return (
    <div className="showme-port__close-panel showme-card-reveal port-close-panel">
      <div className="port-close-panel__head">
        <strong>{preview.dry_run ? "Close preview" : "Position closed"}</strong>
        <Pill
          tone={preview.dry_run ? "muted" : "positive"}
          variant="soft"
          withDot={!preview.dry_run}
        >
          remaining {preview.remaining_positions}
        </Pill>
      </div>
      <div className="port-close-panel__kpi-grid">
        <Kpi label="Symbol" value={r.symbol} />
        <Kpi label="Quantity" value={fmtNum(r.quantity)} />
        <Kpi label="Exit" value={r.exit_price != null ? `$${r.exit_price.toFixed(2)}` : "—"} />
        <Kpi label="Notional" value={fmt$(r.market_value)} />
        <Kpi
          label="Realized P&L"
          value={<ChangeText value={r.realized_pnl ?? 0} prefix="$" digits={0} />}
        />
      </div>
      {preview.dry_run ? (
        <span className="port-close-panel__hint">
          Preview is non-destructive. Close requires a confirmation dialog and writes a legacy skip marker.
        </span>
      ) : null}
    </div>
  );
}

function Kpi({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="showme-port__kpi showme-card-reveal u-kpi-surface">
      <div className="port-class-card__caption">{label}</div>
      <div className="port-class-card__value">{value}</div>
    </div>
  );
}

function liveMotionKey(position: Position, key: keyof Position): string {
  const stamp = Number(position._live_ts ?? 0);
  const raw = position[key];
  const value = typeof raw === "number" ? raw : String(raw ?? "na");
  return `${position.symbol}-${String(key)}-${stamp}-${value}`;
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
  // Routed through sidecarFetch so the auth header (X-ShowMe-Token) and the
  // shared port-discovery / health-wait pipeline both apply. See ARCH-05 P2.
  return sidecarFetch<CloseResponse>(
    `/api/portfolio/positions/${encodeURIComponent(position.symbol)}/close`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        dry_run: dryRun,
        exit_price: Number.isFinite(exit) && exit > 0 ? exit : undefined,
        reason: dryRun ? "ui_preview" : "ui_close",
      }),
    },
  );
}
