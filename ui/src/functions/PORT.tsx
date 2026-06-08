/**
 * PORT — Bloomberg-grade portfolio analytics.
 *
 * Round-redesign: KPI ribbon (StatCard) + asset-class progress strip + dense
 * position table with DeltaChip P&L pills, accent symbol links, weight
 * progress fills, and ghost action buttons. All colors token-driven.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
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
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { subscribeQuote, type StreamStatus } from "@/lib/stream";
import { navigate } from "@/lib/router";
import { sidecarFetch } from "@/lib/sidecar";
import { confirmAction } from "@/lib/confirm";
import {
  formatCurrency,
  formatMissing,
  formatNumber,
  formatPercent,
  formatPrice,
} from "@/lib/format";
import { usePortfolioStore, type PortfolioGroup } from "@/lib/portfolio-store";
import { useExchangeStore } from "@/lib/exchange-store";
import {
  normalizeSide,
  useTradingStore,
  type LastResult,
} from "@/lib/trading-store";
import { toast } from "@/lib/toast";
import { OrderTicket, ConfirmModal as TradingConfirmModal } from "./OrderTicket";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface Position {
  symbol: string;
  asset_class?: string;
  quantity?: number;
  avg_cost?: number | null;
  // UA-HIGH-10: some backend exchange adapters emit `entry_price` /
  // `current_price` instead of `avg_cost` / `last`. Keep both names in the
  // type and use the helpers below at the call sites. `null` is permitted
  // because PortfolioPosition (the upstream aggregator shape) declares
  // these fields as nullable.
  entry_price?: number | null;
  last?: number | null;
  current_price?: number | null;
  market_value?: number;
  unrealized_pnl?: number;
  weight?: number;
  currency?: string;
  [key: string]: unknown;
}

// UA-HIGH-10: tolerant accessors for cross-broker payload drift. Narrow
// parameter shape so they work for both the strict `Position` declared in
// this file AND the upstream `PortfolioPosition` (which declares nullable
// number fields) without a cast at every call site.
type PriceFields = {
  entry_price?: number | null;
  avg_cost?: number | null;
  current_price?: number | null;
  last?: number | null;
};
function positionEntryPrice(p: PriceFields): number | undefined {
  const v = p.entry_price ?? p.avg_cost;
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}
function positionCurrentPrice(p: PriceFields): number | undefined {
  const v = p.current_price ?? p.last;
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
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

function PortfolioExchangeDeck({ hasAnyCredential }: { hasAnyCredential: boolean }) {
  const groups = usePortfolioStore((s) => s.groups);
  const loading = usePortfolioStore((s) => s.loading);
  const aggregateError = usePortfolioStore((s) => s.error);

  if (!hasAnyCredential) {
    return <PortfolioOnboarding />;
  }

  return (
    <section className="port-exchange-deck" aria-label="Connected exchange portfolio">
      <PortfolioCommandBar />
      <SourceFilter />
      {aggregateError ? (
        <div className="port-alert port-alert--error">{aggregateError}</div>
      ) : null}
      {groups.length === 0 ? (
        <div className="port-empty-terminal">
          {loading ? (
            <>
              <Skeleton height={20} width="28%" />
              <Skeleton height={78} />
            </>
          ) : (
            <span>Broker snapshot is empty.</span>
          )}
        </div>
      ) : (
        <div className="port-accounts-grid">
          {groups.map((g) => (
            <CredentialGroup key={g.credential_id} g={g} />
          ))}
        </div>
      )}
    </section>
  );
}

function PortfolioOnboarding() {
  return (
    <section className="port-empty-terminal port-empty-terminal--action">
      <div className="port-empty-terminal__copy">
        <strong>Connect Exchange</strong>
        <span>Bağlı borsa yok. /CONN üzerinden read-only veya trade izinli bağlantı ekle.</span>
      </div>
      <button type="button" className="btn btn--accent" onClick={() => navigate("/fn/CONN")}>
        Open CONN
      </button>
    </section>
  );
}

function PortfolioCommandBar() {
  const totals = usePortfolioStore((s) => s.totals);
  const lastFetched = usePortfolioStore((s) => s.lastFetchedAt);
  const load = usePortfolioStore((s) => s.loadPortfolio);
  const loading = usePortfolioStore((s) => s.loading);
  const groups = usePortfolioStore((s) => s.groups);
  const credentials = useExchangeStore((s) => s.credentials);
  const errors = groups.filter((g) => g.error).length;
  const accountEquity = groups.reduce((sum, g) => sum + (g.account?.equity ?? 0), 0);
  const positions = groups.reduce((sum, g) => sum + g.positions.length, 0);
  const orders = groups.reduce((sum, g) => sum + g.orders.length, 0);
  const currencies = Object.keys(totals.equity_by_currency ?? {});

  return (
    <div className="port-command-bar">
      <div className="port-command-bar__hero">
        <span className="port-label">Net liquidation</span>
        <strong>{formatCurrency(totals.stable_usd_equivalent ?? 0, { compact: true })}</strong>
        <span className="port-subtle">
          {currencies.length ? currencies.join(" / ") : "USD stable eq."}
        </span>
      </div>
      <div className="port-command-bar__stats">
        <AccountStat label="Connections" value={`${groups.length}/${credentials.length}`} />
        <AccountStat label="Positions" value={formatNumber(positions)} />
        <AccountStat label="Open orders" value={formatNumber(orders)} />
        <AccountStat label="Broker equity" value={formatCurrency(accountEquity, { compact: true })} />
        <AccountStat
          label="Status"
          value={errors ? `${errors} error` : loading ? "syncing" : "ready"}
          tone={errors ? "negative" : loading ? "warn" : "positive"}
        />
      </div>
      <div className="port-command-bar__actions">
        <span className="port-subtle">
          {lastFetched ? `Last ${new Date(lastFetched).toLocaleTimeString()}` : "Not fetched"}
        </span>
        <button className="btn btn--ghost port-icon-btn" type="button" onClick={() => load()} disabled={loading} title="Refresh portfolio">
          {loading ? "..." : "↻"}
        </button>
      </div>
    </div>
  );
}

function AccountStat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "positive" | "negative" | "warn";
}) {
  return (
    <div className={`port-account-stat port-account-stat--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SourceFilter() {
  const credentials = useExchangeStore((s) => s.credentials);
  const selected = usePortfolioStore((s) => s.selectedCredentialIds);
  const setSel = usePortfolioStore((s) => s.setSelectedCredentialIds);
  const includeOrders = usePortfolioStore((s) => s.includeOrders);
  const setIncludeOrders = usePortfolioStore((s) => s.setIncludeOrders);
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
    <div className="port-source-filter">
      <button
        type="button"
        onClick={() => setSel(null)}
        aria-pressed={isAll}
        className={`port-source-chip${isAll ? " port-source-chip--active" : ""}`}
      >
        All
      </button>
      {credentials.map((c) => {
        const active = isAll || selected?.includes(c.id);
        return (
          <button
            key={c.id}
            type="button"
            onClick={toggle(c.id)}
            aria-pressed={!!active}
            className={`port-source-chip${active ? " port-source-chip--active" : ""}`}
          >
            {c.exchange_id}:{c.account_label}
          </button>
        );
      })}
      <span className="port-source-filter__divider" />
      <button
        type="button"
        onClick={() => setIncludeOrders(!includeOrders)}
        aria-pressed={includeOrders}
        data-testid="port-include-orders-toggle"
        title="Açık emirleri de portföy fetch'ine dahil et"
        className={`port-source-chip${includeOrders ? " port-source-chip--active" : ""}`}
      >
        {includeOrders ? "Orders included" : "Orders hidden"}
      </button>
    </div>
  );
}

/**
 * Toast bridge — fires once per new `lastResult` for close/cancel kinds.
 * The submit kind keeps the inline OrderTicket banner (legacy). PORT renders
 * its own toast because the original implementation only showed the result
 * inside OrderTicket, which leaves PORT users staring at a silent button.
 *
 * Sentinel ref pattern avoids re-firing on every render: zustand subscribe
 * gives us the new lastResult identity, and we only fire when the identity
 * differs from what we already toasted.
 */
