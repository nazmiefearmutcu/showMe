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
import { useVisibilityTick } from "@/lib/useVisibilityTick";
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

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function TOPPane({ code }: FunctionPaneProps) {
  // Bundle D / PERF-04. Tick nonce blends a manual counter (Refresh/Run
  // buttons + filter changes) with `useVisibilityTick`'s background-paused
  // auto-tick. `setTick(t => t + 1)` continues to work because we expose the
  // manual setter; both inputs feed the composed `tick` used by useFunction.
  const [manualTick, setManualTick] = useState(0);
  const visTick = useVisibilityTick(REFRESH_MS);
  const tick = manualTick + visTick;
  const setTick = (next: ((prev: number) => number) | number) => {
    setManualTick((prev) => (typeof next === "function" ? next(prev) : next));
  };
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

  // Auto-refresh interval lives in `useVisibilityTick(REFRESH_MS)` above —
  // it pauses on hidden tabs and resumes on focus. No local setInterval.

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

  // H1 honesty: detect whether every Veryfinder overlay we received is a
  // fixture/fallback (demo) so we can label the KPI VF caption as DEMO and
  // never let a synthetic social score read as real X/Twitter data.
  const veryfinderOverlays = useMemo(() => Object.values(veryfinderMap), [veryfinderMap]);
  const allVeryfinderFixture = useMemo(
    () => veryfinderOverlays.length > 0 && veryfinderOverlays.every(isFixtureOverlay),
    [veryfinderOverlays],
  );
  const veryfinderScoredCount = useMemo(
    () => veryfinderOverlays.filter((o) => o?.ok).length,
    [veryfinderOverlays],
  );

  // A2 honesty/a11y: ONE shared live region announces the Veryfinder batch
  // state once per transition, instead of every card carrying its own
  // aria-live (which spams screen readers on each 60s poll). Gated through a
  // ref so an unchanged message is not re-announced.
  const veryfinderLastAnnounced = useRef("");
  const veryfinderLiveMessage =
    veryfinderState === "loading"
      ? "Veryfinder sosyal sinyal hesaplanıyor"
      : veryfinderState === "ok"
        ? `Veryfinder ${veryfinderScoredCount} başlık için sosyal sinyal hesaplandı${allVeryfinderFixture ? " (demo verisi)" : ""}`
        : veryfinderState === "error"
          ? "Veryfinder sosyal sinyal alınamadı"
          : "";
  const veryfinderAnnounce =
    veryfinderLiveMessage && veryfinderLiveMessage !== veryfinderLastAnnounced.current
      ? veryfinderLiveMessage
      : "";
  useEffect(() => {
    if (veryfinderAnnounce) {
      veryfinderLastAnnounced.current = veryfinderAnnounce;
    }
  }, [veryfinderAnnounce]);

  // UA-HIGH-17: previously deps were `[articles, query, state]` — every 60s
  // poll handed back a fresh `articles` array identity, so the Veryfinder
  // batch fetch restarted from scratch even when nothing changed. We hash
  // articles into a stable string key (titles + URLs) and depend on that.
  const articlesKeyForVeryfinder = useMemo(
    () => articles.map((a, i) => `${articleKey(a, i)}|${a.title ?? ""}`).join("§"),
    [articles],
  );
  useEffect(() => {
    // P2a: this effect must run only when the distinct article SET changes —
    // not on every loading→ok transition. We therefore drop `state` from the
    // deps and gate on `articlesKeyForVeryfinder` instead of reading `state`.
    // An empty key means there are no articles to score (a non-"ok" state or
    // an empty payload both yield articles=[] → empty key), so we reset and
    // bail without needing the current `state` in the closure.
    if (!articlesKeyForVeryfinder || !articles.length) {
      setVeryfinderMap({});
      setVeryfinderState("idle");
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- articlesKeyForVeryfinder is the stable trigger; `articles` is intentionally read by-value inside but its identity churns every poll, so we key off the hash instead
  }, [articlesKeyForVeryfinder, query]);

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
                Sort indicator. Honesty fix: the tape is NOT newest-first.
                The backend ranks by deterministic importance_score DESC and
                only then by published_at DESC, so the prior recency-only
                label misrepresented the order. The pill now reads
                "ÖNEM → YENİ" (importance, then newest) with a tooltip that
                spells out the composite ranking. It stays a passive label
                (no arrow, no click affordance).
              */}
              <span
                title="Sıralama: önem puanı (yüksekten düşüğe), eşitlikte yayın zamanı (yeniden eskiye). Her başlıkta önem gerekçeleri gösterilir."
                data-testid="top-sort-label"
              >
                <Pill tone="muted" variant="soft" withDot={false}>
                  ÖNEM → YENİ
                </Pill>
              </span>
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
            {/*
              A2: single shared Veryfinder live region. Replaces the
              per-card aria-live on the social-loading state (which spammed
              screen readers every poll). Announces the batch transition once;
              `veryfinderAnnounce` is gated by a ref so the same message is
              not repeated on subsequent renders.
            */}
            <div
              className="u-sr-only"
              role="status"
              aria-live="polite"
              data-testid="top-vf-live"
            >
              {veryfinderAnnounce}
            </div>
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
                    tone="neutral"
                  />
                  <StatCard
                    label="Median impact"
                    value={medianImpact != null ? medianImpact.toFixed(0) : "—"}
                    caption={`AGE ${maxAgeDays}D`}
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
                    tone={positiveCount === negativeCount ? "neutral" : positiveCount > negativeCount ? "positive" : "negative"}
                  />
                  <StatCard
                    label="Sources"
                    value={String(distinctSources)}
                    caption="DISTINCT OUTLETS"
                    tone="neutral"
                  />
                  {/*
                    P2b honesty: the Veryfinder DEMO disclosure lives on its OWN
                    StatCard so the DEMO qualifier is unambiguously about the
                    social-signal overlay, not the news sources. The caption
                    reads DEMO VERİ when every overlay is a fixture/fallback,
                    otherwise the live VF batch state.
                  */}
                  <StatCard
                    label="Veryfinder"
                    value={veryfinderState.toUpperCase()}
                    caption={`VF · ${veryfinderState.toUpperCase()}${allVeryfinderFixture ? " · DEMO" : ""}`}
                    tone={allVeryfinderFixture ? "negative" : "neutral"}
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
                    {/*
                      A1: headlines render as a semantic list with
                      keyboard-focusable rows (mirrors NI's ArticleList).
                      `aria-busy` reflects the social-scoring phase; the
                      single shared live region (above) does the SR
                      announcing, so individual rows no longer carry
                      aria-live.
                    */}
                    <ul
                      className="top-news-list"
                      role="list"
                      aria-label="Başlıklar"
                      aria-busy={veryfinderState === "loading"}
                      style={{ display: "flex", flexDirection: "column", gap: 8, margin: 0, padding: 0, listStyle: "none" }}
                    >
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
                    </ul>
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
  const fullTitle = a.title || a.headline || "(untitled)";
  const href = a.url ?? a.link;
  const sourceLabel = a.source ?? "kaynak";
  const reasonsTitle =
    Array.isArray(a.importance_reasons) && a.importance_reasons.length > 0
      ? a.importance_reasons.join(" · ")
      : undefined;
  // P1 (a11y): open the source URL when the TITLE is activated (click or
  // keyboard). The row <li> is now a PLAIN container — the title button is the
  // primary activator, and the symbol jump buttons + source link are SIBLINGS,
  // so no interactive element is nested inside another interactive element
  // (ARIA/APG forbids interactive-in-interactive). No stopPropagation needed
  // anymore because clicks no longer bubble to a row-level handler.
  const openSource = () => {
    if (href) window.open(href, "_blank", "noopener,noreferrer");
  };
  return (
    <li className="top-news-card">
      <div className="top-news-card__head">
        <button
          type="button"
          className="top-news-card__title"
          aria-label={fullTitle}
          title={fullTitle}
          onClick={openSource}
        >
          {fullTitle}
        </button>
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
            {/*
              A4: sentiment is conveyed by TEXT (POZİTİF / NEGATİF / NÖTR)
              plus the arrow glyph, never color alone. We normalize the
              backend label to a Turkish word so colorblind / SR users get
              the direction without relying on the pill tint.
            */}
            {sentimentText(a.sentiment)}
          </Pill>
        )}
        {a.importance_score != null && (
          <span title="Önem puanı: ilgililik + kritiklik + kaynak + tazelik bileşeninden hesaplanan deterministik skor. Gerekçeler aşağıda listelenir.">
            <Pill
              tone={a.severity === "critical" || a.severity === "high" ? "negative" : "muted"}
              variant="soft"
              withDot={false}
            >
              IMPACT {Number(a.importance_score).toFixed(0)}
            </Pill>
          </span>
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
        <p
          className="top-news-card__summary"
          title={cleanSummary(a.summary)}
        >
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
            aria-label={`${s} detayına git`}
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
            <span key={reason} className="top-news-card__reason" title={reasonsTitle}>{reason}</span>
          ))}
        <span className="u-flex-1" />
        {tsLabel(a) && (
          <span className="top-news-card__ts">{tsLabel(a)}</span>
        )}
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="top-news-card__source"
            aria-label={`${sourceLabel} — haberi aç (yeni sekme)`}
          >
            source ↗
          </a>
        )}
      </div>
    </li>
  );
}

