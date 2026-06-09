import { toast } from "@/lib/toast";
import {
  normalizeVeryfinderSample,
  type VeryfinderOverlay,
  type VeryfinderTone,
} from "@/lib/veryfinder";
import type { ANRSummary, AlertRule } from "./_types";

export function loadAlert(key: string): {
  enabled: boolean;
  rule: AlertRule;
  threshold: string;
  savedAt?: string;
} {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return { enabled: false, rule: "label_change", threshold: "" };
    const parsed = JSON.parse(raw) as Partial<{
      enabled: boolean;
      rule: AlertRule;
      threshold: string;
      savedAt: string;
    }>;
    return {
      enabled: Boolean(parsed.enabled),
      rule: parsed.rule ?? "label_change",
      threshold: parsed.threshold ?? "",
      savedAt: parsed.savedAt,
    };
  } catch {
    return { enabled: false, rule: "label_change", threshold: "" };
  }
}

export function sourceLabel(value?: string): string {
  if (value === "live_analyst_targets") return "Live analyst targets";
  if (value === "derived_reference_range_from_spot") return "Derived from spot";
  if (value === "crypto_market_reference_band") return "Market reference band";
  if (value === "target_price_unavailable") return "Unavailable";
  return providerLabel(value);
}

export function providerLabel(value?: string): string {
  if (!value) return "—";
  const labels: Record<string, string> = {
    yfinance_recommendations: "Yahoo recs",
    yfinance_targets: "Yahoo targets",
    yfinance: "Yahoo Finance",
    live_analyst_targets: "Live analyst targets",
    aggregate_consensus_available: "Consensus available",
    broker_actions_available: "Broker actions",
    provider_not_configured: "Provider not configured",
    provider_unavailable: "Provider unavailable",
    unavailable_no_fabricated_consensus: "Unavailable",
    crypto_market_data: "Crypto market data",
    crypto_market_reference_band: "Market reference band",
    broker_level_analyst_feed: "Broker analyst feed",
    target_price: "Target price",
    binance: "Binance",
    public_search: "Public web/news/social search",
    expanded_public_search: "Expanded public search",
    search_exhausted: "Search exhausted",
    article_context: "Makale bağlamı",
    unavailable: "Kullanılamıyor",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

export function formatSources(sources?: string[]): string {
  if (!sources?.length) return "—";
  return sources.map(providerLabel).join(", ");
}

export function isCryptoSummary(summary?: ANRSummary): boolean {
  return summary?.asset_class === "CRYPTO" || summary?.consensus_kind === "crypto_market_proxy";
}

export function consensusHeaderTone(label?: string): "positive" | "negative" | "warn" | "muted" {
  if (!label) return "muted";
  const l = label.toLowerCase();
  if (l.includes("strong buy") || l.includes("buy")) return "positive";
  if (l.includes("strong sell") || l.includes("sell")) return "negative";
  if (l.includes("hold") || l.includes("neutral")) return "warn";
  return "muted";
}

export function consensusHeaderLabel(label?: string): string {
  if (!label) return "AWAITING";
  const l = label.toLowerCase();
  if (l.includes("strong buy")) return "STRONG BUY";
  if (l.includes("buy")) return "BUY-LEANING";
  if (l.includes("strong sell")) return "STRONG SELL";
  if (l.includes("sell")) return "SELL-LEANING";
  if (l.includes("hold") || l.includes("neutral")) return "HOLD";
  return label.toUpperCase();
}

export function formatHeaderTime(value: string): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value.slice(0, 16);
    return d.toISOString().slice(11, 16) + " UTC";
  } catch {
    return value.slice(0, 16);
  }
}

/**
 * Date + UTC time for a server-provided timestamp (e.g. summary.last_updated,
 * oldest_included_rating_date). Surfaces the date so a raw ISO blob never
 * reaches the UI, and keeps a UTC marker so the user knows it is the server's
 * clock. Falls back to the "—" sentinel when the field is genuinely absent —
 * never fabricates a time.
 */
export function formatConsensusDate(value?: string | null): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value.slice(0, 16);
    const iso = d.toISOString();
    return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
  } catch {
    return value.slice(0, 16);
  }
}

export function formatInt(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function clampTweetSample(value: string | number): number {
  return normalizeVeryfinderSample(value, 50);
}

export function formatScore(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(2);
}

export function formatPct(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(1)}%`;
}

export function formatMoney(value?: number | string | null): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

export function formatSignedInt(value?: number | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const n = Math.round(Number(value));
  return n > 0 ? `+${n}` : String(n);
}

export function distributionLabel(value?: { label: string; score: number } | null): string {
  if (!value) return "—";
  return `${value.label.replaceAll("_", " ")} ${formatPct(value.score * 100)}`;
}

export function veryfinderTone(tone?: VeryfinderTone): "positive" | "negative" | "warn" | "muted" | "neutral" {
  if (tone === "positive" || tone === "negative" || tone === "warn" || tone === "muted") {
    return tone;
  }
  return "neutral";
}

export function formatDateTime(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export function notifyVeryfinderComplete(symbol: string, overlay: VeryfinderOverlay): void {
  const found = Number(overlay.collected_posts ?? 0);
  const title = found > 0 ? "Veryfinder tweets found" : "Veryfinder search complete";
  const body = `${symbol} · ${formatInt(overlay.collected_posts)} collected / ${formatInt(overlay.requested_sample)} requested · ${overlay.label ?? "social view"}`;
  toast.success(title, body);
  if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted") {
    try {
      new Notification(title, { body });
    } catch {
      // In-app toast already handled the notification.
    }
  } else if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
    void Notification.requestPermission().then((permission) => {
      if (permission !== "granted") return;
      try {
        new Notification(title, { body });
      } catch {
        // In-app toast already handled the notification.
      }
    });
  }
}
