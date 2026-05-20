/**
 * DES — Description / company snapshot.
 *
 * Bloomberg-grade company detail with a chart-led header strip and
 * description-first body. Profile data via yfinance + finnhub feeds.
 */
import { type CSSProperties } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  DeltaChip,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusSection,
  StatusDivider,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { SymbolBar } from "@/shell/SymbolBar";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { XSenChip } from "./XSenChip";
import type { FunctionPaneProps } from "./registry-types";

interface DESData {
  status?: string;
  reason?: string;
  nextAction?: string;
  next_actions?: string[];
  provider_errors?: string[];
  asset_class?: string;
  name?: string;
  longName?: string;
  shortName?: string;
  symbol?: string;
  sector?: string;
  industry?: string;
  country?: string;
  city?: string;
  headquarters?: string;
  fullTimeEmployees?: number;
  employees?: number;
  website?: string;
  longBusinessSummary?: string;
  description?: string;
  marketCap?: number;
  market_cap?: number;
  exchange?: string;
  exchange_name?: string;
  currency?: string;
  ipoDate?: string;
  ipo_date?: string;
  price?: number;
  currentPrice?: number;
  regularMarketPrice?: number;
  previousClose?: number;
  regularMarketChangePercent?: number;
  fiftyTwoWeekHigh?: number;
  fiftyTwoWeekLow?: number;
  beta?: number;
  trailingPE?: number;
  forwardPE?: number;
  dividendYield?: number;
  // Crypto-specific fields populated when ``asset_class === "CRYPTO"``.
  circulating_supply?: number;
  total_supply?: number;
  max_supply?: number;
  all_time_high?: number;
  all_time_high_date?: string;
  all_time_low?: number;
  all_time_low_date?: string;
  genesis_date?: string;
  hashing_algorithm?: string;
  block_time_in_minutes?: number;
  categories?: string[];
  rank?: number;
  github_repo?: string;
  [key: string]: unknown;
}

const isCryptoProfile = (data?: DESData) =>
  String(data?.asset_class ?? "").toUpperCase() === "CRYPTO";

const fmtNum = (n?: number | null) =>
  n == null || !Number.isFinite(n)
    ? "—"
    : Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });

const fmtMcap = (n?: number | null) => {
  if (n == null || !Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${fmtNum(n)}`;
};

const fmtPct = (n?: number | null) => {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n.toFixed(2)}%`;
};

const fmtSupply = (n?: number | null) => {
  if (n == null || !Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
};

const fmtDate = (iso?: string | null) => {
  if (!iso) return "—";
  // Accept full ISO timestamps or YYYY-MM-DD bare dates.
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10) || "—";
  return d.toISOString().slice(0, 10);
};

const fmtCurrency = (n?: number | null, currency?: string) => {
  if (n == null || !Number.isFinite(n)) return "—";
  const symbol = currencySymbol(currency);
  return `${symbol}${Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
};

function currencySymbol(currency?: string): string {
  switch ((currency || "USD").toUpperCase()) {
    case "USD":
      return "$";
    case "EUR":
      return "€";
    case "GBP":
      return "£";
    case "JPY":
      return "¥";
    case "TRY":
      return "₺";
    default:
      return "";
  }
}

export function DESPane({ code, symbol }: FunctionPaneProps) {
  // Fall back to a sensible default symbol so the panel doesn't stall on
  // "Pick a symbol" when the palette opens DES cold.
  const effectiveSymbol = symbol || defaultSymbolForFunction(code);
  const { state, data, error, refetch } = useFunction<DESData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
  });
  const payloadStatus = data?.status ?? data?.data?.status;
  const profile = data?.data;

  const last =
    profile?.regularMarketPrice ?? profile?.currentPrice ?? profile?.price ?? null;
  const prev = profile?.previousClose ?? null;
  const changePct =
    profile?.regularMarketChangePercent ??
    (last != null && prev ? ((last - prev) / prev) * 100 : null);
  const change = last != null && prev != null ? last - prev : null;
  const hasLive = last != null && payloadStatus === "ok";

  const body = !effectiveSymbol ? (
    <Empty
      title="Pick a symbol"
      body="DES needs a ticker. Try the bar above or ⌘K — e.g. AAPL, MSFT, TSLA."
      icon="⌖"
    />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-10">
      <Skeleton height={20} width="40%" />
      <Skeleton height={14} width="80%" />
      <Skeleton height={14} width="64%" />
      <Skeleton height={140} />
    </div>
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? "Unknown error"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <DESView data={profile} />
  );

  const provider = data?.sources?.[0] ?? "pending";
  const cached = !!(data as { cached?: boolean } | undefined)?.cached;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={
            profile?.longName ||
            profile?.shortName ||
            profile?.name ||
            effectiveSymbol ||
            "Description"
          }
          subtitle={
            profile
              ? [
                  profile.exchange_name || profile.exchange,
                  profile.industry,
                  profile.country,
                ]
                  .filter(Boolean)
                  .join(" · ") || "Description"
              : "Description"
          }
          trailing={
            <FunctionControlGroup>
              <XSenChip symbol={effectiveSymbol} compact />
              <LoadStatePill state={state} status={payloadStatus} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh description"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={effectiveSymbol} />

        {/* Symbol header strip — chart-led detail row. Shown for any
            resolvable symbol so the default-symbol path renders too. */}
        {effectiveSymbol && (
          <div style={symbolStripStyle}>
            <div className="u-flex u-items-center u-gap-12 u-min-w-0">
              <span style={tickerStyle}>{effectiveSymbol}</span>
              {(profile?.longName || profile?.shortName) && (
                <span
                  style={nameStyle}
                  title={profile?.longName || profile?.shortName}
                >
                  {profile?.longName || profile?.shortName}
                </span>
              )}
              {(profile?.exchange_name || profile?.exchange) && (
                <Pill tone="muted" variant="soft" withDot={false}>
                  {profile?.exchange_name || profile?.exchange}
                </Pill>
              )}
              {profile?.sector && (
                <Pill tone="accent" variant="soft" withDot={false}>
                  {profile.sector}
                </Pill>
              )}
              {hasLive && (
                <Pill tone="positive" variant="soft">
                  RT SESSION
                </Pill>
              )}
            </div>
            <div className="u-flex u-items-center u-gap-14">
              {last != null && (
                <span style={lastPriceStyle}>
                  {fmtCurrency(last, profile?.currency)}
                </span>
              )}
              {changePct != null && (
                <DeltaChip value={changePct} format="percent" fractionDigits={2} />
              )}
              {change != null && (
                <span style={changeAbsStyle}>
                  {change >= 0 ? "+" : ""}
                  {change.toFixed(2)}
                </span>
              )}
            </div>
          </div>
        )}

        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={provider} tone="muted" />
          <StatusSection
            withDot
            tone={cached ? "warn" : "positive"}
            label="cache"
            value={cached ? "hit" : "live"}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
            tone="muted"
          />
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
            tone="muted"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function DESView({ data }: { data?: DESData }) {
  if (!data) return <Empty title="No description data" />;
  const summary = data.longBusinessSummary ?? data.description ?? null;
  const degraded = data.status && data.status !== "ok";
  const crypto = isCryptoProfile(data);

  return (
    <div className="u-grid-gap-12">
      {degraded ? <DESStatusPanel data={data} /> : null}
      {crypto ? <CryptoMetrics data={data} /> : <EquityMetrics data={data} />}

      <div style={mainGridStyle}>
        <Card>
          <CardHeader
            trailing={
              summary ? (
                <Pill tone="muted" withDot={false}>
                  {summary.length.toLocaleString()} chars
                </Pill>
              ) : null
            }
          >
            {crypto ? "About the asset" : "Business summary"}
          </CardHeader>
          <CardBody>
            <p style={summaryParagraphStyle}>
              {summary ??
                (crypto
                  ? "CoinGecko did not return a profile summary for this asset."
                  : "Provider did not return a business summary.")}
            </p>
            {data.website && (
              <div style={websiteRowStyle}>
                <span style={websiteLabelStyle}>Website</span>
                <a
                  href={data.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={websiteLinkStyle}
                >
                  {data.website}
                </a>
              </div>
            )}
            {crypto && data.github_repo && (
              <div style={websiteRowStyle}>
                <span style={websiteLabelStyle}>Repo</span>
                <a
                  href={data.github_repo}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={websiteLinkStyle}
                >
                  {data.github_repo}
                </a>
              </div>
            )}
            {crypto && data.categories && data.categories.length > 0 && (
              <div style={categoriesRowStyle}>
                {data.categories.slice(0, 6).map((c) => (
                  <Pill key={c} tone="accent" variant="soft" withDot={false}>
                    {c}
                  </Pill>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>Snapshot</CardHeader>
          <CardBody>
            <dl style={dlStyle}>
              {crypto ? <CryptoSnapshotTerms data={data} /> : <EquitySnapshotTerms data={data} />}
            </dl>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function EquityMetrics({ data }: { data: DESData }) {
  const marketCap = data.marketCap ?? data.market_cap;
  const dividendPct =
    data.dividendYield != null && Number.isFinite(Number(data.dividendYield))
      ? Number(data.dividendYield) * 100
      : null;
  return (
    <div style={metricsStripStyle}>
      <SnapshotMetric label="Market cap" value={fmtMcap(marketCap)} tone="accent" />
      <SnapshotMetric label="P/E (TTM)" value={fmtNum(data.trailingPE)} />
      <SnapshotMetric label="Forward P/E" value={fmtNum(data.forwardPE)} />
      <SnapshotMetric
        label="Beta"
        value={fmtNum(data.beta)}
        tone={
          data.beta != null && Number.isFinite(data.beta)
            ? data.beta > 1.2
              ? "warn"
              : "neutral"
            : "neutral"
        }
      />
      <SnapshotMetric label="Dividend yield" value={fmtPct(dividendPct)} tone="positive" />
      <SnapshotMetric label="52w high" value={fmtCurrency(data.fiftyTwoWeekHigh, data.currency)} />
      <SnapshotMetric label="52w low" value={fmtCurrency(data.fiftyTwoWeekLow, data.currency)} />
    </div>
  );
}

function CryptoMetrics({ data }: { data: DESData }) {
  const marketCap = data.marketCap ?? data.market_cap;
  const last = data.regularMarketPrice ?? data.currentPrice ?? data.price ?? null;
  return (
    <div style={metricsStripStyle}>
      <SnapshotMetric label="Market cap" value={fmtMcap(marketCap)} tone="accent" />
      <SnapshotMetric label="Last price" value={fmtCurrency(last ?? null, "USD")} />
      <SnapshotMetric
        label="24h change"
        value={fmtPct(data.regularMarketChangePercent ?? null)}
        tone={
          data.regularMarketChangePercent != null
            ? data.regularMarketChangePercent >= 0
              ? "positive"
              : "negative"
            : "neutral"
        }
      />
      <SnapshotMetric label="All-time high" value={fmtCurrency(data.all_time_high, "USD")} />
      <SnapshotMetric label="All-time low" value={fmtCurrency(data.all_time_low, "USD")} />
      <SnapshotMetric label="Circ supply" value={fmtSupply(data.circulating_supply)} />
      <SnapshotMetric
        label="Max supply"
        value={data.max_supply == null ? "∞" : fmtSupply(data.max_supply)}
      />
    </div>
  );
}

function EquitySnapshotTerms({ data }: { data: DESData }) {
  const employees = data.fullTimeEmployees ?? data.employees;
  const hq =
    data.headquarters ??
    ([data.city, data.country].filter(Boolean).join(", ") || "—");
  const exchange = data.exchange_name ?? data.exchange ?? "—";
  const ipo = data.ipoDate ?? data.ipo_date ?? "—";
  return (
    <>
      <Term k="Sector">{data.sector ?? "—"}</Term>
      <Term k="Industry">{data.industry ?? "—"}</Term>
      <Term k="HQ">{hq}</Term>
      <Term k="Employees">
        {employees != null
          ? Number(employees).toLocaleString(undefined, { maximumFractionDigits: 0 })
          : "—"}
      </Term>
      <Term k="Exchange">{exchange}</Term>
      <Term k="Currency">{data.currency ?? "—"}</Term>
      <Term k="IPO">{ipo}</Term>
      <Term k="52w high">{fmtCurrency(data.fiftyTwoWeekHigh, data.currency)}</Term>
      <Term k="52w low">{fmtCurrency(data.fiftyTwoWeekLow, data.currency)}</Term>
    </>
  );
}

function CryptoSnapshotTerms({ data }: { data: DESData }) {
  return (
    <>
      <Term k="Rank">{data.rank != null ? `#${data.rank}` : "—"}</Term>
      <Term k="Symbol">{data.symbol ?? "—"}</Term>
      <Term k="Algorithm">{data.hashing_algorithm ?? "—"}</Term>
      <Term k="Block time">
        {data.block_time_in_minutes != null
          ? `${data.block_time_in_minutes} min`
          : "—"}
      </Term>
      <Term k="Genesis">{fmtDate(data.genesis_date)}</Term>
      <Term k="Circ supply">{fmtSupply(data.circulating_supply)}</Term>
      <Term k="Total supply">{fmtSupply(data.total_supply)}</Term>
      <Term k="Max supply">
        {data.max_supply == null ? "∞" : fmtSupply(data.max_supply)}
      </Term>
      <Term k="ATH">{fmtCurrency(data.all_time_high, "USD")}</Term>
      <Term k="ATH date">{fmtDate(data.all_time_high_date)}</Term>
      <Term k="ATL">{fmtCurrency(data.all_time_low, "USD")}</Term>
      <Term k="ATL date">{fmtDate(data.all_time_low_date)}</Term>
    </>
  );
}

