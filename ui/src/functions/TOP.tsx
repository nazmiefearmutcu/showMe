/**
 * TOP — Latest news feed (Bloomberg "TOP" style).
 *
 * Bloomberg-grade redesign: query preset deck, active-filter chip rail,
 * KPI summary strip (headlines / impact median / refresh ETA / vf state),
 * dense list with semantic delta/impact pills + symbol jump-rail.
 *
 * Pulls headlines via the sidecar's `/api/fn/TOP` endpoint, refreshes
 * every 60 s. Cards link to source URLs and surface symbol/category
 * tags so the trader can pivot into DES from a headline.
 */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  Card,
  CardBody,
  CardHeader,
  CommandTile,
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
import { useFunction } from "@/lib/useFunction";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { relativeTimeLabel, sortNewsNewestFirst } from "@/lib/time";
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

interface TopArticle {
  title?: string;
  headline?: string;
  summary?: string;
  source?: string;
  url?: string;
  link?: string;
  publishedAt?: string;
  published_at?: string;
  published_on?: string;
  published?: string;
  date?: string;
  datetime?: string;
  time?: string;
  ts?: string;
  symbols?: string[];
  symbol?: string;
  category?: string;
  topic?: string;
  sentiment?: string;
  severity?: string;
  importance_score?: number;
  importance_reasons?: string[];
  matched_terms?: string[];
}

const REFRESH_MS = 60_000;
const TOP_QUERIES = ["market", "crypto", "fed", "earnings", "oil", "banks"] as const;

const PRESET_QUERIES: Array<{ code: string; description: string; query: string }> = [
  { code: "MKT", description: "Market-wide tape", query: "market" },
  { code: "CRY", description: "Crypto headlines", query: "crypto" },
  { code: "FED", description: "Fed / central banks", query: "fed" },
  { code: "EAR", description: "Earnings season", query: "earnings" },
  { code: "OIL", description: "Energy & oil", query: "oil" },
  { code: "BNK", description: "Banks & financials", query: "banks" },
];

const TOP_AGE_OPTIONS = [
  { value: 7, label: "7D" },
  { value: 30, label: "30D" },
  { value: 45, label: "45D" },
  { value: 90, label: "90D" },
] as const;
type TopAgeDays = (typeof TOP_AGE_OPTIONS)[number]["value"];

