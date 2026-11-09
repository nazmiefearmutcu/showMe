/**
 * DES — Description / company snapshot.
 *
 * Bloomberg-grade company detail with an engine-led header strip
 * (`@/chart/Chart`, compact — canvas only, seeded 1D) and description-first
 * body. Profile data via yfinance + finnhub feeds.
 */
import { type CSSProperties, useEffect, useMemo, useState } from "react";
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
import { useTickFlash } from "@/design-system";
import { tickFlashClass } from "@/lib/tick-flash";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { useLiveQuote, type TransportState } from "@/lib/market-data";
import { SymbolBar } from "@/shell/SymbolBar";
import { Chart } from "@/chart/Chart";
import type { Bar } from "@/chart/types";
import { sidecarFetch } from "@/lib/sidecar";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import { XSenChip } from "./XSenChip";
import type { FunctionPaneProps } from "./registry-types";
import {
  formatCurrency,
  formatMissing,
  formatNumber,
  formatPercent,
  formatCompactNumber,
} from "@/lib/format";
import { safeHref } from "@/lib/safe-href";

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
  /** Crypto only: last price minus the 24h-ago price (USD). previousClose is null for crypto. */
  change_24h?: number | null;
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

/* ── display-density helpers ──────────────────────────────────────────
 * Missing-data fields are omitted from the pane entirely (owner report,
 * 2026-09-17): a grid of "—" cells and a dead-end "provider did not return…"
 * card read as broken. These helpers drop the missing sentinel at the
 * source, so the pane renders only provider-returned values — or nothing.
 */

type MetricTone = "neutral" | "positive" | "negative" | "accent" | "warn";

interface MetricDef {
  label: string;
  value: string;
  tone?: MetricTone;
}

interface SnapshotTerm {
  k: string;
  v: string;
}

/** Drop metric cells whose formatted value is the missing sentinel. */
function filterMissing(defs: MetricDef[]): MetricDef[] {
  return defs.filter((d) => d.value !== formatMissing);
}

/** Drop snapshot rows that have no provider value. */
function filterMissingTerms(
  terms: Array<{ k: string; v?: string | null }>,
): SnapshotTerm[] {
  return terms.filter((t): t is SnapshotTerm => !!t.v && t.v !== formatMissing);
}

/* ── index instruments ────────────────────────────────────────────────
 * Indices have no company fundamentals (no market cap, P/E, employees or
 * dividend). Instead of an all-"—" grid and a "provider did not return a
 * summary" dead end, the pane routes INDEX instruments to a client-side
 * snapshot computed from the chart engine's daily /api/bars and a curated,
 * factual profile line. Equities/ETFs/crypto are untouched.
 */

const DAY_MS = 86_400_000;

interface IndexProfile {
  name: string;
  line: string;
}

/** Curated factual one-liners — never a fabricated business description. */
const INDEX_PROFILES: Record<string, IndexProfile> = {
  "^GSPC": {
    name: "S&P 500",
    line: "S&P 500 — large-cap U.S. equity benchmark of 500 leading companies.",
  },
  "^NDX": {
    name: "Nasdaq 100",
    line: "Nasdaq 100 — 100 largest non-financial companies listed on Nasdaq.",
  },
  "^DJI": {
    name: "Dow Jones Industrial Average",
    line: "Dow Jones Industrial Average — 30 large U.S. blue-chip companies, price-weighted.",
  },
  "^RUT": {
    name: "Russell 2000",
    line: "Russell 2000 — U.S. small-cap benchmark tracking 2,000 smaller companies.",
  },
  "^GDAXI": {
    name: "DAX",
    line: "DAX — Germany's blue-chip index of 40 major Frankfurt-listed companies.",
  },
  "^FTSE": {
    name: "FTSE 100",
    line: "FTSE 100 — 100 largest companies listed on the London Stock Exchange.",
  },
  "^FCHI": {
    name: "CAC 40",
    line: "CAC 40 — France's benchmark index of 40 large Paris-listed companies.",
  },
  "^STOXX50E": {
    name: "Euro Stoxx 50",
    line: "Euro Stoxx 50 — 50 euro-area blue-chip companies across 11 countries.",
  },
  "^N225": {
    name: "Nikkei 225",
    line: "Nikkei 225 — Japan's price-weighted benchmark of 225 Tokyo-listed companies.",
  },
  "^HSI": {
    name: "Hang Seng",
    line: "Hang Seng — Hong Kong's benchmark of major Hong Kong-listed companies.",
  },
  "XU100.IS": {
    name: "BIST 100",
    line: "BIST 100 — Borsa Istanbul's benchmark index of the top 100 companies.",
  },
};

