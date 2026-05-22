/**
 * Sub-system H supervisor store. Reads /api/bots + /api/bots/feed,
 * computes aggregate stats client-side.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import type { BotMeta, SignalEntry } from "./bot-store";

export interface FeedSignal extends SignalEntry {
  bot_id: string;
  bot_symbol: string;
  bot_strategy_id: string;
  bot_exchange_id: string;
  bot_mode: string;
}

export interface AggregateStats {
  total: number;
  enabled: number;
  live: number;
  signals_today: number;
}

interface SupervisionStoreShape {
  stats: AggregateStats;
  bots: BotMeta[];
  feed: FeedSignal[];
  generatedAt: string | null;
  loading: boolean;
  error: string | null;

  loadAll: (limit?: number) => Promise<void>;
}

function _computeStats(bots: BotMeta[], feed: FeedSignal[]): AggregateStats {
  const today = new Date().toISOString().slice(0, 10);
  return {
    total: bots.length,
    enabled: bots.filter((b) => b.enabled).length,
    live: bots.filter((b) => b.enabled && b.mode === "live").length,
    signals_today: feed.filter((s) => (s.timestamp ?? "").slice(0, 10) === today).length,
  };
}

export const useBotsSupervisionStore = create<SupervisionStoreShape>((set) => ({
  stats: { total: 0, enabled: 0, live: 0, signals_today: 0 },
  bots: [],
  feed: [],
  generatedAt: null,
  loading: false,
  error: null,

  loadAll: async (limit = 50) => {
    set({ loading: true, error: null });
    try {
      const [botsBody, feedBody] = await Promise.all([
        sidecarFetch<{ records: BotMeta[] }>("/api/bots"),
        sidecarFetch<{ generated_at: string; signals: FeedSignal[] }>(`/api/bots/feed?limit=${limit}`),
      ]);
      set({
        bots: botsBody.records,
        feed: feedBody.signals,
        generatedAt: feedBody.generated_at,
        stats: _computeStats(botsBody.records, feedBody.signals),
        loading: false,
      });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },
}));
