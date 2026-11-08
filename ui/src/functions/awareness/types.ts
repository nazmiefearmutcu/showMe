/**
 * Shapes shared by the Awareness-backed panes (news, calendars, sentiment).
 *
 * Every Awareness function returns `metadata.providers` (provider health rows from
 * the awareness-markets service) and, when the service is down,
 * `data.status === "provider_unavailable"` with a human-readable `data.reason`.
 */

export type ProviderStatus = "ok" | "degraded" | "down" | "never";

export interface AwarenessProvider {
  provider: string;
  status: ProviderStatus;
  last_ok_at?: string | null;
  last_error?: string | null;
  items_last_ok?: number;
}

export interface FeedHealth {
  ok?: number;
  degraded?: number;
  down?: number;
  never?: number;
}

export interface AwarenessMeta {
  providers?: AwarenessProvider[];
  feed_health?: FeedHealth;
  generated_at?: string | null;
  notes?: string[];
}
