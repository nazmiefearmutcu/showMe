/**
 * Sentiment store for the Welcome dashboard gauge.
 *
 * Faz 5 binds the previously-hardcoded "Cautiously Bullish / +32%" panel to
 * the live XSEN backend. `refresh(symbols)` fans out
 * `GET /api/x/symbol_chip?symbol=X` for each input symbol and aggregates the
 * results into a single score in `[-1, +1]` via mention-weighted average.
 *
 * Concurrency rule: a fresh `refresh` cancels any in-flight one. On error we
 * keep the last good values and surface the message via `error`.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import type { XSymbolChip } from "./xai";

export type SentimentLabel =
  | "Strongly Bullish"
  | "Cautiously Bullish"
  | "Neutral"
  | "Cautiously Bearish"
  | "Strongly Bearish";

interface SentimentStoreShape {
  score: number;
  label: SentimentLabel;
  mentions: number;
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  /** in-flight controller so a new refresh aborts the previous one */
  _inflight: AbortController | null;

  refresh: (symbols: string[]) => Promise<void>;
}

/** Maps `[-1, +1]` to a five-tier sentiment label. */
export function labelForScore(score: number): SentimentLabel {
  if (score >= 0.66) return "Strongly Bullish";
  if (score >= 0.33) return "Cautiously Bullish";
  if (score >= -0.33) return "Neutral";
  if (score >= -0.66) return "Cautiously Bearish";
  return "Strongly Bearish";
}

/** Number guard — symbol_chip can return `null`/missing on ok=false. */
function _toNum(x: unknown): number | null {
  if (typeof x !== "number") return null;
  if (!Number.isFinite(x)) return null;
  return x;
}

export const useSentimentStore = create<SentimentStoreShape>((set, get) => ({
  score: 0,
  label: "Neutral",
  mentions: 0,
  loading: false,
  error: null,
  lastUpdated: null,
  _inflight: null,

  refresh: async (symbols: string[]) => {
    // CRITICAL FIX (audit S6): when called with an empty watchlist (cold
    // boot / user cleared every pin), we used to flip loading=true → false
    // every 60s for nothing, which made the gauge skeleton blink. Bail
    // EARLY without touching `loading` so the panel stays at its current
    // visual state (neutral baseline).
    if (!Array.isArray(symbols) || symbols.length === 0) {
      // Make sure we don't leak an in-flight controller from a previous
      // non-empty call either — abort + clear so the next refresh sees a
      // clean slate.
      const prevEmpty = get()._inflight;
      if (prevEmpty) {
        prevEmpty.abort();
        set({ _inflight: null });
      }
      return;
    }

    // Cancel any in-flight refresh so concurrent calls don't clobber state in
    // arbitrary order. Last caller wins.
    const prev = get()._inflight;
    if (prev) prev.abort();
    const controller = new AbortController();
    set({ loading: true, _inflight: controller });

    try {
      // Fan out; tolerate per-symbol failures so one dead ticker doesn't kill
      // the whole aggregate.
      const results = await Promise.allSettled(
        symbols.map((sym) =>
          sidecarFetch<XSymbolChip>(
            `/api/x/symbol_chip?symbol=${encodeURIComponent(sym)}`,
            { signal: controller.signal },
          ),
        ),
      );

      // If a newer refresh started while we were waiting, drop our result.
      if (controller.signal.aborted) return;

      let totalMentions = 0;
      let weighted = 0;
      for (const r of results) {
        if (r.status !== "fulfilled") continue;
        const chip = r.value;
        const mentions = _toNum(chip.post_count) ?? 0;
        const score = _toNum(chip.bullish_score);
        if (score == null || mentions <= 0) continue;
        weighted += score * mentions;
        totalMentions += mentions;
      }

      // Aggregate score = mention-weighted average. Fall back to 0 (Neutral)
      // when we have nothing.
      const aggScore =
        totalMentions > 0
          ? Math.max(-1, Math.min(1, weighted / totalMentions))
          : 0;

      set({
        score: aggScore,
        label: labelForScore(aggScore),
        mentions: totalMentions,
        loading: false,
        error: null,
        lastUpdated: new Date(),
        _inflight: null,
      });
    } catch (e) {
      // AbortError = a newer refresh raced us; not a user-visible error.
      // We still need to clear `_inflight` so the next refresh has a clean
      // slate (audit M-tier item: AbortError leak).
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
