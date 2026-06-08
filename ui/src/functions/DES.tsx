/**
 * DES — Description / company snapshot.
 *
 * Bloomberg-grade company detail with a chart-led header strip and
 * description-first body. Profile data via yfinance + finnhub feeds.
 */
import { type CSSProperties, useEffect, useRef, useState } from "react";
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
import { useLiveQuote, type TransportState } from "@/lib/market-data";
import { SymbolBar } from "@/shell/SymbolBar";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { XSenChip } from "./XSenChip";
import type { FunctionPaneProps } from "./registry-types";
import {
  formatCurrency,
  formatMissing,
  formatNumber,
  formatPercent,
  formatCompactNumber,
} from "@/lib/format";

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

// All numeric/currency/percent formatting now delegates to the shared
// `@/lib/format` source of truth (unified rounding + "—" sentinel). The
// previous ~6 bespoke local formatters were removed in the page-by-page pass.
const fmtNum = (n?: number | null) => formatNumber(n, 2);

const fmtMcap = (n?: number | null) =>
  formatCurrency(n, { compact: true, fractionDigits: 2 });

const fmtPct = (n?: number | null) => formatPercent(n, { digits: 2 });

const fmtSupply = (n?: number | null) => formatCompactNumber(n);

const fmtCurrency = (n?: number | null, currency?: string) =>
  formatCurrency(n, { currency: (currency || "USD").toUpperCase(), fractionDigits: 2 });

const fmtDate = (iso?: string | null) => {
  // No `@/lib/format` equivalent exists for dates — keep local. Accepts full
  // ISO timestamps or bare YYYY-MM-DD.
  if (!iso) return formatMissing;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10) || formatMissing;
  return d.toISOString().slice(0, 10);
};

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
  // UA-HIGH-27: previously `last != null && prev` accepted prev<0 (impossible
  // for a price) AND used JS truthiness so `prev === 0` got the null branch
  // but `prev === -0.0001` (impossible but cheap to guard) sailed through.
  // Tighten to "prev is a finite positive number" so we never return
  // ±Infinity / NaN for a corrupt payload.
  const changePct =
    profile?.regularMarketChangePercent ??
    (last != null && typeof prev === "number" && Number.isFinite(prev) && prev > 0
      ? ((last - prev) / prev) * 100
      : null);
  const change = last != null && prev != null ? last - prev : null;
  // S12 alignment (HP/GP already migrated): the prior `hasLive` flag was
  // derived from `payloadStatus === "ok"`, which is the same misleading
  // "real-time session" wording HP shipped before S12. Replace with the
  // canonical `useLiveQuote` transport state so the pill reports honest
  // RT LIVE / RECONNECTING / STALE / SNAPSHOT ONLY / OFFLINE.
  const liveQuote = useLiveQuote(effectiveSymbol, {
    enabled: !!effectiveSymbol,
  });
  const transportState: TransportState = liveQuote.transportState;
  const snapshotOnly =
    payloadStatus === "ok" && last != null && transportState === "idle";

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
              <TransportPill state={transportState} snapshotOnly={snapshotOnly} />
            </div>
            <QuoteHeaderValues
              last={last}
              change={change}
              changePct={changePct}
              currency={profile?.currency}
            />
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

/**
 * S12-aligned transport pill. Reports honest live-channel state instead
 * of the misleading legacy badge DES carried before this fix:
 *   - RT LIVE        — WebSocket open + ticking
 *   - RECONNECTING   — WS dropped, retrying
 *   - STALE          — last tick older than the channel's freshness budget
 *   - SNAPSHOT ONLY  — historical payload available, no live channel
 *   - OFFLINE        — no transport at all (default-symbol cold path)
 */
function TransportPill({
  state,
  snapshotOnly,
}: {
  state: TransportState;
  snapshotOnly: boolean;
}) {
  if (state === "live") {
    return (
      <span data-testid="des-transport-pill" data-state="live">
        <Pill tone="positive" variant="soft">RT LIVE</Pill>
      </span>
    );
  }
  if (state === "stale") {
    return (
      <span data-testid="des-transport-pill" data-state="stale">
        <Pill tone="warn" variant="soft">STALE</Pill>
      </span>
    );
  }
  if (state === "reconnecting" || state === "connecting") {
    return (
      <span data-testid="des-transport-pill" data-state={state}>
        <Pill tone="warn" variant="soft">RECONNECTING</Pill>
      </span>
    );
  }
  if (state === "offline" || state === "error") {
    return (
      <span data-testid="des-transport-pill" data-state="offline">
        <Pill tone="negative" variant="soft">OFFLINE</Pill>
      </span>
    );
  }
  if (snapshotOnly) {
    return (
      <span data-testid="des-transport-pill" data-state="snapshot">
        <Pill tone="warn" variant="soft">SNAPSHOT ONLY</Pill>
      </span>
    );
  }
  return null;
}

