/**
 * WHAL — Cross-market whale / large-flow monitor.
 *
 * The sidecar implementation (`backend/showme/engine/functions/misc/whal.py`)
 * stitches Binance public aggregate trades for crypto, plus a Yahoo
 * chart + SEC EDGAR proxy for everything else. The panel surfaces:
 *   - Cards block (provider, threshold hits, 24h volume etc.)
 *   - Alert grid with severity / source-mode chips and a chain pill
 *   - The "this is a public proxy, not a wallet-label transfer feed"
 *     caveat so the user never mistakes proxy rows for a paid feed.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
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
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface WHALRow {
  alert_type?: string;
  market?: string;
  symbol?: string;
  venue?: string;
  timestamp?: string;
  price?: number;
  amount?: number;
  usd_value?: number;
  threshold_usd?: number;
  threshold_crossed?: boolean;
  direction?: string;
  severity?: string;
  source_mode?: string;
  explanation?: string;
  form?: string;
  url?: string;
}

interface WHALCard {
  label?: string;
  value?: number | string | null;
}

interface WHALPayload {
  status?: string;
  signal_state?: string;
  provider?: string;
  provider_symbol?: string;
  rows?: WHALRow[];
  cards?: WHALCard[];
  summary?: string;
  symbol?: string;
  market?: string;
  chain?: string | null;
  threshold_usd?: number;
  lookback_hours?: number;
  interval?: string;
  whale_alert_api?: string;
  native_transfer_feed?: string;
  methodology?: string;
  field_dictionary?: Record<string, string>;
  provider_warnings?: string[];
  next_actions?: string[];
}

const MARKETS = [
  { id: "CRYPTO", label: "Crypto" },
  { id: "EQUITY", label: "Equity" },
  { id: "ETF", label: "ETF" },
  { id: "FX", label: "FX" },
] as const;
type MarketId = (typeof MARKETS)[number]["id"];
const MARKET_IDS = MARKETS.map((m) => m.id);

const SAMPLES: Record<MarketId, string> = {
  CRYPTO: "BTCUSDT",
  EQUITY: "AAPL",
  ETF: "SPY",
  FX: "EURUSD",
};

const REFRESH_MS = 30_000;

export function WHALPane({ code, symbol }: FunctionPaneProps) {
  const [market, setMarket] = usePersistentOption<MarketId>(
    "showme.whal-market",
    MARKET_IDS,
    "CRYPTO",
  );
  const [thresholdK, setThresholdK] = usePersistentOption<string>(
    "showme.whal-threshold-k",
    ["100", "500", "1000", "5000", "10000"],
    "1000",
  );
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const resolvedSymbol = symbol || SAMPLES[market];
  const threshold = Number(thresholdK) * 1000;

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol: resolvedSymbol,
    params: {
      symbol: resolvedSymbol,
      market,
      threshold_usd: threshold,
      limit: 25,
      lookback_hours: 24,
      tick,
    },
  });

  const payload = useMemo<WHALPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as WHALPayload)
        : {},
    [data?.data],
  );

  const rows = useMemo<WHALRow[]>(
    () => (Array.isArray(payload.rows) ? payload.rows : []),
    [payload.rows],
  );

  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  const warnings = Array.isArray(payload.provider_warnings) ? payload.provider_warnings : [];
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);
  const isLive = payload.status === "ok";
  const thresholdHits = rows.filter((r) => r.threshold_crossed).length;

  const cols = useMemo<DataGridColumn<WHALRow>[]>(
    () => [
      {
        key: "ts",
        header: "When",
        width: 150,
        render: (r) => (
          <span className="u-mono u-text-secondary" style={{ fontSize: "var(--font-size-xs)" }}>
            {formatTimestamp(r.timestamp)}
          </span>
        ),
      },
      {
        key: "alert",
        header: "Type",
        width: 130,
        render: (r) => <AlertTypePill type={r.alert_type ?? "—"} />,
      },
      {
        key: "symbol",
        header: "Symbol",
        width: 110,
        render: (r) => (
          <span style={symbolCell}>
            {r.symbol ?? "—"}
            {r.venue ? (
              <span className="u-text-mute" style={{ fontSize: "var(--font-size-xs)" }}>
                {r.venue}
              </span>
            ) : null}
          </span>
        ),
      },
      {
        key: "side",
        header: "Side",
        width: 80,
        render: (r) => {
          if (!r.direction) return "—";
          const tone =
            r.direction === "buy_initiated" || r.direction === "up"
              ? "positive"
              : r.direction === "sell_initiated" || r.direction === "down"
                ? "negative"
                : "muted";
          return (
            <Pill tone={tone} variant="soft" withDot={false}>
              {r.direction.replace(/_initiated$/, "")}
            </Pill>
          );
        },
      },
      {
        key: "usd",
        header: "USD value",
        numeric: true,
        width: 130,
        render: (r) =>
          r.usd_value == null ? "—" : (
            <span style={usdCell}>${formatLargeNumber(r.usd_value)}</span>
          ),
      },
      {
        key: "severity",
        header: "Severity",
        width: 100,
        render: (r) => (
          <Pill tone={severityTone(r.severity)} variant="soft" withDot={false}>
            {(r.severity ?? "medium").toUpperCase()}
          </Pill>
        ),
      },
      {
        key: "source",
        header: "Source",
        width: 200,
        render: (r) => (
          <span className="u-text-secondary" style={{ fontSize: "var(--font-size-xs)" }}>
            {r.source_mode ?? "—"}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Whale flow · ${resolvedSymbol}`}
          subtitle={`${rows.length} rows · ${thresholdHits} crossed $${(threshold / 1000).toFixed(0)}k · ${payload.provider ?? "—"}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>{rows.length} alerts</Pill>
              <Pill tone="accent" variant="soft" withDot={false}>{utcStamp} UTC</Pill>
              <Pill
                tone={isLive ? "positive" : "warn"}
                variant="soft"
              >
                {isLive ? "live proxy" : payload.status ?? state}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={MARKETS.map((m) => ({ id: m.id, label: m.label }))}
            active={market}
            onChange={(id) => setMarket(id as MarketId)}
          />
          <div style={thresholdRow}>
            <span className="u-text-secondary u-text-10">Min USD (k):</span>
            {(["100", "500", "1000", "5000", "10000"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setThresholdK(v)}
                style={{
                  ...thresholdBtn,
                  color: thresholdK === v ? "var(--accent)" : "var(--text-secondary)",
                  borderColor: thresholdK === v ? "var(--accent)" : "var(--border-subtle)",
                }}
                aria-pressed={thresholdK === v}
              >
                {v === "10000" ? "10M" : `${v}k`}
              </button>
            ))}
          </div>
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : (
            <div className="u-grid-gap-14">
              <div style={proxyNoticeStyle}>
                <strong className="u-text-secondary">Proxy disclosure</strong>
                <span className="u-text-mute">
                  Public market data only — Binance aggregate trades for crypto,
                  Yahoo chart + SEC EDGAR for the rest. These rows are
                  market-flow proxies, not licensed tape prints or on-chain
                  wallet-label transfers.
                </span>
              </div>
              {warnings.length ? (
                <div style={warningBox}>
                  <strong className="u-text-warn">Provider warnings</strong>
                  <ul style={warningList}>
                    {warnings.slice(0, 4).map((w, i) => (
                      <li key={i} className="u-text-secondary">{String(w)}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {cards.length ? (
                <section style={kpiGrid} aria-label="WHAL KPI ribbon">
                  {cards.slice(0, 4).map((card, i) => (
                    <StatCard
                      key={i}
                      label={card.label ?? `Card ${i + 1}`}
                      value={formatCardValue(card.value)}
                      caption={`AS OF ${utcStamp} UTC`}
                      tone="neutral"
                    />
                  ))}
                </section>
              ) : null}
              {rows.length === 0 ? (
                <Empty title="No alerts" body={payload.summary ?? "No public WHAL rows returned."} />
              ) : (
                <DataGrid
                  columns={cols}
                  rows={rows}
                  rowKey={(r, i) => `${r.timestamp ?? ""}-${r.symbol ?? ""}-${i}`}
                  density="compact"
                />
              )}
              {payload.methodology ? (
                <div style={methodologyBox}>
                  <strong className="u-text-secondary">Methodology</strong>
                  <span>{payload.methodology}</span>
                </div>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={payload.provider ?? data?.sources?.join(", ") ?? "—"} />
          <StatusDivider />
          <StatusSection label="market" value={market} />
          <StatusDivider />
          <StatusSection label="threshold" value={`$${(threshold / 1000).toFixed(0)}k`} />
          <StatusDivider />
          <StatusSection label="lookback" value={`${payload.lookback_hours ?? 24}h`} />
          <StatusDivider />
          <StatusSection
            label="transfer feed"
            value={payload.native_transfer_feed ?? "not_configured"}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function AlertTypePill({ type }: { type: string }) {
  const lower = type.toLowerCase();
  let tone: "accent" | "positive" | "warn" | "negative" | "muted" = "muted";
  if (lower.includes("large_trade") || lower.includes("sec_")) tone = "accent";
  else if (lower.includes("large_volume") || lower.includes("impulse")) tone = "warn";
  else if (lower.includes("top_")) tone = "positive";
  return (
    <Pill tone={tone} variant="soft" withDot={false}>
      {type.replace(/_/g, " ")}
    </Pill>
  );
}

function severityTone(severity?: string): "positive" | "negative" | "warn" | "muted" | "accent" {
  switch ((severity ?? "").toLowerCase()) {
    case "critical":
      return "negative";
    case "high":
      return "warn";
    case "medium":
      return "accent";
    case "low":
      return "muted";
    default:
      return "muted";
  }
}

function formatTimestamp(value?: string): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toISOString().slice(5, 16).replace("T", " ");
  } catch {
    return value;
  }
}

function formatLargeNumber(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatCardValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    return formatLargeNumber(value);
  }
  return String(value);
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  display: "grid",
  gap: 8,
};

const thresholdRow: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const thresholdBtn: CSSProperties = {
  background: "transparent",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-pill)",
  padding: "1px 8px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  fontWeight: 600,
  cursor: "pointer",
};

const symbolCell: CSSProperties = {
  display: "grid",
  gridAutoFlow: "row",
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  color: "var(--text-display)",
};

const usdCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const proxyNoticeStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--warn-soft)",
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

const methodologyBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  display: "grid",
  gap: 6,
};
