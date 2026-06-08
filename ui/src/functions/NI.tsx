/**
 * NI / CN — topic-news and company-news headline drawers.
 *
 * Bloomberg-grade news intelligence: header with symbol focus + sentiment
 * score badge, two-column layout (feed left, AI synthesis right with
 * Bull / Bear / Catalysts sections), and a 24h sentiment timeline strip.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Empty,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
} from "@/design-system";
import { runFunction, FunctionCallError } from "@/lib/functions";
import { formatMissing } from "@/lib/format";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { useAppStore } from "@/lib/store";
import { isInTauri } from "@/lib/tauri";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
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
import { XSenChip } from "./XSenChip";
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
  // 2026-05-11 hotfix: in CN (company news) mode fall back to a default
  // equity symbol so palette-cold renders pull headlines immediately.
  // Topic mode (NI) keeps the existing "MACRO" default for `topicText`.
  const effectiveSymbol = topicMode
    ? symbol
    : symbol || defaultSymbolForFunction(code, ["EQUITY"]);
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
  // Bundle D / PERF-04. Manual tick (buttons) blended with the
  // visibility-aware auto-tick so background tabs no longer keep polling
  // every 90s.
  const [manualTick, setManualTick] = useState(0);
  const visTick = useVisibilityTick(REFRESH_MS);
  const tick = manualTick + visTick;
  const setTick = (next: ((prev: number) => number) | number) => {
    setManualTick((prev) => (typeof next === "function" ? next(prev) : next));
  };
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const sidecarPort = useAppStore((s) => s.sidecarPort);
  const waitingForSidecar = isInTauri() && sidecarPort == null;
  const requestLabel = topicMode ? topicText.trim() : effectiveSymbol;
  const veryfinderNotifiedBatch = useRef("");

  useEffect(() => {
    const currentTopic = topicText.trim();
    const currentLabel = topicMode ? currentTopic : effectiveSymbol;
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
        symbol: topicMode ? undefined : effectiveSymbol,
        params,
        timeoutMs: 18_000,
      }).catch(async (err) => {
        if (!topicMode && err instanceof FunctionCallError && err.status === 404) {
          return runFunction<unknown>("NI", {
            symbol: effectiveSymbol,
            params: { ...params, topic: effectiveSymbol },
          });
        }
        throw err;
      });

    requestNews(topicMode ? topicParams : liveParams)
      .then(async (res) => {
        const items = normalize(res.data);
        const hasOnlyPlaceholders =
          items.length > 0 &&
          items.every((item) => {
            const status = String((item as { status?: unknown }).status ?? "").toLowerCase();
            return status === "provider_unavailable" || status === "news_feed_empty";
          });
        const looksEmpty = items.length === 0 || hasOnlyPlaceholders;
        const sourcesUnavailable = res.sources?.some(
          (source) => String(source).toLowerCase() === "no_live_source",
        );
        if (!cancelled && looksEmpty && sourcesUnavailable) {
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
  }, [code, topicMode, effectiveSymbol, tick, waitingForSidecar, sidecarPort, topicText]);

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
      sample: recommendedVeryfinderSampleForNews(article, topicMode ? undefined : effectiveSymbol),
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
      symbol: topicMode ? undefined : effectiveSymbol,
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
  }, [articles, topicMode, topicText, effectiveSymbol, waitingForSidecar, sidecarPort]);

  // Auto-refresh interval lives in `useVisibilityTick(REFRESH_MS)` above —
  // it pauses on hidden tabs and resumes on focus. No local setInterval.

  // P1.3 honesty: Veryfinder no longer gates the headline list, so the
  // load state reflects only the real headline fetch. The social column shows
  // its own inline "scoring…" indicator while `veryfinderState === "loading"`.
  const veryfinderScoring =
    Boolean(articles?.length) && (veryfinderState === "idle" || veryfinderState === "loading");
  const effectiveState: LoadState = state;

  // Aggregate sentiment — average of veryfinder direction scores, mapped -1..+1
  const sentimentScore = useMemo(() => {
    const overlays = Object.values(veryfinderMap).filter((o) => o.ok);
    if (!overlays.length) return null;
    let sum = 0;
    let count = 0;
    for (const o of overlays) {
      const s = Number(o.social_score ?? 0);
      if (Number.isFinite(s) && Number(o.unique_accounts ?? 0) > 0) {
        // social_score is -100..+100 → /100 → -1..+1
        sum += Math.max(-1, Math.min(1, s / 100));
        count++;
      }
    }
    return count > 0 ? sum / count : null;
  }, [veryfinderMap]);

  // Impact distribution for KPI ribbon.
  //
  // UA-HIGH-07: previously each filter callback called `list.indexOf(a)` —
  // O(n) per item → O(n²) overall. On a 500-article feed that's 250k passes
  // *per render*. Single forEach pass + accumulator drops it to O(n).
  const impactStats = useMemo(() => {
    const list = articles ?? [];
    let bull = 0;
    let bear = 0;
    let high = 0;
    list.forEach((a, i) => {
      const k = articleKey(a, i);
      const o = veryfinderMap[k];
      const score = Number(o?.social_score ?? 0);
      if (o?.ok && score > 12) bull += 1;
      if (o?.ok && score < -12) bear += 1;
      if (Number(a.importance_score ?? 0) >= 70) high += 1;
    });
    return { bull, bear, high };
  }, [articles, veryfinderMap]);

  const sortedArticles = useMemo(
    () =>
      articles ? sortNewsNewestFirst(articles, articleTimestamp).slice(0, limit) : [],
    [articles, limit],
  );

  const selectedArticle = useMemo(() => {
    if (!selectedKey) return sortedArticles[0] ?? null;
    return sortedArticles.find((a, i) => articleKey(a, i) === selectedKey) ?? sortedArticles[0] ?? null;
  }, [sortedArticles, selectedKey]);

  const synthesis = useMemo(
    () => buildSynthesis(sortedArticles, veryfinderMap),
    [sortedArticles, veryfinderMap],
  );

  const timeline = useMemo(() => buildTimeline(sortedArticles, veryfinderMap), [sortedArticles, veryfinderMap]);

  // P1.1 honesty: when every row the backend returned is a
  // provider-unavailable / no-live-source placeholder, do NOT render those
  // synthetic cards as real headlines. Surface an honest status banner
  // instead. Real headlines (any non-placeholder row present) render normally.
  const providersUnavailable = isProviderUnavailableFeed(articles);

  // P1.3 honesty: headlines render as soon as they're fetched. The feed is
  // no longer gated on the Veryfinder social-signal service — that column
  // shows its own inline "scoring…" indicator instead. So the body only
  // waits on the headline fetch (`state`), not on `veryfinderIsBlocking`.
  const body = !requestLabel ? (
    <Empty
      title={topicMode ? "Enter a topic" : "Pick a symbol"}
      body={topicMode ? "NI searches recent headlines by topic." : `${code} tails recent headlines for one ticker.`}
      icon="⌖"
    />
  ) : error ? (
    <Empty title="Function error" body={error} icon="!" />
  ) : state === "loading" || articles == null ? (
    <LoadingNews label={requestLabel} />
  ) : providersUnavailable ? (
    <div role="status" aria-live="polite" style={providerDownShell}>
      <Empty
        title="News providers unavailable"
        body="No live headlines right now — every news source ShowMe tried is temporarily down or rate-limited. Try again in a moment."
        icon="⚠"
        action={
          <RefreshButton
            loading={false}
            onClick={() => setTick((t) => t + 1)}
            title="Retry headlines"
            label="Retry"
          />
        }
      />
    </div>
  ) : sortedArticles.length === 0 ? (
    <Empty title="No headlines yet" body={`No news payload for ${requestLabel} in last ${limit}.`} />
  ) : (
    <div style={twoColumnLayout}>
      <section style={feedColumn}>
        <ArticleList
          articles={sortedArticles}
          setFocusedTarget={setFocusedTarget}
          veryfinderMap={veryfinderMap}
          veryfinderState={veryfinderState}
          fallbackSymbol={topicMode ? undefined : effectiveSymbol}
          selectedKey={selectedKey ?? articleKey(sortedArticles[0]!, 0)}
          onSelect={setSelectedKey}
        />
        <SentimentTimeline buckets={timeline} />
      </section>
      <aside style={synthesisColumn}>
        <AISynthesisCard synthesis={synthesis} selectedArticle={selectedArticle} />
      </aside>
    </div>
  );

  return (
    <div className="u-pane-host--bb">
      <Pane>
        <PaneHeader
          code={code}
          title={topicMode ? `News intelligence — ${topicText.trim() || "topic"}` : `Company news — ${effectiveSymbol ?? ""}`}
          subtitle={
            effectiveState === "loading" && requestLabel
              ? `loading ${requestLabel} · fetching latest ${FETCH_NEWS_LIMIT}`
              : providersUnavailable
                ? "news providers unavailable"
                : veryfinderScoring && articles?.length
                  ? `${Math.min(articles.length, limit)}/${articles.length} shown · scoring social signals`
                  : articles
                    ? `${Math.min(articles.length, limit)}/${articles.length} shown`
                    : "polling every 90s"
          }
          trailing={
            <FunctionControlGroup>
              {requestLabel ? (
                <Pill tone="accent" variant="soft" withDot={false}>
                  {topicMode ? "topic" : "symbol"} · {requestLabel}
                </Pill>
              ) : null}
              <SentimentScoreBadge score={sentimentScore} />
              {!topicMode ? <XSenChip symbol={effectiveSymbol} compact /> : null}
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
        {/* KPI ribbon — hidden when only provider-unavailable placeholders
            were returned, so synthetic rows never inflate the headline count. */}
        {articles && articles.length > 0 && !providersUnavailable ? (
          <section style={kpiRibbon}>
            <StatCard
              label="Headlines"
              value={String(articles.length)}
              caption={`shown ${Math.min(articles.length, limit)}`}
              tone="neutral"
            />
            <StatCard
              label="Sentiment"
              value={sentimentScore == null ? "—" : `${sentimentScore >= 0 ? "+" : ""}${sentimentScore.toFixed(2)}`}
              caption={sentimentScore == null ? "no signal" : sentimentScore > 0.18 ? "bullish bias" : sentimentScore < -0.18 ? "bearish bias" : "neutral"}
              tone={sentimentScore == null ? "neutral" : sentimentScore > 0.18 ? "positive" : sentimentScore < -0.18 ? "negative" : "neutral"}
            />
            <StatCard
              label="Bull / Bear"
              value={`${impactStats.bull} / ${impactStats.bear}`}
              caption="vf signal split"
              tone={impactStats.bull > impactStats.bear ? "positive" : impactStats.bear > impactStats.bull ? "negative" : "neutral"}
            />
            <StatCard
              label="High impact"
              value={String(impactStats.high)}
              caption="score ≥ 70"
              tone={impactStats.high > 0 ? "negative" : "neutral"}
            />
          </section>
        ) : null}
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
          <SymbolBar code={code} symbol={effectiveSymbol} />
        )}
        <PaneBody className="ni-pane-body">
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

