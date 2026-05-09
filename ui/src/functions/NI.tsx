/**
 * NI / CN — topic-news and company-news headline drawers.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Card,
  CardBody,
  Empty,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
} from "@/design-system";
import { runFunction, FunctionCallError } from "@/lib/functions";
import { useAppStore } from "@/lib/store";
import { isInTauri } from "@/lib/tauri";
import { relativeTimeLabel, sortNewsNewestFirst } from "@/lib/time";
import { SymbolBar } from "@/shell/SymbolBar";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { toast } from "@/lib/toast";
import {
  fetchVeryfinderBatch,
  recommendedVeryfinderSampleForNews,
  type VeryfinderBatchItem,
  type VeryfinderOverlay,
  type VeryfinderTone,
} from "@/lib/veryfinder";
import {
  FunctionControlGroup,
  LoadStatePill,
  NewsLimitControl,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import {
  NEWS_LIMITS,
  type NewsLimit,
  usePersistentOption,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface NIArticle {
  title?: string;
  headline?: string;
  summary?: string;
  source?: string;
  url?: string;
  link?: string;
  published_at?: string;
  publishedAt?: string;
  published_on?: string;
  published?: string;
  date?: string;
  datetime?: string;
  time?: string;
  ts?: string;
  symbols?: string[];
  symbol?: string;
  category?: string;
  severity?: string;
  importance_score?: number;
  relevance_score?: number;
  importance_reasons?: string[];
  matched_terms?: string[];
}

const REFRESH_MS = 90_000;
const FETCH_NEWS_LIMIT = Math.max(...NEWS_LIMITS);
const TOPIC_PRESETS = ["MACRO", "FED", "EARN", "CHIPS", "OIL", "BANKS", "TECH", "CRYPTO"] as const;
type TopicPreset = (typeof TOPIC_PRESETS)[number];
type LoadState = "idle" | "loading" | "ok" | "error";

export function NIPane({ code, symbol }: FunctionPaneProps) {
  const upperCode = code.toUpperCase();
  const topicMode = upperCode === "NI";
  const [topicText, setTopicText] = useState("MACRO");
  const [articles, setArticles] = useState<NIArticle[] | null>(null);
  const [veryfinderMap, setVeryfinderMap] = useState<Record<string, VeryfinderOverlay>>({});
  const [veryfinderState, setVeryfinderState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [limit, setLimit] = usePersistentOption<NewsLimit>(
    `showme.${topicMode ? "ni-topic" : "cn"}-news-limit`,
    NEWS_LIMITS,
    50,
  );
  const [tick, setTick] = useState(0);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const sidecarPort = useAppStore((s) => s.sidecarPort);
  const waitingForSidecar = isInTauri() && sidecarPort == null;
  const requestLabel = topicMode ? topicText.trim() : symbol;
  const veryfinderNotifiedBatch = useRef("");

  useEffect(() => {
    const currentTopic = topicText.trim();
    const currentLabel = topicMode ? currentTopic : symbol;
    if (!currentLabel) {
      setArticles(null);
      setError(null);
      setState("idle");
      return;
    }
    if (waitingForSidecar) {
      setArticles(null);
      setError(null);
      setState("loading");
      return;
    }
    let cancelled = false;
    setError(null);
    setArticles(null);
    setVeryfinderMap({});
    setVeryfinderState("idle");
    setState("loading");
    const fnCode = topicMode ? "NI" : "CN";
    const liveParams = { limit: FETCH_NEWS_LIMIT, live: true, news_timeout: 6, timeout: 6 };
    const topicParams = { ...liveParams, topic: currentTopic, query: currentTopic };
    const requestNews = (params: Record<string, unknown>) =>
      runFunction<unknown>(fnCode, {
        symbol: topicMode ? undefined : symbol,
        params,
        timeoutMs: 18_000,
      }).catch(async (err) => {
        if (!topicMode && err instanceof FunctionCallError && err.status === 404) {
          return runFunction<unknown>("NI", { symbol, params: { ...params, topic: symbol } });
        }
        throw err;
      });

    requestNews(topicMode ? topicParams : liveParams)
      .then(async (res) => {
        const items = normalize(res.data);
        if (
          !cancelled &&
          items.length === 0 &&
          res.sources?.some((source) => String(source).toLowerCase() === "no_live_source")
        ) {
          await delay(600);
          const retryParams = { ...liveParams, news_timeout: 10, timeout: 10, deep: true };
          return requestNews(
            topicMode
              ? { ...retryParams, topic: currentTopic, query: currentTopic }
              : retryParams,
          );
        }
        return res;
      })
      .then((res) => {
        if (cancelled) return;
        const nextArticles = normalize(res.data);
        setArticles(nextArticles);
        setVeryfinderState(nextArticles.length ? "loading" : "idle");
        setState("ok");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [code, topicMode, symbol, tick, waitingForSidecar, sidecarPort, topicText]);

  useEffect(() => {
    if (!articles?.length || waitingForSidecar) {
      setVeryfinderMap({});
      setVeryfinderState(articles?.length ? "loading" : "idle");
      return;
    }
    const sorted = sortNewsNewestFirst(articles, articleTimestamp);
    const items: VeryfinderBatchItem[] = sorted.map((article, index) => ({
      key: articleKey(article, index),
      title: article.title,
      headline: article.headline,
      summary: article.summary,
      source: article.source,
      url: article.url,
      link: article.link,
      category: article.category,
      symbol: article.symbol,
      sample: recommendedVeryfinderSampleForNews(article, topicMode ? undefined : symbol),
    }));
    if (!items.length) {
      setVeryfinderMap({});
      setVeryfinderState("idle");
      return;
    }
    let cancelled = false;
    setVeryfinderState("loading");
    fetchVeryfinderBatch({
      items,
      symbol: topicMode ? undefined : symbol,
      topic: topicMode ? topicText.trim() : undefined,
      sample: 25,
      source: "auto",
      engine: "rules",
      limit: items.length,
    })
      .then((payload) => {
        if (cancelled) return;
        const next: Record<string, VeryfinderOverlay> = {};
        for (const item of payload.items ?? []) {
          next[item.key] = item.overlay;
        }
        setVeryfinderMap(next);
        setVeryfinderState(payload.ok ? "ok" : "error");
        const batchId = items.map((item) => `${item.key}:${item.sample}`).join("|");
        if (payload.ok && batchId && veryfinderNotifiedBatch.current !== batchId) {
          veryfinderNotifiedBatch.current = batchId;
          toast.success("Veryfinder news inference ready", `${payload.items?.length ?? 0} headline(s) scored with article-level tweet targets.`);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setVeryfinderMap({});
        setVeryfinderState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [articles, topicMode, topicText, symbol, waitingForSidecar, sidecarPort]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const veryfinderTweetTarget = useMemo(
    () =>
      articles?.reduce(
        (sum, article) => sum + recommendedVeryfinderSampleForNews(article, topicMode ? undefined : symbol),
        0,
      ) ?? 0,
    [articles, topicMode, symbol],
  );
  const veryfinderIsBlocking =
    Boolean(articles?.length) && (veryfinderState === "idle" || veryfinderState === "loading");
  const effectiveState: LoadState = state === "ok" && veryfinderIsBlocking ? "loading" : state;

  const body = !requestLabel ? (
    <Empty
      title={topicMode ? "Enter a topic" : "Pick a symbol"}
      body={topicMode ? "NI searches recent headlines by topic." : `${code} tails recent headlines for one ticker.`}
      icon="⌖"
    />
  ) : error ? (
    <Empty title="Function error" body={error} icon="!" />
  ) : effectiveState === "loading" || articles == null ? (
    <LoadingNews
      label={requestLabel}
      phase={veryfinderIsBlocking ? "veryfinder" : "headlines"}
      headlineCount={articles?.length ?? 0}
      tweetTarget={veryfinderTweetTarget}
    />
  ) : articles.length === 0 ? (
    <Empty title="No headlines yet" body={`No news payload for ${requestLabel} in last ${limit}.`} />
  ) : (
    <ArticleList
      articles={articles}
      displayLimit={limit}
      setFocusedTarget={setFocusedTarget}
      veryfinderMap={veryfinderMap}
      veryfinderState={veryfinderState}
      fallbackSymbol={topicMode ? undefined : symbol}
    />
  );

  return (
    <div style={{ padding: 18, height: "100%", minHeight: 0, boxSizing: "border-box" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={topicMode ? `News by topic - ${topicText.trim() || "topic"}` : `Company news - ${symbol ?? ""}`}
          subtitle={
            effectiveState === "loading" && requestLabel
              ? veryfinderIsBlocking
                ? `scanning evidence for ${requestLabel} · ${articles?.length ?? 0} headline(s)`
                : `loading ${requestLabel} · fetching latest ${FETCH_NEWS_LIMIT}`
              : articles
                ? `${Math.min(articles.length, limit)}/${articles.length} shown`
                : "polling every 90s"
          }
          trailing={
            <FunctionControlGroup>
              <NewsLimitControl value={limit} onChange={setLimit} disabled={effectiveState === "loading"} />
              <LoadStatePill state={effectiveState} />
              <RefreshButton
                loading={effectiveState === "loading"}
                onClick={() => setTick((t) => t + 1)}
                title="Refresh headlines"
              />
            </FunctionControlGroup>
          }
        />
        {topicMode ? (
          <section style={topicBar}>
            <Field
              label="Topic"
              value={topicText}
              onChange={(e) => setTopicText(e.target.value)}
              placeholder="FED, earnings, crypto liquidity..."
              hint="Topic text is sent as topic/query; it is not treated as a ticker."
              onKeyDown={(e) => {
                if (e.key === "Enter") setTick((t) => t + 1);
              }}
            />
            <SegmentedControl
              label="TOPIC"
              value={TOPIC_PRESETS.includes(topicText as TopicPreset) ? topicText : ""}
              options={TOPIC_PRESETS}
              onChange={(next) => {
                setTopicText(String(next));
                setTick((t) => t + 1);
              }}
              disabled={effectiveState === "loading"}
            />
          </section>
        ) : (
          <SymbolBar code={code} symbol={symbol} />
        )}
        <PaneBody
          style={{
            overflowY: "auto",
            overflowX: "hidden",
            overscrollBehavior: "contain",
            WebkitOverflowScrolling: "touch",
          }}
        >
          {body}
        </PaneBody>
        <PaneFooter>
          <span>refresh · {REFRESH_MS / 1000}s</span>
          <span>last · show {limit}</span>
          <span>cached · {articles?.length ?? 0} news</span>
          <span>veryfinder · {veryfinderState}</span>
          <span>{topicMode ? `topic · ${topicText || "—"}` : `symbol · ${symbol ?? "—"}`}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

const NEWS_PIPELINE_STEPS = [
  {
    title: "Headlines",
    status: "fetching",
    detail: "Live company headlines, source timestamps, direct links.",
  },
  {
    title: "Symbol map",
    status: "normalizing",
    detail: "Ticker aliases, company names, crypto suffixes, query terms.",
  },
  {
    title: "Social window",
    status: "sizing",
    detail: "Efficient min-tweet target and newest evidence window.",
  },
  {
    title: "Search",
    status: "probing",
    detail: "Public web/news/social rows, recency filter, source fallback.",
  },
  {
    title: "Dedupe",
    status: "hashing",
    detail: "Unique-account vote, duplicate rows and stale evidence dropped.",
  },
  {
    title: "Inference",
    status: "scoring",
    detail: "Sentiment, action, market view, impact label, render payload.",
  },
] as const;

const NEWS_PIPELINE_LOGS = [
  "news.fetch: requesting latest headline batch",
  "symbol.resolve: matching ticker, aliases, and source tags",
  "window.size: assigning min tweet target per article",
  "source.search: querying public web/news/social evidence",
  "recency.filter: dropping stale rows before scoring",
  "account.dedupe: one visible vote per source/account",
  "inference.run: sentiment, action, view, impact",
  "render.queue: cards update as soon as rows finish",
] as const;

function LoadingNews({
  label,
  phase = "headlines",
  headlineCount = 0,
  tweetTarget = 0,
}: {
  label: string;
  phase?: "headlines" | "veryfinder";
  headlineCount?: number;
  tweetTarget?: number;
}) {
  const waitingForVeryfinder = phase === "veryfinder";
  return (
    <div aria-live="polite" style={newsLoadShell}>
      <style>{newsLoadAnimationCss}</style>
      <div className="showme-news-scanline" />
      <div style={newsLoadHeader}>
        <div style={{ minWidth: 0 }}>
          <div style={newsLoadKicker}>
            {waitingForVeryfinder ? "Veryfinder evidence pipeline" : "News + Veryfinder pipeline"}
          </div>
          <strong style={newsLoadTitle}>
            {waitingForVeryfinder ? `Scanning evidence for ${label}` : `Building live view for ${label}`}
          </strong>
          <p style={newsLoadText}>
            {waitingForVeryfinder
              ? `Headline batch is ready (${headlineCount} rows). Keeping the loading screen open while Veryfinder collects the newest usable evidence, filters stale rows, dedupes sources, and scores every card. Target window: ${tweetTarget} evidence rows.`
              : "Fetching headlines first, then rolling each item through source search, recency filtering, unique-account dedupe, and sentiment/action inference. Rows appear when each article has enough usable evidence or a clear source-capacity note."}
          </p>
        </div>
        <div style={newsLoadDial} title="Pipeline activity">
          <span style={newsLoadDialCenter}>VF</span>
          {Array.from({ length: 12 }).map((_, index) => (
            <span
              key={index}
              className="showme-news-orbit-dot"
              style={{ transform: `rotate(${index * 30}deg) translateY(-34px)` }}
            />
          ))}
        </div>
      </div>

      <div style={newsLoadRail} className="showme-news-data-rail">
        <span style={newsLoadRailLabel}>packet rail</span>
        <span style={newsLoadRailValue}>
          {waitingForVeryfinder
            ? "headline batch ready -&gt; newest evidence -&gt; scored cards"
            : "headline rows -&gt; evidence rows -&gt; scored cards"}
        </span>
      </div>

      <div style={newsLoadSteps}>
        {NEWS_PIPELINE_STEPS.map((step, index) => (
          <div key={step.title} style={newsLoadStep}>
            <div style={newsLoadStepIndex}>{index + 1}</div>
            <div style={{ minWidth: 0 }}>
              <strong style={newsLoadStepTitle}>{step.title}</strong>
              <span style={newsLoadStepStatus}>{step.status}</span>
              <small style={newsLoadStepDetail}>{step.detail}</small>
            </div>
          </div>
        ))}
      </div>

      <div style={newsLoadTelemetryGrid}>
        <div style={newsLoadTerminal}>
          <div style={newsLoadTerminalHeader}>
            <span>live pipeline log</span>
            <strong>streaming</strong>
          </div>
          <div style={newsLoadLogList}>
            {NEWS_PIPELINE_LOGS.map((line, index) => (
              <div
                key={line}
                className="showme-news-log-line"
                style={{ animationDelay: `${index * 220}ms` }}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <code>{line}</code>
              </div>
            ))}
          </div>
        </div>
        <div style={newsLoadStatusPanel}>
          <div style={newsLoadStatusRow}>
            <strong>Why this can take time</strong>
            <span>Veryfinder waits for usable evidence instead of filling cards with stale rows.</span>
          </div>
          <div style={newsLoadStatusRow}>
            <strong>Slow-source behavior</strong>
            <span>If a provider is late, ShowMe keeps the search alive, records the source-capacity note, and renders partial rows.</span>
          </div>
          <div style={newsLoadStatusRow}>
            <strong>Freshness rule</strong>
            <span>Known old evidence is filtered before scoring, so the view stays recent.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function VeryfinderScanBanner({
  label,
  pending,
  total,
  tweetTarget,
}: {
  label: string;
  pending: number;
  total: number;
  tweetTarget: number;
}) {
  return (
    <section aria-live="polite" style={vfScanBanner}>
      <style>{newsLoadAnimationCss}</style>
      <div className="showme-news-scanline" />
      <div style={{ minWidth: 0 }}>
        <div style={newsLoadKicker}>Veryfinder rolling evidence window</div>
        <strong style={vfScanTitle}>Scanning {label}</strong>
        <p style={vfScanText}>
          Headlines are on screen. ShowMe is now collecting newest usable social/news evidence,
          filtering stale rows, deduping accounts/sources, and updating each card as inference finishes.
        </p>
      </div>
      <div style={vfScanMetrics}>
        <div style={vfScanMetric}>
          <span>pending rows</span>
          <strong style={vfScanMetricValue}>{pending}/{total}</strong>
        </div>
        <div style={vfScanMetric}>
          <span>target window</span>
          <strong style={vfScanMetricValue}>{tweetTarget}</strong>
        </div>
        <div style={vfScanMetric}>
          <span>active step</span>
          <strong style={vfScanMetricValue}>dedupe + score</strong>
        </div>
      </div>
      <div style={newsLoadRail} className="showme-news-data-rail">
        <span style={newsLoadRailLabel}>live rail</span>
        <span style={newsLoadRailValue}>newest evidence -&gt; recency filter -&gt; unique-source score</span>
      </div>
    </section>
  );
}

function ArticleList({
  articles,
  displayLimit,
  setFocusedTarget,
  veryfinderMap,
  veryfinderState,
  fallbackSymbol,
}: {
  articles: NIArticle[];
  displayLimit: NewsLimit;
  setFocusedTarget: (code: string, symbol?: string) => void;
  veryfinderMap: Record<string, VeryfinderOverlay>;
  veryfinderState: LoadState;
  fallbackSymbol?: string;
}) {
  const sortedArticles = useMemo(
    () => sortNewsNewestFirst(articles, articleTimestamp),
    [articles],
  );
  const visibleArticles = useMemo(
    () => sortedArticles.slice(0, displayLimit),
    [sortedArticles, displayLimit],
  );
  const totalTweetTarget = useMemo(
    () =>
      visibleArticles.reduce(
        (sum, article) => sum + recommendedVeryfinderSampleForNews(article, fallbackSymbol),
        0,
      ),
    [visibleArticles, fallbackSymbol],
  );
  const pendingVeryfinderRows = visibleArticles.reduce((count, article, index) => {
    const key = articleKey(article, index);
    return count + (veryfinderMap[key] ? 0 : 1);
  }, 0);
  const scanLabel =
    fallbackSymbol ?? visibleArticles[0]?.symbol ?? visibleArticles[0]?.symbols?.[0] ?? "news";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingBottom: 8 }}>
      {veryfinderState === "loading" ? (
        <VeryfinderScanBanner
          label={scanLabel}
          pending={pendingVeryfinderRows}
          total={visibleArticles.length}
          tweetTarget={totalTweetTarget}
        />
      ) : null}
      {visibleArticles.map((a, i) => {
        const key = articleKey(a, i);
        const veryfinder = veryfinderMap[key];
        const tweetTarget = recommendedVeryfinderSampleForNews(a, fallbackSymbol);
        return (
          <Card key={key} density="compact">
            <CardBody>
              <div style={articleHead}>
                <strong style={{ fontSize: 13, color: "var(--text-primary)" }}>
                  {a.title ?? a.headline ?? "(untitled)"}
                </strong>
                {a.source ? (
                  <Pill tone="muted" withDot={false}>
                    {a.source}
                  </Pill>
                ) : null}
                {a.category ? <span style={tinyMute}>{a.category}</span> : null}
                {a.importance_score != null ? (
                  <Pill tone={a.severity === "critical" || a.severity === "high" ? "negative" : "muted"} withDot={false}>
                    impact {Number(a.importance_score).toFixed(0)}
                  </Pill>
                ) : null}
                {veryfinder ? <VeryfinderImpactPill overlay={veryfinder} /> : null}
                {!veryfinder && veryfinderState === "loading" && i < 3 ? (
                  <Pill tone="muted" withDot={false}>vf scanning {tweetTarget}</Pill>
                ) : null}
              </div>
            {a.summary ? <p style={summaryStyle}>{truncate(cleanSummary(a.summary), 220)}</p> : null}
            {veryfinder ? (
              <VeryfinderArticleInsight overlay={veryfinder} target={tweetTarget} />
            ) : veryfinderState === "loading" ? (
              <VeryfinderArticleLoading target={tweetTarget} />
            ) : null}
            <div style={articleMeta}>
              {(a.symbols ?? (a.symbol ? [a.symbol] : [])).slice(0, 5).map((s) => (
                <button
                  key={s}
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => {
                    setFocusedTarget("DES", s);
                    navigate(`/symbol/${s}/DES`);
                  }}
                  style={symbolButton}
                >
                  {s}
                </button>
              ))}
              {Array.isArray(a.importance_reasons)
                ? a.importance_reasons.slice(0, 2).map((reason) => (
                    <span key={reason} style={tinyMute}>
                      {reason}
                    </span>
                  ))
                : null}
              <span style={{ flex: 1 }} />
              <span style={tinyMute}>{tsLabel(a) ?? ""}</span>
              {(a.url ?? a.link) ? (
                <a
                  href={a.url ?? a.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ fontSize: 10, color: "var(--accent)" }}
                >
                  source ↗
                </a>
              ) : null}
            </div>
          </CardBody>
        </Card>
        );
      })}
    </div>
  );
}

function VeryfinderImpactPill({ overlay }: { overlay: VeryfinderOverlay }) {
  if (!overlay.ok) {
    return (
      <Pill tone="warn" withDot={false}>
        vf error
      </Pill>
    );
  }
  if ((overlay.dominant_view?.label ?? "") === "no_data" || Number(overlay.unique_accounts ?? 0) <= 0) {
    return (
      <Pill tone="muted" withDot={false}>
        vf no match
      </Pill>
    );
  }
  const vfScore = formatInt(veryfinderDisplayScore(overlay));
  const directionScore = formatSignedInt(overlay.social_score);
  const view = overlay.dominant_view?.display ?? "social";
  const confidence = Math.round(Number(overlay.dominant_view?.score ?? 0) * 100);
  const source = veryfinderSourceLabel(overlay);
  const title = [
    overlay.meaning,
    `vf impact score: ${vfScore}`,
    `direction score: ${directionScore}`,
    `query: ${overlay.query ?? "n/a"}`,
    `source: ${source}`,
    `unique accounts: ${overlay.unique_accounts ?? "n/a"}`,
    overlay.top_mood ? `mood: ${overlay.top_mood.label}` : null,
    overlay.top_action ? `action: ${overlay.top_action.label}` : null,
  ].filter(Boolean).join("\n");
  return (
    <span title={title}>
      <Pill tone={veryfinderTone(overlay.tone)} withDot={false}>
        vf {vfScore} {view} {confidence}%
      </Pill>
    </span>
  );
}

function VeryfinderArticleInsight({ overlay, target }: { overlay: VeryfinderOverlay; target: number }) {
  if (!overlay.ok) {
    return (
      <div style={vfInsightStyle}>
        <strong>Veryfinder</strong>
        <span>analysis failed: {overlay.error ?? "unknown error"}</span>
      </div>
    );
  }
  if ((overlay.dominant_view?.label ?? "") === "no_data" || Number(overlay.unique_accounts ?? 0) <= 0) {
    return (
      <div style={vfInsightStyle}>
        <strong>Veryfinder inference</strong>
        <span>{veryfinderNoDataLabel(overlay)}</span>
        <span>
          target {formatInt(target)} · requested {formatInt(overlay.requested_sample)} · source posts {formatInt(overlay.source_posts)}
        </span>
        <span>{veryfinderSourceLabel(overlay)}</span>
      </div>
    );
  }
  const view = overlay.dominant_view?.display ?? "no view";
  const confidence = Math.round(Number(overlay.dominant_view?.score ?? 0) * 100);
  const action = overlay.top_action?.label?.replaceAll("_", " ") ?? "action —";
  const mood = overlay.top_mood?.label?.replaceAll("_", " ") ?? "mood —";
  return (
    <div style={vfInsightStyle}>
      <strong>Veryfinder inference</strong>
      <span>vf score {formatInt(veryfinderDisplayScore(overlay))} · {view} · {confidence}% confidence · action {action} · mood {mood}</span>
      <span>
        {veryfinderSampleLabel(overlay, target)}
      </span>
      <span>{veryfinderSourceLabel(overlay)}</span>
    </div>
  );
}

function VeryfinderArticleLoading({ target }: { target: number }) {
  return (
    <div style={vfInsightLoadingStyle}>
      <span>Veryfinder searching</span>
      <strong>{formatInt(target)} social target</strong>
      <span>fetching posts or news context, deduping sources, scoring sentiment</span>
    </div>
  );
}

function veryfinderSourceLabel(overlay: VeryfinderOverlay): string {
  if (overlay.fallback_mode === "article_context" || overlay.source === "news_proxy") {
    const from = overlay.source_fallback_from ? ` after ${overlay.source_fallback_from}` : "";
    return `news context proxy${from}`;
  }
  return overlay.fixture_mode ? "fixture source" : overlay.source ?? "source —";
}

function veryfinderNoDataLabel(overlay: VeryfinderOverlay): string {
  if (overlay.fixture_mode) return "no query-relevant fixture/social posts found";
  return "no query-relevant social posts found";
}

function veryfinderSampleLabel(overlay: VeryfinderOverlay, target: number): string {
  if (overlay.fallback_mode === "article_context" || overlay.source === "news_proxy") {
    return `context rows ${formatInt(overlay.collected_posts)} · unique sources ${formatInt(overlay.unique_accounts)} · requested social target ${formatInt(overlay.requested_sample ?? target)}`;
  }
  return `target ${formatInt(target)} · requested ${formatInt(overlay.requested_sample)} · collected ${formatInt(overlay.collected_posts)} · unique ${formatInt(overlay.unique_accounts)}`;
}

function veryfinderDisplayScore(overlay: VeryfinderOverlay): number {
  const explicit = Number(overlay.impact_score);
  if (Number.isFinite(explicit)) return Math.round(explicit);
  const confidence = Number(overlay.dominant_view?.score);
  if (Number.isFinite(confidence) && Number(overlay.unique_accounts ?? 0) > 0) {
    return Math.round(Math.max(0, Math.min(1, confidence)) * 100);
  }
  return Math.abs(Math.round(Number(overlay.social_score ?? 0)));
}

function articleKey(a: NIArticle, index: number): string {
  return [
    a.url ?? a.link ?? "",
    a.title ?? a.headline ?? "",
    articleTimestamp(a) ?? "",
    String(index),
  ].join("|");
}

function formatSignedInt(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const n = Math.round(Number(value));
  return n > 0 ? `+${n}` : String(n);
}

function formatInt(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function veryfinderTone(tone?: VeryfinderTone): "positive" | "negative" | "warn" | "muted" | "neutral" {
  if (tone === "positive" || tone === "negative" || tone === "warn" || tone === "muted") {
    return tone;
  }
  return "neutral";
}

function normalize(payload: unknown): NIArticle[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as NIArticle[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.items ?? o.articles ?? o.news ?? o.headlines;
    if (Array.isArray(items)) return items as NIArticle[];
  }
  return [];
}

function cleanSummary(value: string): string {
  try {
    const doc = new DOMParser().parseFromString(value, "text/html");
    const text = doc.body.textContent?.replace(/\s+/g, " ").trim();
    if (text) return text;
  } catch {
    // Fall back to a lightweight strip below.
  }
  return value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

function truncate(value: string, max: number): string {
  return value.length > max ? value.slice(0, max) + "…" : value;
}

function tsLabel(a: NIArticle): string | null {
  return relativeTimeLabel(articleTimestamp(a));
}

function articleTimestamp(a: NIArticle): string | null | undefined {
  return (
    a.published_at ??
    a.publishedAt ??
    a.published_on ??
    a.published ??
    a.date ??
    a.datetime ??
    a.time ??
    a.ts
  );
}

const topicBar: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(220px, 1fr) auto",
  gap: 8,
  alignItems: "end",
  padding: "0 14px 10px",
  borderBottom: "1px solid var(--border-subtle)",
};

const articleHead: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 8,
  flexWrap: "wrap",
  marginBottom: 4,
};

const articleMeta: CSSProperties = {
  display: "flex",
  gap: 6,
  alignItems: "center",
  flexWrap: "wrap",
};

const summaryStyle: CSSProperties = {
  margin: "0 0 6px",
  fontSize: 11,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

const newsLoadShell: CSSProperties = {
  position: "relative",
  overflow: "hidden",
  display: "grid",
  gap: 14,
  padding: 14,
  border: "1px solid rgba(42,198,238,0.42)",
  borderRadius: "var(--radius-md)",
  background: [
    "linear-gradient(135deg, rgba(42,198,238,0.09), rgba(155,107,255,0.045))",
    "radial-gradient(circle at 86% 12%, rgba(155,107,255,0.16), transparent 24%)",
    "linear-gradient(180deg, rgba(255,255,255,0.026), rgba(255,255,255,0.012))",
  ].join(", "),
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04), 0 18px 42px rgba(0,0,0,0.28)",
};

const newsLoadHeader: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(320px, 1fr) 86px",
  gap: 18,
  alignItems: "center",
  position: "relative",
  zIndex: 1,
};

const newsLoadKicker: CSSProperties = {
  fontSize: 10,
  color: "var(--accent)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontFamily: "JetBrains Mono, monospace",
};

const newsLoadTitle: CSSProperties = {
  display: "block",
  marginTop: 5,
  color: "var(--text-primary)",
  fontSize: 20,
  letterSpacing: 0,
};

const newsLoadText: CSSProperties = {
  margin: "8px 0 0",
  color: "var(--text-secondary)",
  fontSize: 12,
  lineHeight: 1.55,
  maxWidth: 920,
};

const newsLoadDial: CSSProperties = {
  position: "relative",
  width: 78,
  height: 78,
  borderRadius: "50%",
  border: "1px solid rgba(42,198,238,0.28)",
  background: "radial-gradient(circle, rgba(42,198,238,0.16), rgba(10,12,18,0.45) 58%, transparent 60%)",
  boxShadow: "0 0 22px rgba(42,198,238,0.2)",
  display: "grid",
  placeItems: "center",
  animation: "showme-news-dial 4.8s linear infinite",
};

const newsLoadDialCenter: CSSProperties = {
  width: 36,
  height: 36,
  borderRadius: "50%",
  display: "grid",
  placeItems: "center",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--accent)",
  background: "rgba(0,0,0,0.36)",
  border: "1px solid rgba(42,198,238,0.3)",
  animation: "showme-news-dial-core 1.6s ease-in-out infinite",
};

const newsLoadRail: CSSProperties = {
  position: "relative",
  zIndex: 1,
  minHeight: 34,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  padding: "8px 10px",
  border: "1px solid rgba(42,198,238,0.22)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(0,0,0,0.18)",
  overflow: "hidden",
};

const newsLoadRailLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--accent)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const newsLoadRailValue: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--text-secondary)",
  overflowWrap: "anywhere",
};

const newsLoadSteps: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
  gap: 8,
  position: "relative",
  zIndex: 1,
};

const newsLoadStep: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "28px minmax(0, 1fr)",
  alignItems: "start",
  gap: 10,
  minHeight: 78,
  padding: "10px 11px",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: "var(--radius-sm)",
  background: "linear-gradient(180deg, rgba(255,255,255,0.038), rgba(255,255,255,0.018))",
  color: "var(--text-secondary)",
  fontSize: 11,
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.035)",
};

const newsLoadStepIndex: CSSProperties = {
  width: 24,
  height: 24,
  borderRadius: "50%",
  display: "grid",
  placeItems: "center",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--accent)",
  background: "rgba(42,198,238,0.1)",
  border: "1px solid rgba(42,198,238,0.22)",
};

const newsLoadStepTitle: CSSProperties = {
  display: "block",
  color: "var(--text-primary)",
  fontSize: 11,
  lineHeight: 1.25,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};

const newsLoadStepStatus: CSSProperties = {
  display: "block",
  marginTop: 4,
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
};

const newsLoadStepDetail: CSSProperties = {
  display: "block",
  marginTop: 5,
  color: "var(--text-secondary)",
  lineHeight: 1.35,
};

const newsLoadTelemetryGrid: CSSProperties = {
  position: "relative",
  zIndex: 1,
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 10,
};

const newsLoadTerminal: CSSProperties = {
  minHeight: 152,
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(3,5,10,0.38)",
  overflow: "hidden",
};

const newsLoadTerminalHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 10,
  padding: "8px 10px",
  borderBottom: "1px solid rgba(255,255,255,0.07)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
};

const newsLoadLogList: CSSProperties = {
  display: "grid",
  gap: 5,
  padding: 10,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

const newsLoadStatusPanel: CSSProperties = {
  display: "grid",
  gap: 8,
  minWidth: 0,
};

const newsLoadStatusRow: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "9px 10px",
  border: "1px solid rgba(245,166,35,0.18)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(245,166,35,0.035)",
  color: "var(--text-secondary)",
  fontSize: 11,
};

const vfScanBanner: CSSProperties = {
  position: "relative",
  overflow: "hidden",
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
  gap: 12,
  padding: 14,
  border: "1px solid rgba(42,198,238,0.28)",
  borderRadius: "var(--radius-md)",
  background:
    "radial-gradient(circle at 88% 15%, rgba(162,124,255,0.24), transparent 32%), linear-gradient(135deg, rgba(42,198,238,0.09), rgba(10,12,22,0.68) 55%, rgba(245,166,35,0.06))",
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05), 0 14px 34px rgba(0,0,0,0.22)",
};

const vfScanTitle: CSSProperties = {
  display: "block",
  color: "var(--text-primary)",
  fontSize: 16,
  lineHeight: 1.2,
};

const vfScanText: CSSProperties = {
  maxWidth: 760,
  margin: "7px 0 0",
  color: "var(--text-secondary)",
  fontSize: 12,
  lineHeight: 1.45,
};

const vfScanMetrics: CSSProperties = {
  position: "relative",
  zIndex: 1,
  display: "grid",
  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
  gap: 8,
};

const vfScanMetric: CSSProperties = {
  display: "grid",
  gap: 5,
  minWidth: 0,
  padding: "10px 11px",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(3,5,10,0.34)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};

const vfScanMetricValue: CSSProperties = {
  minWidth: 0,
  overflow: "hidden",
  textOverflow: "ellipsis",
  color: "var(--text-primary)",
  fontSize: 15,
  lineHeight: 1.1,
  letterSpacing: "0",
  textTransform: "none",
};

const newsLoadAnimationCss = `
@keyframes showme-news-rail {
  from { background-position: 0 0; }
  to { background-position: 56px 0; }
}
@keyframes showme-news-scan {
  0% { transform: translateY(-100%); opacity: 0; }
  18% { opacity: 0.18; }
  100% { transform: translateY(520px); opacity: 0; }
}
@keyframes showme-news-dial {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
@keyframes showme-news-dial-core {
  0%, 100% { box-shadow: 0 0 0 rgba(42,198,238,0); }
  50% { box-shadow: 0 0 18px rgba(42,198,238,0.35); }
}
@keyframes showme-news-log {
  0%, 18% { opacity: 0.32; transform: translateX(-4px); }
  35%, 100% { opacity: 1; transform: translateX(0); }
}
.showme-news-scanline {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(180deg, transparent, rgba(42,198,238,0.1), transparent);
  height: 80px;
  animation: showme-news-scan 4.8s linear infinite;
}
.showme-news-orbit-dot {
  position: absolute;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: rgba(42,198,238,0.7);
  box-shadow: 0 0 10px rgba(42,198,238,0.55);
}
.showme-news-data-rail::after {
  content: "";
  position: absolute;
  inset: 0;
  opacity: 0.28;
  background-image: repeating-linear-gradient(
    -45deg,
    transparent,
    transparent 10px,
    rgba(42,198,238,0.28) 10px,
    rgba(42,198,238,0.28) 18px
  );
  background-size: 56px 56px;
  animation: showme-news-rail 900ms linear infinite;
}
.showme-news-log-line {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 9px;
  color: var(--text-secondary);
  animation: showme-news-log 1.8s ease-in-out infinite alternate;
}
.showme-news-log-line span {
  color: var(--text-mute);
}
.showme-news-log-line code {
  color: var(--text-secondary);
  white-space: normal;
}
`;

const vfInsightStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
  alignItems: "center",
  margin: "0 0 7px",
  padding: "7px 8px",
  border: "1px solid rgba(245,166,35,0.25)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(245,166,35,0.055)",
  color: "var(--text-secondary)",
  fontSize: 11,
};

const vfInsightLoadingStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
  alignItems: "center",
  margin: "0 0 7px",
  padding: "7px 8px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(255,255,255,0.025)",
  color: "var(--text-mute)",
  fontSize: 11,
};

const symbolButton: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  padding: "1px 6px",
  height: 18,
  color: "var(--accent)",
};

const tinyMute: CSSProperties = {
  fontSize: 10,
  color: "var(--text-mute)",
};
