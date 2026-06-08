/**
 * Sub-system H supervisor store. Reads /api/bots + /api/bots/feed,
 * computes aggregate stats client-side.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import type { BotMeta as BaseBotMeta, SignalEntry } from "./bot-store";

/**
 * Supervisor view of a bot.  Extends the base `BotMeta` with optional fields
 * Agent 2 may attach to `/api/bots` records:
 *
 *   - `signal_count`: total entries in `signal_log` (NOT capped by the feed
 *     limit; fixes H-SUP-2 where the table column summed the limited feed).
 *   - `permission_revoked`: true if the broker now rejects the credential's
 *     `trade` scope — emit a red badge so the user knows the bot is stale
 *     (UI half of H-SUP-4; backend cascade-disable still does the real fix).
 *
 * Both are optional — if the backend hasn't shipped them yet the supervisor
 * gracefully falls back to feed-derived counts and shows no badge.
 *
 * Terminal-grade supervision health (all optional for backward compat with
 * an older payload):
 *
 *   - `is_running`: whether the runner's asyncio task is alive. Cheap
 *     server-side check (no broker/network). An `enabled` bot with
 *     `is_running === false` is STUCK.
 *   - `last_event_at`: ISO timestamp of the bot's most recent signal_log
 *     entry (used for last-tick freshness). `null` when it has never ticked.
 *   - `last_action`: the `action` ("placed"/"shadow"/"skipped") of that same
 *     most-recent entry. A live/alive bot whose latest tick was "skipped" is
 *     DEGRADED.
 */
export interface SupervisedBot extends BaseBotMeta {
  signal_count?: number;
  permission_revoked?: boolean;
  is_running?: boolean;
  last_event_at?: string | null;
  last_action?: string | null;
}

export type BotMeta = SupervisedBot;

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
  bots: SupervisedBot[];
  feed: FeedSignal[];
  generatedAt: string | null;
  loading: boolean;
  error: string | null;

  loadAll: (limit?: number) => Promise<void>;
}

// H-7 — `signals_today` previously sliced the UTC ISO string, which mis-bucketed
// signals around midnight in non-UTC zones (Istanbul UTC+3 was off-by-one daily).
// Compare in local TZ instead: convert each signal's timestamp to the user's
// local calendar date via `toLocaleDateString('en-CA')` (YYYY-MM-DD).
function _localDateOf(ts: string | undefined | null): string | null {
  if (!ts) return null;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  // 'en-CA' formats as YYYY-MM-DD; toLocaleDateString uses the host's local TZ.
  return d.toLocaleDateString("en-CA");
}

function _computeStats(bots: SupervisedBot[], feed: FeedSignal[]): AggregateStats {
  const today = new Date().toLocaleDateString("en-CA");
  return {
    total: bots.length,
    enabled: bots.filter((b) => b.enabled).length,
    live: bots.filter((b) => b.enabled && b.mode === "live").length,
    signals_today: feed.filter((s) => _localDateOf(s.timestamp) === today).length,
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
        sidecarFetch<{ records: SupervisedBot[] }>("/api/bots"),
        sidecarFetch<{ generated_at: string; signals: FeedSignal[] }>(`/api/bots/feed?limit=${limit}`),
      ]);
      // H-5 — defend against null/undefined arrays in the response body.
      // Without this, `.filter` downstream throws and `loading` never clears.
      const records: SupervisedBot[] = Array.isArray(botsBody?.records) ? botsBody.records : [];
      const signals: FeedSignal[] = Array.isArray(feedBody?.signals) ? feedBody.signals : [];
      set({
        bots: records,
        feed: signals,
        generatedAt: feedBody?.generated_at ?? null,
        stats: _computeStats(records, signals),
        loading: false,
      });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },
}));