function useTradingResultToasts() {
  useEffect(() => {
    let last: LastResult | null = null;
    const fire = (r: LastResult | null) => {
      if (!r || r === last) return;
      last = r;
      if (r.kind !== "close" && r.kind !== "cancel") return;
      if (r.ok) {
        const title =
          r.kind === "close"
            ? `Pozisyon kapatıldı${r.symbol ? `: ${r.symbol}` : ""}`
            : `Emir iptal edildi${r.symbol ? `: ${r.symbol}` : r.orderId ? ` (${r.orderId})` : ""}`;
        toast.success(title);
      } else {
        const title =
          r.kind === "close" ? "Pozisyon kapatılamadı" : "Emir iptal edilemedi";
        toast.error(title, r.error ?? "Bilinmeyen hata");
      }
    };
    // Fire immediately for any pre-existing state, then subscribe.
    fire(useTradingStore.getState().lastResult);
    const unsub = useTradingStore.subscribe((s) => {
      fire(s.lastResult);
    });
    return () => unsub();
  }, []);
}

/**
 * BUG #12 — mirror of the backend `_STABLE_TO_USD` allowlist.  Balances in
 * any currency NOT in this set are excluded from the aggregate USD total;
 * the UI surfaces this with a "USD'ye dönüştürülmedi" badge so users don't
 * mistakenly think a EUR/GBP/TRY group is being counted.
 */
