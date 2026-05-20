import { sidecarFetch } from "./sidecar";
import type { InstantEvent } from "./instant";

export interface XHealth {
  ok: boolean;
  model_loaded: boolean;
  model_dir: string | null;
  load_error: string | null;
  scraper: {
    backends: {
      guest_token: boolean;
      nitter_pool_size: number;
      jina_proxy: boolean;
    };
    guest_token_present: boolean;
    nitter_mirrors_active: string[];
  };
}

export interface XScores {
  bullish_score_avg: number;
  bullish_score_engagement_weighted: number;
  confidence: number;
}

export interface XDistributions {
  sentiment_pct: Record<string, number>;
  emotion_pct: Record<string, number>;
  topic_pct: Record<string, number>;
}

export interface XDominant {
  sentiment: string;
  emotion: string;
  topic: string;
}

export interface XEngagement {
  avg_likes: number;
  avg_retweets: number;
  total_likes: number;
  total_retweets: number;
}

export interface XExample {
  user: string;
  text: string;
  likes: number;
  retweets: number;
  url: string;
  score: number;
  emotion: string;
  topic: string;
  date: string;
}

export interface XAnalysisResponse {
  query: string;
  post_count: number;
  scrape_seconds?: number;
  device?: string;
  model_dir?: string | null;
  summary_tr?: string;
  mood?: "bullish" | "bearish" | "mixed";
  scores?: XScores;
  distributions?: XDistributions;
  dominant?: XDominant;
  engagement?: XEngagement;
  examples?: Record<string, XExample[]>;
  warning?: string;
  error?: string;
  ok?: boolean;
}

export interface XSymbolChip {
  symbol: string;
  ok: boolean;
  post_count: number;
  mood?: "bullish" | "bearish" | "mixed";
  summary_tr?: string;
  bullish_score?: number;
  confidence?: number;
  dominant?: XDominant;
  distributions?: XDistributions;
  examples?: Record<string, XExample[]>;
  warning?: string;
  error?: string;
}

export interface XInstantEventsResponse {
  ok: boolean;
  events: InstantEvent[];
  transport?: string;
  warning?: string | null;
  error?: string;
}

export async function fetchXHealth(): Promise<XHealth> {
  return sidecarFetch<XHealth>("/api/x/health");
}

export async function analyzeXTopic(body: {
  query?: string;
  symbol?: string;
  limit?: number;
  since?: string;
  until?: string;
  lang?: string;
}): Promise<XAnalysisResponse> {
  return sidecarFetch<XAnalysisResponse>("/api/x/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function classifyXTexts(texts: string[]): Promise<{
  ok: boolean;
  results?: Array<{
    text: string;
    sentiment: string;
    sentiment_score: number;
    emotion: string;
    emotion_score: number;
    topic: string;
    topic_score: number;
  }>;
  labels?: Record<string, string[]>;
  error?: string;
}> {
  return sidecarFetch("/api/x/classify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts }),
  });
}

export async function fetchXSymbolChip(
  symbol: string,
  options: { limit?: number; since?: string; lang?: string } = {},
): Promise<XSymbolChip> {
  const params = new URLSearchParams({ symbol });
  if (options.limit != null) params.set("limit", String(options.limit));
  if (options.since) params.set("since", options.since);
  if (options.lang) params.set("lang", options.lang);
  return sidecarFetch<XSymbolChip>(`/api/x/symbol_chip?${params.toString()}`);
}

export async function fetchXInstantEvents(
  symbol: string | undefined,
  options: { query?: string; limit?: number; since?: string; lang?: string } = {},
): Promise<XInstantEventsResponse> {
  const params = new URLSearchParams();
  if (symbol) params.set("symbol", symbol);
  if (options.query) params.set("query", options.query);
  if (options.limit != null) params.set("limit", String(options.limit));
  if (options.since) params.set("since", options.since);
  if (options.lang) params.set("lang", options.lang);
  return sidecarFetch<XInstantEventsResponse>(`/api/x/instant_events?${params.toString()}`);
}