function SentimentScoreBadge({ score }: { score: number | null }) {
  if (score == null) {
    return (
      <Pill tone="muted" variant="soft" withDot={false}>
        sentiment · —
      </Pill>
    );
  }
  const clamped = Math.max(-1, Math.min(1, score));
  const tone = clamped > 0.18 ? "positive" : clamped < -0.18 ? "negative" : "warn";
  const sign = clamped >= 0 ? "+" : "";
  // Inline mini-bar
  return (
    <span
      title={`Aggregate sentiment ${clamped.toFixed(2)} (-1..+1)`}
      className={`ni-sent-badge ni-sent-badge--${tone}`}
    >
      <span className="ni-sent-badge__label">sentiment</span>
      <span className="ni-sent-badge__track">
        <span
          className="ni-sent-badge__fill"
          style={{
            ["--u-left" as string]: clamped >= 0 ? "50%" : `${50 + clamped * 50}%`,
            ["--u-width" as string]: `${Math.abs(clamped) * 50}%`,
          }}
        />
        <span className="ni-sent-badge__mid" />
      </span>
      <strong>
        {sign}
        {clamped.toFixed(2)}
      </strong>
    </span>
  );
}

interface SynthesisData {
  bull: Array<{ text: string; cite: number }>;
  bear: Array<{ text: string; cite: number }>;
  catalysts: Array<{ text: string; cite: number }>;
}

