/**
 * News payload shapes for the Awareness-backed news panes (TOP, NI/CN, NSE, NALRT).
 *
 * Mirrors `showme-payload-contract.md` "News" section: rows are `mapping.news_row`
 * output, flat sentiment fields, story detail via `story_id`.
 */
import type { AwarenessMeta } from "./types";

export type NewsQuality = "premium" | "standard" | "low" | "rejected";
export type NewsContentType =
  "news" | "analysis" | "opinion" | "press_release" | "official" | "filing" | "social";
export type SentimentLabel = "positive" | "negative" | "neutral";

export interface NewsEntity {
  type: string;
  id: string;
  name?: string | null;
  confidence?: number | null;
}

export interface EntitySentiment {
  label: SentimentLabel;
  score: number;
  confidence?: number | null;
  model?: string | null;
}

export interface NewsRow {
  id: string;
  title: string;
  url?: string | null;
  link?: string | null;
  source?: string | null;
  publisher: string;
  publisher_id?: string | null;
  publisher_domain?: string | null;
  publisher_tier: number;
  author?: string | null;
  published_at: string;
  first_seen_at?: string | null;
  summary?: string | null;
  excerpt?: string | null;
  language?: string | null;
  content_type?: NewsContentType | null;
  symbols: string[];
  countries: string[];
  topics: string[];
  asset_classes: string[];
  entities: NewsEntity[];
  sentiment: SentimentLabel;
  sentiment_score: number;
  sentiment_confidence?: number | null;
  sentiment_model?: string | null;
  entity_sentiment?: Record<string, EntitySentiment>;
  importance_score?: number | null;
  importance: number;
  quality_label: NewsQuality;
  quality_score: number;
  quality_reasons: string[];
  story_id?: string | null;
  story_size: number;
  is_paywalled: boolean;
  /** NALRT only: `critical` when importance >= 85, otherwise `high`. */
  severity?: "critical" | "high";
}

export interface StoryItem {
  id: string;
  title: string;
  publisher_name: string;
  publisher_tier: number;
  url?: string | null;
  published_at: string;
  quality_label?: NewsQuality | null;
}

export interface StoryDetail {
  id: string;
  title?: string | null;
  corroboration?: number | null;
  publishers?: Array<{ id: string; name: string; tier: number }>;
  items: StoryItem[];
  first_seen_at?: string | null;
  last_updated_at?: string | null;
}

export interface NewsPayload {
  status: string;
  reason?: string;
  rows?: NewsRow[];
  count?: number;
  next_cursor?: string | null;
  filters?: Record<string, unknown>;
  hidden_note?: string | null;
  relax?: { min_quality?: string } | null;
  story?: StoryDetail | null;
  meta?: AwarenessMeta;
}

/** Narrow the untyped `data.meta` (or envelope metadata) to the awareness meta shape. */
export function newsMeta(
  payload: NewsPayload | undefined,
  metadata?: Record<string, unknown>,
): AwarenessMeta {
  const fromPayload = payload?.meta ?? {};
  const providers =
    fromPayload.providers ?? (metadata?.providers as AwarenessMeta["providers"]) ?? [];
  const feedHealth =
    fromPayload.feed_health ?? (metadata?.feed_health as AwarenessMeta["feed_health"]);
  const generatedAt =
    fromPayload.generated_at ??
    (typeof metadata?.generated_at === "string" ? metadata.generated_at : null);
  const notes = fromPayload.notes ?? (metadata?.notes as string[] | undefined) ?? [];
  return { providers, feed_health: feedHealth, generated_at: generatedAt, notes };
}
