export interface ANRSummary {
  title?: string;
  asset_class?: string;
  consensus_kind?: string;
  count_label?: string;
  signal_count?: number;
  analyst_count?: number;
  consensus_score?: number | null;
  label?: string;
  positive_pct?: number;
  neutral_pct?: number;
  negative_pct?: number;
  last_updated?: string | null;
  included_count?: number;
  excluded_stale_count?: number;
  oldest_included_rating_date?: string | null;
  target_price_source?: string;
  target_price_source_mode?: string;
  not_analyst_target?: boolean;
  analyst_detail_status?: string;
  consensus_source?: string;
}

export interface AnalystRow {
  broker?: string;
  analyst?: string;
  rating?: string;
  previous_rating?: string;
  action?: string;
  target_price?: number | string | null;
  target_period?: string;
  date?: string;
  last_update?: string;
}

export interface SignalRow {
  source?: string;
  signal?: string;
  value?: string | number | null;
  score?: number;
  weight?: number;
  weighted_score?: number;
  explanation?: string;
}

export interface BucketRow {
  bucket?: string;
  count?: number;
  sentiment_score?: number;
  pct_of_consensus?: number;
}

export interface TargetRow {
  metric?: string;
  price?: number | null;
  source_mode?: string;
  not_analyst_target?: boolean;
}

export interface StaleRule {
  rule_type?: string;
  cutoff_days?: number;
  cutoff_date?: string;
  included_count?: number;
  excluded_stale_count?: number;
  oldest_included_rating_date?: string | null;
  oldest_stale_rating_date?: string | null;
  undated_provider_rows?: number;
  latest_market_data_at?: string | null;
  rule?: string;
}

export interface SourceDetail {
  name?: string;
  status?: string;
  asOf?: string | null;
  fields?: string;
}

export interface ANRData {
  status?: string;
  symbol?: string;
  summary?: ANRSummary;
  rows?: AnalystRow[];
  analyst_rows?: AnalystRow[];
  signal_rows?: SignalRow[];
  analyst_detail_status?: string;
  analyst_detail_reason?: string;
  bucket_rows?: BucketRow[];
  target_rows?: TargetRow[];
  target_price_source?: {
    mode?: string;
    label?: string;
    display_name?: string;
    not_analyst_target?: boolean;
  };
  stale_rule?: StaleRule;
  source_details?: SourceDetail[];
  spot?: number | null;
  methodology?: string;
  field_dictionary?: Record<string, string>;
  analyst_quality?: Record<string, unknown>;
  /**
   * Honest data-quality caveats emitted by the backend (anr.py). These are
   * genuine disclosures (e.g. "Derived target-price ranges are display
   * references, not analyst targets.") and are surfaced to the user.
   */
  data_notes?: string[];
}

export type AlertRule = "label_change" | "score_below" | "score_above" | "positive_pct_below";
export type ANRScreen = "overview" | "analysis";
export type VeryfinderRunState = "idle" | "loading" | "refreshing" | "ok" | "error";

export const ANR_SCREEN_OPTIONS = [
  { value: "overview", label: "Overview" },
  { value: "analysis", label: "Analysis" },
] as const;

export const VERYFINDER_LIVE_REFRESH_MS = 30_000;
export const VERYFINDER_BACKGROUND_REFRESH_MS = 60_000;

/**
 * REL-04 P8 — LRU cap on the background-refresh dedupe map.
 *
 * Without this, every distinct `symbol:sample:source` key that ever
 * scrolls through `listRecentSymbols()` accumulates forever — in a
 * long-running session with hundreds of watched symbols that's a real
 * memory leak. Cap to 256 entries and evict the oldest insertion when
 * full. 256 is comfortably above the typical recent-symbol window
 * (≤ 100) so the dedupe stays effective during normal use.
 */
export const BACKGROUND_VERYFINDER_REFRESH_CAP = 256;

class LRUTimestampMap {
  private readonly inner = new Map<string, number>();
  private readonly cap: number;

  constructor(cap: number) {
    this.cap = cap;
  }

  get size(): number {
    return this.inner.size;
  }

  get(key: string): number | undefined {
    return this.inner.get(key);
  }

  set(key: string, value: number): this {
    // Refresh insertion order so the most-recently-touched key survives
    // an eviction pass.
    if (this.inner.has(key)) {
      this.inner.delete(key);
    } else if (this.inner.size >= this.cap) {
      // Map iteration preserves insertion order — delete the oldest.
      const oldest = this.inner.keys().next().value;
      if (oldest !== undefined) {
        this.inner.delete(oldest);
      }
    }
    this.inner.set(key, value);
    return this;
  }

  delete(key: string): boolean {
    return this.inner.delete(key);
  }

  clear(): void {
    this.inner.clear();
  }

  has(key: string): boolean {
    return this.inner.has(key);
  }
}

export const BACKGROUND_VERYFINDER_REFRESHED_AT: LRUTimestampMap = new LRUTimestampMap(
  BACKGROUND_VERYFINDER_REFRESH_CAP,
);
