import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface PerformanceMetrics {
  total_pnl: number;
  win_rate: number;
  trade_count: number;
  avg_pnl: number;
  max_drawdown: number;
  // Q4-audit risk metrics the backend already computes. Optional so the
  // leaderboard (which spreads metrics flat) and older payloads stay valid.
  // `profit_factor` / `sharpe` / `sortino` can serialise as the string "inf"
  // (via the backend _safe_float guard) when there are no losses — the type
  // admits a string and the UI handles it without NaN.
  net_pnl?: number;
  sharpe?: number | string;
  sortino?: number | string;
  profit_factor?: number | string;
  expectancy?: number;
  max_consecutive_losses?: number;
}

export interface LeaderboardEntry extends PerformanceMetrics {
  bot_id: string;
  symbol: string;
  strategy_id: string;
  mode: string;
  enabled: boolean;
}

export interface TradeRow {
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl: number;
  pnl_pct: number;
}

export interface BotPerformanceDetail {
  bot_id: string;
  symbol: string;
  strategy_id: string;
  metrics: PerformanceMetrics;
  trades: TradeRow[];
  equity_curve: { t: string; equity: number }[];
  // B2 — honest equity provenance. `starting_equity` is the exact simulated
  // baseline the curve is seeded at ($10k); `equity_source` is the live-order
  // sizing source ("broker" | "fallback_10k" | null for shadow / no sizing).
  starting_equity?: number;
  equity_source?: string | null;
  // B1 — freshness stamp for the detail read.
  generated_at?: string;
}

interface PerfStoreShape {
  leaderboard: LeaderboardEntry[];
  selected: BotPerformanceDetail | null;
  /**
   * Combined spinner flag (UI-ROBUSTNESS F4 keeps it for PERF.tsx). True
   * while EITHER the leaderboard or a bot-detail load is in flight.
   */
  loading: boolean;
  /** F4 — leaderboard load in flight (independent of `loadingBot`). */
  loadingLeaderboard: boolean;
  /** F4 — bot-detail load in flight (independent of `loadingLeaderboard`). */
  loadingBot: boolean;
  error: string | null;
  // B1 — leaderboard freshness stamp ("last updated" indicator). Null until
  // the first successful load (or when the backend omits it on an old build).
  generatedAt: string | null;

  loadLeaderboard: () => Promise<void>;
  loadBot: (id: string) => Promise<void>;
  clearSelected: () => void;
}

// UI-ROBUSTNESS F4 — module-scoped abort plumbing, copied from the
// portfolio-store pattern (portfolio-store.ts `_loadCtl` / `_pendingReload`).
// Rapidly selecting bot A then bot B used to let A's slow response land after
// B's and overwrite `selected` with the wrong bot; both loads also shared a
// single `loading` flag so one spinner masked the other. Now each load owns
// an AbortController, drops its result when aborted, and queues at most one
// trailing reload per lane.
let _leaderboardCtl: AbortController | null = null;
let _leaderboardPendingReload = false;
let _botCtl: AbortController | null = null;
let _botPendingReload = false;
/** Latest bot id requested — the trailing reload must use THIS id, not the aborted call's. */
let _lastBotId: string | null = null;

export const usePerformanceStore = create<PerfStoreShape>((set, get) => ({
  leaderboard: [],
  selected: null,
  loading: false,
  loadingLeaderboard: false,
  loadingBot: false,
  error: null,
  generatedAt: null,

  loadLeaderboard: async () => {
    // Coalesce concurrent loads: abort whatever is in flight and queue a
    // single trailing reload (mirrors portfolio-store loadPortfolio).
    if (_leaderboardCtl) {
      _leaderboardCtl.abort();
      _leaderboardPendingReload = true;
    }
    const ctl = new AbortController();
    _leaderboardCtl = ctl;

    set((prev) => ({
      loading: true,
      loadingLeaderboard: true,
      error: null,
      leaderboard: prev.leaderboard,
    }));
    try {
      const body = await sidecarFetch<{ records: LeaderboardEntry[]; generated_at?: string }>(
        "/api/bots/performance",
        { signal: ctl.signal },
      );
      // If we were aborted while awaiting, do not overwrite newer state.
      if (ctl.signal.aborted) return;
      // H-5 style defence — guard against a null/undefined records array so a
      // malformed body can't throw downstream and leave loading stuck.
      const records = Array.isArray(body?.records) ? body.records : [];
      set((prev) => ({
        leaderboard: records,
        generatedAt: body?.generated_at ?? null,
        loadingLeaderboard: false,
        loading: prev.loadingBot,
      }));
    } catch (e) {
      if (ctl.signal.aborted) return; // swallow abort — newer load owns state
      const message = e instanceof Error ? e.message : String(e);
      if (e instanceof Error && (e.name === "AbortError" || /aborted/i.test(message))) {
        return;
      }
      set((prev) => ({
        loadingLeaderboard: false,
        loading: prev.loadingBot,
        error: message,
      }));
    } finally {
      if (_leaderboardCtl === ctl) _leaderboardCtl = null;
      if (_leaderboardPendingReload && _leaderboardCtl == null) {
        _leaderboardPendingReload = false;
        void get().loadLeaderboard();
      }
    }
  },

  loadBot: async (id) => {
    _lastBotId = id;
    if (_botCtl) {
      _botCtl.abort();
      _botPendingReload = true;
    }
    const ctl = new AbortController();
    _botCtl = ctl;

    set((prev) => ({
      loading: true,
      loadingBot: true,
      error: null,
      selected: prev.selected,
    }));
    try {
      const body = await sidecarFetch<BotPerformanceDetail>(
        `/api/bots/${id}/performance`,
        { signal: ctl.signal },
      );
      if (ctl.signal.aborted) return;
      set((prev) => ({
        selected: body,
        loadingBot: false,
        loading: prev.loadingLeaderboard,
      }));
    } catch (e) {
      if (ctl.signal.aborted) return; // swallow abort — newer load owns state
      const message = e instanceof Error ? e.message : String(e);
      if (e instanceof Error && (e.name === "AbortError" || /aborted/i.test(message))) {
        return;
      }
      set((prev) => ({
        loadingBot: false,
        loading: prev.loadingLeaderboard,
        error: message,
      }));
    } finally {
      if (_botCtl === ctl) _botCtl = null;
      if (_botPendingReload && _botCtl == null) {
        _botPendingReload = false;
        // Trailing reload re-runs with the LATEST requested bot id.
        if (_lastBotId != null) void get().loadBot(_lastBotId);
      }
    }
  },

  clearSelected: () => set({ selected: null }),
}));
