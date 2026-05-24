/**
 * ANR — Analyst Recommendations.
 *
 * Consensus-first view with explicit target-price provenance, stale-rule
 * accounting, broker-level table readiness, and local alert editing.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import { SymbolBar } from "@/shell/SymbolBar";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { listRecentSymbols } from "@/lib/symbols";
import {
  fetchVeryfinderQuery,
  recommendedVeryfinderSampleForSymbol,
  type VeryfinderOverlay,
} from "@/lib/veryfinder";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "../function-controls";
import type { FunctionPaneProps } from "../registry-types";
import {
  ANR_SCREEN_OPTIONS,
  BACKGROUND_VERYFINDER_REFRESHED_AT,
  VERYFINDER_BACKGROUND_REFRESH_MS,
  VERYFINDER_LIVE_REFRESH_MS,
  type ANRData,
  type ANRScreen,
  type VeryfinderRunState,
} from "./_types";
import {
  clampTweetSample,
  consensusHeaderLabel,
  consensusHeaderTone,
  formatHeaderTime,
  formatInt,
  formatScore,
  formatSources,
  isCryptoSummary,
  notifyVeryfinderComplete,
} from "./formatters";
import {
  footerSourceStyle,
  miniSelectStyle,
  screenBarStyle,
  screenHintStyle,
  veryfinderToggleStyle,
} from "./styles";
import {
  ConsensusCard,
  StaleRuleCard,
  TargetCard,
  VeryfinderConsensusCard,
} from "./cards";
import {
  AlertEditor,
  AnalystQuality,
  AnalystTable,
  BucketTable,
  Methodology,
  SignalInputsTable,
  SourceFreshness,
} from "./tables";
import { ANRAnalysisScreen } from "./analysis";

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
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      veryfinderRequestId.current += 1;
    };
  }, []);
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
        if (!mountedRef.current || requestId !== veryfinderRequestId.current) return;
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
        if (!mountedRef.current || requestId !== veryfinderRequestId.current) return;
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

  // Bundle D / PERF-04. Both the live and background poll loops now lean on
  // `useVisibilityTick` so background tabs stop pulling Veryfinder data.
  // We still gate on `veryfinderEnabled` + `effectiveSymbol` inside the
  // effects; the tick value is the only thing driving the time axis.
  const veryfinderLiveTick = useVisibilityTick(VERYFINDER_LIVE_REFRESH_MS);
  const veryfinderBackgroundTick = useVisibilityTick(VERYFINDER_BACKGROUND_REFRESH_MS);
  const liveTickFirstRef = useRef(true);
  const bgTickFirstRef = useRef(true);
  useEffect(() => {
    if (!veryfinderEnabled || !effectiveSymbol) return;
    // Skip the initial tick value (0) — the first fetch is already issued by
    // the runVeryfinderFetch effect on mount / symbol change. We only want
    // *subsequent* ticks to trigger the live refresh.
    if (liveTickFirstRef.current) {
      liveTickFirstRef.current = false;
      return;
    }
    runVeryfinderFetch({ refresh: true, background: true });
  }, [effectiveSymbol, runVeryfinderFetch, veryfinderEnabled, veryfinderLiveTick]);

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
    // First tick (0) acts as the warmup — fire after 500ms; subsequent ticks
    // are the real visibility-aware interval.
    if (bgTickFirstRef.current) {
      bgTickFirstRef.current = false;
      const warmup = window.setTimeout(refreshBackgroundSymbols, 500);
      return () => window.clearTimeout(warmup);
    }
    refreshBackgroundSymbols();
  }, [effectiveSymbol, veryfinderEnabled, veryfinderSource, veryfinderBackgroundTick]);

  const runVeryfinderTweetSearch = () => {
    const next = clampTweetSample(veryfinderMinTweetsInput);
    manualVeryfinderRun.current = true;
    setVeryfinderMinTweets(next);
    setVeryfinderMinTweetsInput(String(next));
    setVeryfinderTick((tick) => tick + 1);
  };

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-10">
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

  const headerTone = consensusHeaderTone(summary?.label);
  const headerPillLabel = consensusHeaderLabel(summary?.label);
  const analystCount =
    summary?.analyst_count ??
    summary?.signal_count ??
    summary?.included_count ??
    null;
  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`${effectiveSymbol} ${isCryptoSummary(summary) ? "Crypto Market Consensus" : "Analyst Consensus"}`}
          subtitle={`${summary?.label ?? "loading"} · target: ${summary?.target_price_source ?? "—"}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={headerTone} variant="soft" withDot={headerTone !== "muted"}>
                {headerPillLabel}
              </Pill>
              {analystCount != null ? (
                <Pill tone="muted" variant="soft" withDot={false}>
                  {formatInt(analystCount)} {isCryptoSummary(summary) ? "sig" : "anl"}
                </Pill>
              ) : null}
              {summary?.last_updated ? (
                <Pill tone="muted" variant="soft" withDot={false}>
                  AS OF {formatHeaderTime(summary.last_updated)}
                </Pill>
              ) : null}
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
            <div className="u-grid-gap-8 u-text-secondary u-text-mute">
              <strong className="u-text-accent u-mono">
                ANR · Analyst Recommendations
              </strong>
              <span >
                Shows consensus score, bucket distribution, target-price source, stale exclusions,
                broker-level table status, crypto signal inputs, and editable local recommendation-alert rules.
              </span>
              <span >
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
    <div data-testid="function-payload" className="u-grid-gap-12">
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

export default ANRPane;
