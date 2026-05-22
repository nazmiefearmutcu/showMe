import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface PerformanceMetrics {
  total_pnl: number;
  win_rate: number;
  trade_count: number;
  avg_pnl: number;
  max_drawdown: number;
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
}

interface PerfStoreShape {
  leaderboard: LeaderboardEntry[];
  selected: BotPerformanceDetail | null;
  loading: boolean;
  error: string | null;

  loadLeaderboard: () => Promise<void>;
  loadBot: (id: string) => Promise<void>;
  clearSelected: () => void;
}

export const usePerformanceStore = create<PerfStoreShape>((set) => ({
  leaderboard: [],
  selected: null,
  loading: false,
  error: null,

  loadLeaderboard: async () => {
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<{ records: LeaderboardEntry[] }>("/api/bots/performance");
      set({ leaderboard: body.records, loading: false });
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
