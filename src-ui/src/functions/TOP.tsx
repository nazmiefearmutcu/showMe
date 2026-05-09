/**
 * TOP — Latest news feed (Bloomberg "TOP" style).
 *
 * Pulls headlines via the sidecar's `/api/fn/TOP` endpoint, refreshes
 * every 60 s. Cards link to source URLs and surface symbol/category
 * tags so the trader can pivot into DES from a headline.
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
  Skeleton,
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
const TOP_AGE_OPTIONS = [
  { value: 7, label: "7D" },
  { value: 30, label: "30D" },
  { value: 45, label: "45D" },
  { value: 90, label: "90D" },
] as const;
type TopAgeDays = (typeof TOP_AGE_OPTIONS)[number]["value"];

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

  return (
    <div style={{ padding: 18, height: "100%" }}>
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
        <section style={queryBar}>
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
        </section>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <div style={{ display: "grid", gap: 8 }}>
              <Skeleton height={56} />
              <Skeleton height={56} />
              <Skeleton height={56} />
            </div>
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : articles.length === 0 ? (
            <Empty title="No headlines" body="TOP returned an empty feed." />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {articles.map((a, i) => (
                <Card key={(a.url ?? a.title ?? "") + i} density="compact">
                  <CardBody>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "baseline",
                        gap: 8,
                        flexWrap: "wrap",
                        marginBottom: 4,
                      }}
                    >
                      <strong
                        style={{
                          fontSize: 13,
                          color: "var(--text-primary)",
                          letterSpacing: "-0.01em",
                        }}
                      >
                        {a.title || a.headline || "(untitled)"}
                      </strong>
                      {a.source && (
                        <Pill tone="muted" withDot={false}>
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
                          withDot={false}
                        >
                          {a.sentiment}
                        </Pill>
                      )}
                      {a.importance_score != null && (
                        <Pill
                          tone={a.severity === "critical" || a.severity === "high" ? "negative" : "muted"}
                          withDot={false}
                        >
                          impact {Number(a.importance_score).toFixed(0)}
                        </Pill>
                      )}
                      {veryfinderMap[articleKey(a, i)] ? (
                        <VeryfinderImpactPill overlay={veryfinderMap[articleKey(a, i)]} />
                      ) : veryfinderState === "loading" && i < 5 ? (
                        <Pill tone="warn" withDot={false}>vf scanning {recommendedVeryfinderSampleForNews(a)}</Pill>
                      ) : null}
                    </div>
                    {a.summary && (
                      <p
                        style={{
                          margin: "0 0 6px",
                          fontSize: 11,
                          color: "var(--text-secondary)",
                          lineHeight: 1.45,
                        }}
                      >
                        {truncate(cleanSummary(a.summary), 240)}
                      </p>
                    )}
                    {veryfinderMap[articleKey(a, i)] ? (
                      <VeryfinderArticleInsight
                        overlay={veryfinderMap[articleKey(a, i)]}
                        target={recommendedVeryfinderSampleForNews(a)}
                      />
                    ) : veryfinderState === "loading" ? (
                      <VeryfinderArticleLoading target={recommendedVeryfinderSampleForNews(a)} />
                    ) : null}
                    <div
                      style={{
                        display: "flex",
                        gap: 6,
                        flexWrap: "wrap",
                        alignItems: "center",
                      }}
                    >
                      {(a.symbols ?? (a.symbol ? [a.symbol] : [])).slice(0, 6).map((s) => (
                        <button
                          key={s}
                          type="button"
                          className="btn btn--ghost"
                          style={{
                            fontFamily: "JetBrains Mono, monospace",
                            fontSize: 10,
                            color: "var(--accent)",
                            padding: "1px 6px",
                            height: 18,
                          }}
                          onClick={() => {
                            setFocusedTarget("DES", s);
                            navigate(`/symbol/${s}/DES`);
                          }}
                        >
                          {s}
                        </button>
                      ))}
                      {a.category && (
                        <span
                          style={{
                            fontSize: 10,
                            color: "var(--text-mute)",
                          }}
                        >
                          {a.category}
                        </span>
                      )}
                      {Array.isArray(a.importance_reasons) &&
                        a.importance_reasons.slice(0, 2).map((reason) => (
                          <span
                            key={reason}
                            style={{
                              fontSize: 10,
                              color: "var(--text-mute)",
                            }}
                          >
                            {reason}
                          </span>
                        ))}
                      <span style={{ flex: 1 }} />
                      {tsLabel(a) && (
                        <span style={{ fontSize: 10, color: "var(--text-mute)" }}>
                          {tsLabel(a)}
                        </span>
                      )}
                      {(a.url ?? a.link) && (
                        <a
                          href={a.url ?? a.link}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            fontSize: 10,
                            color: "var(--accent)",
                          }}
                        >
                          source ↗
                        </a>
                      )}
                    </div>
                  </CardBody>
                </Card>
              ))}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
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
      <Pill tone="muted" withDot={false}>
        VF no match
      </Pill>
    );
  }
  const score = Number(overlay.social_score ?? 0);
  const label = overlay.dominant_view?.display ?? overlay.label ?? "social view";
  return (
    <Pill tone={veryfinderTone(overlay.tone)} withDot={false}>
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

const queryBar = {
  padding: "0 14px 10px",
  borderBottom: "1px solid var(--border-subtle)",
};

const vfInsightStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  margin: "0 0 7px",
  padding: "6px 8px",
  border: "1px solid rgba(245, 158, 11, 0.32)",
  borderRadius: 6,
  background: "rgba(245, 158, 11, 0.06)",
  color: "var(--text-secondary)",
  fontSize: 10,
};

const vfInsightLoadingStyle: CSSProperties = {
  ...vfInsightStyle,
  border: "1px solid rgba(34, 211, 238, 0.28)",
  background: "linear-gradient(90deg, rgba(34, 211, 238, 0.08), rgba(167, 139, 250, 0.07))",
};