const INDEX_FALLBACK_PROFILE = "Index instrument — fundamentals not applicable";

function indexSymbolOf(symbol: string, data?: DESData): string {
  return String(data?.symbol || symbol || "").toUpperCase();
}

function isIndexInstrument(symbol: string, data?: DESData): boolean {
  const sym = indexSymbolOf(symbol, data);
  if (!sym) return false;
  const assetClass = String(data?.asset_class ?? "").toUpperCase();
  return (
    assetClass === "INDEX" ||
    sym.startsWith("^") ||
    Object.prototype.hasOwnProperty.call(INDEX_PROFILES, sym)
  );
}

function indexProfileLine(symbol: string): string {
  return INDEX_PROFILES[symbol.toUpperCase()]?.line ?? INDEX_FALLBACK_PROFILE;
}

interface IndexSnapshot {
  last: number | null;
  dayLow: number | null;
  dayHigh: number | null;
  low52: number | null;
  high52: number | null;
  r1m: number | null;
  r3m: number | null;
  r6m: number | null;
  ytd: number | null;
}

/**
 * Compute the honest index snapshot from daily bars: last close, latest
 * session range, trailing 52-week range and 1M/3M/6M/YTD returns. Returns
 * nulls when the inputs are missing — the UI renders "—", never a guess.
 */
export function computeIndexSnapshot(bars: Bar[]): IndexSnapshot {
  const empty: IndexSnapshot = {
    last: null,
    dayLow: null,
    dayHigh: null,
    low52: null,
    high52: null,
    r1m: null,
    r3m: null,
    r6m: null,
    ytd: null,
  };
  const sorted = (bars ?? [])
    .filter((b) => Number.isFinite(b?.t) && Number.isFinite(b?.c))
    .sort((a, b) => a.t - b.t);
  if (!sorted.length) return empty;
  const lastBar = sorted[sorted.length - 1];
  const last = lastBar.c;
  const trailing = sorted.filter((b) => b.t >= lastBar.t - 365 * DAY_MS);
  const high52 = trailing.length
    ? Math.max(...trailing.map((b) => b.h).filter(Number.isFinite))
    : null;
  const low52 = trailing.length
    ? Math.min(...trailing.map((b) => b.l).filter(Number.isFinite))
    : null;

  function returnFrom(cutoffMs: number): number | null {
    let ref: number | null = null;
    for (const bar of sorted) {
      if (bar.t > cutoffMs) break;
      if (Number.isFinite(bar.c)) ref = bar.c;
    }
    if (ref == null || ref === 0) return null;
    return (last / ref - 1) * 100;
  }

  const lastStamp = new Date(lastBar.t);
  const ytdStart = Date.UTC(lastStamp.getUTCFullYear(), 0, 1);
  return {
    last: Number.isFinite(last) ? last : null,
    dayLow: Number.isFinite(lastBar.l) ? lastBar.l : null,
    dayHigh: Number.isFinite(lastBar.h) ? lastBar.h : null,
    low52: low52 != null && Number.isFinite(low52) ? low52 : null,
    high52: high52 != null && Number.isFinite(high52) ? high52 : null,
    r1m: returnFrom(lastBar.t - 30 * DAY_MS),
    r3m: returnFrom(lastBar.t - 91 * DAY_MS),
    r6m: returnFrom(lastBar.t - 182 * DAY_MS),
    ytd: returnFrom(ytdStart - 1),
  };
}

