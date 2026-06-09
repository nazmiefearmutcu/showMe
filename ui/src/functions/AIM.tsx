/**
 * AIM — Order Management (cross-broker open + history ledger).
 *
 * Read-only counterpart to EMSX/TSOX. The sidecar handler
 * (`engine/functions/trade/_funcs.py::AIMFunction`) returns a single
 * `orders[]` array (live open orders from every configured broker plus a
 * persisted history tail), a `cards{}` KPI dict, a `data_mode`, the
 * `brokers_checked` / `brokers_online` lists, `warnings`, `next_actions`,
 * `methodology` and (in `metadata`) a `provider_errors` list.
 *
 * Open vs terminal is decided client-side via `OPEN_STATES` (mirrors the
 * backend status vocabulary). With no broker adapters configured the handler
 * returns `orders: []`, `data_mode: "not_configured"` and an actionable
 * `next_actions` — the pane renders an empty-but-honest blotter and never
 * fakes fills.
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
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { formatCurrency, formatMissing, formatNumber } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface AimOrder {
  created_at?: string | null;
  broker?: string | null;
  order_id?: string | null;
  symbol?: string | null;
  side?: string | null;
  quantity?: number | null;
  price?: number | null;
  type?: string | null;
  tif?: string | null;
  status?: string | null;
  filled_qty?: number | null;
  avg_fill_px?: number | null;
}

// Backend returns `cards` as a flat dict keyed by slot name.
interface AimCards {
  open_count?: number;
  filled_today?: number;
  brokers_online?: number;
  total_notional?: number;
  data_mode?: string;
  as_of?: string;
}

interface AimPayload {
  status?: string;
  reason?: string;
  orders?: AimOrder[];
  cards?: AimCards;
  brokers_checked?: string[];
  brokers_online?: string[];
  data_mode?: string;
  as_of?: string;
  methodology?: string;
  warnings?: string[];
  next_actions?: string[];
}

// Mirrors the backend status vocabulary for "still working" orders.
const OPEN_STATES = new Set([
  "open",
  "working",
  "partially_filled",
  "pending",
  "accepted",
  "new",
]);

const TABS = ["open", "history"] as const;
type TabId = (typeof TABS)[number];

const REFRESH_MS = 15_000;
const LIVE_MODES = new Set(["live_exchange"]);

export function AIMPane({ code, symbol }: FunctionPaneProps) {
  const [tab, setTab] = usePersistentOption<TabId>(
    "showme.aim-tab",
    TABS,
    "open",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { limit: 200, tick },
  });

  const payload = useMemo<AimPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as AimPayload)
        : {},
    [data?.data],
  );

  // Handler returns one combined `orders[]`; scope to the focused symbol when
  // the pane has one so a per-symbol blotter is honest.
  const allOrders = useMemo<AimOrder[]>(() => {
    const list = Array.isArray(payload.orders) ? payload.orders : [];
    if (!symbol) return list;
    const want = symbol.toUpperCase();
    return list.filter((o) => (o.symbol ?? "").toUpperCase() === want);
  }, [payload.orders, symbol]);

  const openOrders = useMemo(
    () => allOrders.filter((o) => OPEN_STATES.has((o.status ?? "").toLowerCase())),
    [allOrders],
  );
  const historyOrders = useMemo(
    () => allOrders.filter((o) => !OPEN_STATES.has((o.status ?? "").toLowerCase())),
    [allOrders],
  );
  const activeRows = tab === "open" ? openOrders : historyOrders;

  const dataMode = payload.data_mode ?? payload.cards?.data_mode ?? "not_configured";
  const isLive = LIVE_MODES.has(dataMode);
  const isDegraded = dataMode === "provider_unavailable" || dataMode === "degraded";
  const notConfigured = dataMode === "not_configured";

  const brokersChecked = Array.isArray(payload.brokers_checked)
    ? payload.brokers_checked
    : [];
  // provider_errors lives under metadata (string[]) per the handler.
  const providerErrors = useMemo<string[]>(() => {
    const meta = (data as { metadata?: { provider_errors?: unknown } } | undefined)
      ?.metadata;
    return Array.isArray(meta?.provider_errors)
      ? (meta?.provider_errors as unknown[]).map((e) => String(e))
      : [];
  }, [data]);
  const warningsList = Array.isArray(payload.warnings)
    ? payload.warnings
    : Array.isArray(data?.warnings)
      ? (data?.warnings as string[])
      : [];
  const nextActions = Array.isArray(payload.next_actions)
    ? payload.next_actions
    : [];

  const cards = payload.cards ?? {};
  const openCount = numeric(cards.open_count) ?? openOrders.length;
  const filledToday = numeric(cards.filled_today) ?? 0;
  const brokersOnline =
    numeric(cards.brokers_online) ??
    (Array.isArray(payload.brokers_online) ? payload.brokers_online.length : 0);
  const totalNotional = numeric(cards.total_notional) ?? 0;
  const rejectedCount = historyOrders.filter(
    (o) => (o.status ?? "").toLowerCase() === "rejected",
  ).length;

  const sources =
    data?.sources?.join(", ") ||
    (brokersChecked.length ? brokersChecked.join(", ") : "no broker adapters");
  // Client wall-clock fallback for "AS OF" captions when the server omits as_of.
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);
  // Server data-freshness (payload.as_of) as an HH:MM UTC stamp; falls back to
  // the client clock so the header always shows something honest.
  const asOfStamp = useMemo(() => extractAsOfHHMM(payload.as_of) ?? utcStamp, [
    payload.as_of,
    utcStamp,
  ]);

  const cols = useMemo<DataGridColumn<AimOrder>[]>(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 92,
        render: (r) => <span style={symbolCell}>{r.symbol || formatMissing}</span>,
      },
      {
        key: "side",
        header: "Side",
        width: 64,
        render: (r) => <SideChip side={r.side} />,
      },
      {
        key: "type",
        header: "Type",
        width: 84,
        render: (r) => (
          <span style={typeCell}>{(r.type || formatMissing).toUpperCase()}</span>
        ),
      },
      {
        key: "quantity",
        header: "Qty",
        numeric: true,
        width: 108,
        render: (r) => {
          const q = numeric(r.quantity);
          const f = numeric(r.filled_qty);
          const partial = f != null && q != null && f > 0 && f < q;
          return (
            <span style={mutedNumStyle}>
              {fmtNum(r.quantity)}
              {partial && (
                <span style={fillTagStyle}>· {fmtNum(r.filled_qty)} fl</span>
              )}
            </span>
          );
        },
      },
      {
        key: "price",
        header: "Price",
        numeric: true,
        width: 100,
        render: (r) =>
          r.price == null ? (
            <span style={marketTagStyle}>MKT</span>
          ) : (
            <span style={primaryNumStyle}>{fmtNum(r.price)}</span>
          ),
      },
      {
        key: "avg_fill_px",
        header: "Avg Fill",
        numeric: true,
        width: 100,
        render: (r) =>
          r.avg_fill_px == null ? (
            <span style={mutedNumStyle}>{formatMissing}</span>
          ) : (
            <span style={primaryNumStyle}>{fmtNum(r.avg_fill_px)}</span>
          ),
      },
      {
        key: "status",
        header: "Status",
        width: 124,
        render: (r) => <StatusPill status={r.status} />,
      },
      {
        key: "tif",
        header: "TIF",
        width: 56,
        render: (r) => (
          <span style={mutedNumStyle}>{(r.tif || "—").toUpperCase()}</span>
        ),
      },
      {
        key: "broker",
        header: "Broker",
        width: 124,
        render: (r) => (
          <Pill tone="muted" variant="soft" withDot={false}>
            {r.broker ?? formatMissing}
          </Pill>
        ),
      },
      {
        key: "created_at",
        header: "Created",
        width: 162,
        render: (r) => <span style={mutedNumStyle}>{fmtTime(r.created_at)}</span>,
      },
    ],
    [],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Order management"
          subtitle={`${symbol ? `${symbol} · ` : ""}${openOrders.length} open · ${historyOrders.length} history · ${brokersOnline} broker${brokersOnline === 1 ? "" : "s"} · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {openOrders.length} open
              </Pill>
              {/* H3 — freshness derived from server as_of (falls back to client). */}
              <Pill tone="accent" variant="soft" withDot={false}>
                {`Veri: ${asOfStamp} UTC`}
              </Pill>
              <Pill
                tone={isLive ? "positive" : isDegraded ? "negative" : "warn"}
                variant="soft"
                aria-label={`Veri modu: ${dataModeExplanation(dataMode)}`}
              >
                {dataMode}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                busy={state === "loading" || state === "refreshing"}
                onClick={refetch}
              />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={[
              { id: "open", label: `Open (${openOrders.length})` },
              { id: "history", label: `History (${historyOrders.length})` },
            ]}
            active={tab}
            onChange={(id) => setTab(id as TabId)}
          />
        </div>
        <PaneBody>
          {/* A1 — async transitions (loading / error / empty) are announced to
              screen readers via a polite live region; aria-busy flips while the
              poll is in flight. */}
          <div
            role="status"
            aria-live="polite"
            aria-busy={state === "loading" || state === "refreshing"}
          >
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty
              title="Function error"
              body={error?.message ?? formatMissing}
              icon="!"
            />
          ) : (
            <div className="u-grid-gap-14">
              {/* H3 — the degraded/cached state EXPLAINS itself rather than just
                  colouring a pill. role=status so the reason reaches SR users. */}
              {!isLive ? (
                <section
                  style={noticeStyle}
                  role="status"
                  aria-live="polite"
                  data-testid="aim-mode-notice"
                >
                  <strong className="u-text-warn">{dataModeTitle(dataMode)}</strong>
                  <span className="u-text-secondary">
                    {dataModeExplanation(dataMode)}
                    {payload.reason ? ` — ${payload.reason}` : ""}
                  </span>
                  {nextActions[0] ? (
                    <span className="u-text-mute">{nextActions[0]}</span>
                  ) : null}
                </section>
              ) : null}
              {providerErrors.length ? (
                <section style={warningBox} role="alert">
                  <strong className="u-text-warn">Broker errors</strong>
                  <ul style={warningList}>
                    {providerErrors.slice(0, 3).map((e, i) => (
                      <li key={i} className="u-text-secondary">
                        {e}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : warningsList.length ? (
                <section style={warningBox} role="status" aria-live="polite">
                  <strong className="u-text-warn">Warnings</strong>
                  <ul style={warningList}>
                    {warningsList.slice(0, 3).map((w, i) => (
                      <li key={i} className="u-text-secondary">
                        {String(w)}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <section style={kpiGridStyle} aria-label="AIM KPI ribbon">
                <StatCard
                  label="Open"
                  value={String(openCount)}
                  caption={`${historyOrders.length} historical`}
                  tone="neutral"
                />
                {/* H1 — counts ALL filled/partially-filled rows in the history
                    tail, not just today's. Labelled honestly as "Filled". */}
                <StatCard
                  label="Filled"
                  value={String(filledToday)}
                  caption={`AS OF ${asOfStamp} UTC`}
                  tone={filledToday > 0 ? "positive" : "neutral"}
                />
                <StatCard
                  label="Brokers"
                  value={String(brokersOnline)}
                  caption={
                    providerErrors.length
                      ? `${providerErrors.length} erroring`
                      : brokersOnline > 0
                        ? "online"
                        : "none configured"
                  }
                  tone={
                    providerErrors.length
                      ? "negative"
                      : brokersOnline > 0
                        ? "positive"
                        : "neutral"
                  }
                />
                <StatCard
                  label="Notional"
                  value={fmtNotional(totalNotional)}
                  caption={
                    rejectedCount > 0 ? `${rejectedCount} rejected` : "USD est."
                  }
                  tone={rejectedCount > 0 ? "negative" : "neutral"}
                />
              </section>

              {activeRows.length === 0 ? (
                <Empty
                  title={tab === "open" ? "No open orders" : "No order history"}
                  body={
                    tab === "open"
                      ? notConfigured
                        ? "Configure a broker adapter in Settings to view live orders."
                        : symbol
                          ? `No working orders for ${symbol}.`
                          : "No working orders across configured brokers."
                      : "No filled, cancelled, or rejected orders on record."
                  }
                />
              ) : (
                <DataGrid
                  columns={cols}
                  rows={activeRows}
                  rowKey={(r, i) =>
                    `${r.broker ?? ""}-${r.order_id ?? r.symbol ?? "order"}-${i}`
                  }
                  density="compact"
                  ariaLabel="AIM order blotter"
                />
              )}
            </div>
          )}
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="brokers" value={sources} />
          <StatusDivider />
          <StatusSection
            label="mode"
            value={dataMode}
            tone={isLive ? "positive" : isDegraded ? "negative" : "muted"}
          />
          <StatusDivider />
          <StatusSection label="orders" value={allOrders.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="as of"
            value={payload.as_of ? fmtTime(payload.as_of) : `${utcStamp} UTC`}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

// D1 — design-system Pill (not a hand-rolled span) so side is theme-consistent.
// A3 — accessible name so buy/sell isn't conveyed by colour alone.
function SideChip({ side }: { side?: string | null }) {
  const s = (side ?? "").toLowerCase();
  if (!s) return <span style={mutedNumStyle}>{formatMissing}</span>;
  const tone: "positive" | "negative" | "accent" =
    s === "buy" ? "positive" : s === "sell" ? "negative" : "accent";
  return (
    <Pill
      tone={tone}
      variant="soft"
      withDot={false}
      aria-label={`yön: ${s === "buy" ? "alış" : s === "sell" ? "satış" : s}`}
    >
      {s.toUpperCase()}
    </Pill>
  );
}

function StatusPill({ status }: { status?: string | null }) {
  const s = (status ?? "").toLowerCase();
  const tone: "neutral" | "positive" | "negative" | "accent" | "warn" | "muted" =
    s === "filled"
      ? "positive"
      : s === "rejected" || s === "expired"
        ? "negative"
        : s === "partially_filled" || s === "working" || s === "pending"
          ? "warn"
          : s === "cancelled"
            ? "muted"
            : s === "open" || s === "accepted" || s === "new"
              ? "accent"
              : "muted";
  const text = s ? s.replace(/_/g, " ").toUpperCase() : formatMissing;
  // A3 — accessible name so status isn't conveyed by colour alone.
  return (
    <Pill
      tone={tone}
      variant="soft"
      withDot={false}
      aria-label={s ? `durum: ${s.replace(/_/g, " ")}` : "durum: yok"}
    >
      {text}
    </Pill>
  );
}

function numeric(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

// D1 — delegate to the shared format.ts (single source of truth). Quantities /
// prices keep up to 6 fractional digits; missing values share the "—" sentinel.
function fmtNum(v: number | null | undefined): string {
  return formatNumber(v, 6);
}

// D1 — notional uses the shared compact currency formatter ("$1.20M").
function fmtNotional(v: number): string {
  if (!Number.isFinite(v) || v === 0) return formatMissing;
  return formatCurrency(v, { compact: true });
}

// format.ts has no ISO HH:MM helper, so keep a local UTC time formatter.
function fmtTime(ts: string | null | undefined): string {
  if (!ts) return formatMissing;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toISOString().slice(0, 16).replace("T", " ");
}

/** Server data-freshness (`as_of`) as an HH:MM UTC stamp, if parseable. */
function extractAsOfHHMM(raw: string | null | undefined): string | undefined {
  if (typeof raw !== "string" || !raw) return undefined;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString().slice(11, 16);
}

// H3 — honest, human-readable data_mode title + reason (no raw token).
function dataModeTitle(mode: string): string {
  switch (mode) {
    case "live_exchange":
      return "Canlı";
    case "cached_snapshot":
      return "Önbellek anlık görüntüsü";
    case "not_configured":
      return "Broker yapılandırılmamış";
    case "provider_unavailable":
    case "degraded":
      return "Brokerlara ulaşılamıyor";
    default:
      return "Referans defteri";
  }
}

function dataModeExplanation(mode: string): string {
  switch (mode) {
    case "live_exchange":
      return "Canlı broker emir akışı.";
    case "cached_snapshot":
      return "Canlı broker bağlantısı yok — son anlık görüntü gösteriliyor.";
    case "not_configured":
      return "Broker yapılandırılmamış.";
    case "provider_unavailable":
    case "degraded":
      return "Brokerlara ulaşılamıyor — kayıtlı emir geçmişi gösteriliyor.";
    default:
      return "Canlı broker emir akışı yok. Defter etiketlendi ve hiçbir gerçekleşme uydurulmuyor.";
  }
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const symbolCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  letterSpacing: "0.02em",
  color: "var(--text-display)",
};

const typeCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--text-secondary)",
};

const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
};

const mutedNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const fillTagStyle: CSSProperties = {
  marginLeft: 4,
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.02em",
};

const marketTagStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  fontWeight: 600,
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
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