/**
 * Quote-header price + change cluster. The price flashes (reusing the shared
 * `.flash-pos` / `.flash-neg` keyframes) on each tick via a ref + effect keyed
 * on the value — the DOM node is stable (no remount) so the strip never
 * jitters. Price and absolute change carry `terminal-grid-numeric` (monospace
 * tabular figures) and the change is sign-coloured like the percent chip.
 */
function QuoteHeaderValues({
  last,
  change,
  changePct,
  currency,
}: {
  last: number | null;
  change: number | null;
  changePct: number | null;
  currency?: string;
}) {
  const priceRef = useRef<HTMLSpanElement>(null);
  const prevPriceRef = useRef<number | null>(null);

  useEffect(() => {
    const el = priceRef.current;
    if (!el || last == null) return;
    const prev = prevPriceRef.current;
    prevPriceRef.current = last;
    // No flash on the first paint or when the price is unchanged.
    if (prev == null || prev === last) return;
    const cls = last >= prev ? "flash-pos" : "flash-neg";
    el.classList.remove("flash-pos", "flash-neg");
    // Force reflow so the animation restarts on the same stable node.
    void el.offsetWidth;
    el.classList.add(cls);
  }, [last]);

  const changeColor =
    change == null
      ? "var(--text-secondary)"
      : change > 0
        ? "var(--positive)"
        : change < 0
          ? "var(--negative)"
          : "var(--text-secondary)";

  return (
    <div className="u-flex u-items-center u-gap-14">
      {last != null && (
        <span
          ref={priceRef}
          data-testid="des-last-price"
          className="terminal-grid-numeric"
          style={lastPriceStyle}
        >
          {fmtCurrency(last, currency)}
        </span>
      )}
      {changePct != null && (
        <DeltaChip value={changePct} format="percent" fractionDigits={2} />
      )}
      {change != null && (
        <span
          data-testid="des-change-abs"
          className="terminal-grid-numeric"
          style={{ ...changeAbsStyle, color: changeColor }}
        >
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)}
        </span>
      )}
    </div>
  );
}

/** Threshold past which a business summary is clamped behind a toggle. */
const SUMMARY_CLAMP_CHARS = 480;

/**
 * Business summary with a readability clamp. Long descriptions (a 2000-char
 * yfinance summary would otherwise blow out the pane) collapse to a few lines
 * with a "Show more" / "Show less" toggle. Short summaries render in full with
 * no affordance.
 */
function BusinessSummary({
  summary,
  fallback,
}: {
  summary: string | null;
  fallback: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const clampable = !!summary && summary.length > SUMMARY_CLAMP_CHARS;

  return (
    <>
      <p
        data-testid="des-summary"
        data-expanded={expanded ? "true" : "false"}
        style={
          clampable && !expanded
            ? { ...summaryParagraphStyle, ...summaryClampedStyle }
            : summaryParagraphStyle
        }
      >
        {summary ?? fallback}
      </p>
      {clampable && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="des-link"
          style={summaryToggleStyle}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </>
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
            <BusinessSummary
              summary={summary}
              fallback={
                crypto
                  ? "CoinGecko did not return a profile summary for this asset."
                  : "Provider did not return a business summary."
              }
            />
            {data.website && (
              <div style={websiteRowStyle}>
                <span style={websiteLabelStyle}>Website</span>
                <a
                  href={data.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Company website (opens in new tab)"
                  className="des-link"
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
                  aria-label="GitHub repository (opens in new tab)"
                  className="des-link"
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
  lineHeight: 1.6,
  color: "var(--text-secondary)",
  whiteSpace: "pre-line",
};

// Collapsed state: clamp to ~7 lines and fade nothing harshly — overflow is
// hidden and the toggle reveals the rest. Avoids a 2000-char wall of text.
const summaryClampedStyle: CSSProperties = {
  display: "-webkit-box",
  WebkitLineClamp: 7,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
  maxHeight: "calc(1.6em * 7)",
};

const summaryToggleStyle: CSSProperties = {
  marginTop: 8,
  padding: 0,
  background: "none",
  border: "none",
  cursor: "pointer",
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  letterSpacing: "0.04em",
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