/**
 * A4: maps the backend sentiment label to an explicit Turkish word so the
 * direction is carried by text, not just the pill colour. Unknown labels
 * pass through verbatim (still text, never color-only).
 */
function sentimentText(sentiment: string): string {
  const s = sentiment.toLowerCase();
  if (s.startsWith("pos")) return "POZİTİF";
  if (s.startsWith("neg")) return "NEGATİF";
  if (s.startsWith("neu") || s.startsWith("nöt") || s.startsWith("not")) return "NÖTR";
  return sentiment.toUpperCase();
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
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
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
  if ((state === "loading" || state === "refreshing") && !hasArticles) {
    return (
      <Pill tone="warn" variant="soft" withDot={false}>
        LOADING
      </Pill>
    );
  }
  if ((state === "loading" || state === "refreshing") && hasArticles) {
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
  const provenance = veryfinderProvenance(overlay);
  if ((overlay.dominant_view?.label ?? "") === "no_data" || Number(overlay.unique_accounts ?? 0) <= 0) {
    return (
      <span title={provenance?.title}>
        <Pill tone="muted" variant="soft" withDot={false}>
          VF NO MATCH{provenance ? ` ${provenance.marker}` : ""}
        </Pill>
      </span>
    );
  }
  const score = Number(overlay.social_score ?? 0);
  const label = overlay.dominant_view?.display ?? overlay.label ?? "social view";
  // H1 honesty: when the overlay is a fixture (demo) or served from a
  // fallback source, append a clear [DEMO]/[YEDEK] marker and a tooltip
  // explaining its provenance so a synthetic social score is never read as
  // real X/Twitter data. The score itself is NOT hidden.
  return (
    <span title={provenance?.title}>
      <Pill tone={provenance ? "warn" : veryfinderTone(overlay.tone)} variant="soft" withDot={false}>
        <span>
          VF {score > 0 ? "+" : ""}
          {formatInt(score)} {label.toUpperCase()} {formatPct(Number(overlay.dominant_view?.score ?? 0))}
        </span>
        {provenance && (
          <span data-testid="top-vf-fixture"> {provenance.marker}</span>
        )}
      </Pill>
    </span>
  );
}

/**
 * H1: returns a provenance marker for a Veryfinder overlay whose social
 * signal is NOT real live X/Twitter data. Reads `fixture_mode` (demo
 * fixture), then `fallback_mode` / `source_fallback_from` (served from a
 * proxy/fallback source). Returns null for genuine live overlays.
 */
function veryfinderProvenance(
  overlay: VeryfinderOverlay,
): { marker: string; title: string } | null {
  if (overlay.fixture_mode === true) {
    const reason =
      overlay.model_notes?.[0] ??
      "Demo/fixture sosyal verisi — gerçek X/Twitter verisi değildir.";
    return { marker: "[DEMO]", title: `Veryfinder demo verisi · ${reason}` };
  }
  const fallback = overlay.fallback_mode || overlay.source_fallback_from;
  if (fallback) {
    const reason =
      overlay.model_notes?.[0] ??
      (overlay.source_fallback_from
        ? `${overlay.source_fallback_from} kaynağından yedeğe düşüldü`
        : String(fallback));
    return { marker: "[YEDEK]", title: `Veryfinder yedek kaynak · ${reason}` };
  }
  return null;
}

/**
 * H1 (KPI caption): true when an overlay carries no real live social data —
 * either a fixture (demo) or any fallback mode. Used to label the KPI VF
 * caption "VF · DEMO" when EVERY overlay is non-live.
 */
function isFixtureOverlay(overlay: VeryfinderOverlay | undefined): boolean {
  if (!overlay) return false;
  return Boolean(
    overlay.fixture_mode || overlay.fallback_mode || overlay.source_fallback_from,
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
  // A2: no per-card aria-live here — the single shared `top-vf-live` region
  // (rendered once in PaneBody) announces the batch state. Marked aria-hidden
  // so the redundant per-row visual loader is not read out by screen readers.
  return (
    <div style={vfInsightLoadingStyle} aria-hidden="true">
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
