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

/** Human labels for `quality_reasons` tokens (`name:+pts` / `name:-pts`). Unknown names fall back to the raw name. */
export const QUALITY_REASON_LABELS: Record<string, string> = {
  tier2: "Tier 2 publisher",
  depth_body300: "Depth: 300+ word body",
  depth_summary: "Depth: summary 140+ chars",
  author: "Author named",
  precise_time: "Precise publish time",
  entity: "High-confidence entity",
  topic: "Topic identified",
  corroboration: "Corroboration",
  clickbait: "Clickbait pattern",
  opinion: "Opinion",
  press_release: "Press release",
  paywalled_no_summary: "Paywalled, no summary",
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
