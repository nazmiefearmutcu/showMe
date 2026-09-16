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
  /** Mean 24 h change of the same symbols when the tape was measurable. */
  tapePct: number | null;
  /** in-flight controller so a new refresh aborts the previous one */
  _inflight: AbortController | null;

  refresh: (symbols: string[]) => Promise<void>;
}

/**
 * Price-consistency guard (owner 2026-09-16: retail chatter must not read
 * "Cautiously Bullish" on a -6 % tape day). Retail sentiment is structurally
 * bullish-skewed; when the SAME symbols' mean 24 h change is negative the
 * aggregate is damped toward neutral (-6 % tape pulls a full -0.5). A flat or
 * rising tape leaves the reading untouched - nothing is fabricated upward.
 */
function tapePenalty(tapePct: number | null): number {
  if (tapePct == null || !Number.isFinite(tapePct) || tapePct >= 0) return 0;
  return Math.max(-0.5, tapePct / 12);
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

/**
 * One quick follow-up pass when no chip had live posts yet (chips warm in
 * the background server-side; 6 s is typically enough). Single-shot: the
 * timer is cleared by every new refresh.
 */
let sentimentRetryTimer: ReturnType<typeof setTimeout> | null = null;
let sentimentRetryAttempts = 0;

function scheduleSentimentRetry(symbols: string[]): void {
  if (sentimentRetryTimer != null) return;
  /* Chips warm serially server-side (polite throttle, ~1-2 s each); a single
     6 s retry caught only the first few. Keep re-arming (bounded) until a
     coverage-passing reading lands. */
  if (sentimentRetryAttempts >= 10) return;
  sentimentRetryAttempts += 1;
  try {
    sentimentRetryTimer = setTimeout(() => {
      sentimentRetryTimer = null;
      void useSentimentStore.getState().refresh(symbols);
    }, 6_000);
  } catch {
    sentimentRetryTimer = null;
  }
}

/** Test hook - drops a pending warming retry between cases. */
export function __clearSentimentRetryForTests(): void {
  if (sentimentRetryTimer != null) {
    clearTimeout(sentimentRetryTimer);
    sentimentRetryTimer = null;
  }
}

export const useSentimentStore = create<SentimentStoreShape>((set, get) => ({
  score: 0,
  label: "Neutral",
  mentions: 0,
  loading: false,
  error: null,
  lastUpdated: null,
  tapePct: null,
  _inflight: null,

  refresh: async (symbols: string[]) => {
    const cleanedSymbols = Array.isArray(symbols)
      ? symbols.map((sym) => sym.replace(/[^A-Za-z0-9._:=-]/g, "")).filter(Boolean)
      : [];

    // CRITICAL FIX (audit S6): when called with an empty watchlist (cold
    // boot / user cleared every pin), we used to flip loading=true → false
    // every 60s for nothing, which made the gauge skeleton blink. Bail
    // EARLY without touching `loading` so the panel stays at its current
    // visual state (neutral baseline).
    if (cleanedSymbols.length === 0) {
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
    // arbitrary order. Last caller wins. A pending warming retry is dropped
    // too - this call IS the refresh.
    if (sentimentRetryTimer != null) {
      clearTimeout(sentimentRetryTimer);
      sentimentRetryTimer = null;
    }
    const prev = get()._inflight;
    if (prev) prev.abort();
    const controller = new AbortController();
    set({ loading: true, _inflight: controller });

    try {
      // Fan out; tolerate per-symbol failures so one dead ticker doesn't kill
      // the whole aggregate.
      const results = await Promise.allSettled(
        cleanedSymbols.map((sym) =>
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
      let validSymbols = 0;
      for (const r of results) {
        if (r.status !== "fulfilled") continue;
        const chip = r.value;
        const mentions = _toNum(chip.post_count) ?? 0;
        const score = _toNum(chip.bullish_score);
        if (score == null || mentions <= 0) continue;
        weighted += score * mentions;
        totalMentions += mentions;
        validSymbols += 1;
      }

      /* Coverage floor: a reading off one stray chip is a skewed number, not
         sentiment (owner 2026-09-16: the gauge showed a wrong ~55% euphoria
         while markets were red). Require at least 3 live chips (or all of a
         shorter request) before publishing a score. */
      const minCoverage = Math.min(3, cleanedSymbols.length);

      if (totalMentions === 0 || validSymbols < minCoverage) {
        // No chip carried live labeled posts this pass (the backend serves a
        // fast "warming" placeholder while it back-fills Stocktwits, owner
        // 2026-09-16). NEVER fabricate a 0%/Neutral reading: keep the last
        // good value, surface the waiting state only when nothing was ever
        // measured, and retry quickly so the next pass catches the warmed
        // chips.
        const hadReading = get().lastUpdated != null;
        set({
          loading: false,
          error: hadReading ? null : "Waiting for live sentiment",
          _inflight: null,
        });
        scheduleSentimentRetry(cleanedSymbols);
        return;
      }

      // Aggregate score = mention-weighted average over live chips only.
      const rawScore = Math.max(-1, Math.min(1, weighted / totalMentions));
      sentimentRetryAttempts = 0;

      // Price-consistency: measure the tape for the SAME symbols (capped at
      // six quotes) and damp bullish chatter on red days.
      let tapePct: number | null = null;
      try {
        const tapeTargets = cleanedSymbols.slice(0, 6);
        const quoteResults = await Promise.allSettled(
          tapeTargets.map((sym) =>
            sidecarFetch<{ data?: { change_pct?: number | null } }>(
              `/api/quote/${encodeURIComponent(sym)}`,
              { signal: controller.signal },
            ),
          ),
        );
        if (controller.signal.aborted) return;
        const changes: number[] = [];
        for (const r of quoteResults) {
          if (r.status !== "fulfilled") continue;
          const pct = _toNum(r.value?.data?.change_pct);
          if (pct != null) changes.push(pct);
        }
        if (changes.length >= 2) {
          tapePct = changes.reduce((sum, v) => sum + v, 0) / changes.length;
        }
      } catch {
        tapePct = null;
      }

      const aggScore = Math.max(
        -1,
        Math.min(1, rawScore + tapePenalty(tapePct)),
      );

      set({
        score: aggScore,
        label: labelForScore(aggScore),
        mentions: totalMentions,
        loading: false,
        error: null,
        lastUpdated: new Date(),
        tapePct,
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