function SnapshotMetric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "negative" | "accent" | "warn";
}) {
  const valueColor =
    tone === "positive"
      ? "var(--positive)"
      : tone === "negative"
        ? "var(--negative)"
        : tone === "accent"
          ? "var(--accent)"
          : tone === "warn"
            ? "var(--warn)"
            : "var(--text-display)";
  return (
    <div style={snapshotMetricStyle}>
      <span style={snapshotLabelStyle}>{label}</span>
      <span style={{ ...snapshotValueStyle, color: valueColor }}>{value}</span>
    </div>
  );
}

function DESStatusPanel({ data }: { data: DESData }) {
  const actions =
    data.next_actions ?? (data.nextAction ? [data.nextAction] : []);
  const providerErrors = data.provider_errors ?? [];
  return (
    <Card
      variant="elev-2"
      style={{
        borderColor: "color-mix(in srgb, var(--warn) 36%, var(--border-subtle))",
      }}
    >
      <CardHeader trailing={<Pill tone="warn">{data.status ?? "degraded"}</Pill>}>
        Data quality
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-8 u-text-12">
          <div className="u-text-primary">
            {data.reason ??
              "The function completed but did not return a full live profile."}
          </div>
          {actions.length ? (
            <div className="u-flex u-flex-wrap u-gap-6">
              {actions.slice(0, 3).map((action) => (
                <span key={action} style={actionPillStyle}>
                  {action}
                </span>
              ))}
            </div>
          ) : null}
          {providerErrors.length ? (
            <details style={providerErrorsStyle}>
              <summary style={providerErrorsSummaryStyle}>
                Provider errors ({providerErrors.length})
              </summary>
              <ul style={providerErrorsListStyle}>
                {providerErrors.slice(0, 6).map((err, i) => (
                  <li key={`${err}-${i}`} style={providerErrorsItemStyle}>
                    {err}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function Term({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="u-text-mute">{k}</dt>
      <dd style={dlValueStyle}>{children}</dd>
    </>
  );
}

// ----- styles -----

const symbolStripStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 14,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  flexWrap: "wrap",
};

const tickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 18,
  fontWeight: 700,
  letterSpacing: "0.04em",
  color: "var(--text-display)",
};

const nameStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--text-secondary)",
  maxWidth: 320,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const lastPriceStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 22,
  fontWeight: 600,
  color: "var(--text-display)",
  fontVariantNumeric: "tabular-nums",
};

const changeAbsStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  color: "var(--text-secondary)",
  fontVariantNumeric: "tabular-nums",
};

const metricsStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 8,
};

const snapshotMetricStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "10px 12px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  minWidth: 0,
};

const snapshotLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const snapshotValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 16,
  fontWeight: 600,
  fontVariantNumeric: "tabular-nums",
};

const mainGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
  gap: 12,
};

const summaryParagraphStyle: CSSProperties = {
  margin: 0,
  fontSize: 12,
  lineHeight: 1.55,
  color: "var(--text-secondary)",
};

const websiteRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginTop: 12,
  paddingTop: 10,
  borderTop: "1px solid var(--border-row)",
};

const websiteLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const websiteLinkStyle: CSSProperties = {
  color: "var(--accent)",
  fontSize: 11,
  fontFamily: "JetBrains Mono, monospace",
  textDecoration: "none",
};

const categoriesRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  marginTop: 10,
  paddingTop: 10,
  borderTop: "1px solid var(--border-row)",
};

const dlStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "120px 1fr",
  gap: "6px 12px",
  fontSize: 12,
  margin: 0,
};

const dlValueStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
};

const actionPillStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-secondary)",
  padding: "4px 7px",
  fontSize: 11,
};

const providerErrorsStyle: CSSProperties = {
  marginTop: 4,
  fontSize: 11,
  color: "var(--text-secondary)",
};

const providerErrorsSummaryStyle: CSSProperties = {
  cursor: "pointer",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};

const providerErrorsListStyle: CSSProperties = {
  margin: "6px 0 0 0",
  padding: "0 0 0 16px",
};

const providerErrorsItemStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  lineHeight: 1.5,
};