function buildSynthesis(
  articles: NIArticle[],
  veryfinderMap: Record<string, VeryfinderOverlay>,
): SynthesisData {
  const bull: Array<{ text: string; cite: number }> = [];
  const bear: Array<{ text: string; cite: number }> = [];
  const catalysts: Array<{ text: string; cite: number }> = [];
  articles.forEach((a, i) => {
    const cite = i + 1;
    const overlay = veryfinderMap[articleKey(a, i)];
    const score = overlay?.ok ? Number(overlay.social_score ?? 0) : null;
    const headline = a.title ?? a.headline ?? "(untitled)";
    const importance = Number(a.importance_score ?? 0);
    if (score != null && score > 18) {
      bull.push({ text: truncate(cleanSummary(headline), 120), cite });
    } else if (score != null && score < -18) {
      bear.push({ text: truncate(cleanSummary(headline), 120), cite });
    }
    if (importance >= 70 || a.severity === "high" || a.severity === "critical") {
      catalysts.push({ text: truncate(cleanSummary(headline), 120), cite });
    }
  });
  return {
    bull: bull.slice(0, 5),
    bear: bear.slice(0, 5),
    catalysts: catalysts.slice(0, 5),
  };
}

function AISynthesisCard({
  synthesis,
  selectedArticle,
}: {
  synthesis: SynthesisData;
  selectedArticle: NIArticle | null;
}) {
  return (
    <Card variant="elev-2">
      <CardHeader trailing={<Pill tone="accent" variant="soft" withDot={false}>AI</Pill>}>
        Synthesis
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-12">
          {selectedArticle ? (
            <div style={selectedSummaryStyle}>
              <div style={selectedKickerStyle}>NOW READING</div>
              <strong style={selectedTitleStyle}>
                {selectedArticle.title ?? selectedArticle.headline ?? "(untitled)"}
              </strong>
              {selectedArticle.summary ? (
                <p style={selectedExcerptStyle}>
                  {truncate(cleanSummary(selectedArticle.summary), 220)}
                </p>
              ) : null}
            </div>
          ) : null}
          <SynthSection
            title="Bull"
            tone="positive"
            items={synthesis.bull}
            emptyText="No bullish signal in this window."
          />
          <SynthSection
            title="Bear"
            tone="negative"
            items={synthesis.bear}
            emptyText="No bearish signal in this window."
          />
          <SynthSection
            title="Catalysts"
            tone="warn"
            items={synthesis.catalysts}
            emptyText="No high-impact catalysts."
          />
        </div>
      </CardBody>
    </Card>
  );
}

