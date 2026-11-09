/**
 * Market-mood store for the Welcome dashboard gauge.
 *
 * Reads the CNN Fear & Greed reading through `GET /api/sentiment/market-gauge`
 * (backend route proxying awareness-markets). The store never fabricates a
 * value:
 *  - `ok: true` with a finite score in [0, 100] sets `gauge`;
 *  - `ok: false` (or a malformed body) clears `gauge` and keeps the backend
 *    `reason` in `unavailableReason`, so the gauge shows no number;
 *  - a transport failure keeps the last good `gauge` and sets `error`.
 *
 * Concurrency rule: a fresh `refresh` cancels any in-flight one; the last
 * caller wins.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export const MARKET_GAUGE_PATH = "/api/sentiment/market-gauge";

/** A reading older than this is still shown, but flagged as stale. */
export const MARKET_GAUGE_STALE_MS = 36 * 60 * 60 * 1000;

/** Provider health behind a CNN reading Awareness reports down or degraded (M-6). */
export interface MarketGaugeProviderStatus {
  provider: string | null;
  status: string | null;
  last_error: string | null;
}

export interface MarketGauge {
  score: number;
  rating: string | null;
  as_of: string;
  previous_close: number | null;
  source: string | null;
  /** True when the CNN provider is degraded or down: the value may not be current. */
  stale: boolean;
  providerStatus: MarketGaugeProviderStatus | null;
  /** Crypto Fear & Greed for the footnote; null when Awareness has none. */
  cryptoScore: number | null;
  cryptoRating: string | null;
}

/** Wire shape of `/api/sentiment/market-gauge` (see showme-payload-contract). */
export interface MarketGaugeResponse {
  ok?: boolean;
  score?: number | null;
  rating?: string | null;
  as_of?: string | null;
  previous_close?: number | null;
  source?: string | null;
  reason?: string | null;
  stale?: boolean | null;
  provider_status?: {
    provider?: string | null;
    status?: string | null;
    last_error?: string | null;
  } | null;
  crypto_score?: number | null;
  crypto_rating?: string | null;
}

interface SentimentStoreShape {
  /** Last accepted reading. `null` until one arrives or after `ok: false`. */
  gauge: MarketGauge | null;
  /** Backend reason for the current `ok: false` answer (verbatim). */
  unavailableReason: string | null;
  loading: boolean;
  /** Transport-level failure text; cleared by the next answered request. */
  error: string | null;
  /** When the last accepted reading arrived on this client. */
  lastUpdated: Date | null;
  /** in-flight controller so a new refresh aborts the previous one */
  _inflight: AbortController | null;

  refresh: () => Promise<void>;
}

/** Validates a route answer. Pure, exported for tests. */
export function parseMarketGauge(
  raw: MarketGaugeResponse | null | undefined,
): { gauge: MarketGauge } | { reason: string } {
  if (!raw || typeof raw !== "object") {
    return { reason: "Market gauge unavailable" };
  }
  if (raw.ok !== true) {
    const reason = typeof raw.reason === "string" && raw.reason.trim() ? raw.reason : null;
    return { reason: reason ?? "Market gauge unavailable" };
  }
  const score = raw.score;
  const asOf = raw.as_of;
  if (typeof score !== "number" || !Number.isFinite(score) || score < 0 || score > 100) {
    return { reason: "Market gauge payload had no valid score" };
  }
  if (typeof asOf !== "string" || Number.isNaN(Date.parse(asOf))) {
    return { reason: "Market gauge payload had no valid timestamp" };
  }
  const prev = raw.previous_close;
  const ps = raw.provider_status;
  const cryptoScore = raw.crypto_score;
  return {
    gauge: {
      score,
      rating: typeof raw.rating === "string" && raw.rating ? raw.rating : null,
      as_of: asOf,
      previous_close: typeof prev === "number" && Number.isFinite(prev) ? prev : null,
      source: typeof raw.source === "string" && raw.source ? raw.source : null,
      stale: raw.stale === true,
      providerStatus:
        ps && typeof ps === "object"
          ? {
              provider: typeof ps.provider === "string" ? ps.provider : null,
              status: typeof ps.status === "string" ? ps.status : null,
              last_error: typeof ps.last_error === "string" ? ps.last_error : null,
            }
          : null,
      cryptoScore:
        typeof cryptoScore === "number" && Number.isFinite(cryptoScore)
          ? cryptoScore
          : null,
      cryptoRating:
        typeof raw.crypto_rating === "string" && raw.crypto_rating
          ? raw.crypto_rating
          : null,
    },
  };
}

/** True when the reading is older than {@link MARKET_GAUGE_STALE_MS}. */
export function isGaugeStale(asOf: string, nowMs: number = Date.now()): boolean {
  const t = Date.parse(asOf);
  if (Number.isNaN(t)) return true;
  return nowMs - t > MARKET_GAUGE_STALE_MS;
}

export const useSentimentStore = create<SentimentStoreShape>((set, get) => ({
  gauge: null,
  unavailableReason: null,
  loading: false,
  error: null,
  lastUpdated: null,
  _inflight: null,

  refresh: async () => {
    const prev = get()._inflight;
    if (prev) prev.abort();
    const controller = new AbortController();
    set({ loading: true, _inflight: controller });

    try {
      const raw = await sidecarFetch<MarketGaugeResponse>(MARKET_GAUGE_PATH, {
        signal: controller.signal,
      });
      // A newer refresh started while we waited: drop this answer.
      if (controller.signal.aborted) return;

      const parsed = parseMarketGauge(raw);
      if ("gauge" in parsed) {
        set({
          gauge: parsed.gauge,
          unavailableReason: null,
          error: null,
          loading: false,
          lastUpdated: new Date(),
          _inflight: null,
        });
      } else {
        set({
          gauge: null,
          unavailableReason: parsed.reason,
          error: null,
          loading: false,
          _inflight: null,
        });
      }
    } catch (e) {
      // AbortError = a newer refresh raced us; not a user-visible error.
      if (controller.signal.aborted || (e as Error)?.name === "AbortError") {
        if (get()._inflight === controller) set({ _inflight: null });
        return;
      }
      set({
        loading: false,
        error: e instanceof Error ? e.message : String(e),
        _inflight: null,
      });
    }
  },
}));
