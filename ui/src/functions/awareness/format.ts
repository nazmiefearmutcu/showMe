/** Shared formatting helpers for Awareness news surfaces. Pure functions only. */

const MINUS = "\u2212";

export function hhmmUtc(iso: string | null | undefined): string {
  if (!iso) return "--:--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** Signed sentiment-style value with a real minus sign and fixed decimals. */
export function signedValue(value: number, digits = 2): string {
  const abs = Math.abs(value).toFixed(digits);
  if (value > 0) return `+${abs}`;
  if (value < 0) return `${MINUS}${abs}`;
  return abs;
}

export const TIER_TITLES: Record<number, string> = {
  1: "Tier 1: wire or official source",
  2: "Tier 2: established outlet",
  3: "Tier 3: specialist or trade press",
  4: "Tier 4: aggregator or blog",
  5: "Tier 5: community or social",
};

/**
 * Human labels for `quality_reasons` tokens (`name:+pts` / `name:-pts`, or a bare cap/reject
 * name). Keys are the live tokens from awareness `markets/news/quality.py`. Unknown names
 * fall back to the raw name.
 */
export const QUALITY_REASON_LABELS: Record<string, string> = {
  tier1: "Tier 1 publisher",
  tier2: "Tier 2 publisher",
  tier3: "Tier 3 publisher",
  tier4: "Tier 4 publisher",
  tier5: "Tier 5 publisher",
  relevance: "Finance relevance",
  depth_body300: "Depth: 300+ word body",
  depth_body120: "Depth: 120+ word body",
  depth_summary140: "Depth: summary 140+ chars",
  depth_summary60: "Depth: summary 60+ chars",
  author: "Author named",
  time_precise: "Precise publish time",
  entity_high_conf: "High-confidence entity",
  topic: "Topic identified",
  corroboration: "Corroboration",
  clickbait: "Clickbait pattern",
  all_caps_title: "All-caps headline",
  opinion: "Opinion",
  press_release: "Press release",
  paywalled_no_summary: "Paywalled, no summary",
  question_no_entity: "Question headline, no entity",
  boilerplate_summary: "Boilerplate summary",
  premium_cap: "Capped below premium",
  low_relevance_cap: "Capped: low finance relevance",
  tier4_cap: "Capped: tier 4 publisher",
  tier4_release_cap: "Capped: tier 4 press release",
  tier5_cap: "Capped: tier 5 publisher",
  official_floor: "Official source floor",
  unknown_publisher: "Unknown publisher",
  missing_url: "Missing article URL",
  missing_title: "Missing headline",
  missing_timestamp: "Missing timestamp",
  stale: "Too old to count",
  future_timestamp: "Timestamp in the future",
  title_too_short: "Headline too short",
  non_finance: "Not finance news",
  community_low_signal: "Community post, low signal",
};

export interface ParsedReason {
  raw: string;
  name: string;
  points: number | null;
  label: string;
}

export function parseQualityReason(raw: string): ParsedReason {
  const idx = raw.lastIndexOf(":");
  let name = raw;
  let points: number | null = null;
  if (idx > 0) {
    const n = Number(raw.slice(idx + 1));
    if (!Number.isNaN(n) && /^[+-]?\d+(\.\d+)?$/.test(raw.slice(idx + 1))) {
      name = raw.slice(0, idx);
      points = n;
    }
  }
  return { raw, name, points, label: QUALITY_REASON_LABELS[name] ?? name };
}

/** Topic / asset-class tokens use underscores; show them as words. */
export function prettyToken(token: string): string {
  return token.replace(/_/g, " ");
}

export function uniqueCount<T>(values: T[]): number {
  return new Set(values).size;
}

/** Window label: 24 -> "24h", 72 -> "3d". */
export function hourLabel(hours: number): string {
  return hours <= 24 ? `${hours}h` : `${Math.round(hours / 24)}d`;
}

const FLOOR_NAMES: Record<string, string> = {
  premium: "Premium",
  standard: "Standard+",
  low: "Include low",
};

/** Quality-floor segment option with a display label. */
export function floorOption(floor: string): { value: string; label: string } {
  return { value: floor, label: FLOOR_NAMES[floor] ?? floor };
}

export function hourOption(hours: number): { value: number; label: string } {
  return { value: hours, label: hourLabel(hours) };
}