interface BarsPayload {
  bars?: Bar[];
  source?: string;
  asOf?: string;
  reason?: string;
}

/** Daily bars from the chart-engine route for the index snapshot. */
function useIndexBars(symbol: string, enabled: boolean) {
  const [bars, setBars] = useState<Bar[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !symbol) return;
    let cancelled = false;
    setLoading(true);
    sidecarFetch<BarsPayload>(
      `/api/bars?symbol=${encodeURIComponent(symbol)}&interval=1D&limit=400`,
    )
      .then((res) => {
        if (cancelled) return;
        setBars(Array.isArray(res.bars) ? res.bars : []);
        setSource(res.source ?? null);
        setAsOf(res.asOf ?? null);
        setReason(res.reason ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setBars([]);
        setSource(null);
        setAsOf(null);
        setReason(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, enabled]);

  return { bars, source, asOf, reason, loading };
}

function returnTone(value: number | null): "positive" | "negative" | "neutral" {
  if (value == null) return "neutral";
  return value >= 0 ? "positive" : "negative";
}

function fmtRange(low: number | null, high: number | null, currency?: string): string {
  if (low == null || high == null) return formatMissing;
  return `${fmtCurrency(low, currency)} – ${fmtCurrency(high, currency)}`;
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
  // ASOF-9: crypto has no previousClose; its absolute change is the declared 24h rolling
  // change (change_24h), never a derived prior close.
  const change24h =
    typeof profile?.change_24h === "number" && Number.isFinite(profile.change_24h)
      ? profile.change_24h
      : null;
  const change =
    last != null && prev != null ? last - prev : change24h;
  // S12 alignment (HP/GP already migrated): the prior `hasLive` flag was
  // derived from `payloadStatus === "ok"`, which is the same misleading
  // "real-time session" wording HP shipped before S12. Replace with the
  // canonical `useLiveQuote` transport state so the pill reports honest
  // RT LIVE / RECONNECTING / STALE / SNAPSHOT ONLY / OFFLINE.
  const liveQuote = useLiveQuote(effectiveSymbol, {
    enabled: !!effectiveSymbol,
  });
  const transportState: TransportState = liveQuote.transportState;
  const snapshotOnly = payloadStatus === "ok" && last != null && transportState === "idle";
  const indexInstrument = isIndexInstrument(effectiveSymbol, profile);
  const indexName = INDEX_PROFILES[effectiveSymbol.toUpperCase()]?.name;

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
    <DESView data={profile} symbol={effectiveSymbol} />
  );

  // No answering provider is a state of its own, not a request still in flight.
  const provider =
    data?.sources?.[0] ??
    (payloadStatus === "provider_unavailable" ? "unavailable" : "pending");
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
            indexName ||
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
                  .join(" · ") || (indexInstrument ? "Index" : "Description")
              : "Description"
          }
          trailing={
            <FunctionControlGroup>
              <XSenChip symbol={effectiveSymbol} compact />
              {indexInstrument ? (
                <span data-testid="des-index-pill">
                  <Pill tone="accent" variant="soft" withDot={false}>
                    INDEX SNAPSHOT
                  </Pill>
                </span>
              ) : (
                <LoadStatePill state={state} status={payloadStatus} />
              )}
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
                <span style={nameStyle} title={profile?.longName || profile?.shortName}>
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
            <div style={stripChartStyle}>
              <Chart
                symbol={effectiveSymbol}
                compact
                height={170}
                layoutScope={code.toUpperCase()}
                initialInterval="1D"
              />
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
        <Pill tone="positive" variant="soft">
          RT LIVE
        </Pill>
      </span>
    );
  }
  if (state === "stale") {
    return (
      <span data-testid="des-transport-pill" data-state="stale">
        <Pill tone="warn" variant="soft">
          STALE
        </Pill>
      </span>
    );
  }
  if (state === "reconnecting" || state === "connecting") {
    return (
      <span data-testid="des-transport-pill" data-state={state}>
        <Pill tone="warn" variant="soft">
          RECONNECTING
        </Pill>
      </span>
    );
  }
  if (state === "offline" || state === "error") {
    return (
      <span data-testid="des-transport-pill" data-state="offline">
        <Pill tone="negative" variant="soft">
          OFFLINE
        </Pill>
      </span>
    );
  }
  if (snapshotOnly) {
    return (
      <span data-testid="des-transport-pill" data-state="snapshot">
        <Pill tone="warn" variant="soft">
          SNAPSHOT ONLY
        </Pill>
      </span>
    );
  }
  return null;
}

