/**
 * ANR — Analyst Recommendations.
 *
 * Consensus-first view with explicit target-price provenance, stale-rule
 * accounting, broker-level table readiness, and local alert editing.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  DataGrid,
  Empty,
  Field,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  type DataGridColumn,
} from "@/design-system";
import { SymbolBar } from "@/shell/SymbolBar";
import { useFunction } from "@/lib/useFunction";
import { toast } from "@/lib/toast";
import { listRecentSymbols } from "@/lib/symbols";
import {
  fetchVeryfinderQuery,
  normalizeVeryfinderSample,
  recommendedVeryfinderSampleForSymbol,
  type VeryfinderOverlay,
  type VeryfinderPost,
  type VeryfinderTone,
} from "@/lib/veryfinder";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface ANRSummary {
  title?: string;
  asset_class?: string;
  consensus_kind?: string;
  count_label?: string;
  signal_count?: number;
  analyst_count?: number;
  consensus_score?: number | null;
  label?: string;
  positive_pct?: number;
  neutral_pct?: number;
  negative_pct?: number;
  last_updated?: string | null;
  included_count?: number;
  excluded_stale_count?: number;
  oldest_included_rating_date?: string | null;
  target_price_source?: string;
  target_price_source_mode?: string;
  not_analyst_target?: boolean;
  analyst_detail_status?: string;
  consensus_source?: string;
}

interface AnalystRow {
  broker?: string;
  analyst?: string;
  rating?: string;
  previous_rating?: string;
  action?: string;
  target_price?: number | string | null;
  target_period?: string;
  date?: string;
  last_update?: string;
}

interface SignalRow {
  source?: string;
  signal?: string;
  value?: string | number | null;
  score?: number;
  weight?: number;
  weighted_score?: number;
  explanation?: string;
}

interface BucketRow {
  bucket?: string;
  count?: number;
  sentiment_score?: number;
  pct_of_consensus?: number;
}

interface TargetRow {
  metric?: string;
  price?: number | null;
  source_mode?: string;
  not_analyst_target?: boolean;
}

interface StaleRule {
  rule_type?: string;
  cutoff_days?: number;
  cutoff_date?: string;
  included_count?: number;
  excluded_stale_count?: number;
  oldest_included_rating_date?: string | null;
  oldest_stale_rating_date?: string | null;
  undated_provider_rows?: number;
  latest_market_data_at?: string | null;
  rule?: string;
}

interface SourceDetail {
  name?: string;
  status?: string;
  asOf?: string | null;
  fields?: string;
}

interface ANRData {
  status?: string;
  symbol?: string;
  summary?: ANRSummary;
  rows?: AnalystRow[];
  analyst_rows?: AnalystRow[];
  signal_rows?: SignalRow[];
  analyst_detail_status?: string;
  analyst_detail_reason?: string;
  bucket_rows?: BucketRow[];
  target_rows?: TargetRow[];
  target_price_source?: {
    mode?: string;
    label?: string;
    display_name?: string;
    not_analyst_target?: boolean;
  };
  stale_rule?: StaleRule;
  source_details?: SourceDetail[];
  spot?: number | null;
  methodology?: string;
  field_dictionary?: Record<string, string>;
  analyst_quality?: Record<string, unknown>;
}

type AlertRule = "label_change" | "score_below" | "score_above" | "positive_pct_below";
type ANRScreen = "overview" | "analysis";
type VeryfinderRunState = "idle" | "loading" | "refreshing" | "ok" | "error";

const ANR_SCREEN_OPTIONS = [
  { value: "overview", label: "Overview" },
  { value: "analysis", label: "Analysis" },
] as const;

const VERYFINDER_LIVE_REFRESH_MS = 30_000;
const VERYFINDER_BACKGROUND_REFRESH_MS = 60_000;
const BACKGROUND_VERYFINDER_REFRESHED_AT = new Map<string, number>();

export function ANRPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || "AMZN";
  const recommendedTweetSample = recommendedVeryfinderSampleForSymbol(effectiveSymbol);
  const [veryfinderEnabled, setVeryfinderEnabled] = useState(true);
  const [veryfinderSource, setVeryfinderSource] = useState("auto");
  const [veryfinderMinTweets, setVeryfinderMinTweets] = useState(recommendedTweetSample);
  const [veryfinderMinTweetsInput, setVeryfinderMinTweetsInput] = useState(String(recommendedTweetSample));
  const [veryfinderTick, setVeryfinderTick] = useState(0);
  const [veryfinderState, setVeryfinderState] = useState<VeryfinderRunState>("idle");
  const [veryfinderData, setVeryfinderData] = useState<VeryfinderOverlay | null>(null);
  const [veryfinderError, setVeryfinderError] = useState<string | null>(null);
  const [veryfinderStartedAt, setVeryfinderStartedAt] = useState<string | null>(null);
  const [veryfinderUpdatedAt, setVeryfinderUpdatedAt] = useState<string | null>(null);
  const [veryfinderLiveRefreshCount, setVeryfinderLiveRefreshCount] = useState(0);
  const manualVeryfinderRun = useRef(false);
  const veryfinderInFlight = useRef(false);
  const veryfinderRequestId = useRef(0);
  const { state, data, error, refetch } = useFunction<ANRData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
  });
  const summary = data?.data?.summary;
  const sourceText = formatSources(data?.sources);

  useEffect(() => {
    const next = recommendedVeryfinderSampleForSymbol(effectiveSymbol);
    setVeryfinderMinTweets(next);
    setVeryfinderMinTweetsInput(String(next));
  }, [effectiveSymbol]);

  const runVeryfinderFetch = useCallback((options?: { manual?: boolean; refresh?: boolean; background?: boolean }) => {
    if (!veryfinderEnabled || !effectiveSymbol) {
      veryfinderRequestId.current += 1;
      veryfinderInFlight.current = false;
      setVeryfinderState("idle");
      setVeryfinderData(null);
      setVeryfinderError(null);
      setVeryfinderStartedAt(null);
      setVeryfinderUpdatedAt(null);
      return;
    }
    if (!options?.manual && veryfinderInFlight.current) return;
    const requestId = veryfinderRequestId.current + 1;
    veryfinderRequestId.current = requestId;
    veryfinderInFlight.current = true;
    const started = new Date().toISOString();
    const manual = Boolean(options?.manual);
    const background = Boolean(options?.background);
    setVeryfinderState((current) => (background && (current === "ok" || current === "refreshing") ? "refreshing" : "loading"));
    setVeryfinderStartedAt(started);
    setVeryfinderError(null);
    fetchVeryfinderQuery({
      symbol: effectiveSymbol,
      sample: veryfinderMinTweets,
      source: veryfinderSource,
      engine: "rules",
      refresh: Boolean(options?.refresh),
    })
      .then((payload) => {
        if (requestId !== veryfinderRequestId.current) return;
        setVeryfinderData(payload);
        setVeryfinderState(payload.ok ? "ok" : "error");
        setVeryfinderError(payload.ok ? null : payload.error ?? "Veryfinder unavailable");
        if (payload.ok) {
          setVeryfinderUpdatedAt(payload.refreshed_at ?? new Date().toISOString());
          if (options?.refresh) setVeryfinderLiveRefreshCount((count) => count + 1);
        }
        if (manual && payload.ok) notifyVeryfinderComplete(effectiveSymbol, payload);
      })
      .catch((err) => {
        if (requestId !== veryfinderRequestId.current) return;
        setVeryfinderState("error");
        setVeryfinderError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (requestId === veryfinderRequestId.current) {
          veryfinderInFlight.current = false;
        }
      });
  }, [effectiveSymbol, veryfinderEnabled, veryfinderMinTweets, veryfinderSource]);

  useEffect(() => {
    const manual = manualVeryfinderRun.current;
    manualVeryfinderRun.current = false;
    runVeryfinderFetch({ manual, refresh: manual });
  }, [runVeryfinderFetch, veryfinderTick]);

  useEffect(() => {
    if (!veryfinderEnabled || !effectiveSymbol) return;
    const timer = window.setInterval(() => {
      runVeryfinderFetch({ refresh: true, background: true });
    }, VERYFINDER_LIVE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [effectiveSymbol, runVeryfinderFetch, veryfinderEnabled]);

  useEffect(() => {
    if (!veryfinderEnabled) return;
    const refreshBackgroundSymbols = () => {
      const symbols = listRecentSymbols()
        .filter((item) => item && item !== effectiveSymbol)
        .slice(0, 10);
      const now = Date.now();
      symbols.forEach((item, index) => {
        const sample = recommendedVeryfinderSampleForSymbol(item);
        const key = `${item}:${sample}:${veryfinderSource}`;
        const last = BACKGROUND_VERYFINDER_REFRESHED_AT.get(key) ?? 0;
        if (now - last < VERYFINDER_BACKGROUND_REFRESH_MS) return;
        BACKGROUND_VERYFINDER_REFRESHED_AT.set(key, now);
        window.setTimeout(() => {
          fetchVeryfinderQuery({
            symbol: item,
            sample,
            source: veryfinderSource,
            engine: "rules",
            refresh: true,
          }).catch(() => {
            BACKGROUND_VERYFINDER_REFRESHED_AT.delete(key);
          });
        }, index * 300);
      });
    };
    const warmup = window.setTimeout(refreshBackgroundSymbols, 500);
    const timer = window.setInterval(refreshBackgroundSymbols, VERYFINDER_BACKGROUND_REFRESH_MS);
    return () => {
      window.clearTimeout(warmup);
      window.clearInterval(timer);
    };
  }, [effectiveSymbol, veryfinderEnabled, veryfinderSource]);

  const runVeryfinderTweetSearch = () => {
    const next = clampTweetSample(veryfinderMinTweetsInput);
    manualVeryfinderRun.current = true;
    setVeryfinderMinTweets(next);
    setVeryfinderMinTweetsInput(String(next));
    setVeryfinderTick((tick) => tick + 1);
  };

  const body =
    state === "loading" || state === "idle" ? (
      <div style={{ display: "grid", gap: 10 }}>
        <Skeleton height={72} />
        <Skeleton height={160} />
        <Skeleton height={160} />
      </div>
    ) : state === "error" ? (
      <Empty
        title="Function error"
        body={error?.message ?? "ANR failed."}
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : data?.data?.status && data.data.status !== "ok" ? (
      <Empty title="ANR unavailable" body={String(data.data.status)} icon="!" />
    ) : (
      <ANRView
        data={data?.data}
        symbol={effectiveSymbol}
        functionSources={data?.sources ?? []}
        warnings={data?.warnings?.map(String) ?? []}
        elapsedMs={data?.elapsed_ms ?? undefined}
        veryfinderEnabled={veryfinderEnabled}
        veryfinder={veryfinderData}
        veryfinderState={veryfinderState}
        veryfinderError={veryfinderError}
        veryfinderMinTweets={veryfinderMinTweets}
        veryfinderMinTweetsInput={veryfinderMinTweetsInput}
        veryfinderRecommendedTweets={recommendedTweetSample}
        veryfinderSource={veryfinderSource}
        veryfinderStartedAt={veryfinderStartedAt}
        veryfinderUpdatedAt={veryfinderUpdatedAt}
        veryfinderLiveRefreshCount={veryfinderLiveRefreshCount}
        onVeryfinderMinTweetsInputChange={setVeryfinderMinTweetsInput}
        onVeryfinderTweetSearch={runVeryfinderTweetSearch}
      />
    );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={`${effectiveSymbol} ${isCryptoSummary(summary) ? "Crypto Market Consensus" : "Analyst Consensus"}`}
          subtitle={`${summary?.label ?? "loading"} · target: ${summary?.target_price_source ?? "—"}`}
          trailing={
            <FunctionControlGroup>
              <label style={veryfinderToggleStyle} title="Show Veryfinder social overlay beside ANR consensus">
                <input
                  type="checkbox"
                  checked={veryfinderEnabled}
                  onChange={(event) => setVeryfinderEnabled(event.target.checked)}
                />
                VF
              </label>
              <select
                value={veryfinderSource}
                onChange={(event) => setVeryfinderSource(event.target.value)}
                disabled={!veryfinderEnabled}
                title="Veryfinder source"
                style={miniSelectStyle}
              >
                <option value="auto">auto</option>
                <option value="fixture">fixture</option>
                <option value="official">x api</option>
              </select>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={() => {
                  refetch();
                  setVeryfinderTick((tick) => tick + 1);
                }}
                disabled={!effectiveSymbol}
                title="Refresh analyst recommendations"
              />
            </FunctionControlGroup>
          }
          help={
            <div style={{ display: "grid", gap: 8 }}>
              <strong style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
                ANR · Analyst Recommendations
              </strong>
              <span style={{ color: "var(--text-secondary)" }}>
                Shows consensus score, bucket distribution, target-price source, stale exclusions,
                broker-level table status, crypto signal inputs, and editable local recommendation-alert rules.
              </span>
              <span style={{ color: "var(--text-mute)" }}>
                Equity ratings older than one year are excluded from consensus. Crypto ANR is a labelled
                market-data proxy; reference bands are not analyst targets.
              </span>
            </div>
          }
        />
        <SymbolBar code={code} symbol={effectiveSymbol} />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <span data-testid="function-status">{data?.data?.status ?? data?.status ?? state}</span>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span data-testid="function-source" title={sourceText} style={footerSourceStyle}>
            sources · {sourceText}
          </span>
          {data?.warnings?.length ? <span>warnings · {data.warnings.length}</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function ANRView({
  data,
  symbol,
  functionSources,
  warnings,
  elapsedMs,
  veryfinderEnabled,
  veryfinder,
  veryfinderState,
  veryfinderError,
  veryfinderMinTweets,
  veryfinderMinTweetsInput,
  veryfinderRecommendedTweets,
  veryfinderSource,
  veryfinderStartedAt,
  veryfinderUpdatedAt,
  veryfinderLiveRefreshCount,
  onVeryfinderMinTweetsInputChange,
  onVeryfinderTweetSearch,
}: {
  data?: ANRData;
  symbol: string;
  functionSources: string[];
  warnings: string[];
  elapsedMs?: number;
  veryfinderEnabled: boolean;
  veryfinder: VeryfinderOverlay | null;
  veryfinderState: VeryfinderRunState;
  veryfinderError: string | null;
  veryfinderMinTweets: number;
  veryfinderMinTweetsInput: string;
  veryfinderRecommendedTweets: number;
  veryfinderSource: string;
  veryfinderStartedAt: string | null;
  veryfinderUpdatedAt: string | null;
  veryfinderLiveRefreshCount: number;
  onVeryfinderMinTweetsInputChange: (value: string) => void;
  onVeryfinderTweetSearch: () => void;
}) {
  const [screen, setScreen] = useState<ANRScreen>("overview");
  if (!data) return <Empty title="Payload unavailable" />;
  const summary = data.summary ?? {};
  const analystRows = data.analyst_rows ?? data.rows ?? [];
  const crypto = isCryptoSummary(summary);
  const content = screen === "analysis" ? (
    <ANRAnalysisScreen
      data={data}
      symbol={symbol}
      crypto={crypto}
      analystRows={analystRows}
      functionSources={functionSources}
      warnings={warnings}
      elapsedMs={elapsedMs}
      veryfinderEnabled={veryfinderEnabled}
      veryfinder={veryfinder}
      veryfinderState={veryfinderState}
      veryfinderError={veryfinderError}
      veryfinderMinTweets={veryfinderMinTweets}
      veryfinderMinTweetsInput={veryfinderMinTweetsInput}
      veryfinderRecommendedTweets={veryfinderRecommendedTweets}
      veryfinderSource={veryfinderSource}
      veryfinderStartedAt={veryfinderStartedAt}
      veryfinderUpdatedAt={veryfinderUpdatedAt}
      veryfinderLiveRefreshCount={veryfinderLiveRefreshCount}
      onVeryfinderMinTweetsInputChange={onVeryfinderMinTweetsInputChange}
      onVeryfinderTweetSearch={onVeryfinderTweetSearch}
    />
  ) : (
    <>
      <ConsensusCard summary={summary} symbol={symbol} />
      {veryfinderEnabled ? (
        <VeryfinderConsensusCard
          overlay={veryfinder}
          state={veryfinderState}
          error={veryfinderError}
        />
      ) : null}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(280px, 1.05fr) minmax(280px, 0.95fr)",
          gap: 12,
        }}
      >
        <TargetCard data={data} />
        <StaleRuleCard stale={data.stale_rule} />
      </div>
      {crypto ? (
        <SignalInputsTable rows={data.signal_rows ?? []} detailReason={data.analyst_detail_reason} />
      ) : (
        <AnalystTable
          rows={analystRows}
          detailStatus={data.analyst_detail_status ?? summary.analyst_detail_status}
          detailReason={data.analyst_detail_reason}
        />
      )}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(260px, 0.85fr) minmax(320px, 1.15fr)",
          gap: 12,
        }}
      >
        <BucketTable rows={data.bucket_rows ?? []} />
        <AlertEditor symbol={symbol} summary={summary} />
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(300px, 1fr) minmax(300px, 1fr)",
          gap: 12,
        }}
      >
        <SourceFreshness sources={data.source_details ?? []} />
        <AnalystQuality status={data.analyst_detail_status} crypto={crypto} />
      </div>
      <Methodology data={data} />
    </>
  );
  return (
    <div data-testid="function-payload" style={{ display: "grid", gap: 12 }}>
      <div style={screenBarStyle}>
        <SegmentedControl
          label="VIEW"
          value={screen}
          options={ANR_SCREEN_OPTIONS}
          onChange={setScreen}
          title="ANR screen"
        />
        <span style={screenHintStyle}>
          {screen === "analysis" ? "analysis audit" : `${summary.label ?? "consensus"} · ${formatScore(summary.consensus_score)} / 5`}
        </span>
      </div>
      {content}
    </div>
  );
}

function ConsensusCard({ summary, symbol }: { summary: ANRSummary; symbol: string }) {
  const label = summary.label ?? "No consensus";
  const crypto = isCryptoSummary(summary);
  const count = crypto ? summary.signal_count ?? summary.analyst_count : summary.analyst_count;
  const countLabel = summary.count_label ?? (crypto ? "signals" : "analysts");
  const tone = label.toLowerCase().includes("buy")
    ? "positive"
    : label.toLowerCase().includes("sell")
      ? "negative"
      : "neutral";
  return (
    <Card variant="elev-2" style={{ borderColor: "rgba(42,198,238,0.36)" }}>
      <CardHeader
        trailing={
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <Pill tone={tone}>{label}</Pill>
            {summary.not_analyst_target ? <Pill tone="warn">not analyst target</Pill> : null}
          </div>
        }
      >
        Consensus
      </CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "end" }}>
            <div>
              <div style={{ fontSize: 22, color: "var(--text-primary)", fontWeight: 700 }}>
                {summary.title ?? `${symbol} ${crypto ? "Crypto Market Consensus" : "Analyst Consensus"}`}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 3 }}>
                {formatInt(count)} {countLabel} · last updated {summary.last_updated ?? "—"}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 11, color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Consensus
              </div>
              <div style={{ fontSize: 28, color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
                {formatScore(summary.consensus_score)} / 5
              </div>
            </div>
          </div>
          <StatGrid
            items={[
              ["Positive", `${formatPct(summary.positive_pct)}`],
              ["Neutral", `${formatPct(summary.neutral_pct)}`],
              ["Negative", `${formatPct(summary.negative_pct)}`],
              ["Source", providerLabel(summary.consensus_source)],
              ["Included", formatInt(summary.included_count)],
              [crypto ? "Freshness excluded" : "Stale excluded", formatInt(summary.excluded_stale_count)],
              [crypto ? "Market data" : "Oldest included", crypto ? summary.last_updated ?? "—" : summary.oldest_included_rating_date ?? "—"],
            ]}
          />
        </div>
      </CardBody>
    </Card>
  );
}

function VeryfinderConsensusCard({
  overlay,
  state,
  error,
}: {
  overlay: VeryfinderOverlay | null;
  state: VeryfinderRunState;
  error: string | null;
}) {
  const tone = veryfinderTone(overlay?.tone);
  const loading = state === "loading";
  const refreshing = state === "refreshing";
  const label = loading ? "loading" : refreshing ? "refreshing" : overlay?.label ?? (error ? "unavailable" : "waiting");
  return (
    <Card variant="elev-2" style={{ borderColor: "rgba(245,166,35,0.34)" }}>
      <CardHeader
        trailing={
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <Pill tone={tone}>{label}</Pill>
            {overlay?.fixture_mode ? <Pill tone="warn">fixture</Pill> : null}
            {overlay?.fallback_mode ? <Pill tone="warn">{providerLabel(overlay.fallback_mode)}</Pill> : null}
            {overlay?.quality ? <Pill tone={overlay.quality === "ok" ? "positive" : "warn"}>{overlay.quality}</Pill> : null}
            {overlay ? <Pill tone={refreshing ? "warn" : "positive"}>live rolling</Pill> : null}
          </div>
        }
      >
        Veryfinder Social Overlay
      </CardHeader>
      <CardBody>
        {loading ? (
          <div style={{ display: "grid", gap: 8 }}>
            <Skeleton height={24} />
            <Skeleton height={58} />
          </div>
        ) : error ? (
          <p style={{ margin: 0, color: "var(--text-secondary)", fontSize: 12 }}>
            {error}
          </p>
        ) : overlay ? (
          <div style={{ display: "grid", gap: 10 }}>
            <StatGrid
              items={[
                ["Dominant view", overlay.dominant_view?.display ?? "—"],
                ["Confidence", formatPct(Number(overlay.dominant_view?.score ?? 0) * 100)],
                ["Social score", formatSignedInt(overlay.social_score)],
                ["Unique accounts", formatInt(overlay.unique_accounts)],
                ["Source", providerLabel(overlay.source)],
                ["Engine", overlay.engine ?? "—"],
                ["Mood", distributionLabel(overlay.top_mood)],
                ["Action", distributionLabel(overlay.top_action)],
              ]}
            />
            <p style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.45 }}>
              {overlay.meaning ?? "Veryfinder is a social overlay, not analyst consensus."}
            </p>
            <p title={overlay.query} style={{ margin: 0, fontSize: 11, color: "var(--text-mute)", overflowWrap: "anywhere" }}>
              Query: {overlay.query ?? "—"}
            </p>
          </div>
        ) : (
          <p style={{ margin: 0, color: "var(--text-secondary)", fontSize: 12 }}>
            Enable Veryfinder to compare ANR consensus against unique-account social reaction.
          </p>
        )}
      </CardBody>
    </Card>
  );
}

function ANRAnalysisScreen({
  data,
  symbol,
  crypto,
  analystRows,
  functionSources,
  warnings,
  elapsedMs,
  veryfinderEnabled,
  veryfinder,
  veryfinderState,
  veryfinderError,
  veryfinderMinTweets,
  veryfinderMinTweetsInput,
  veryfinderRecommendedTweets,
  veryfinderSource,
  veryfinderStartedAt,
  veryfinderUpdatedAt,
  veryfinderLiveRefreshCount,
  onVeryfinderMinTweetsInputChange,
  onVeryfinderTweetSearch,
}: {
  data: ANRData;
  symbol: string;
  crypto: boolean;
  analystRows: AnalystRow[];
  functionSources: string[];
  warnings: string[];
  elapsedMs?: number;
  veryfinderEnabled: boolean;
  veryfinder: VeryfinderOverlay | null;
  veryfinderState: VeryfinderRunState;
  veryfinderError: string | null;
  veryfinderMinTweets: number;
  veryfinderMinTweetsInput: string;
  veryfinderRecommendedTweets: number;
  veryfinderSource: string;
  veryfinderStartedAt: string | null;
  veryfinderUpdatedAt: string | null;
  veryfinderLiveRefreshCount: number;
  onVeryfinderMinTweetsInputChange: (value: string) => void;
  onVeryfinderTweetSearch: () => void;
}) {
  const summary = data.summary ?? {};
  const signalRows = data.signal_rows ?? [];
  const count = crypto ? summary.signal_count ?? signalRows.length : summary.analyst_count ?? analystRows.length;
  const dataMode = crypto ? "market-data proxy" : analystRows.length ? "broker-level + consensus" : "aggregate consensus";
  return (
    <div data-testid="anr-analysis-screen" style={{ display: "grid", gap: 12 }}>
      <Card variant="elev-2" style={{ borderColor: "rgba(42,198,238,0.32)" }}>
        <CardHeader
          trailing={
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
              <Pill tone={crypto ? "accent" : "positive"}>{dataMode}</Pill>
              {summary.not_analyst_target ? <Pill tone="warn">target caveat</Pill> : null}
            </div>
          }
        >
          Analysis Detail
        </CardHeader>
        <CardBody>
          <div style={{ display: "grid", gap: 12 }}>
            <div style={analysisTitleRowStyle}>
              <div>
                <div style={analysisTitleStyle}>{symbol} ANR analysis</div>
                <p style={analysisTextStyle}>
                  {crypto
                    ? "Crypto ANR is a market-data consensus proxy. It combines live price/volume signals, freshness checks, reference bands, and the optional Veryfinder social overlay."
                    : "Equity ANR combines recommendation consensus, broker action rows, live target-price provenance, stale-rating filtering, and the optional Veryfinder social overlay."}
                </p>
              </div>
              <div style={analysisScoreStyle}>
                <span style={analysisScoreLabelStyle}>consensus</span>
                <strong>{formatScore(summary.consensus_score)} / 5</strong>
              </div>
            </div>
            <StatGrid
              items={[
                ["Label", summary.label ?? "—"],
                [crypto ? "Signals analyzed" : "Ratings analyzed", formatInt(count)],
                ["Positive", formatPct(summary.positive_pct)],
                ["Neutral", formatPct(summary.neutral_pct)],
                ["Negative", formatPct(summary.negative_pct)],
                ["Last updated", summary.last_updated ?? "—"],
                ["Elapsed", elapsedMs == null ? "—" : `${elapsedMs.toFixed(0)} ms`],
                ["Asset class", summary.asset_class ?? (crypto ? "CRYPTO" : "EQUITY")],
              ]}
            />
          </div>
        </CardBody>
      </Card>

      <AnalysisFlowCard crypto={crypto} veryfinderEnabled={veryfinderEnabled} />

      <div style={twoColumnAnalysisGridStyle}>
        <AnalysisSourceAuditCard
          sources={data.source_details ?? []}
          functionSources={functionSources}
          warnings={warnings}
          detailStatus={data.analyst_detail_status ?? summary.analyst_detail_status}
          detailReason={data.analyst_detail_reason}
        />
        <AnalysisRulesCard data={data} crypto={crypto} />
      </div>

      {crypto ? (
        <AnalysisSignalAuditCard rows={signalRows} />
      ) : (
        <AnalysisAnalystCoverageCard rows={analystRows} detailReason={data.analyst_detail_reason} />
      )}

      <div style={twoColumnAnalysisGridStyle}>
        <AnalysisBucketAuditCard rows={data.bucket_rows ?? []} />
        <AnalysisTargetAuditCard data={data} />
      </div>

      <VeryfinderAnalysisCard
        enabled={veryfinderEnabled}
        overlay={veryfinder}
        state={veryfinderState}
        error={veryfinderError}
        minTweets={veryfinderMinTweets}
        minTweetsInput={veryfinderMinTweetsInput}
        recommendedTweets={veryfinderRecommendedTweets}
        source={veryfinderSource}
        startedAt={veryfinderStartedAt}
        updatedAt={veryfinderUpdatedAt}
        liveRefreshCount={veryfinderLiveRefreshCount}
        onMinTweetsInputChange={onVeryfinderMinTweetsInputChange}
        onTweetSearch={onVeryfinderTweetSearch}
      />

      <Methodology data={data} />
    </div>
  );
}

function AnalysisFlowCard({ crypto, veryfinderEnabled }: { crypto: boolean; veryfinderEnabled: boolean }) {
  const steps = crypto
    ? [
        ["Input", "symbol + asset class"],
        ["Market signals", "trend, momentum, volatility, liquidity"],
        ["Freshness", "market-data recency filter"],
        ["Score", "weighted 1-5 consensus proxy"],
        ["Overlay", veryfinderEnabled ? "Veryfinder social view" : "Veryfinder off"],
      ]
    : [
        ["Input", "symbol + recommendation feed"],
        ["Rows", "rating, previous rating, action, target"],
        ["Freshness", "1Y stale-rating exclusion"],
        ["Score", "buy/hold/sell consensus map"],
        ["Overlay", veryfinderEnabled ? "Veryfinder social view" : "Veryfinder off"],
      ];
  return (
    <Card>
      <CardHeader>Analysis Path</CardHeader>
      <CardBody>
        <div style={analysisFlowStyle}>
          {steps.map(([label, value], index) => (
            <div key={label} style={analysisStepStyle}>
              <span style={analysisStepIndexStyle}>{index + 1}</span>
              <strong>{label}</strong>
              <span>{value}</span>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisSourceAuditCard({
  sources,
  functionSources,
  warnings,
  detailStatus,
  detailReason,
}: {
  sources: SourceDetail[];
  functionSources: string[];
  warnings: string[];
  detailStatus?: string;
  detailReason?: string;
}) {
  return (
    <Card>
      <CardHeader trailing={<Pill tone={warnings.length ? "warn" : "positive"}>{warnings.length ? "warnings" : "clean"}</Pill>}>
        Source Audit
      </CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10 }}>
          <StatGrid
            items={[
              ["Runtime sources", formatSources(functionSources)],
              ["Source rows", formatInt(sources.length)],
              ["Detail status", providerLabel(detailStatus)],
              ["Warnings", formatInt(warnings.length)],
            ]}
          />
          {sources.length ? (
            <div style={analysisListStyle}>
              {sources.map((source, index) => (
                <div key={`${source.name ?? "source"}-${index}`} style={analysisListRowStyle}>
                  <strong>{providerLabel(source.name)}</strong>
                  <span>{providerLabel(source.status)} · {source.asOf ?? "as-of —"} · {source.fields ?? "fields —"}</span>
                </div>
              ))}
            </div>
          ) : null}
          {detailReason ? <p style={analysisTextStyle}>{detailReason}</p> : null}
          {warnings.length ? (
            <div style={analysisWarningListStyle}>
              {warnings.slice(0, 6).map((warning) => (
                <span key={warning}>{warning}</span>
              ))}
            </div>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisRulesCard({ data, crypto }: { data: ANRData; crypto: boolean }) {
  const stale = data.stale_rule;
  const source = data.target_price_source;
  return (
    <Card>
      <CardHeader trailing={<Pill tone={crypto ? "accent" : "muted"}>{crypto ? "crypto" : "equity"}</Pill>}>
        Rules & Caveats
      </CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10 }}>
          <StatGrid
            items={[
              ["Freshness rule", stale?.rule_type === "market_data_freshness" ? "market data" : "1Y stale rule"],
              ["Included", formatInt(stale?.included_count)],
              ["Excluded", formatInt(stale?.excluded_stale_count)],
              ["Undated rows", formatInt(stale?.undated_provider_rows)],
              ["Target source", source?.label ?? "—"],
              ["Target caveat", source?.not_analyst_target ? "not analyst target" : "live target"],
            ]}
          />
          <p style={analysisTextStyle}>{stale?.rule ?? "No stale/freshness rule text supplied."}</p>
          {source?.not_analyst_target ? (
            <p style={analysisTextStyle}>
              Price references in this run are explicitly labelled as non-analyst targets so they are not confused with broker target prices.
            </p>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisSignalAuditCard({ rows }: { rows: SignalRow[] }) {
  const cols: DataGridColumn<SignalRow>[] = [
    { key: "signal", header: "Signal", width: "1fr", render: (r) => r.signal ?? "—" },
    { key: "value", header: "Value", width: 110, render: (r) => r.value ?? "—" },
    { key: "score", header: "Score", width: 80, numeric: true, render: (r) => formatScore(r.score) },
    { key: "weight", header: "Weight", width: 80, numeric: true, render: (r) => formatPct(Number(r.weight ?? 0) * 100) },
    { key: "weighted_score", header: "Weighted", width: 90, numeric: true, render: (r) => formatScore(r.weighted_score) },
    { key: "explanation", header: "Meaning", width: "1.4fr", render: (r) => r.explanation ?? "—" },
  ];
  return (
    <Card>
      <CardHeader trailing={<Pill tone={rows.length ? "positive" : "warn"}>{rows.length} signals</Pill>}>
        Signal Weight Audit
      </CardHeader>
      <CardBody>
        <DataGrid columns={cols} rows={rows} density="compact" empty="signal rows unavailable" />
      </CardBody>
    </Card>
  );
}

function AnalysisAnalystCoverageCard({ rows, detailReason }: { rows: AnalystRow[]; detailReason?: string }) {
  const brokerCount = new Set(rows.map((row) => row.broker).filter(Boolean)).size;
  const targetCount = rows.filter((row) => row.target_price != null && row.target_price !== "").length;
  const actionCount = rows.filter((row) => row.action).length;
  const cols: DataGridColumn<AnalystRow>[] = [
    { key: "broker", header: "Broker", width: 150, render: (r) => r.broker ?? "—" },
    { key: "rating", header: "Rating", width: 110, render: (r) => r.rating ?? "—" },
    { key: "previous_rating", header: "Previous", width: 110, render: (r) => r.previous_rating ?? "—" },
    { key: "action", header: "Action", width: 120, render: (r) => r.action ?? "—" },
    { key: "target_price", header: "Target", width: 100, numeric: true, render: (r) => formatMoney(r.target_price) },
    { key: "date", header: "Date", width: 110, render: (r) => r.date ?? "—" },
  ];
  return (
    <Card>
      <CardHeader trailing={<Pill tone={rows.length ? "positive" : "warn"}>{rows.length} rows</Pill>}>
        Analyst Coverage Audit
      </CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10 }}>
          <StatGrid
            items={[
              ["Brokers", formatInt(brokerCount)],
              ["Rows", formatInt(rows.length)],
              ["Rows with target", formatInt(targetCount)],
              ["Rows with action", formatInt(actionCount)],
            ]}
          />
          <DataGrid columns={cols} rows={rows.slice(0, 12)} density="compact" empty="analyst rows unavailable" />
          {detailReason ? <p style={analysisTextStyle}>{detailReason}</p> : null}
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisBucketAuditCard({ rows }: { rows: BucketRow[] }) {
  const cols: DataGridColumn<BucketRow>[] = [
    { key: "bucket", header: "Bucket", width: "1fr", render: (r) => r.bucket ?? "—" },
    { key: "count", header: "Count", width: 90, numeric: true, render: (r) => formatInt(r.count) },
    { key: "pct_of_consensus", header: "%", width: 80, numeric: true, render: (r) => formatPct(r.pct_of_consensus) },
    { key: "sentiment_score", header: "Score", width: 80, numeric: true, render: (r) => formatInt(r.sentiment_score) },
  ];
  return (
    <Card>
      <CardHeader>Consensus Distribution</CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10 }}>
          <DistributionBars
            distribution={Object.fromEntries(
              rows.map((row) => [row.bucket ?? "unknown", Number(row.pct_of_consensus ?? 0) / 100]),
            )}
          />
          <DataGrid columns={cols} rows={rows} density="compact" empty="bucket rows unavailable" />
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisTargetAuditCard({ data }: { data: ANRData }) {
  const rows = data.target_rows ?? [];
  const cols: DataGridColumn<TargetRow>[] = [
    { key: "metric", header: "Metric", width: "1fr", render: (r) => r.metric ?? "—" },
    { key: "price", header: "Price", width: 110, numeric: true, render: (r) => formatMoney(r.price) },
    { key: "source_mode", header: "Source", width: 180, render: (r) => sourceLabel(r.source_mode) },
  ];
  return (
    <Card>
      <CardHeader
        trailing={<Pill tone={data.target_price_source?.not_analyst_target ? "warn" : "positive"}>{data.target_price_source?.label ?? "target source"}</Pill>}
      >
        Target Price Provenance
      </CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10 }}>
          <StatGrid
            items={[
              ["Spot", formatMoney(data.spot)],
              ["Mode", sourceLabel(data.target_price_source?.mode)],
              ["Rows", formatInt(rows.length)],
              ["Caveat", data.target_price_source?.not_analyst_target ? "not analyst target" : "analyst target"],
            ]}
          />
          <DataGrid columns={cols} rows={rows} density="compact" empty="target rows unavailable" />
        </div>
      </CardBody>
    </Card>
  );
}

function VeryfinderAnalysisCard({
  enabled,
  overlay,
  state,
  error,
  minTweets,
  minTweetsInput,
  recommendedTweets,
  source,
  startedAt,
  updatedAt,
  liveRefreshCount,
  onMinTweetsInputChange,
  onTweetSearch,
}: {
  enabled: boolean;
  overlay: VeryfinderOverlay | null;
  state: VeryfinderRunState;
  error: string | null;
  minTweets: number;
  minTweetsInput: string;
  recommendedTweets: number;
  source: string;
  startedAt: string | null;
  updatedAt: string | null;
  liveRefreshCount: number;
  onMinTweetsInputChange: (value: string) => void;
  onTweetSearch: () => void;
}) {
  const requestedTweets = clampTweetSample(minTweetsInput);
  const [tweetDrawerOpen, setTweetDrawerOpen] = useState(false);
  const posts = overlay?.posts ?? overlay?.analyzed_posts ?? [];
  const refreshing = state === "refreshing";
  return (
    <Card>
      <CardHeader
        trailing={
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <Pill tone={enabled ? veryfinderTone(overlay?.tone) : "muted"}>{enabled ? state : "off"}</Pill>
            {enabled ? <Pill tone={refreshing ? "warn" : "positive"}>rolling · 30s</Pill> : null}
            {overlay?.fixture_mode ? <Pill tone="warn">fixture</Pill> : null}
            {overlay?.fallback_mode ? <Pill tone="warn">{providerLabel(overlay.fallback_mode)}</Pill> : null}
          </div>
        }
      >
        Veryfinder Analysis
      </CardHeader>
      <CardBody>
        <div style={tweetSearchControlStyle}>
          <label style={tweetSearchLabelStyle}>
            <span>Min tweets</span>
            <input
              type="number"
              min={1}
              step={1}
              value={minTweetsInput}
              disabled={!enabled || state === "loading"}
              onChange={(event) => onMinTweetsInputChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onTweetSearch();
              }}
              style={tweetSearchInputStyle}
            />
          </label>
          <button
            type="button"
            className="btn"
            onClick={onTweetSearch}
            disabled={!enabled || state === "loading"}
            title="Apply rolling tweet window and refresh now"
            style={tweetSearchGoButtonStyle}
          >
            GO
          </button>
          <span style={tweetSearchIntentStyle}>rolling window · newest {formatInt(requestedTweets)} tweets</span>
          <span style={analysisMutedStyle}>applied · {formatInt(minTweets)}</span>
          <span style={analysisMutedStyle}>efficient default · {formatInt(recommendedTweets)}</span>
          <span style={analysisMutedStyle}>auto refresh · 30s</span>
        </div>
        {!enabled ? (
          <p style={analysisTextStyle}>Veryfinder overlay is disabled for this ANR run.</p>
        ) : state === "loading" ? (
          <VeryfinderSearchLoadScreen
            target={minTweets}
            requestedInput={requestedTweets}
            source={source}
            startedAt={startedAt}
            previous={overlay}
            postsOpen={tweetDrawerOpen}
            onTogglePosts={() => setTweetDrawerOpen((open) => !open)}
          />
        ) : error ? (
          <p style={analysisTextStyle}>{error}</p>
        ) : overlay ? (
          <div style={{ display: "grid", gap: 12 }}>
            <StatGrid
              items={[
                ["Dominant view", overlay.dominant_view?.display ?? "—"],
                ["Confidence", formatPct(Number(overlay.dominant_view?.score ?? 0) * 100)],
                ["Social score", formatSignedInt(overlay.social_score)],
                ["Min tweet target", formatInt(minTweets)],
                ["Rolling window", `${formatInt(overlay.rolling_window_size ?? minTweets)} newest`],
                ["Requested sample", formatInt(overlay.requested_sample ?? minTweets)],
                ["Unique accounts", formatInt(overlay.unique_accounts)],
                ["Collected posts", formatInt(overlay.collected_posts)],
                ["Last refresh", updatedAt ? formatDateTime(updatedAt) : "—"],
                ["Live refreshes", formatInt(liveRefreshCount)],
                ["Tweet estimate", formatInt(overlay.tweet_count_estimate)],
                ["Source", providerLabel(overlay.source)],
                ["Engine", overlay.engine ?? "—"],
              ]}
            />
            {Number(overlay.collected_posts ?? 0) < Number(overlay.requested_sample ?? minTweets) ? (
              <p style={analysisTextStyle}>
                Source capacity note: this rolling window requested {formatInt(overlay.requested_sample ?? minTweets)} tweets;
                {overlay.fixture_mode ? " fixture mode contains 12 demo posts." : ` the source returned ${formatInt(overlay.collected_posts)} posts.`}
              </p>
            ) : null}
            <div style={twoColumnAnalysisGridStyle}>
              <DistributionBlock title="View distribution" distribution={overlay.view_distribution} />
              <DistributionBlock title="Mood distribution" distribution={overlay.mood_distribution} />
              <DistributionBlock title="Action distribution" distribution={overlay.action_distribution} />
              <DistributionBlock title="Sentiment distribution" distribution={overlay.sentiment_distribution} />
            </div>
            <p style={analysisTextStyle}>{overlay.meaning}</p>
            <p title={overlay.query} style={analysisQueryStyle}>Query: {overlay.query ?? "—"}</p>
            <TweetEvidenceDrawer
              posts={posts}
              open={tweetDrawerOpen}
              onToggle={() => setTweetDrawerOpen((open) => !open)}
              title={`Rolling tweet window · ${formatInt(posts.length)} newest`}
            />
            {overlay.model_notes?.length ? (
              <div style={analysisListStyle}>
                {overlay.model_notes.slice(0, 5).map((note) => (
                  <div key={note} style={analysisListRowStyle}>
                    <strong>note</strong>
                    <span>{note}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <p style={analysisTextStyle}>Veryfinder returned no analysis payload.</p>
        )}
      </CardBody>
    </Card>
  );
}

function VeryfinderSearchLoadScreen({
  target,
  requestedInput,
  source,
  startedAt,
  previous,
  postsOpen,
  onTogglePosts,
}: {
  target: number;
  requestedInput: number;
  source: string;
  startedAt: string | null;
  previous: VeryfinderOverlay | null;
  postsOpen: boolean;
  onTogglePosts: () => void;
}) {
  const posts = previous?.posts ?? previous?.analyzed_posts ?? [];
  return (
    <div style={veryfinderLoadShellStyle} aria-live="polite">
      <div style={veryfinderLoadTopStyle}>
        <div>
          <div style={veryfinderLoadKickerStyle}>Veryfinder live search</div>
          <div style={veryfinderLoadTitleStyle}>Searching social reaction</div>
          <p style={analysisTextStyle}>
            Requesting {formatInt(target)} tweets from {providerLabel(source)}; current input target is {formatInt(requestedInput)}.
            The pipeline is fetching posts, deduping unique accounts, then scoring sentiment, mood, action, and market view.
          </p>
        </div>
        <div style={veryfinderLoadMeterStyle}>
          <span style={{ ...veryfinderLoadBarStyle, height: 18 }} />
          <span style={{ ...veryfinderLoadBarStyle, height: 34 }} />
          <span style={{ ...veryfinderLoadBarStyle, height: 26 }} />
        </div>
      </div>
      <div style={veryfinderStepGridStyle}>
        {[
          ["1", "Search", "X/RSS query dispatch"],
          ["2", "Dedupe", "one vote per account"],
          ["3", "Score", "sentiment/action/view"],
          ["4", "Render", "evidence drawer + alert"],
        ].map(([index, label, value]) => (
          <div key={label} style={veryfinderStepCardStyle}>
            <strong>{index}</strong>
            <span>{label}</span>
            <small>{value}</small>
          </div>
        ))}
      </div>
      <div style={veryfinderLoadMetaStyle}>
        <span>started · {startedAt ? formatDateTime(startedAt) : "now"}</span>
        <span>previous collected · {formatInt(previous?.collected_posts)}</span>
        <span>previous requested · {formatInt(previous?.requested_sample)}</span>
      </div>
      {posts.length ? (
        <TweetEvidenceDrawer
          posts={posts}
          open={postsOpen}
          onToggle={onTogglePosts}
          title={`Last tweet evidence while search runs · ${formatInt(posts.length)}`}
        />
      ) : null}
    </div>
  );
}

function TweetEvidenceDrawer({
  posts,
  open,
  onToggle,
  title,
}: {
  posts: VeryfinderPost[];
  open: boolean;
  onToggle: () => void;
  title: string;
}) {
  return (
    <div style={tweetDrawerStyle}>
      <button
        type="button"
        className="btn btn--ghost"
        onClick={onToggle}
        style={tweetDrawerToggleStyle}
      >
        <span>{open ? "-" : "+"}</span>
        <strong>{title}</strong>
        <small>{open ? "hide" : "inspect"}</small>
      </button>
      {open ? (
        posts.length ? (
          <div style={tweetListStyle}>
            {posts.map((post, index) => (
              <TweetEvidenceRow key={post.id || `${post.username}-${index}`} post={post} />
            ))}
          </div>
        ) : (
          <p style={analysisTextStyle}>No tweet evidence was returned by the source for this run.</p>
        )
      ) : null}
    </div>
  );
}

function TweetEvidenceRow({ post }: { post: VeryfinderPost }) {
  const handle = post.username ? `@${post.username}` : post.author_id ?? "unknown";
  const label = post.view?.label || post.sentiment?.label || "unclassified";
  return (
    <div style={tweetRowStyle}>
      <div style={tweetRowMetaStyle}>
        <strong>{handle}</strong>
        <span>{label.replaceAll("_", " ")}</span>
        <span>rel {formatPct(Number(post.relevance ?? 0) * 100)}</span>
        <span>eng {formatInt(post.engagement)}</span>
        <span>{post.created_at ? formatDateTime(post.created_at) : "time —"}</span>
        {post.url ? (
          <a href={post.url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
            open ↗
          </a>
        ) : null}
      </div>
      <p style={tweetTextStyle}>{post.text || "Text unavailable."}</p>
      <div style={tweetTagRowStyle}>
        <span>sentiment · {post.sentiment?.label ?? "—"}</span>
        <span>action · {post.action?.label ?? "—"}</span>
        <span>mood · {post.mood?.label ?? "—"}</span>
      </div>
    </div>
  );
}

function DistributionBlock({ title, distribution }: { title: string; distribution?: Record<string, number> }) {
  return (
    <div style={distributionBlockStyle}>
      <div style={distributionTitleStyle}>{title}</div>
      <DistributionBars distribution={distribution} />
    </div>
  );
}

function DistributionBars({ distribution }: { distribution?: Record<string, number> }) {
  const entries = Object.entries(distribution ?? {})
    .filter(([, value]) => Number.isFinite(Number(value)))
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  if (!entries.length) {
    return <span style={analysisMutedStyle}>distribution unavailable</span>;
  }
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {entries.map(([label, value]) => {
        const pct = Math.max(0, Math.min(100, Number(value) * 100));
        return (
          <div key={label} style={{ display: "grid", gap: 3 }}>
            <div style={distributionRowStyle}>
              <span>{label.replaceAll("_", " ")}</span>
              <strong>{formatPct(pct)}</strong>
            </div>
            <div style={distributionTrackStyle}>
              <span style={{ ...distributionFillStyle, width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function TargetCard({ data }: { data: ANRData }) {
  const source = data.target_price_source;
  const rows = data.target_rows ?? [];
  const crypto = isCryptoSummary(data.summary);
  const title = crypto ? source?.display_name ?? "Crypto Reference Bands" : "Price Target";
  const cols = useMemo<DataGridColumn<TargetRow>[]>(
    () => [
      { key: "metric", header: crypto ? "Reference" : "Target", width: "1fr" },
      { key: "price", header: "Price", width: 100, numeric: true, render: (r) => formatMoney(r.price) },
      {
        key: "source_mode",
        header: "Source",
        width: 180,
        render: (r) => sourceLabel(r.source_mode),
      },
    ],
    [crypto],
  );
  return (
    <Card>
      <CardHeader
        trailing={
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <Pill tone={source?.not_analyst_target ? "warn" : "positive"}>
              {source?.label ?? "Target source —"}
            </Pill>
            {source?.not_analyst_target ? <Pill tone="warn">not an analyst target</Pill> : null}
          </div>
        }
      >
        {title}
      </CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            Spot reference: {formatMoney(data.spot)}
          </div>
          <DataGrid columns={cols} rows={rows} density="compact" empty={crypto ? "reference bands unavailable" : "target fields unavailable"} />
        </div>
      </CardBody>
    </Card>
  );
}

function StaleRuleCard({ stale }: { stale?: StaleRule }) {
  const marketFreshness = stale?.rule_type === "market_data_freshness";
  return (
    <Card>
      <CardHeader trailing={<Pill tone="accent">{marketFreshness ? "market data" : "1Y rule"}</Pill>}>
        {marketFreshness ? "Freshness Rule" : "Stale Data Rule"}
      </CardHeader>
      <CardBody>
        <StatGrid
          items={marketFreshness
            ? [
                ["Latest data", stale?.latest_market_data_at ?? "—"],
                ["Signals included", formatInt(stale?.included_count)],
                ["Excluded", formatInt(stale?.excluded_stale_count)],
                ["Undated rows", formatInt(stale?.undated_provider_rows)],
              ]
            : [
                ["Cutoff date", stale?.cutoff_date ?? "—"],
                ["Included", formatInt(stale?.included_count)],
                ["Stale excluded", formatInt(stale?.excluded_stale_count)],
                ["Oldest included", stale?.oldest_included_rating_date ?? "—"],
                ["Oldest stale", stale?.oldest_stale_rating_date ?? "—"],
                ["Undated rows", formatInt(stale?.undated_provider_rows)],
              ]}
        />
        <p style={{ margin: "10px 0 0", fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.45 }}>
          {stale?.rule ?? "Recommendation rows older than one year are excluded from consensus."}
        </p>
      </CardBody>
    </Card>
  );
}

function AnalystTable({
  rows,
  detailStatus,
  detailReason,
}: {
  rows: AnalystRow[];
  detailStatus?: string;
  detailReason?: string;
}) {
  const cols = useMemo<DataGridColumn<AnalystRow>[]>(
    () => [
      { key: "broker", header: "Broker", width: 130, render: (r) => r.broker ?? "—" },
      { key: "analyst", header: "Analyst", width: 150, render: (r) => r.analyst ?? "—" },
      { key: "rating", header: "Rating", width: 100, render: (r) => r.rating ?? "—" },
      { key: "previous_rating", header: "Previous", width: 110, render: (r) => r.previous_rating ?? "—" },
      { key: "action", header: "Action", width: 105, render: (r) => r.action ?? "—" },
      { key: "target_price", header: "Target price", width: 115, numeric: true, render: (r) => formatMoney(r.target_price) },
      { key: "target_period", header: "Period", width: 85, render: (r) => r.target_period ?? "—" },
      { key: "date", header: "Date", width: 100, render: (r) => r.date ?? "—" },
      { key: "last_update", header: "Last update", width: 115, render: (r) => r.last_update ?? "—" },
    ],
    [],
  );
  return (
    <Card>
      <CardHeader
        trailing={<Pill tone={rows.length ? "positive" : "warn"}>{detailStatus ?? "broker feed"}</Pill>}
      >
        Analyst-Level Ratings
      </CardHeader>
      <CardBody>
        <DataGrid
          columns={cols}
          rows={rows}
          density="compact"
          empty={
            <span>
              Broker-level analyst feed is not configured. Aggregate consensus is shown above; no
              broker or analyst rows are fabricated.
            </span>
          }
        />
        {detailReason ? (
          <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>
            {detailReason}
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}

function SignalInputsTable({ rows, detailReason }: { rows: SignalRow[]; detailReason?: string }) {
  const cols = useMemo<DataGridColumn<SignalRow>[]>(
    () => [
      { key: "signal", header: "Signal", width: 170, render: (r) => r.signal ?? "—" },
      { key: "value", header: "Value", width: 120, render: (r) => r.value ?? "—" },
      { key: "score", header: "Score", width: 80, numeric: true, render: (r) => formatScore(r.score) },
      { key: "weight", header: "Weight", width: 80, numeric: true, render: (r) => formatPct(Number(r.weight ?? 0) * 100) },
      { key: "source", header: "Source", width: 130, render: (r) => providerLabel(r.source) },
      { key: "explanation", header: "Meaning", width: "1fr", render: (r) => r.explanation ?? "—" },
    ],
    [],
  );
  return (
    <Card>
      <CardHeader trailing={<Pill tone={rows.length ? "positive" : "warn"}>{rows.length ? "live proxy" : "no signals"}</Pill>}>
        Crypto Consensus Inputs
      </CardHeader>
      <CardBody>
        <DataGrid
          columns={cols}
          rows={rows}
          density="compact"
          empty="crypto market-data signals unavailable"
        />
        {detailReason ? (
          <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>
            {detailReason}
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}

function BucketTable({ rows }: { rows: BucketRow[] }) {
  const cols = useMemo<DataGridColumn<BucketRow>[]>(
    () => [
      { key: "bucket", header: "Bucket", width: "1fr", render: (r) => r.bucket ?? "—" },
      { key: "count", header: "Count", width: 90, numeric: true, render: (r) => formatInt(r.count) },
      { key: "pct_of_consensus", header: "%", width: 80, numeric: true, render: (r) => formatPct(r.pct_of_consensus) },
      { key: "sentiment_score", header: "Score", width: 80, numeric: true, render: (r) => formatInt(r.sentiment_score) },
    ],
    [],
  );
  return (
    <Card>
      <CardHeader>Bucket Distribution</CardHeader>
      <CardBody>
        <DataGrid columns={cols} rows={rows} density="compact" empty="bucket rows unavailable" />
      </CardBody>
    </Card>
  );
}

function AlertEditor({ symbol, summary }: { symbol: string; summary: ANRSummary }) {
  const storageKey = `showme.anr.alert.${symbol}`;
  const saved = loadAlert(storageKey);
  const [enabled, setEnabled] = useState(saved.enabled);
  const [rule, setRule] = useState<AlertRule>(saved.rule);
  const [threshold, setThreshold] = useState(saved.threshold);
  const [savedAt, setSavedAt] = useState(saved.savedAt);

  const save = () => {
    const next = {
      enabled,
      rule,
      threshold,
      savedAt: new Date().toISOString(),
    };
    localStorage.setItem(storageKey, JSON.stringify(next));
    setSavedAt(next.savedAt);
  };

  return (
    <Card>
      <CardHeader trailing={<Pill tone={enabled ? "positive" : "muted"}>{enabled ? "on" : "off"}</Pill>}>
        Recommendation Alert
      </CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10 }}>
          <FieldRow>
            <label style={{ display: "grid", gap: 4 }}>
              <span style={labelStyle}>Rule</span>
              <select
                value={rule}
                onChange={(e) => setRule(e.target.value as AlertRule)}
                style={selectStyle}
              >
                <option value="label_change">Consensus label changes</option>
                <option value="score_below">Consensus score below</option>
                <option value="score_above">Consensus score above</option>
                <option value="positive_pct_below">Positive pct below</option>
              </select>
            </label>
            <Field
              label="Threshold"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              placeholder={rule.includes("pct") ? "60" : "3.5"}
              disabled={rule === "label_change"}
            />
          </FieldRow>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text-secondary)" }}>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Enable local ANR alert draft for {symbol}
          </label>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              Current consensus: {formatScore(summary.consensus_score)} / 5 · {summary.label ?? "—"}
            </span>
            <button type="button" className="btn" onClick={save}>
              Save alert
            </button>
          </div>
          <span style={{ fontSize: 11, color: "var(--text-mute)" }}>
            Saved: {savedAt ? formatDateTime(savedAt) : "—"} · editable from this ANR panel.
          </span>
        </div>
      </CardBody>
    </Card>
  );
}

function SourceFreshness({ sources }: { sources: SourceDetail[] }) {
  const cols = useMemo<DataGridColumn<SourceDetail>[]>(
    () => [
      { key: "name", header: "Source", width: 145, render: (r) => providerLabel(r.name) },
      { key: "status", header: "Status", width: 180, render: (r) => providerLabel(r.status) },
      { key: "asOf", header: "As of", width: 115, render: (r) => r.asOf ?? "—" },
      { key: "fields", header: "Fields", width: "1fr", render: (r) => r.fields ?? "—" },
    ],
    [],
  );
  return (
    <Card>
      <CardHeader>Source & Freshness</CardHeader>
      <CardBody>
        <DataGrid columns={cols} rows={sources} density="compact" empty="source details unavailable" />
      </CardBody>
    </Card>
  );
}

function AnalystQuality({ status, crypto }: { status?: string; crypto?: boolean }) {
  return (
    <Card>
      <CardHeader trailing={<Pill tone="warn">{status ?? "provider not configured"}</Pill>}>
        {crypto ? "Consensus Quality" : "Analyst Quality"}
      </CardHeader>
      <CardBody>
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.45 }}>
          {crypto
            ? "Crypto consensus quality is limited by live quote/OHLCV coverage. Sell-side analyst hit-rate scoring is not applicable unless a real broker-level crypto research feed is configured."
            : "Analyst accuracy scoring requires broker-level historical ratings, target prices, realized returns, and revision history. The current configured ANR feed is aggregate-level, so ShowMe exposes the missing provider state instead of presenting a synthetic accuracy score."}
        </p>
      </CardBody>
    </Card>
  );
}

function Methodology({ data }: { data: ANRData }) {
  const entries = Object.entries(data.field_dictionary ?? {}).filter(([, value]) =>
    value != null && String(value).trim().length > 0,
  );
  return (
    <Card density="compact">
      <CardHeader>Methodology</CardHeader>
      <CardBody>
        <div style={{ display: "grid", gap: 10, fontSize: 12 }}>
          {data.methodology ? (
            <p style={{ margin: 0, color: "var(--text-secondary)", lineHeight: 1.45 }}>
              {data.methodology}
            </p>
          ) : null}
          {entries.length ? (
            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "minmax(140px, 0.36fr) 1fr", gap: "6px 12px" }}>
              {entries.map(([key, value]) => (
                <span key={key} style={{ display: "contents" }}>
                  <dt style={{ color: "var(--text-mute)", fontFamily: "JetBrains Mono, monospace" }}>
                    {key}
                  </dt>
                  <dd style={{ margin: 0, color: "var(--text-secondary)" }}>{value}</dd>
                </span>
              ))}
            </dl>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function StatGrid({ items }: { items: [string, string][] }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(128px, 1fr))",
        gap: 8,
      }}
    >
      {items.map(([label, value]) => (
        <div
          key={label}
          style={{
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
            background: "rgba(255,255,255,0.025)",
            padding: "7px 9px",
            minHeight: 48,
            minWidth: 0,
          }}
        >
          <div style={{ fontSize: 10, color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            {label}
          </div>
          <div
            title={value}
            style={{
              marginTop: 5,
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 13,
              lineHeight: 1.18,
              color: "var(--text-primary)",
              minWidth: 0,
              overflowWrap: "anywhere",
              wordBreak: "break-word",
            }}
          >
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

function loadAlert(key: string): {
  enabled: boolean;
  rule: AlertRule;
  threshold: string;
  savedAt?: string;
} {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return { enabled: false, rule: "label_change", threshold: "" };
    const parsed = JSON.parse(raw) as Partial<{
      enabled: boolean;
      rule: AlertRule;
      threshold: string;
      savedAt: string;
    }>;
    return {
      enabled: Boolean(parsed.enabled),
      rule: parsed.rule ?? "label_change",
      threshold: parsed.threshold ?? "",
      savedAt: parsed.savedAt,
    };
  } catch {
    return { enabled: false, rule: "label_change", threshold: "" };
  }
}

function sourceLabel(value?: string): string {
  if (value === "live_analyst_targets") return "Live analyst targets";
  if (value === "derived_reference_range_from_spot") return "Derived from spot";
  if (value === "crypto_market_reference_band") return "Market reference band";
  if (value === "target_price_unavailable") return "Unavailable";
  return providerLabel(value);
}

function providerLabel(value?: string): string {
  if (!value) return "—";
  const labels: Record<string, string> = {
    yfinance_recommendations: "Yahoo recs",
    yfinance_targets: "Yahoo targets",
    yfinance: "Yahoo Finance",
    live_analyst_targets: "Live analyst targets",
    aggregate_consensus_available: "Consensus available",
    broker_actions_available: "Broker actions",
    provider_not_configured: "Provider not configured",
    provider_unavailable: "Provider unavailable",
    unavailable_no_fabricated_consensus: "Unavailable",
    crypto_market_data: "Crypto market data",
    crypto_market_reference_band: "Market reference band",
    broker_level_analyst_feed: "Broker analyst feed",
    target_price: "Target price",
    binance: "Binance",
    public_search: "Public web/news/social search",
    expanded_public_search: "Expanded public search",
    search_exhausted: "Search exhausted",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function formatSources(sources?: string[]): string {
  if (!sources?.length) return "—";
  return sources.map(providerLabel).join(", ");
}

function isCryptoSummary(summary?: ANRSummary): boolean {
  return summary?.asset_class === "CRYPTO" || summary?.consensus_kind === "crypto_market_proxy";
}

function formatInt(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function clampTweetSample(value: string | number): number {
  return normalizeVeryfinderSample(value, 50);
}

function formatScore(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(2);
}

function formatPct(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(1)}%`;
}

function formatMoney(value?: number | string | null): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

function formatSignedInt(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const n = Math.round(Number(value));
  return n > 0 ? `+${n}` : String(n);
}

function distributionLabel(value?: { label: string; score: number } | null): string {
  if (!value) return "—";
  return `${value.label.replaceAll("_", " ")} ${formatPct(value.score * 100)}`;
}

function veryfinderTone(tone?: VeryfinderTone): "positive" | "negative" | "warn" | "muted" | "neutral" {
  if (tone === "positive" || tone === "negative" || tone === "warn" || tone === "muted") {
    return tone;
  }
  return "neutral";
}

function formatDateTime(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function notifyVeryfinderComplete(symbol: string, overlay: VeryfinderOverlay): void {
  const found = Number(overlay.collected_posts ?? 0);
  const title = found > 0 ? "Veryfinder tweets found" : "Veryfinder search complete";
  const body = `${symbol} · ${formatInt(overlay.collected_posts)} collected / ${formatInt(overlay.requested_sample)} requested · ${overlay.label ?? "social view"}`;
  toast.success(title, body);
  if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted") {
    try {
      new Notification(title, { body });
    } catch {
      // In-app toast already handled the notification.
    }
  } else if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
    void Notification.requestPermission().then((permission) => {
      if (permission !== "granted") return;
      try {
        new Notification(title, { body });
      } catch {
        // In-app toast already handled the notification.
      }
    });
  }
}

const screenBarStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 10,
  flexWrap: "wrap" as const,
};

const screenHintStyle = {
  fontSize: 11,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  textTransform: "uppercase" as const,
};

const twoColumnAnalysisGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
  gap: 12,
};

const analysisTitleRowStyle = {
  display: "grid",
  gridTemplateColumns: "minmax(260px, 1fr) auto",
  gap: 16,
  alignItems: "end",
};

const analysisTitleStyle = {
  fontSize: 18,
  fontWeight: 700,
  color: "var(--text-primary)",
};

const analysisTextStyle = {
  margin: 0,
  fontSize: 12,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

const analysisScoreStyle = {
  display: "grid",
  justifyItems: "end",
  gap: 2,
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 24,
};

const analysisScoreLabelStyle = {
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "uppercase" as const,
};

const analysisFlowStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 8,
};

const analysisStepStyle = {
  display: "grid",
  gap: 5,
  minWidth: 0,
  padding: "9px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(255,255,255,0.025)",
  fontSize: 12,
  color: "var(--text-secondary)",
};

const analysisStepIndexStyle = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 18,
  height: 18,
  borderRadius: "50%",
  background: "var(--bg-elev-3)",
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
};

const analysisListStyle = {
  display: "grid",
  gap: 6,
};

const analysisListRowStyle = {
  display: "grid",
  gridTemplateColumns: "minmax(120px, 0.3fr) 1fr",
  gap: 8,
  alignItems: "baseline",
  fontSize: 12,
  color: "var(--text-secondary)",
  minWidth: 0,
};

const analysisWarningListStyle = {
  display: "grid",
  gap: 4,
  color: "var(--warn)",
  fontSize: 11,
  overflowWrap: "anywhere" as const,
};

const analysisQueryStyle = {
  margin: 0,
  fontSize: 11,
  color: "var(--text-mute)",
  overflowWrap: "anywhere" as const,
};

const analysisMutedStyle = {
  fontSize: 11,
  color: "var(--text-mute)",
};

const veryfinderLoadShellStyle = {
  display: "grid",
  gap: 12,
  padding: 12,
  border: "1px solid rgba(245,166,35,0.28)",
  borderRadius: "var(--radius-md)",
  background: "linear-gradient(135deg, rgba(245,166,35,0.09), rgba(42,198,238,0.05))",
};

const veryfinderLoadTopStyle = {
  display: "grid",
  gridTemplateColumns: "minmax(240px, 1fr) auto",
  gap: 14,
  alignItems: "center",
};

const veryfinderLoadKickerStyle = {
  fontSize: 10,
  color: "var(--warn)",
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  fontFamily: "JetBrains Mono, monospace",
};

const veryfinderLoadTitleStyle = {
  marginTop: 3,
  marginBottom: 5,
  fontSize: 18,
  color: "var(--text-primary)",
  fontWeight: 700,
};

const veryfinderLoadMeterStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(3, 11px)",
  gap: 5,
  alignItems: "end",
  height: 42,
};

const veryfinderLoadBarStyle = {
  display: "block",
  width: 11,
  borderRadius: 8,
  background: "linear-gradient(180deg, var(--accent), rgba(245,166,35,0.88))",
  boxShadow: "0 0 14px rgba(42,198,238,0.35)",
};

const veryfinderStepGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 8,
};

const veryfinderStepCardStyle = {
  display: "grid",
  gap: 3,
  padding: "8px 9px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(0,0,0,0.16)",
  color: "var(--text-secondary)",
  fontSize: 11,
};

const veryfinderLoadMetaStyle = {
  display: "flex",
  flexWrap: "wrap" as const,
  gap: 10,
  fontSize: 11,
  color: "var(--text-mute)",
};

const tweetSearchControlStyle = {
  display: "flex",
  alignItems: "end",
  gap: 8,
  flexWrap: "wrap" as const,
  marginBottom: 12,
  minWidth: 0,
};

const tweetSearchLabelStyle = {
  display: "grid",
  gap: 4,
  minWidth: 116,
  color: "var(--text-mute)",
  fontSize: 10,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
};

const tweetSearchInputStyle = {
  height: 28,
  width: 154,
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 12,
  padding: "0 8px",
};

const tweetSearchGoButtonStyle = {
  minHeight: 28,
  minWidth: 48,
  padding: "0 12px",
  fontWeight: 700,
};

const tweetSearchIntentStyle = {
  minHeight: 28,
  display: "inline-flex",
  alignItems: "center",
  color: "var(--text-secondary)",
  fontSize: 11,
  fontFamily: "JetBrains Mono, monospace",
};

const tweetDrawerStyle = {
  display: "grid",
  gap: 8,
  minWidth: 0,
};

const tweetDrawerToggleStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  width: "100%",
  minHeight: 30,
  textAlign: "left" as const,
};

const tweetListStyle = {
  display: "grid",
  gap: 8,
  maxHeight: 340,
  overflowY: "auto" as const,
  paddingRight: 4,
};

const tweetRowStyle = {
  display: "grid",
  gap: 6,
  padding: "9px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(255,255,255,0.025)",
  minWidth: 0,
};

const tweetRowMetaStyle = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  flexWrap: "wrap" as const,
  fontSize: 10,
  color: "var(--text-mute)",
};

const tweetTextStyle = {
  margin: 0,
  color: "var(--text-secondary)",
  fontSize: 12,
  lineHeight: 1.42,
  overflowWrap: "anywhere" as const,
};

const tweetTagRowStyle = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap" as const,
  color: "var(--text-mute)",
  fontSize: 10,
  textTransform: "uppercase" as const,
};

const distributionBlockStyle = {
  display: "grid",
  gap: 8,
  minWidth: 0,
  padding: "9px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(255,255,255,0.025)",
};

const distributionTitleStyle = {
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
};

const distributionRowStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  fontSize: 11,
  color: "var(--text-secondary)",
  minWidth: 0,
};

const distributionTrackStyle = {
  height: 5,
  overflow: "hidden",
  borderRadius: 999,
  background: "rgba(255,255,255,0.06)",
};

const distributionFillStyle = {
  display: "block",
  height: "100%",
  borderRadius: 999,
  background: "var(--accent)",
};

const labelStyle = {
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase" as const,
  color: "var(--text-mute)",
};

const selectStyle = {
  height: 28,
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 12,
  padding: "0 8px",
  width: "100%",
};

const miniSelectStyle = {
  height: 24,
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 11,
  padding: "0 6px",
};

const veryfinderToggleStyle = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  height: 24,
  color: "var(--text-secondary)",
  fontSize: 11,
  fontFamily: "JetBrains Mono, monospace",
};

const footerSourceStyle = {
  minWidth: 0,
  maxWidth: "48%",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap" as const,
};
