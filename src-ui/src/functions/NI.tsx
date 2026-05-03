/**
 * NI — Company news (symbol-filtered headline drawer).
 *
 * Mirrors the ShowMe NI/CN function: prompts for a symbol, polls
 * `/api/fn/NI` (or `/CN` if NI doesn't exist yet) and renders the
 * headlines stream. Reuses the TOP card layout but drives it from a
 * symbol bar so the trader can pivot.
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
import { runFunction, FunctionCallError } from "@/lib/functions";
import { useAppStore } from "@/lib/store";
import { isInTauri } from "@/lib/tauri";
import { relativeTimeLabel, sortNewsNewestFirst } from "@/lib/time";
import { SymbolBar } from "@/shell/SymbolBar";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
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
}

const REFRESH_MS = 90_000;
type LoadState = "idle" | "loading" | "ok" | "error";

export function NIPane({ code, symbol }: FunctionPaneProps) {
  const [articles, setArticles] = useState<NIArticle[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [limit, setLimit] = usePersistentOption<NewsLimit>(
    "showme.cn-news-limit",
    NEWS_LIMITS,
    50,
  );
  const [tick, setTick] = useState(0);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const sidecarPort = useAppStore((s) => s.sidecarPort);
  const waitingForSidecar = isInTauri() && sidecarPort == null;

  useEffect(() => {
    if (!symbol) {
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
    setState("loading");
    const fnCode = code.toUpperCase() === "CN" ? "CN" : "NI";
    const liveParams = { limit, live: true, news_timeout: 6, timeout: 6 };
    const requestNews = (params: Record<string, unknown>) =>
      runFunction<unknown>(fnCode, { symbol, params })
      .catch(async (err) => {
        // Some ShowMe builds expose this as CN instead of NI.
        if (fnCode === "NI" && err instanceof FunctionCallError && err.status === 404) {
          return runFunction<unknown>("CN", { symbol, params });
        }
        throw err;
      });
    requestNews(fnCode === "NI" ? { ...liveParams, topic: symbol } : liveParams)
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
            fnCode === "NI" ? { ...retryParams, topic: symbol } : retryParams,
          );
        }
        return res;
      })
      .then((res) => {
        if (cancelled) return;
        setArticles(normalize(res.data));
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
  }, [code, symbol, limit, tick, waitingForSidecar, sidecarPort]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const body = !symbol ? (
    <Empty title="Pick a symbol" body={`${code} tails recent headlines for one ticker.`} icon="⌖" />
  ) : error ? (
    <Empty title="Function error" body={error} icon="!" />
  ) : state === "loading" || articles == null ? (
    <LoadingNews symbol={symbol} />
  ) : articles.length === 0 ? (
    <Empty title="No headlines yet" body={`No NI/CN payload for ${symbol} in last ${limit}.`} />
  ) : (
    <ArticleList articles={articles} setFocusedTarget={setFocusedTarget} />
  );

  return (
    <div style={{ padding: 18, height: "100%", minHeight: 0, boxSizing: "border-box" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={`Company news — ${symbol ?? ""}`}
          subtitle={
            state === "loading" && symbol
              ? `loading ${symbol} · last ${limit}`
              : articles
                ? `${articles.length}/${limit} headline(s)`
                : "polling every 90s"
          }
          trailing={
            <FunctionControlGroup>
              <NewsLimitControl value={limit} onChange={setLimit} disabled={state === "loading"} />
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={() => setTick((t) => t + 1)}
                title="Refresh headlines"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={symbol} />
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
          <span>last · {limit} news</span>
          <span>symbol · {symbol ?? "—"}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function LoadingNews({ symbol }: { symbol: string }) {
  return (
    <div
      aria-live="polite"
      style={{
        display: "grid",
        gap: 8,
      }}
    >
      <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
        Loading {symbol} headlines...
      </div>
      <Skeleton height={26} width="58%" />
      <Skeleton height={70} />
      <Skeleton height={70} />
      <Skeleton height={70} width="92%" />
    </div>
  );
}

function ArticleList({
  articles,
  setFocusedTarget,
}: {
  articles: NIArticle[];
  setFocusedTarget: (code: string, symbol?: string) => void;
}) {
  const sortedArticles = useMemo(
    () => sortNewsNewestFirst(articles, articleTimestamp),
    [articles],
  );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingBottom: 8 }}>
      {sortedArticles.map((a, i) => (
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
              <strong style={{ fontSize: 13, color: "var(--text-primary)" }}>
                {a.title ?? a.headline ?? "(untitled)"}
              </strong>
              {a.source && (
                <Pill tone="muted" withDot={false}>
                  {a.source}
                </Pill>
              )}
              {a.category && (
                <span style={{ fontSize: 10, color: "var(--text-mute)" }}>
                  {a.category}
                </span>
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
                {truncate(cleanSummary(a.summary), 220)}
              </p>
            )}
            <div
              style={{
                display: "flex",
                gap: 6,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              {(a.symbols ?? (a.symbol ? [a.symbol] : []))
                .slice(0, 5)
                .map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => {
                      setFocusedTarget("DES", s);
                      navigate(`/symbol/${s}/DES`);
                    }}
                    style={{
                      fontFamily: "JetBrains Mono, monospace",
                      fontSize: 10,
                      padding: "1px 6px",
                      height: 18,
                      color: "var(--accent)",
                    }}
                  >
                    {s}
                  </button>
                ))}
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 10, color: "var(--text-mute)" }}>
                {tsLabel(a) ?? ""}
              </span>
              {(a.url ?? a.link) && (
                <a
                  href={a.url ?? a.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ fontSize: 10, color: "var(--accent)" }}
                >
                  source ↗
                </a>
              )}
            </div>
          </CardBody>
        </Card>
      ))}
    </div>
  );
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