function SynthSection({
  title,
  tone,
  items,
  emptyText,
}: {
  title: string;
  tone: "positive" | "negative" | "warn";
  items: Array<{ text: string; cite: number }>;
  emptyText: string;
}) {
  return (
    <div>
      <header style={synthSectionHeader}>
        <Pill tone={tone} variant="soft" withDot={false}>
          {title}
        </Pill>
        <span className="ni-section-count">{items.length}</span>
      </header>
      {items.length === 0 ? (
        <p style={synthEmpty}>{emptyText}</p>
      ) : (
        <ul style={synthList}>
          {items.map((item, i) => (
            <li key={i} style={synthListItem}>
              <span style={citationChipStyle} title={`citation [${item.cite}]`}>
                [{item.cite}]
              </span>
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface TimelineBucket {
  hour: number; // 0..23 (relative, 23 = newest)
  count: number;
  posScore: number;
  negScore: number;
}

function buildTimeline(
  articles: NIArticle[],
  veryfinderMap: Record<string, VeryfinderOverlay>,
): TimelineBucket[] {
  const buckets: TimelineBucket[] = Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    count: 0,
    posScore: 0,
    negScore: 0,
  }));
  const now = Date.now();
  articles.forEach((a, i) => {
    const ts = articleTimestamp(a);
    const parsed = ts ? Date.parse(ts) : NaN;
    if (!Number.isFinite(parsed)) return;
    const hoursAgo = (now - parsed) / 3_600_000;
    if (hoursAgo < 0 || hoursAgo > 24) return;
    const idx = Math.max(0, Math.min(23, 23 - Math.floor(hoursAgo)));
    buckets[idx].count += 1;
    const overlay = veryfinderMap[articleKey(a, i)];
    if (overlay?.ok) {
      const s = Number(overlay.social_score ?? 0);
      if (s > 0) buckets[idx].posScore += s;
      else if (s < 0) buckets[idx].negScore += Math.abs(s);
    }
  });
  return buckets;
}

function SentimentTimeline({ buckets }: { buckets: TimelineBucket[] }) {
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));
  const totalEvents = buckets.reduce((sum, b) => sum + b.count, 0);
  return (
    <section style={timelineWrap}>
      <header style={timelineHeader}>
        <span style={timelineLabel}>24H sentiment timeline</span>
        <span className="ni-section-count">{totalEvents} events</span>
      </header>
      <div style={timelineBars}>
        {buckets.map((b, i) => {
          const height = (b.count / maxCount) * 28;
          const tone =
            b.posScore > b.negScore
              ? "var(--positive)"
              : b.negScore > b.posScore
                ? "var(--negative)"
                : "var(--text-mute)";
          return (
            <span
              key={i}
              title={`${24 - i}h ago · ${b.count} events`}
              className={`ni-timeline-bar${b.count > 0 ? "" : " ni-timeline-bar--empty"}`}
              style={{
                ["--u-height" as string]: `${Math.max(2, height)}px`,
                ["--u-bg" as string]: b.count > 0 ? tone : "var(--border-subtle)",
              }}
            />
          );
        })}
      </div>
      <footer style={timelineAxis}>
        <span>-24h</span>
        <span>-12h</span>
        <span>now</span>
      </footer>
    </section>
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function LoadingNews({ label }: { label: string }) {
  // Honest loader: a labelled spinner + skeleton rows. No fabricated
  // step-by-step "streaming" logs — only the two real phases the page runs
  // (fetch headlines, then score social signals).
  return (
    <div role="status" aria-busy="true" aria-live="polite" style={newsLoadShell}>
      <div style={newsLoadHeader}>
        <span className="ni-load-spinner" aria-hidden="true" />
        <div className="u-min-w-0">
          <strong style={newsLoadTitle}>Fetching live headlines…</strong>
          <p style={newsLoadText}>
            Pulling the latest headlines for {label}, then scoring social signals.
          </p>
        </div>
      </div>
      <div style={newsLoadSkeletonList} aria-hidden="true">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} style={newsLoadSkeletonRow}>
            <Skeleton width="78%" height={12} />
            <Skeleton width="94%" height={10} />
            <Skeleton width="40%" height={10} />
          </div>
        ))}
      </div>
    </div>
  );
}

