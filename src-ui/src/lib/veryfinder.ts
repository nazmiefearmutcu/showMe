import { sidecarFetch } from "./sidecar";

export type VeryfinderTone = "positive" | "negative" | "warn" | "muted" | "neutral";

export interface VeryfinderDistributionTop {
  label: string;
  score: number;
}

export interface VeryfinderPostLabel {
  label: string;
  score: number;
}

export interface VeryfinderPost {
  id?: string;
  text?: string;
  username?: string | null;
  author_id?: string | null;
  created_at?: string | null;
  url?: string | null;
  lang?: string | null;
  source?: string | null;
  like_count?: number;
  reply_count?: number;
  repost_count?: number;
  quote_count?: number;
  view_count?: number;
  engagement?: number;
  relevance?: number;
  sentiment?: VeryfinderPostLabel | null;
  financial_sentiment?: VeryfinderPostLabel | null;
  emotion?: VeryfinderPostLabel | null;
  action?: VeryfinderPostLabel | null;
  mood?: VeryfinderPostLabel | null;
  view?: VeryfinderPostLabel | null;
  signals?: string[];
}

export interface VeryfinderOverlay {
  ok: boolean;
  error?: string;
  query?: string;
  source?: string;
  source_requested?: string;
  source_fallback_from?: string;
  engine?: string;
  fixture_mode?: boolean;
  fallback_mode?: string;
  dominant_view?: {
    label: string;
    display: string;
    score: number;
  };
  label?: string;
  tone?: VeryfinderTone;
  social_score?: number;
  impact_score?: number;
  quality?: string;
  unique_accounts?: number;
  requested_sample?: number;
  collected_posts?: number;
  source_posts?: number;
  tweet_count_estimate?: number | null;
  evidence_window_days?: number | null;
  evidence_cutoff?: string | null;
  rolling_window_size?: number | null;
  refreshed_at?: string | null;
  view_distribution?: Record<string, number>;
  sentiment_distribution?: Record<string, number>;
  mood_distribution?: Record<string, number>;
  action_distribution?: Record<string, number>;
  top_mood?: VeryfinderDistributionTop | null;
  top_action?: VeryfinderDistributionTop | null;
  posts?: VeryfinderPost[];
  analyzed_posts?: VeryfinderPost[];
  model_notes?: string[];
  meaning?: string;
  cache?: string;
}

export interface VeryfinderBatchItem {
  key: string;
  title?: string;
  headline?: string;
  summary?: string;
  source?: string;
  url?: string;
  link?: string;
  category?: string;
  symbol?: string;
  sample?: number;
  min_tweets?: number;
}

export interface VeryfinderBatchResponse {
  ok: boolean;
  error?: string;
  count?: number;
  meaning?: string;
  items: Array<{
    key: string;
    overlay: VeryfinderOverlay;
  }>;
}

export const VERYFINDER_MIN_SAMPLE = 140;

export async function fetchVeryfinderQuery(params: {
  q?: string;
  symbol?: string;
  sample?: number;
  source?: string;
  engine?: string;
  refresh?: boolean;
}): Promise<VeryfinderOverlay> {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.symbol) search.set("symbol", params.symbol);
  search.set("sample", String(normalizeVeryfinderSample(params.sample ?? VERYFINDER_MIN_SAMPLE)));
  search.set("source", params.source ?? "auto");
  search.set("engine", params.engine ?? "rules");
  if (params.refresh) search.set("refresh", "1");
  return sidecarFetch<VeryfinderOverlay>(`/api/veryfinder/query?${search.toString()}`);
}

export async function fetchVeryfinderBatch(params: {
  items: VeryfinderBatchItem[];
  symbol?: string;
  topic?: string;
  sample?: number;
  source?: string;
  engine?: string;
  limit?: number;
}): Promise<VeryfinderBatchResponse> {
  return sidecarFetch<VeryfinderBatchResponse>("/api/veryfinder/batch", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      items: params.items,
      symbol: params.symbol,
      topic: params.topic,
      sample: normalizeVeryfinderSample(params.sample ?? VERYFINDER_MIN_SAMPLE),
      source: params.source ?? "auto",
      engine: params.engine ?? "rules",
      limit: params.limit ?? params.items.length,
    }),
  });
}

const LIQUID_SYMBOL_SAMPLES: Record<string, number> = {
  BTC: 160,
  BTCUSDT: 160,
  ETH: 140,
  ETHUSDT: 140,
  SOL: 120,
  SOLUSDT: 120,
  AAPL: 90,
  AMZN: 90,
  MSFT: 90,
  NVDA: 110,
  TSLA: 120,
  META: 90,
  GOOGL: 90,
  SPY: 80,
  QQQ: 80,
};

export function normalizeVeryfinderSample(value: string | number, fallback = 50): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return Math.max(VERYFINDER_MIN_SAMPLE, Math.round(fallback));
  return Math.max(VERYFINDER_MIN_SAMPLE, Math.round(parsed));
}

export function recommendedVeryfinderSampleForSymbol(symbol?: string): number {
  const clean = String(symbol ?? "").trim().toUpperCase().replace("/", "").replace("-", "");
  if (!clean) return VERYFINDER_MIN_SAMPLE;
  if (LIQUID_SYMBOL_SAMPLES[clean] != null) return normalizeVeryfinderSample(LIQUID_SYMBOL_SAMPLES[clean]);
  if (clean.endsWith("USDT") || clean.endsWith("USDC") || clean.endsWith("USD")) return VERYFINDER_MIN_SAMPLE;
  if (clean.endsWith("=F")) return VERYFINDER_MIN_SAMPLE;
  if (clean.endsWith("=X") || /^[A-Z]{6}$/.test(clean)) return VERYFINDER_MIN_SAMPLE;
  if (clean.startsWith("^")) return VERYFINDER_MIN_SAMPLE;
  if (clean.length <= 5) return VERYFINDER_MIN_SAMPLE;
  return VERYFINDER_MIN_SAMPLE;
}

export function recommendedVeryfinderSampleForNews(item: {
  importance_score?: number;
  relevance_score?: number;
  severity?: string;
  symbol?: string;
  symbols?: string[];
  category?: string;
}, fallbackSymbol?: string): number {
  const symbol = item.symbol ?? item.symbols?.[0] ?? fallbackSymbol;
  let base = Math.round(recommendedVeryfinderSampleForSymbol(symbol) * 0.66);
  const impact = Number(item.importance_score ?? item.relevance_score ?? 0);
  if (Number.isFinite(impact) && impact >= 85) base += 45;
  else if (Number.isFinite(impact) && impact >= 70) base += 30;
  else if (Number.isFinite(impact) && impact >= 50) base += 15;
  const severity = String(item.severity ?? "").toLowerCase();
  if (severity === "critical") base += 50;
  else if (severity === "high") base += 30;
  const category = String(item.category ?? "").toLowerCase();
  if (category.includes("earn") || category.includes("fed") || category.includes("macro")) base += 20;
  return normalizeVeryfinderSample(base, 40);
}
