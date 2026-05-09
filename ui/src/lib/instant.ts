import { sidecarFetch } from "./sidecar";

export interface InstantEvent {
  id?: number;
  dedupe_key?: string;
  source_id?: string;
  source_name?: string;
  source_category?: string;
  source_region?: string;
  official_url?: string;
  title?: string;
  link?: string;
  summary?: string;
  generated_summary?: string;
  priority_score?: number;
  priority_label?: string;
  matched_keywords?: string[];
  calendar_window?: string | null;
  published_at?: string | null;
  fetched_at?: string;
  latency_seconds?: number | null;
}

export interface InstantSourceHealth {
  source_id?: string;
  source_name?: string;
  enabled?: boolean | number;
  ok?: boolean | number;
  status?: string;
  last_error?: string | null;
  last_latency_ms?: number | null;
  last_item_count?: number;
}

export interface InstantSpeedup {
  name: string;
  impact: string;
}

export interface InstantMetrics {
  total_events?: number;
  breaking_events?: number;
  avg_latency_seconds?: number | null;
  newest_fetched_at?: string | null;
}

export interface InstantStatus {
  ok: boolean;
  mode: "secondary";
  primary: false;
  transport: "http" | "sqlite-fallback" | "unavailable";
  base_url?: string;
  warning?: string | null;
  health?: {
    status?: string;
    metrics?: InstantMetrics;
    sources?: InstantSourceHealth[];
  };
  performance?: {
    metrics?: InstantMetrics;
    speedups?: InstantSpeedup[];
    http_cache?: Array<{
      source_id: string;
      etag: boolean;
      last_modified: boolean;
      last_checked_at?: string | null;
      last_status_code?: number | null;
    }>;
  };
}

export interface InstantEventsPayload {
  ok?: boolean;
  mode?: "secondary";
  transport?: string;
  warning?: string | null;
  events: InstantEvent[];
}

export interface InstantBackfillPayload {
  ok?: boolean;
  checked_sources?: number;
  items_seen?: number;
  items_inserted?: number;
  items_duplicate?: number;
  not_modified_sources?: number;
  warning?: string | null;
}

export async function fetchInstantStatus(): Promise<InstantStatus> {
  return sidecarFetch<InstantStatus>("/api/instant/status");
}

export async function fetchInstantEvents(limit = 100): Promise<InstantEventsPayload> {
  return sidecarFetch<InstantEventsPayload>(`/api/instant/events?limit=${limit}`);
}

export async function runInstantBackfill(limit = 15): Promise<InstantBackfillPayload> {
  return sidecarFetch<InstantBackfillPayload>(`/api/instant/backfill?limit=${limit}`, {
    method: "POST",
  });
}