function deterministicTrend(seed: string, n = 22): number[] {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < n; i++) {
    h = (h * 1664525 + 1013904223) >>> 0;
    const x = ((h & 0xff) / 255 - 0.5) * 14;
    v = Math.max(15, Math.min(85, v + x));
    out.push(v);
  }
  return out;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function TOPPane({ code }: FunctionPaneProps) {
  const [tick, setTick] = useState(0);
  const [query, setQuery] = useState("market");
  const [veryfinderMap, setVeryfinderMap] = useState<Record<string, VeryfinderOverlay>>({});
  const [veryfinderState, setVeryfinderState] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const veryfinderNotifiedBatch = useRef("");
  const [limit, setLimit] = usePersistentOption<NewsLimit>(
    "showme.top-news-limit",
    NEWS_LIMITS,
    50,
  );
  const [maxAgeDays, setMaxAgeDays] = usePersistentOption<TopAgeDays>(
    "showme.top-news-max-age-days",
    TOP_AGE_OPTIONS.map((option) => option.value),
    45,
  );
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { tick, limit, query, max_age_days: maxAgeDays, live: true, news_timeout: 6, timeout: 6 },
  });
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const articles = useMemo(
    () => sortNewsNewestFirst(normalizeArticles(data?.data), articleTimestamp).slice(0, limit),
    [data, limit],
  );

  // KPI summaries
  const positiveCount = articles.filter((a) =>
    (a.sentiment ?? "").toLowerCase().startsWith("pos"),
  ).length;
  const negativeCount = articles.filter((a) =>
    (a.sentiment ?? "").toLowerCase().startsWith("neg"),
  ).length;
  const medianImpact = useMemo(
    () =>
      median(
        articles
          .map((a) => a.importance_score ?? null)
          .filter((v): v is number => typeof v === "number" && Number.isFinite(v)),
      ),
    [articles],
  );
  const distinctSources = useMemo(() => {
    const set = new Set<string>();
    for (const a of articles) {
      if (a.source) set.add(a.source);
    }
    return set.size;
  }, [articles]);

  useEffect(() => {
    if (state !== "ok" || !articles.length) {
      setVeryfinderMap({});
      setVeryfinderState(state === "loading" ? "loading" : "idle");
      return;
    }

    const items: VeryfinderBatchItem[] = articles.map((article, index) => ({
      key: articleKey(article, index),
      title: article.title,
      headline: article.headline,
      summary: article.summary,
      source: article.source,
      url: article.url,
      link: article.link,
      category: article.category ?? article.topic,
      symbol: article.symbol ?? article.symbols?.[0],
      sample: recommendedVeryfinderSampleForNews(article),
    }));
    const batchId = items.map((item) => `${item.key}:${item.sample}`).join("|");
    let cancelled = false;
    setVeryfinderState("loading");
    fetchVeryfinderBatch({
      items,
      topic: query,
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
        if (payload.ok && batchId && veryfinderNotifiedBatch.current !== batchId) {
          veryfinderNotifiedBatch.current = batchId;
          toast.success("Veryfinder top-news inference ready", `${payload.items?.length ?? 0} headline(s) scored with article-level tweet targets.`);
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
  }, [articles, query, state]);

  const activeFilters: Array<{ id: string; label: string; onRemove?: () => void }> = [
    { id: "q", label: `QUERY · ${query.toUpperCase()}` },
    { id: "age", label: `AGE · ${maxAgeDays}D` },
    { id: "lim", label: `LIMIT · ${limit}` },
    { id: "live", label: "LIVE · POLL 60s" },
  ];

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Top news"
          subtitle={
            state === "loading"
              ? `loading top news · last ${limit}`
              : `${articles.length}/${limit} headline(s) · refresh ${REFRESH_MS / 1000}s`
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="accent" variant="soft" withDot={false}>
                MATCHED {articles.length} / {limit}
              </Pill>
              {/*
                Header live-state pill. The previous version pinned
                "LIVE · 60s" regardless of fetch state — it stayed green
                while the feed was failing, loading on a cold pane, or
                returning an empty payload. Now the tone, dot, and label
                track `useFunction` state plus a non-empty payload check.
                Poll cadence is still surfaced because the user uses it
                to predict the next refresh.
              */}
              <FeedStatePill
                state={state}
                hasArticles={articles.length > 0}
                intervalSec={REFRESH_MS / 1000}
              />
              {/*
                Sort indicator. There is only one sort mode for the news
                tape (newest first); the prior `↓` arrow read as a
                clickable sort toggle and would mislead the user into
                tapping a static pill. Dropped the arrow and reworded
                so the pill is unambiguously a passive label.
              */}
              <Pill tone="muted" variant="soft" withDot={false}>
                RECENT FIRST
              </Pill>
              <NewsLimitControl value={limit} onChange={setLimit} disabled={state === "loading"} />
              <SegmentedControl
                label="QUERY"
                value={TOP_QUERIES.includes(query as (typeof TOP_QUERIES)[number]) ? query : ""}
                options={TOP_QUERIES}
                onChange={(next) => {
                  setQuery(String(next));
                  setTick((t) => t + 1);
                }}
                disabled={state === "loading"}
              />
              <SegmentedControl
                label="AGE"
                value={maxAgeDays}
                options={TOP_AGE_OPTIONS}
                onChange={(next) => {
                  setMaxAgeDays(next);
                  setTick((t) => t + 1);
                }}
                disabled={state === "loading"}
              />
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-flex u-flex-col u-gap-14">
            <Card variant="elev-2">
              <CardHeader
                trailing={
                  <Pill tone="muted" variant="soft" withDot={false}>
                    {PRESET_QUERIES.length} PRESETS
                  </Pill>
                }
              >
                Saved queries
              </CardHeader>
              <CardBody>
                <div style={presetGridStyle}>
                  {PRESET_QUERIES.map((p) => (
                    <CommandTile
                      key={p.code}
                      code={p.code}
                      description={p.description}
                      active={query === p.query}
                      onClick={() => {
                        setQuery(p.query);
                        setTick((t) => t + 1);
                      }}
                    />
                  ))}
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                trailing={
                  <span className="u-inline-flex u-gap-6 u-items-center">
                    <button
                      type="button"
                      className="btn btn--ghost u-btn-mini"
                      onClick={() => {
                        setQuery("market");
                        setMaxAgeDays(45);
                        setTick((t) => t + 1);
                      }}
                    >
                      Reset
                    </button>
                    <button
                      type="button"
                      className="btn btn--accent u-btn-mini"
                      onClick={() => {
                        setTick((t) => t + 1);
                        refetch();
                      }}
                    >
                      Apply
                    </button>
                  </span>
                }
              >
                Filter rail
              </CardHeader>
              <CardBody>
                <div className="u-flex u-flex-col u-gap-12">
                  <div style={filterChipRowStyle}>
                    {activeFilters.map((f) => (
                      <FilterChip key={f.id} label={f.label} onRemove={f.onRemove} />
                    ))}
                  </div>
                  <Field
                    label="Query"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="market, bitcoin, Fed, earnings..."
                    hint="Search text is sent to TOP; ranking reasons appear on each headline."
                    onKeyDown={(e) => {
                      if (e.key === "Enter") setTick((t) => t + 1);
                    }}
                  />
                </div>
              </CardBody>
            </Card>

            {state === "loading" || state === "idle" ? (
              <Card>
                <CardBody>
                  <div className="u-grid-gap-8">
                    <Skeleton height={56} />
                    <Skeleton height={56} />
                    <Skeleton height={56} />
                  </div>
                </CardBody>
              </Card>
            ) : state === "error" ? (
              <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
            ) : articles.length === 0 ? (
              <Empty
                title="No matches with current filters"
                body="TOP returned an empty feed. Try widening the AGE filter or query."
                action={
                  <button
                    type="button"
                    className="btn btn--accent"
                    onClick={() => {
                      setQuery("market");
                      setMaxAgeDays(90);
                      setTick((t) => t + 1);
                    }}
                  >
                    Reset & retry
                  </button>
                }
              />
            ) : (
              <>
                <div style={kpiStripStyle}>
                  <StatCard
                    label="Headlines"
                    value={String(articles.length)}
                    caption={`OF ${limit} REQUESTED`}
                    trend={deterministicTrend(`h-${articles.length}-${query}`)}
                    tone="neutral"
                  />
                  <StatCard
                    label="Median impact"
                    value={medianImpact != null ? medianImpact.toFixed(0) : "—"}
                    caption={`AGE ${maxAgeDays}D`}
                    trend={deterministicTrend(`i-${medianImpact ?? 0}-${maxAgeDays}`)}
                    tone="neutral"
                  />
                  <StatCard
                    label="Sentiment"
                    value={
                      <span>
                        <span className="u-text-positive">{positiveCount}</span>
                        <span className="scan-divider">·</span>
                        <span className="u-text-negative">{negativeCount}</span>
                      </span>
                    }
                    caption={`POS / NEG`}
                    trend={deterministicTrend(`s-${positiveCount}-${negativeCount}`)}
                    tone={positiveCount === negativeCount ? "neutral" : positiveCount > negativeCount ? "positive" : "negative"}
                  />
                  <StatCard
                    label="Sources"
                    value={String(distinctSources)}
                    caption={`VF · ${veryfinderState.toUpperCase()}`}
                    trend={deterministicTrend(`src-${distinctSources}-${veryfinderState}`)}
                    tone="neutral"
                  />
                </div>

                <Card>
                  <CardHeader
                    trailing={
                      <span className="u-inline-flex u-gap-6 u-flex-wrap">
                        <Pill tone="positive" variant="soft" withDot={false}>
                          {articles.length} HEADLINES
                        </Pill>
                        <Pill tone="muted" variant="soft" withDot={false}>
                          {distinctSources} SOURCE{distinctSources === 1 ? "" : "S"}
                        </Pill>
                        {medianImpact != null && (
                          <Pill tone="muted" variant="soft" withDot={false}>
                            IMPACT MED {medianImpact.toFixed(0)}
                          </Pill>
                        )}
                      </span>
                    }
                  >
                    News tape
                  </CardHeader>
                  <CardBody>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {articles.map((a, i) => (
                        <NewsRow
                          key={(a.url ?? a.title ?? "") + i}
                          article={a}
                          index={i}
                          veryfinderMap={veryfinderMap}
                          veryfinderState={veryfinderState}
                          onJumpDES={(s) => {
                            setFocusedTarget("DES", s);
                            navigate(`/symbol/${s}/DES`);
                          }}
                        />
                      ))}
                    </div>
                  </CardBody>
                </Card>
              </>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>provider · TOP</span>
          <span>poll · {REFRESH_MS / 1000}s</span>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>last · {limit} news</span>
          <span>veryfinder · {veryfinderState}</span>
          <span>age · {maxAgeDays}d</span>
          <span>query · {query}</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function NewsRow({
  article,
  index,
  veryfinderMap,
  veryfinderState,
  onJumpDES,
}: {
  article: TopArticle;
  index: number;
  veryfinderMap: Record<string, VeryfinderOverlay>;
  veryfinderState: "idle" | "loading" | "ok" | "error";
  onJumpDES: (sym: string) => void;
}) {
  const a = article;
  const key = articleKey(a, index);
  return (
    <div className="top-news-card">
      <div className="top-news-card__head">
        <strong className="top-news-card__title">
          {a.title || a.headline || "(untitled)"}
        </strong>
        {a.source && (
          <Pill tone="muted" variant="soft" withDot={false}>
            {a.source}
          </Pill>
        )}
        {a.sentiment && (
          <Pill
            tone={
              a.sentiment.toLowerCase().startsWith("pos")
                ? "positive"
                : a.sentiment.toLowerCase().startsWith("neg")
                  ? "negative"
                  : "muted"
            }
            variant="soft"
            withDot={false}
            arrow={
              a.sentiment.toLowerCase().startsWith("pos")
                ? "up"
                : a.sentiment.toLowerCase().startsWith("neg")
                  ? "down"
                  : null
            }
          >
            {a.sentiment}
          </Pill>
        )}
        {a.importance_score != null && (
          <Pill
            tone={a.severity === "critical" || a.severity === "high" ? "negative" : "muted"}
            variant="soft"
            withDot={false}
          >
            IMPACT {Number(a.importance_score).toFixed(0)}
          </Pill>
        )}
        {veryfinderMap[key] ? (
          <VeryfinderImpactPill overlay={veryfinderMap[key]} />
        ) : veryfinderState === "loading" && index < 5 ? (
          <Pill tone="warn" variant="soft" withDot={false}>
            VF SCANNING {recommendedVeryfinderSampleForNews(a)}
          </Pill>
        ) : null}
      </div>
      {a.summary && (
        <p className="top-news-card__summary">
          {truncate(cleanSummary(a.summary), 240)}
        </p>
      )}
      {veryfinderMap[key] ? (
        <VeryfinderArticleInsight
          overlay={veryfinderMap[key]}
          target={recommendedVeryfinderSampleForNews(a)}
        />
      ) : veryfinderState === "loading" ? (
        <VeryfinderArticleLoading target={recommendedVeryfinderSampleForNews(a)} />
      ) : null}
      <div className="top-news-card__tags">
        {(a.symbols ?? (a.symbol ? [a.symbol] : [])).slice(0, 6).map((s) => (
          <button
            key={s}
            type="button"
            className="btn btn--ghost top-news-card__sym"
            onClick={() => onJumpDES(s)}
          >
            {s}
          </button>
        ))}
        {a.category && (
          <span className="top-news-card__category">{a.category}</span>
        )}
        {Array.isArray(a.importance_reasons) &&
          a.importance_reasons.slice(0, 2).map((reason) => (
            <span key={reason} className="top-news-card__reason">{reason}</span>
          ))}
        <span className="u-flex-1" />
        {tsLabel(a) && (
          <span className="top-news-card__ts">{tsLabel(a)}</span>
        )}
        {(a.url ?? a.link) && (
          <a
            href={a.url ?? a.link}
            target="_blank"
            rel="noopener noreferrer"
            className="top-news-card__source"
          >
            source ↗
          </a>
        )}
      </div>
    </div>
  );
}

/**
 * Honest LIVE / SNAPSHOT / EMPTY / OFFLINE / LOADING pill for the TOP
 * header. Encodes the four observable conditions of the `/api/fn/TOP`
 * cycle so the user can't be tricked into thinking a stalled or
 * offline feed is still streaming.
 *
 *   state === "error"                     → OFFLINE   (red, no dot)
 *   state === "loading" && cold pane      → LOADING   (warn, no dot)
 *   state === "ok" && articles.length=0   → EMPTY · 60s  (warn)
 *   state === "loading" && have articles  → SNAPSHOT · refreshing
 *                                                       (warn, dot)
 *   state === "ok" && articles.length>0   → LIVE · 60s   (green, dot)
 */
function FeedStatePill({
  state,
  hasArticles,
  intervalSec,
}: {
  state: "idle" | "loading" | "ok" | "error";
  hasArticles: boolean;
  intervalSec: number;
}) {
  if (state === "error") {
    return (
      <Pill tone="negative" variant="soft" withDot={false}>
        OFFLINE
      </Pill>
    );
  }
  if (state === "loading" && !hasArticles) {
    return (
      <Pill tone="warn" variant="soft" withDot={false}>
        LOADING
      </Pill>
    );
  }
  if (state === "loading" && hasArticles) {
    return (
      <Pill tone="warn" variant="soft" withDot>
        SNAPSHOT · refreshing
      </Pill>
    );
  }
  if (state === "ok" && !hasArticles) {
    return (
      <Pill tone="warn" variant="soft" withDot={false}>
        EMPTY · {intervalSec}s
      </Pill>
    );
  }
  if (state === "ok") {
    return (
      <Pill tone="positive" variant="soft" withDot>
        LIVE · {intervalSec}s
      </Pill>
    );
  }
  // state === "idle" cold start, before the first fetch resolves.
  return (
    <Pill tone="muted" variant="soft" withDot={false}>
      IDLE
    </Pill>
  );
}

function FilterChip({
  label,
  onRemove,
}: {
  label: string;
  onRemove?: () => void;
}) {
  return (
    <span style={filterChipStyle}>
      <span>{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          style={filterChipCloseStyle}
          title="Remove filter"
          aria-label={`Remove filter ${label}`}
        >
          ×
        </button>
      )}
    </span>
  );
}

function normalizeArticles(payload: unknown): TopArticle[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as TopArticle[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.items ?? o.articles ?? o.headlines ?? o.news ?? null;
    if (Array.isArray(items)) return items as TopArticle[];
  }
  return [];
}

function cleanSummary(value: string): string {
  try {
    const doc = new DOMParser().parseFromString(value, "text/html");
    const text = doc.body.textContent?.replace(/\s+/g, " ").trim();
    if (text) return text;
  } catch {
    // Fall through to a regex strip.
  }
  return value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

function truncate(value: string, max: number): string {
  return value.length > max ? value.slice(0, max) + "…" : value;
}

function VeryfinderImpactPill({ overlay }: { overlay: VeryfinderOverlay }) {
  if ((overlay.dominant_view?.label ?? "") === "no_data" || Number(overlay.unique_accounts ?? 0) <= 0) {
    return (
      <Pill tone="muted" variant="soft" withDot={false}>
        VF NO MATCH
      </Pill>
    );
  }
  const score = Number(overlay.social_score ?? 0);
  const label = overlay.dominant_view?.display ?? overlay.label ?? "social view";
  return (
    <Pill tone={veryfinderTone(overlay.tone)} variant="soft" withDot={false}>
      VF {score > 0 ? "+" : ""}
      {formatInt(score)} {label.toUpperCase()} {formatPct(Number(overlay.dominant_view?.score ?? 0))}
    </Pill>
  );
}

function VeryfinderArticleInsight({ overlay, target }: { overlay: VeryfinderOverlay; target: number }) {
  if ((overlay.dominant_view?.label ?? "") === "no_data" || Number(overlay.unique_accounts ?? 0) <= 0) {
    return (
      <div style={vfInsightStyle}>
        <strong>Veryfinder inference</strong>
        <span>no query-relevant tweets found</span>
        <span>target {formatInt(target)}</span>
        <span>requested {formatInt(overlay.requested_sample ?? target)}</span>
        <span>source posts {formatInt(overlay.source_posts)}</span>
        <span>{overlay.source ?? "—"} source</span>
      </div>
    );
  }
  return (
    <div style={vfInsightStyle}>
      <strong>Veryfinder inference</strong>
      <span>{overlay.dominant_view?.display ?? overlay.label ?? "—"}</span>
      <span>{formatPct(Number(overlay.dominant_view?.score ?? 0))} confidence</span>
      <span>action {overlay.top_action?.label ?? "—"}</span>
      <span>mood {overlay.top_mood?.label ?? "—"}</span>
      <span>target {formatInt(target)}</span>
      <span>requested {formatInt(overlay.requested_sample ?? target)}</span>
      <span>collected {formatInt(overlay.collected_posts)}</span>
      <span>unique {formatInt(overlay.unique_accounts)}</span>
      <span>{overlay.source ?? "—"} source</span>
    </div>
  );
}

function VeryfinderArticleLoading({ target }: { target: number }) {
  return (
    <div style={vfInsightLoadingStyle} aria-live="polite">
      <span>Veryfinder searching</span>
      <span>target {formatInt(target)} tweets</span>
      <span>dedupe + social inference</span>
    </div>
  );
}

function articleKey(a: TopArticle, index: number): string {
  return String(a.url ?? a.link ?? a.title ?? a.headline ?? index);
}

function tsLabel(a: TopArticle): string | null {
  return relativeTimeLabel(articleTimestamp(a));
}

function articleTimestamp(a: TopArticle): string | null | undefined {
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

function veryfinderTone(tone?: VeryfinderTone): "positive" | "negative" | "warn" | "muted" | "neutral" {
  if (tone === "positive" || tone === "negative" || tone === "warn" || tone === "neutral") return tone;
  return "muted";
}

function formatPct(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "0%";
  return `${Math.round(n * 100)}%`;
}

function formatInt(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "0";
  return Math.round(n).toLocaleString();
}

const presetGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
  gap: 8,
};

const filterChipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  alignItems: "center",
};

const filterChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 22,
  padding: "0 8px",
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 11,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  color: "var(--text-secondary)",
};

const filterChipCloseStyle: CSSProperties = {
  all: "unset",
  cursor: "default",
  width: 14,
  height: 14,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: "50%",
  color: "var(--text-mute)",
  fontSize: 12,
  lineHeight: 1,
};

const vfInsightStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  margin: "0 0 7px",
  padding: "6px 8px",
  border: "1px solid var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  background: "var(--warn-soft)",
  color: "var(--text-secondary)",
  fontSize: 10,
};

const vfInsightLoadingStyle: CSSProperties = {
  ...vfInsightStyle,
  border: "1px solid var(--accent-soft)",
  background: "var(--accent-soft)",
};

const kpiStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};
