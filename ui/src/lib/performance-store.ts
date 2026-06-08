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
  loading: boolean;
  error: string | null;
  // B1 — leaderboard freshness stamp ("last updated" indicator). Null until
  // the first successful load (or when the backend omits it on an old build).
  generatedAt: string | null;

  loadLeaderboard: () => Promise<void>;
  loadBot: (id: string) => Promise<void>;
  clearSelected: () => void;
}

export const usePerformanceStore = create<PerfStoreShape>((set) => ({
  leaderboard: [],
  selected: null,
  loading: false,
  error: null,
  generatedAt: null,

  loadLeaderboard: async () => {
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<{ records: LeaderboardEntry[]; generated_at?: string }>(
        "/api/bots/performance",
      );
      // H-5 style defence — guard against a null/undefined records array so a
      // malformed body can't throw downstream and leave loading stuck.
      const records = Array.isArray(body?.records) ? body.records : [];
      set({ leaderboard: records, generatedAt: body?.generated_at ?? null, loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  loadBot: async (id) => {
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<BotPerformanceDetail>(`/api/bots/${id}/performance`);
      set({ selected: body, loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  clearSelected: () => set({ selected: null }),
}));
