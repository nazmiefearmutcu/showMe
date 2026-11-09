export type Scope = "countries" | "global" | "turkey" | "crypto";
export type Metric = "investment" | "deals" | "fundraising";
export type Unit = "USD" | "PERCENT_GDP" | "COUNT";
export interface Query {
  scope: Scope;
  source_ids: string[];
  geographies: string[];
  metric: Metric;
  stage: string;
  frequency: "annual" | "quarterly";
  unit: Unit;
  start_year: number;
  end_year: number;
  financing_scope: "vc" | "all_raises";
  vintage?: string | null;
}
export interface Observation {
  source_id: string;
  source_name: string;
  scope: Scope;
  geography: string;
  period: string;
  period_start?: string;
  period_end?: string;
  frequency: string;
  metric: Metric;
  stage: string;
  unit: Unit;
  value: number | null;
  status: string;
  published_at?: string | null;
  retrieved_at?: string;
  snapshot_id?: string;
  vintage?: string;
  methodology_version?: string;
  methodology?: string;
  geography_basis?: string;
  date_basis?: string;
  sector?: string;
  source_url?: string;
  coverage_note?: string | null;
  financing_scope?: string;
  is_partial?: boolean;
  coverage_cutoff?: string;
  data_mode?: string;
  underlying_access_date?: string;
  publication_id?: string;
  publication_table?: string;
  global_total_basis?: string;
}
export interface Source {
  source_id: string;
  source_name: string;
  scopes: string[];
  available_scopes?: string[];
  available_geographies?: string[];
  available_units?: string[];
  access_mode?: string;
  access_status?: string;
  status?: string;
  access_notes?: string;
  reason?: string;
  source_url?: string;
  terms_url?: string;
  references?: string[];
  lineage?: string;
  published_at?: string | null;
  retrieved_at?: string;
  validation_summary?: Record<string, number>;
  underlying_access_date?: string;
}
export interface Snapshot {
  snapshot_id: string;
  source_id: string;
  source_name: string;
  published_at: string | null;
  retrieved_at: string;
  observation_count: number;
  methodology_version?: string;
}
export interface Payload {
  status: string;
  query?: Query;
  rows: Observation[];
  sources: Source[];
  snapshots: Snapshot[];
  series?: { id: string; source_name: string; geography: string }[];
  comparison?: {
    comparable_pairs: { left: string; right: string; reason: string }[];
    blocked_pairs: { left: string; right: string; reasons: string[] }[];
  };
  methodology?: string;
  reason?: string;
  warnings?: string[];
  next_actions?: string[];
  cache_note?: string;
  snapshot_id?: string;
  imported_snapshot?: Snapshot;
  idempotent?: boolean;
  coverage?: {
    requested_start: string;
    requested_end: string;
    series: CoverageSeries[];
  };
}
export interface CoverageSeries {
  source_id: string;
  source_name: string;
  geography: string;
  first_period: string | null;
  last_period: string | null;
  periods: string[];
  snapshot_id?: string;
  published_at?: string | null;
}
export interface Dataset {
  schema_version: number;
  source_id: string;
  source_name?: string;
  source_url: string;
  published_at: string;
  methodology: string;
  methodology_version: string;
  geography_basis: string;
  date_basis: string;
  sector: string;
  observations: Record<string, unknown>[];
  financing_scope?: string;
}
export const SCOPE_LABELS: Record<Scope, string> = {
  countries: "Countries",
  global: "Global",
  turkey: "Turkey",
  crypto: "Crypto & Web3",
};
export function defaultQuery(scope: Scope = "countries"): Query {
  const sources = {
    countries: ["oecd"],
    global: ["nsf_ncses_2020", "nsf_ncses"],
    turkey: ["startups_watch"],
    crypto: ["defillama", "galaxy"],
  };
  return {
    scope,
    source_ids: sources[scope],
    geographies: [scope === "countries" ? "USA" : scope === "turkey" ? "TUR" : "WORLD"],
    metric: "investment",
    stage: "total",
    frequency: scope === "countries" || scope === "global" ? "annual" : "quarterly",
    unit: "USD",
    start_year: scope === "global" ? 1999 : 2007,
    end_year: new Date().getFullYear(),
    financing_scope: "vc",
  };
}
export function safeReference(value: unknown): string | undefined {
  if (typeof value !== "string" || [...value].some((ch) => ch.charCodeAt(0) <= 32))
    return undefined;
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.hostname === "pro-api.llama.fi"
    )
      return undefined;
    // Reference links never need credentials or provider query parameters.
    url.search = "";
    url.hash = "";
    return url.href;
  } catch {
    return undefined;
  }
}