const STABLE_USD_CURRENCIES = new Set([
  "USD", "USDT", "USDC", "DAI", "BUSD", "TUSD",
]);

export function isStableUsd(currency: string | undefined | null): boolean {
  if (!currency) return false;
  return STABLE_USD_CURRENCIES.has(currency.toUpperCase());
}

function NonStableCurrencyBadge({ currency }: { currency: string }) {
  return (
    <span
      data-testid="port-non-stable-badge"
      title="Bu hesabın bakiyesi toplam USD'ye eklenmedi."
      className="port-non-stable-badge"
    >
      {currency} (USD'ye dönüştürülmedi)
    </span>
  );
}

function CredentialGroup({ g }: { g: PortfolioGroup }) {
  if (g.error) {
    return (
      <section className="port-account-card port-account-card--error">
        <header className="port-account-card__head">
          <strong>{g.exchange_id}:{g.account_label}</strong>
          <Pill tone="negative" variant="soft">error</Pill>
        </header>
        <div className="port-alert port-alert--error">{g.error}</div>
      </section>
    );
  }
  const ccy = g.account?.currency;
  const showNonStableBadge = Boolean(
    ccy && !isStableUsd(ccy) && g.account && g.account.equity !== 0,
  );
  return (
    <section className="port-account-card">
      <header className="port-account-card__head">
        <div className="port-account-card__identity">
          <strong>{g.exchange_id}:{g.account_label}</strong>
          <span>{g.permissions.includes("trade") ? "read + trade" : "read-only"}</span>
        </div>
        <div className="port-account-card__pills">
          <Pill tone={g.permissions.includes("trade") ? "warn" : "muted"} variant="soft" withDot={false}>
            {g.permissions.includes("trade") ? "trade" : "read"}
          </Pill>
          <Pill tone={g.positions.length ? "positive" : "muted"} variant="soft" withDot={g.positions.length > 0}>
            {g.positions.length} pos
          </Pill>
        </div>
      </header>
      {g.account && (
        <div className="port-account-card__metrics">
          <AccountStat
            label="Equity"
            value={`${formatNumber(g.account.equity, 2)} ${g.account.currency}`}
            tone={g.account.equity > 0 ? "positive" : g.account.equity < 0 ? "negative" : "neutral"}
          />
          <AccountStat label="Cash" value={`${formatNumber(g.account.cash, 2)} ${g.account.currency}`} />
          <AccountStat label="Buying power" value={`${formatNumber(g.account.buying_power, 2)} ${g.account.currency}`} />
          {showNonStableBadge && ccy ? <NonStableCurrencyBadge currency={ccy} /> : null}
        </div>
      )}
      {g.positions.length > 0 && (
        <table className="port-broker-table">
          <thead>
            <tr>
              <th align="left">Symbol</th>
              <th align="right">Qty</th>
              <th align="right">Entry</th>
              <th align="right">Mark</th>
              <th align="right">Notional</th>
              <th align="right">PnL</th>
              <th align="right">Action</th>
            </tr>
          </thead>
          <tbody>
            {g.positions.map((p, i) => {
              // UA-HIGH-10 + UA-HIGH-26: tolerant field accessors AND a
              // group-scoped unique key (multiple credentials can hold the
              // same symbol — `${symbol}-${i}` collides at the React level).
              const entry = positionEntryPrice(p);
              const current = positionCurrentPrice(p);
              const qty = Number(p.quantity) || 0;
              const notional = qty * (current ?? entry ?? 0);
              return (
              <tr key={`${g.credential_id ?? "g"}-${p.symbol}-${i}`}>
                <td>{p.symbol}</td>
                <td align="right" className="terminal-grid-numeric">{formatNumber(p.quantity, 6)}</td>
                <td align="right" className="terminal-grid-numeric">
                  {entry != null ? formatPrice(entry) : formatMissing}
                </td>
                <td align="right" className="terminal-grid-numeric">
                  {current != null ? formatPrice(current) : formatMissing}
                </td>
                <td align="right" className="terminal-grid-numeric">{formatCurrency(notional, { compact: true })}</td>
                <td align="right" className="terminal-grid-numeric">
                  <DeltaChip value={p.unrealized_pnl ?? 0} format="currency" fractionDigits={2} />
                </td>
                <td align="right">
                  {g.permissions.includes("trade") && (
                    <button
                      type="button"
                      onClick={() => useTradingStore.getState().closePosition(
                        `${g.exchange_id}:${g.credential_id}`,
                        p.symbol,
                        normalizeSide(p.side),
                        p.quantity,
                        g.account_label,
                      )}
                      data-testid={`port-broker-close-${p.symbol}`}
                      title="Gerçek brokerda pozisyonu kapatır (irreversible)"
                      className="btn btn--ghost port-danger-btn"
                    >
                      Close
                    </button>
                  )}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {g.orders.length > 0 && (
        <details className="port-orders-panel">
          <summary>Açık emirler ({g.orders.length})</summary>
          <table className="port-broker-table">
            <thead>
              <tr>
                <th align="left">Symbol</th><th>Side</th><th align="right">Qty</th>
                <th align="right">Type</th><th align="right">Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {(g.orders as Array<Record<string, unknown>>).map((o, i) => (
                <tr key={String(o.id ?? i)}>
                  <td>{String(o.symbol ?? formatMissing)}</td>
                  <td>{String(o.side ?? formatMissing)}</td>
                  <td align="right">{String(o.quantity ?? formatMissing)}</td>
                  <td align="right">{String(o.order_type ?? formatMissing)}</td>
                  <td align="right">{String(o.status ?? formatMissing)}</td>
                  <td align="right">
                    {g.permissions.includes("trade") && (
                      <button
                        type="button"
                        onClick={() => useTradingStore.getState().requestCancel(
                          `${g.exchange_id}:${g.credential_id}`,
                          String(o.id ?? ""),
                          g.account_label,
                          o.symbol != null ? String(o.symbol) : undefined,
                        )}
                        data-testid={`port-order-cancel-${String(o.id ?? "")}`}
                        title="Emri iptal eder — onay gerekli"
                        className="btn btn--ghost port-danger-btn"
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
        <div className="port-ticket-shell">
          <OrderTicket
            credentialId={g.credential_id}
            brokerName={`${g.exchange_id}:${g.credential_id}`}
            accountLabel={g.account_label}
          />
        </div>
      )}
    </section>
  );
}

export function PORTPane({ code }: FunctionPaneProps) {
  const portfolioGroups = usePortfolioStore((s) => s.groups);
  const credentialsCount = useExchangeStore((s) => s.credentials.length);
  const loadPortfolio = usePortfolioStore((s) => s.loadPortfolio);
  const loadCredentials = useExchangeStore((s) => s.loadCredentials);
  const pendingConfirm = useTradingStore((s) => s.pendingConfirm);

  // Surface close/cancel results as toasts — without this hook, PORT's Close
  // and Cancel buttons fail silently (QA-2026-05-23).
  useTradingResultToasts();

  // Bundle D / PERF-04. Pause the 30s aggregate-portfolio poll while the tab
  // is hidden. The browser was hammering the sidecar even when the user was
  // off in another desktop space; resume on visibilitychange.
  const portfolioTick = useVisibilityTick(30_000);
  useEffect(() => {
    loadCredentials();
    loadPortfolio();
  }, [loadPortfolio, loadCredentials, portfolioTick]);

  const hasAnyCredential = credentialsCount > 0;

  const { state, data, error, refetch } = useFunction<PortData>({ code });
  const positions = useMemo(() => data?.data?.positions ?? [], [data?.data?.positions]);
  const totals = data?.data?.totals;
  const payloadStatus = data?.status ?? data?.data?.status;
  const [live, setLive] = useState<Record<string, { price: number; ts: number }>>({});
  const [streamStatus, setStreamStatus] = useState<Record<string, StreamStatus>>({});
  const [closePreview, setClosePreview] = useState<CloseResponse | null>(null);
  const [closeError, setCloseError] = useState<string | null>(null);
  const [busySymbol, setBusySymbol] = useState<string | null>(null);

  // Bundle D / SOCKET-01. The previous effect listed `positions` directly,
  // so every poll cycle (new array identity from `useFunction`) tore down
  // every WebSocket and reopened the lot — a reconnect storm that hammered
  // the sidecar each minute even when no actual symbol set had changed.
  // Derive a stable signature from the *unique sorted symbol set* and key
  // the subscribe effect off that; identity changes on the parent array no
  // longer matter, only set membership does.
  const symbolsKey = useMemo(
    () => {
      const seen = new Set<string>();
      for (const p of positions) {
        if (p.symbol) seen.add(p.symbol);
      }
      return Array.from(seen).sort().join(",");
    },
    [positions],
  );

  useEffect(() => {
    if (!symbolsKey) return;
    const symbols = symbolsKey.split(",").filter(Boolean);
    const handles = symbols.map((sym) =>
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
  }, [symbolsKey]);

  const enriched = useMemo<Position[]>(() => {
    const overlaid = positions.map((p) => {
      const tick = live[p.symbol];
      if (!tick) return p;
      const last = tick.price;
      const qty = Number(p.quantity) || 0;
      const cost = positionEntryPrice(p) ?? 0;
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
      (s, p) => s + (Number(p.quantity) || 0) * (positionEntryPrice(p) ?? 0),
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

  // DATA-SUFFICIENCY (P4): the PORT function only returns *local paper*
  // positions, which are empty for most users. Connected-broker positions
  // arrive via the portfolio store (already fetched for the account cards).
  // When the main table would otherwise be empty, surface those real broker
  // positions here so a user with connected brokers never sees a false
  // "Empty portfolio". We reuse data already in memory — nothing fabricated.
  const brokerPositions = useMemo<Position[]>(() => {
    if (enriched.length > 0) return [];
    const rows: Position[] = [];
    for (const g of portfolioGroups) {
      for (const bp of g.positions) {
        const entry = positionEntryPrice(bp);
        const current = positionCurrentPrice(bp);
        const qty = Number(bp.quantity) || 0;
        const mark = current ?? entry ?? 0;
        const market_value = qty * mark;
        rows.push({
          symbol: bp.symbol,
          asset_class: "CRYPTO",
          quantity: qty,
          entry_price: entry ?? null,
          current_price: current ?? null,
          market_value,
          unrealized_pnl:
            typeof bp.unrealized_pnl === "number"
              ? bp.unrealized_pnl
              : (mark - (entry ?? mark)) * qty,
          currency: g.account?.currency,
          _broker: `${g.exchange_id}:${g.account_label}`,
        });
      }
    }
    const totalMv = rows.reduce((s, p) => s + (Number(p.market_value) || 0), 0);
    return rows.map((p) => ({
      ...p,
      weight: totalMv > 0 ? (Number(p.market_value) || 0) / totalMv : undefined,
    }));
  }, [enriched.length, portfolioGroups]);

  // The view shows local positions when present, else surfaced broker rows.
  const viewPositions = enriched.length > 0 ? enriched : brokerPositions;
  const brokerSurfaced = enriched.length === 0 && brokerPositions.length > 0;
  const viewTotals = brokerSurfaced
    ? {
        market_value: brokerPositions.reduce((s, p) => s + (Number(p.market_value) || 0), 0),
        cost_basis: brokerPositions.reduce(
          (s, p) => s + (Number(p.quantity) || 0) * (positionEntryPrice(p) ?? 0),
          0,
        ),
        unrealized_pnl: brokerPositions.reduce((s, p) => s + (Number(p.unrealized_pnl) || 0), 0),
        n_positions: brokerPositions.length,
      }
    : liveTotals;
  const viewClassBreakdown = brokerSurfaced
    ? aggregateByClass(brokerPositions)
    : classBreakdown;

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
    const px = Number(positionCurrentPrice(position) ?? positionEntryPrice(position) ?? 0);
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
  const pnlValue = viewTotals?.unrealized_pnl ?? 0;
  const pnlTone: "positive" | "negative" | "neutral" =
    pnlValue > 0 ? "positive" : pnlValue < 0 ? "negative" : "neutral";
  const pnlPct =
    viewTotals?.cost_basis && viewTotals.cost_basis !== 0
      ? (pnlValue / Math.abs(viewTotals.cost_basis)) * 100
      : null;
  const positionCount = viewTotals?.n_positions ?? positions.length;
  const liveProvider = data?.sources?.[0] ?? "—";

  const body =
    state === "loading" || state === "idle" ? (
      <div
        className="skeleton-stack"
        role="status"
        aria-busy="true"
        aria-live="polite"
        aria-label="Loading portfolio"
      >
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
    ) : viewPositions.length === 0 ? (
      <Empty
        title="Empty portfolio"
        body={
          data?.data?.next_actions?.[0] ??
          "No local positions are attached to this runtime. Connect a broker account or use Portfolio What-If to simulate trades."
        }
        icon="∅"
        action={
          <div style={{ display: "flex", gap: "8px" }}>
            <button type="button" className="btn btn--accent" onClick={() => navigate("/fn/CONN")}>
              Connect Broker
            </button>
            <button type="button" className="btn" onClick={() => navigate("/fn/PORT_WHATIF")}>
              Open What-If
            </button>
          </div>
        }
      />
    ) : (
      <>
        {brokerSurfaced ? (
          <div className="port-alert port-alert--info" data-testid="port-broker-surfaced-note">
            Showing live <strong>connected-broker</strong> positions (no local paper
            positions yet). These mirror the account cards above; close actions
            for them live in those cards. Use <em>Open What-If</em> to add paper
            positions.
          </div>
        ) : null}
        <PORTView
          positions={viewPositions}
          totals={viewTotals}
          byClass={viewClassBreakdown}
          closePreview={closePreview}
          closeError={closeError}
          busySymbol={busySymbol}
          utcNow={utcNow}
          pnlTone={pnlTone}
          pnlPct={pnlPct}
          brokerReadOnly={brokerSurfaced}
          onPreviewClose={previewClose}
          onClosePosition={closePosition}
        />
      </>
    );

  // Cancel + close confirmations come from the credential-group table buttons
  // (close-position) or the per-order Cancel button. The OrderTicket only
  // mounts inside trade-permitted credential groups, but the cancel flow can
  // fire on read+trade credentials that aren't currently showing the ticket
  // — so the modal needs a host at the PORT level.
  const orphanedConfirm =
    pendingConfirm &&
    (pendingConfirm.kind === "cancel" || pendingConfirm.kind === "close");

  return (
    <div className="showme-port showme-port-motion port-pane-host">
      {orphanedConfirm && (
        <TradingConfirmModal accountLabel={pendingConfirm.accountLabel} />
      )}
      <h2 className="u-sr-only">{code} — Portfolio</h2>
      <Pane>
        <PaneHeader
          code={code}
          title="Portfolio Terminal"
          subtitle={`${portfolioGroups.length} account(s) · ${positions.length} local position(s) · ${liveProvider}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {portfolioGroups.length} acct
              </Pill>
              <Pill tone="muted" variant="soft" withDot={false}>
                {positionCount} local
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
        <PaneBody className="port-pane-body">
          <PortfolioExchangeDeck hasAnyCredential={hasAnyCredential} />
          {body}
        </PaneBody>
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
  brokerReadOnly = false,
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
  brokerReadOnly?: boolean;
  onPreviewClose: (position: Position) => void;
  onClosePosition: (position: Position) => void;
}) {
  const cardClasses = byClass ?? aggregateByClass(positions);
  const totalMV = totals?.market_value ?? positions.reduce(
    (s, p) => s + (p.market_value ?? 0), 0,
  );
  const maxPosition = positions.reduce(
    (best, p) => ((p.weight ?? 0) > (best?.weight ?? -1) ? p : best),
    null as Position | null,
  );
  const topPositions = [...positions]
    .sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0))
    .slice(0, 5);

  // P5 — local column sort. DataGrid supports sortBy/sortDir/onSort but PORT
  // never wired them. Clicking a sortable header cycles desc → asc → off.
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"ascending" | "descending">("descending");
  const onSort = (key: string) => {
    if (sortBy !== key) {
      setSortBy(key);
      setSortDir("descending");
    } else if (sortDir === "descending") {
      setSortDir("ascending");
    } else {
      setSortBy(null); // third click clears the sort
    }
  };
  const sortedPositions = useMemo(() => {
    if (!sortBy) return positions;
    const accessor = (p: Position): number | undefined => {
      if (sortBy === "quantity") return p.quantity;
      if (sortBy === "avg_cost") return positionEntryPrice(p);
      if (sortBy === "last") return positionCurrentPrice(p);
      if (sortBy === "market_value") return p.market_value;
      if (sortBy === "unrealized_pnl") return p.unrealized_pnl;
      if (sortBy === "weight") return p.weight;
      return undefined;
    };
    const dir = sortDir === "ascending" ? 1 : -1;
    return [...positions].sort((a, b) => {
      const av = accessor(a);
      const bv = accessor(b);
      // Push missing values to the bottom regardless of direction.
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * dir;
    });
  }, [positions, sortBy, sortDir]);

  const cols = useMemo(
    () => positionColumns({ busySymbol, brokerReadOnly, onPreviewClose, onClosePosition }),
    [busySymbol, brokerReadOnly, onPreviewClose, onClosePosition],
  );
  return (
    <div className="showme-port__view showme-card-reveal port-view">
      <section className="port-terminal-summary" aria-label="Portfolio summary">
        <div className="port-terminal-summary__primary">
          <span className="port-label">Local analytics equity</span>
          <strong className="terminal-grid-numeric">{fmt$(totalMV)}</strong>
          <span className={`port-terminal-summary__pnl port-terminal-summary__pnl--${pnlTone}`}>
            <ChangeText value={totals?.unrealized_pnl ?? 0} prefix="$" digits={0} />
            {pnlPct != null ? <em>{formatPercent(pnlPct, { signed: true })}</em> : null}
          </span>
        </div>
        <div className="port-terminal-summary__tiles">
          <PortfolioMetric label="Cost basis" value={fmt$(totals?.cost_basis)} />
          <PortfolioMetric label="Cash" value={fmt$(totals?.cash)} />
          <PortfolioMetric label="Positions" value={formatNumber(positions.length)} />
          <PortfolioMetric
            label="Largest"
            value={maxPosition ? `${maxPosition.symbol} ${formatPercent((maxPosition.weight ?? 0) * 100)}` : formatMissing}
          />
        </div>
        {/* Honest real metric replaces the former seeded fake sparkline
            (DATA-HONESTY): no tick history is available to draw a true
            series, so we surface the genuine unrealized return vs cost
            basis instead of a synthetic squiggle that looked like data. */}
        <div
          className={`port-terminal-summary__return port-terminal-summary__return--${pnlTone}`}
          data-testid="port-return-badge"
        >
          <span className="port-label">Unrealized return</span>
          <strong className="terminal-grid-numeric">
            {pnlPct != null ? formatPercent(pnlPct, { signed: true, digits: 2 }) : formatMissing}
          </strong>
        </div>
      </section>

      <div className="port-workbench">
        <section className="port-positions-panel">
          <header className="port-section-head">
            <div>
              <h3>Positions</h3>
              <span>{positions.length} rows · as of {utcNow} UTC</span>
            </div>
            <Pill tone={Object.keys(cardClasses).length > 1 ? "accent" : "muted"} variant="soft" withDot={false}>
              {Object.keys(cardClasses).length} classes
            </Pill>
          </header>
          <DataGrid
            className="showme-port__grid showme-motion-grid port-main-grid"
            columns={cols}
            rows={sortedPositions}
            rowKey={(p, idx) => `${p.symbol}-${idx}`}
            rowClassName={(p, idx) =>
              [
                "showme-motion-grid__row",
                "showme-row-reveal",
                `showme-motion-grid__row--${Math.min(idx, 10)}`,
                p._live_ts ? "showme-motion-grid__row--live" : "",
              ].filter(Boolean).join(" ")
            }
            density="compact"
            ariaLabel="Portfolio positions"
            sortBy={sortBy ?? undefined}
            sortDir={sortBy ? sortDir : "none"}
            onSort={onSort}
          />
        </section>

        <aside className="port-risk-rail" aria-label="Portfolio risk and allocation">
          <section className="port-rail-panel">
            <header className="port-section-head port-section-head--compact">
              <h3>Allocation</h3>
            </header>
            <div className="port-allocation-stack">
              {Object.entries(cardClasses).map(([cls, mv]) => (
                <AssetClassCard key={cls} cls={cls} mv={mv} totalMV={totalMV} />
              ))}
            </div>
          </section>

          <section className="port-rail-panel">
            <header className="port-section-head port-section-head--compact">
              <h3>Concentration</h3>
            </header>
            <div className="port-concentration-list">
              {topPositions.map((p) => (
                <div key={p.symbol} className="port-concentration-row">
                  <span>{p.symbol}</span>
                  <WeightFill pct={p.weight != null ? p.weight * 100 : null} />
                </div>
              ))}
            </div>
          </section>

          {closePreview || closeError ? (
            <ClosePreviewPanel preview={closePreview} error={closeError} />
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function PortfolioMetric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="port-metric-tile">
      <span>{label}</span>
      <strong className="terminal-grid-numeric">{value}</strong>
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
          className={`${liveCellClass("neutral")} terminal-grid-numeric`}
        >
          {fmt$(mv)}
        </span>
      </div>
      {totalMV > 0 && (
        <div className="port-class-card__share terminal-grid-numeric">
          {formatPercent(pct, { digits: 1 })}
        </div>
      )}
    </div>
  );
}

function positionColumns({
  busySymbol,
  brokerReadOnly = false,
  onPreviewClose,
  onClosePosition,
}: {
  busySymbol: string | null;
  brokerReadOnly?: boolean;
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
          aria-label={`View ${p.symbol} details`}
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
      sortable: true,
      width: 90,
      render: (p) => (
        <span className="terminal-grid-numeric">
          {p.quantity != null ? formatNumber(p.quantity, 6) : formatMissing}
        </span>
      ),
    },
    {
      key: "avg_cost",
      header: "Entry",
      numeric: true,
      sortable: true,
      width: 96,
      render: (p) => (
        <span className="terminal-grid-numeric">
          {positionEntryPrice(p) != null
            ? `$${formatPrice(positionEntryPrice(p))}`
            : formatMissing}
        </span>
      ),
    },
    {
      key: "last",
      header: "Mark",
      numeric: true,
      sortable: true,
      width: 96,
      render: (p) => {
        const px = positionCurrentPrice(p);
        return px != null ? (
          <span
            key={liveMotionKey(p, "last")}
            className={`${liveCellClass("neutral")} terminal-grid-numeric`}
          >
            ${formatPrice(px)}
          </span>
        ) : (
          <span className="terminal-grid-numeric">{formatMissing}</span>
        );
      },
    },
    {
      key: "market_value",
      header: "MV",
      numeric: true,
      sortable: true,
      width: 110,
      render: (p) => (
        <span
          key={liveMotionKey(p, "market_value")}
          className={`${liveCellClass("neutral")} terminal-grid-numeric`}
        >
          {fmt$(p.market_value)}
        </span>
      ),
    },
    {
      key: "unrealized_pnl",
      header: "Unrl P&L",
      numeric: true,
      sortable: true,
      width: 122,
      render: (p) => {
        const v = p.unrealized_pnl;
        if (v == null || !Number.isFinite(v))
          return <span className="u-text-mute terminal-grid-numeric">—</span>;
        return (
          <span key={liveMotionKey(p, "unrealized_pnl")} className="terminal-grid-numeric">
            <DeltaChip value={v} format="currency" fractionDigits={0} />
          </span>
        );
      },
    },
    {
      key: "weight",
      header: "%",
      numeric: true,
      sortable: true,
      width: 88,
      render: (p) => <WeightFill pct={p.weight != null ? p.weight * 100 : null} />,
    },
    {
      key: "actions",
      header: "Actions",
      width: 154,
      render: (p) => {
        // Broker-surfaced rows are real exchange positions, not local paper —
        // the local paper close/preview would be misleading. Point users to
        // the account cards instead of showing inert buttons.
        if (brokerReadOnly) {
          return (
            <span className="u-text-mute" title="Manage this position in the account card above">
              broker
            </span>
          );
        }
        const busy = busySymbol === p.symbol;
        return (
          <div className="port-action-row">
            <button
              type="button"
              className="btn btn--ghost port-action-btn"
              disabled={busy}
              onClick={() => onPreviewClose(p)}
              title="Preview the local paper close order without changing state"
              data-testid={`port-paper-preview-${p.symbol}`}
            >
              Preview
            </button>
            <button
              type="button"
              className="btn btn--ghost port-action-btn"
              disabled={busy}
              onClick={() => onClosePosition(p)}
              title="Local paper engine close — writes a legacy skip marker, does NOT touch the live broker"
              data-testid={`port-paper-close-${p.symbol}`}
            >
              <span aria-hidden style={{ marginRight: 4, opacity: 0.6 }}>◇</span>
              Close (paper)
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
      <span className="port-weight__label terminal-grid-numeric">
        {formatPercent(clamped, { digits: 1 })}
      </span>
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
        <Kpi label="Quantity" numeric value={formatNumber(r.quantity, 6)} />
        <Kpi
          label="Exit"
          numeric
          value={
            r.exit_price != null && Number.isFinite(r.exit_price)
              ? `$${formatPrice(r.exit_price)}`
              : formatMissing
          }
        />
        <Kpi label="Notional" numeric value={fmt$(r.market_value)} />
        <Kpi
          label="Realized P&L"
          numeric
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
  numeric = false,
}: {
  label: string;
  value: ReactNode;
  numeric?: boolean;
}) {
  return (
    <div className="showme-port__kpi showme-card-reveal u-kpi-surface">
      <div className="port-class-card__caption">{label}</div>
      <div className={`port-class-card__value${numeric ? " terminal-grid-numeric" : ""}`}>
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

async function requestPortfolioClose(position: Position, dryRun: boolean): Promise<CloseResponse> {
  const exit = Number(positionCurrentPrice(position) ?? positionEntryPrice(position) ?? 0);
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
