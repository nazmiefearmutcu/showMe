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
export const BACKGROUND_VERYFINDER_REFRESHED_AT = new Map<string, number>();