/**
 * Quote-header price + change cluster. The price pulses with the shared
 * themed flash classes (`useTickFlash` → `.flash-pos` / `.flash-neg`) on each
 * tick — no first-render flash, no flash on unchanged values, no extra DOM
 * wrapper (the stable span keeps its testid + tabular-numerics class).
 * Price and absolute change carry `terminal-grid-numeric` (monospace tabular
 * figures) and the change is sign-coloured like the percent chip.
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
  const flash = useTickFlash(last);
  const flashClass = tickFlashClass(flash);

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
          data-testid="des-last-price"
          className={`terminal-grid-numeric${flashClass ? ` ${flashClass}` : ""}`}
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
          {change >= 0 ? "+" : "−"}
          {fmtCurrency(Math.abs(change), currency)}
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
 *
 * Missing-data density (2026-09-17): callers render this only when a real
 * summary exists — there is no dead-end "provider did not return…" fallback.
 */
function BusinessSummary({ summary }: { summary: string }) {
  const [expanded, setExpanded] = useState(false);
  const clampable = summary.length > SUMMARY_CLAMP_CHARS;

  const summaryId = "des-business-summary";

  return (
    <>
      <p
        id={summaryId}
        data-testid="des-summary"
        data-expanded={expanded ? "true" : "false"}
        style={
          clampable && !expanded
            ? { ...summaryParagraphStyle, ...summaryClampedStyle }
            : summaryParagraphStyle
        }
      >
        {summary}
      </p>
      {clampable && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={summaryId}
          className="des-link"
          style={summaryToggleStyle}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </>
  );
}

function DESView({ data, symbol }: { data?: DESData; symbol: string }) {
  if (!data) return <Empty title="No description data" />;
  // Indices: no company fundamentals exist. Render the honest client-side
  // snapshot + curated profile line instead of the all-"-" equity grid and
  // the "provider did not return a business summary" dead end.
  if (isIndexInstrument(symbol, data)) {
    return <IndexView data={data} symbol={indexSymbolOf(symbol, data)} />;
  }
  const summary = data.longBusinessSummary ?? data.description ?? null;
  const degraded = data.status && data.status !== "ok";
  const crypto = isCryptoProfile(data);

  // Missing-data density (owner, 2026-09-17): cells and panels with no value
  // are omitted entirely — never a wall of "-" placeholders or a dead-end
  // "provider did not return…" card. Only real provider data is rendered.
  const snapshotTerms = crypto ? cryptoSnapshotTerms(data) : equitySnapshotTerms(data);
  const hasSummaryCard =
    !!summary ||
    !!data.website ||
    (crypto && (!!data.github_repo || (data.categories?.length ?? 0) > 0));
  const hasGrid = hasSummaryCard || snapshotTerms.length > 0;

  return (
    <div className="u-grid-gap-12">
      {degraded ? <DESStatusPanel data={data} /> : null}
      {crypto ? <CryptoMetrics data={data} /> : <EquityMetrics data={data} />}

      {hasGrid ? (
        <div
          style={
            hasSummaryCard && snapshotTerms.length > 0
              ? mainGridStyle
              : singleColumnGridStyle
          }
        >
          {hasSummaryCard ? (
            <Card>
              <CardHeader
                trailing={
                  summary ? (
                    <Pill tone="muted" withDot={false}>
                      {summary.length.toLocaleString("en-US")} chars
                    </Pill>
                  ) : null
                }
              >
                {crypto ? "About the asset" : "Business summary"}
              </CardHeader>
              <CardBody>
                {summary ? <BusinessSummary summary={summary} /> : null}
                {safeHref(data.website) && (
                  <div style={websiteRowStyle}>
                    <span style={websiteLabelStyle}>Website</span>
                    <a
                      href={safeHref(data.website)}
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
                {crypto && safeHref(data.github_repo) && (
                  <div style={websiteRowStyle}>
                    <span style={websiteLabelStyle}>Repo</span>
                    <a
                      href={safeHref(data.github_repo)}
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
          ) : null}

          {snapshotTerms.length > 0 ? (
            <Card>
              <CardHeader>Snapshot</CardHeader>
              <CardBody>
                <dl style={dlStyle}>
                  {snapshotTerms.map((t) => (
                    <Term key={t.k} k={t.k}>
                      {t.v}
                    </Term>
                  ))}
                </dl>
              </CardBody>
            </Card>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * INDEX branch — a factual snapshot computed from the chart engine's daily
 * bars (the same /api/bars route the embedded chart uses) plus a curated
 * index profile line. Never invents a business summary and never renders an
 * all-"—" fundamentals grid.
 */
function IndexView({ data, symbol }: { data?: DESData; symbol: string }) {
  const { bars, source, asOf, reason, loading } = useIndexBars(symbol, true);
  const snapshot = useMemo(() => computeIndexSnapshot(bars), [bars]);
  const currency = data?.currency ?? "USD";
  const indexName = INDEX_PROFILES[symbol.toUpperCase()]?.name;

  const note =
    loading && bars.length === 0
      ? "Loading daily bars…"
      : bars.length === 0
        ? `Index snapshot unavailable${reason ? ` — ${reason}` : ""}`
        : `Index snapshot — computed from daily bars${source ? ` · ${source}` : ""}${
            asOf ? ` · as of ${asOf.slice(0, 10)}` : ""
          }`;

  // Missing-data density (owner, 2026-09-17): a failed/partial snapshot
  // renders no empty metric cells or placeholder rows — only real values.
  const shownMetrics: MetricDef[] = filterMissing([
    { label: "Last", value: fmtCurrency(snapshot.last, currency), tone: "accent" },
    { label: "Day range", value: fmtRange(snapshot.dayLow, snapshot.dayHigh, currency) },
    { label: "52w range", value: fmtRange(snapshot.low52, snapshot.high52, currency) },
    { label: "1M", value: fmtPct(snapshot.r1m), tone: returnTone(snapshot.r1m) },
    { label: "3M", value: fmtPct(snapshot.r3m), tone: returnTone(snapshot.r3m) },
    { label: "6M", value: fmtPct(snapshot.r6m), tone: returnTone(snapshot.r6m) },
    { label: "YTD", value: fmtPct(snapshot.ytd), tone: returnTone(snapshot.ytd) },
  ]);
  const indexTerms = filterMissingTerms([
    { k: "Index", v: indexName ?? symbol },
    { k: "Symbol", v: symbol },
    { k: "Currency", v: currency },
    { k: "Bars", v: bars.length ? bars.length.toLocaleString("en-US") : null },
    { k: "Source", v: source },
    { k: "As of", v: asOf ? asOf.slice(0, 10) : null },
  ]);

  return (
    <div className="u-grid-gap-12">
      {shownMetrics.length > 0 ? (
        <div style={metricsStripStyle} data-testid="des-index-snapshot">
          {shownMetrics.map((m) => (
            <SnapshotMetric key={m.label} label={m.label} value={m.value} tone={m.tone} />
          ))}
        </div>
      ) : null}

      <p style={indexNoteStyle} data-testid="des-index-note">
        {note}
      </p>

      <div style={mainGridStyle}>
        <Card>
          <CardHeader
            trailing={
              <Pill tone="muted" withDot={false}>
                index
              </Pill>
            }
          >
            Index profile
          </CardHeader>
          <CardBody>
            <p data-testid="des-index-profile" style={summaryParagraphStyle}>
              {indexProfileLine(symbol)}
            </p>
            <p style={indexMutedNoteStyle}>
              Indices have no company fundamentals — market cap, P/E, employees and dividend
              fields are not applicable by definition.
            </p>
          </CardBody>
        </Card>

        {indexTerms.length > 0 ? (
          <Card>
            <CardHeader>Snapshot</CardHeader>
            <CardBody>
              <dl style={dlStyle}>
                {indexTerms.map((t) => (
                  <Term key={t.k} k={t.k}>
                    {t.v}
                  </Term>
                ))}
              </dl>
            </CardBody>
          </Card>
        ) : null}
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
  // Missing-data density (owner, 2026-09-17): cells the provider left empty
  // are dropped, not rendered as "-" cards. All-missing -> no strip at all.
  const shown: MetricDef[] = filterMissing([
    { label: "Market cap", value: fmtMcap(marketCap), tone: "accent" },
    { label: "P/E (TTM)", value: fmtNum(data.trailingPE) },
    { label: "Forward P/E", value: fmtNum(data.forwardPE) },
    {
      label: "Beta",
      value: fmtNum(data.beta),
      tone:
        data.beta != null && Number.isFinite(data.beta) && data.beta > 1.2
          ? "warn"
          : "neutral",
    },
    { label: "Dividend yield", value: fmtPct(dividendPct), tone: "positive" },
    { label: "52w high", value: fmtCurrency(data.fiftyTwoWeekHigh, data.currency) },
    { label: "52w low", value: fmtCurrency(data.fiftyTwoWeekLow, data.currency) },
  ]);
  if (shown.length === 0) return null;
  return (
    <div style={metricsStripStyle}>
      {shown.map((m) => (
        <SnapshotMetric key={m.label} label={m.label} value={m.value} tone={m.tone} />
      ))}
    </div>
  );
}

function CryptoMetrics({ data }: { data: DESData }) {
  const marketCap = data.marketCap ?? data.market_cap;
  const last = data.regularMarketPrice ?? data.currentPrice ?? data.price ?? null;
  const changePct = data.regularMarketChangePercent ?? null;
  const shown: MetricDef[] = filterMissing([
    { label: "Market cap", value: fmtMcap(marketCap), tone: "accent" },
    { label: "Last price", value: fmtCurrency(last, "USD") },
    {
      label: "24h change",
      value: fmtPct(changePct),
      tone: changePct != null ? (changePct >= 0 ? "positive" : "negative") : "neutral",
    },
    { label: "All-time high", value: fmtCurrency(data.all_time_high, "USD") },
    { label: "All-time low", value: fmtCurrency(data.all_time_low, "USD") },
    { label: "Circ supply", value: fmtSupply(data.circulating_supply) },
    {
      label: "Max supply",
      value: data.max_supply == null ? "∞" : fmtSupply(data.max_supply),
    },
  ]);
  if (shown.length === 0) return null;
  return (
    <div style={metricsStripStyle}>
      {shown.map((m) => (
        <SnapshotMetric key={m.label} label={m.label} value={m.value} tone={m.tone} />
      ))}
    </div>
  );
}

/**
 * Equity snapshot terms as data. Missing values are dropped — the pane never
 * renders a "—" row (owner, 2026-09-17); only provider-returned fields show.
 */
function equitySnapshotTerms(data: DESData): SnapshotTerm[] {
  const employees = data.fullTimeEmployees ?? data.employees;
  const hq =
    data.headquarters ?? ([data.city, data.country].filter(Boolean).join(", ") || null);
  return filterMissingTerms([
    { k: "Sector", v: data.sector },
    { k: "Industry", v: data.industry },
    { k: "HQ", v: hq },
    {
      k: "Employees",
      v:
        employees != null
          ? Number(employees).toLocaleString("en-US", {
              maximumFractionDigits: 0,
            })
          : null,
    },
    { k: "Exchange", v: data.exchange_name ?? data.exchange },
    { k: "Currency", v: data.currency },
    { k: "IPO", v: data.ipoDate ?? data.ipo_date },
    { k: "52w high", v: fmtCurrency(data.fiftyTwoWeekHigh, data.currency) },
    { k: "52w low", v: fmtCurrency(data.fiftyTwoWeekLow, data.currency) },
  ]);
}

function cryptoSnapshotTerms(data: DESData): SnapshotTerm[] {
  return filterMissingTerms([
    { k: "Rank", v: data.rank != null ? `#${data.rank}` : null },
    { k: "Symbol", v: data.symbol },
    { k: "Algorithm", v: data.hashing_algorithm },
    {
      k: "Block time",
      v: data.block_time_in_minutes != null ? `${data.block_time_in_minutes} min` : null,
    },
    { k: "Genesis", v: fmtDate(data.genesis_date) },
    { k: "Circ supply", v: fmtSupply(data.circulating_supply) },
    { k: "Total supply", v: fmtSupply(data.total_supply) },
    {
      k: "Max supply",
      v: data.max_supply == null ? "∞" : fmtSupply(data.max_supply),
    },
    { k: "ATH", v: fmtCurrency(data.all_time_high, "USD") },
    { k: "ATH date", v: fmtDate(data.all_time_high_date) },
    { k: "ATL", v: fmtCurrency(data.all_time_low, "USD") },
    { k: "ATL date", v: fmtDate(data.all_time_low_date) },
  ]);
}

function SnapshotMetric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: MetricTone;
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
  const actions = data.next_actions ?? (data.nextAction ? [data.nextAction] : []);
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

// Full-width row inside the wrapped header strip: the compact engine chart
// sits under the ticker/quote row.
const stripChartStyle: CSSProperties = {
  flexBasis: "100%",
  width: "100%",
  minWidth: 0,
};

const tickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xl)",
  fontWeight: 700,
  letterSpacing: "0.04em",
  color: "var(--text-display)",
};

const nameStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  color: "var(--text-secondary)",
  maxWidth: 320,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const lastPriceStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-3xl)",
  fontWeight: 600,
  color: "var(--text-display)",
  fontVariantNumeric: "tabular-nums",
};

const changeAbsStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
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
  fontSize: "var(--font-size-xs)",
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

// One-card layout (summary or snapshot card missing entirely): a single
// column so the surviving card never leaves an empty half-grid behind
// (owner, 2026-09-17).
const singleColumnGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr)",
  gap: 12,
};

const summaryParagraphStyle: CSSProperties = {
  margin: 0,
  fontSize: "var(--font-size-md)",
  lineHeight: 1.6,
  color: "var(--text-secondary)",
  whiteSpace: "pre-line",
};

const indexNoteStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
  fontFamily: "JetBrains Mono, monospace",
};

const indexMutedNoteStyle: CSSProperties = {
  margin: "10px 0 0 0",
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.5,
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
  fontSize: "var(--font-size-sm)",
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
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const websiteLinkStyle: CSSProperties = {
  color: "var(--accent)",
  fontSize: "var(--font-size-sm)",
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
  fontSize: "var(--font-size-md)",
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
  fontSize: "var(--font-size-sm)",
};

const providerErrorsStyle: CSSProperties = {
  marginTop: 4,
  fontSize: "var(--font-size-sm)",
  color: "var(--text-secondary)",
};

const providerErrorsSummaryStyle: CSSProperties = {
  cursor: "pointer",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};

const providerErrorsListStyle: CSSProperties = {
  margin: "6px 0 0 0",
  padding: "0 0 0 16px",
};

const providerErrorsItemStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  lineHeight: 1.5,
};