function ArticleList({
  articles,
  setFocusedTarget,
  veryfinderMap,
  veryfinderState,
  fallbackSymbol,
  selectedKey,
  onSelect,
}: {
  articles: NIArticle[];
  setFocusedTarget: (code: string, symbol?: string) => void;
  veryfinderMap: Record<string, VeryfinderOverlay>;
  veryfinderState: LoadState;
  fallbackSymbol?: string;
  selectedKey: string;
  onSelect: (key: string) => void;
}) {
  // P1.3: the social column scores asynchronously; surface its own inline
  // status instead of blocking the whole feed.
  const scoring = veryfinderState === "idle" || veryfinderState === "loading";
  return (
    <ul
      className="ni-feed-list"
      role="list"
      aria-label="Headlines"
      aria-live="polite"
      aria-busy={scoring}
    >
      {scoring ? (
        <li className="ni-feed-scoring">
          <span className="ni-load-spinner ni-load-spinner--sm" aria-hidden="true" />
          Scoring social signals…
        </li>
      ) : null}
      {articles.map((a, i) => {
        const key = articleKey(a, i);
        const veryfinder = veryfinderMap[key];
        const tweetTarget = recommendedVeryfinderSampleForNews(a, fallbackSymbol);
        const isSelected = key === selectedKey;
        const fullTitle = a.title ?? a.headline ?? "(untitled)";
        const fullSummary = a.summary ? cleanSummary(a.summary) : "";
        const sourceLabel = a.source ?? "source";
        return (
          <li
            key={key}
            role="button"
            tabIndex={0}
            data-selected={isSelected}
            aria-label={fullTitle}
            onClick={() => onSelect(key)}
            onKeyDown={(ev) => {
              if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                onSelect(key);
              }
            }}
            className="ni-feed-row"
            style={feedRowStyle(isSelected)}
          >
            <div style={feedRowDot}>
              <SentimentDot overlay={veryfinder} />
              <span style={feedRowIndex}>{i + 1}</span>
            </div>
            <div className="u-min-w-0">
              <div style={articleHead}>
                <strong className="ni-feed-title" title={fullTitle}>
                  {fullTitle}
                </strong>
              </div>
              {fullSummary ? (
                <p className="ni-feed-summary" style={summaryStyle} title={fullSummary}>
                  {fullSummary}
                </p>
              ) : null}
              <div style={articleMeta}>
                {a.source ? (
                  <Pill tone="muted" variant="soft" withDot={false}>
                    {a.source}
                  </Pill>
                ) : null}
                {a.category ? <span style={tinyMute}>{a.category}</span> : null}
                {a.importance_score != null ? (
                  <Pill
                    tone={a.severity === "critical" || a.severity === "high" ? "negative" : "muted"}
                    variant="soft"
                    withDot={false}
                  >
                    impact {Number(a.importance_score).toFixed(0)}
                  </Pill>
                ) : null}
                {veryfinder ? <VeryfinderImpactPill overlay={veryfinder} /> : null}
                {!veryfinder && veryfinderState === "loading" && i < 3 ? (
                  <Pill tone="muted" variant="soft" withDot={false}>
                    vf scanning {tweetTarget}
                  </Pill>
                ) : null}
                {(a.symbols ?? (a.symbol ? [a.symbol] : [])).slice(0, 3).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="btn btn--ghost"
                    aria-label={`Navigate to ${s}`}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      setFocusedTarget("DES", s);
                      navigate(`/symbol/${s}/DES`);
                    }}
                    style={symbolButton}
                  >
                    {s}
                  </button>
                ))}
                <span className="u-flex-1" />
                <span style={tinyMute}>{tsLabel(a) ?? formatMissing}</span>
                {(a.url ?? a.link) ? (
                  <a
                    href={a.url ?? a.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open article at ${sourceLabel} (opens in new tab)`}
                    onClick={(ev) => ev.stopPropagation()}
                    className="ni-feed-source"
                  >
                    source ↗
                  </a>
                ) : null}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function SentimentDot({ overlay }: { overlay?: VeryfinderOverlay }) {
  if (!overlay?.ok) {
    return <span className="ni-feed-dot ni-feed-dot--empty" />;
  }
  const s = Number(overlay.social_score ?? 0);
  const color =
    s > 12 ? "var(--positive)" : s < -12 ? "var(--negative)" : "var(--warn)";
  return (
    <span
      className="ni-feed-dot"
      style={{ ["--u-color" as string]: color }}
    />
  );
}

function VeryfinderImpactPill({ overlay }: { overlay: VeryfinderOverlay }) {
  if (!overlay.ok) {
    return (
      <Pill tone="warn" variant="soft" withDot={false}>
        vf error
      </Pill>
    );
  }
  if ((overlay.dominant_view?.label ?? "") === "no_data" || Number(overlay.unique_accounts ?? 0) <= 0) {
    return (
      <Pill tone="muted" variant="soft" withDot={false}>
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
      <Pill tone={veryfinderTone(overlay.tone)} variant="soft" withDot={false}>
        vf {vfScore} {view} {confidence}%
      </Pill>
    </span>
  );
}

function veryfinderSourceLabel(overlay: VeryfinderOverlay): string {
  if (overlay.fallback_mode === "article_context" || overlay.source === "news_proxy") {
    const from = overlay.source_fallback_from ? ` after ${overlay.source_fallback_from}` : "";
    return `news context proxy${from}`;
  }
  return overlay.fixture_mode ? "fixture source" : overlay.source ?? "source —";
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

/**
 * True when the backend returned only synthetic provider-unavailable
 * placeholders (status `provider_unavailable`, severity `unavailable`, or a
 * `no_live_source` source marker) — i.e. there are no real headlines to show.
 * Returns false the moment a single genuine headline is present, so partial
 * live feeds still render normally.
 */
function isProviderUnavailableFeed(articles: NIArticle[] | null): boolean {
  if (!articles || articles.length === 0) return false;
  return articles.every((a) => {
    const status = String((a as { status?: unknown }).status ?? "").toLowerCase();
    const severity = String(a.severity ?? "").toLowerCase();
    const source = String(a.source ?? "").toLowerCase();
    return (
      status === "provider_unavailable" ||
      severity === "unavailable" ||
      source === "no_live_source"
    );
  });
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

// ─── styles ────────────────────────────────────────────────────────────

const kpiRibbon: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 8,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "color-mix(in srgb, var(--surface) 80%, transparent)",
};

const topicBar: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(220px, 1fr) auto",
  gap: 8,
  alignItems: "end",
  padding: "0 14px 10px",
  borderBottom: "1px solid var(--border-subtle)",
};

const twoColumnLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 6fr) minmax(0, 4fr)",
  gap: 0,
  height: "100%",
  minHeight: 0,
};

const feedColumn: CSSProperties = {
  minWidth: 0,
  minHeight: 0,
  overflow: "auto",
  padding: "10px 12px",
  borderRight: "1px solid var(--border-subtle)",
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const synthesisColumn: CSSProperties = {
  minWidth: 0,
  minHeight: 0,
  overflow: "auto",
  padding: "10px 12px",
  background: "color-mix(in srgb, var(--bg) 70%, transparent)",
};

const feedRowStyle = (selected: boolean): CSSProperties => ({
  display: "grid",
  gridTemplateColumns: "32px minmax(0, 1fr)",
  gap: 8,
  padding: "10px 10px 10px 8px",
  background: selected ? "var(--surface-2)" : "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderLeft: selected ? "2px solid var(--accent)" : "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  cursor: "pointer",
  transition: "background var(--motion-fast), border-color var(--motion-fast)",
});

const feedRowDot: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 6,
  paddingTop: 4,
};

const feedRowIndex: CSSProperties = {
  fontSize: 9,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.04em",
};

const articleHead: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 6,
  flexWrap: "wrap",
  marginBottom: 4,
};

const articleMeta: CSSProperties = {
  display: "flex",
  gap: 6,
  alignItems: "center",
  flexWrap: "wrap",
  marginTop: 4,
};

const summaryStyle: CSSProperties = {
  margin: "0 0 4px",
  fontSize: 11,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
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

const selectedSummaryStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "10px 12px",
  background: "var(--accent-soft)",
  border: "1px solid color-mix(in srgb, var(--accent) 38%, transparent)",
  borderRadius: "var(--radius-md)",
};

const selectedKickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--accent)",
};

const selectedTitleStyle: CSSProperties = {
  fontSize: 13,
  color: "var(--text-primary)",
  lineHeight: 1.4,
};

const selectedExcerptStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  lineHeight: 1.5,
  color: "var(--text-secondary)",
};

const synthSectionHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 6,
  marginBottom: 6,
};

const synthEmpty: CSSProperties = {
  margin: 0,
  fontSize: 11,
  color: "var(--text-mute)",
  fontStyle: "italic",
};

const synthList: CSSProperties = {
  margin: 0,
  padding: 0,
  display: "flex",
  flexDirection: "column",
  gap: 6,
  listStyle: "none",
};

const synthListItem: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  gap: 6,
  alignItems: "start",
  fontSize: 11,
  color: "var(--text-primary)",
  lineHeight: 1.5,
};

const citationChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 22,
  height: 16,
  padding: "0 4px",
  borderRadius: 3,
  background: "var(--accent-soft)",
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  fontWeight: 600,
};

const timelineWrap: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "10px 12px",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
};

const timelineHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};

const timelineLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const timelineBars: CSSProperties = {
  display: "flex",
  alignItems: "flex-end",
  gap: 4,
  height: 32,
};

const timelineAxis: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontSize: 9,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.04em",
};

const providerDownShell: CSSProperties = {
  display: "grid",
  placeItems: "center",
  height: "100%",
  minHeight: 0,
  padding: 14,
};

const newsLoadShell: CSSProperties = {
  display: "grid",
  gap: 14,
  padding: 14,
  margin: 14,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  background: "linear-gradient(180deg, var(--scrim-low), transparent)",
};

const newsLoadHeader: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "20px minmax(0, 1fr)",
  gap: 12,
  alignItems: "center",
};

const newsLoadTitle: CSSProperties = {
  display: "block",
  color: "var(--text-primary)",
  fontSize: 15,
  letterSpacing: 0,
};

const newsLoadText: CSSProperties = {
  margin: "4px 0 0",
  color: "var(--text-secondary)",
  fontSize: 12,
  lineHeight: 1.5,
};

const newsLoadSkeletonList: CSSProperties = {
  display: "grid",
  gap: 10,
};

const newsLoadSkeletonRow: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "10px 11px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-1)",
};
