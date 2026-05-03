/**
 * TOP — Latest news feed (Bloomberg "TOP" style).
 *
 * Pulls headlines via the sidecar's `/api/fn/TOP` endpoint, refreshes
 * every 60 s. Cards link to source URLs and surface symbol/category
 * tags so the trader can pivot into DES from a headline.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Card,
  CardBody,
  Empty,
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
import {
  FunctionControlGroup,
  LoadStatePill,
  NewsLimitControl,
  RefreshButton,
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
}

const REFRESH_MS = 60_000;

export function TOPPane({ code }: FunctionPaneProps) {
  const [tick, setTick] = useState(0);
  const [limit, setLimit] = usePersistentOption<NewsLimit>(
    "showme.top-news-limit",
    NEWS_LIMITS,
    50,
  );
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { tick, limit },
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
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
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
                        {a.summary.length > 240
                          ? a.summary.slice(0, 240) + "…"
                          : a.summary}
                      </p>
                    )}
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
