/**
 * Unified polling hook for BOTS + PERF panes.
 *
 * BUG #10 fix — BOTS used 10s polling, PERF used 15s. The asymmetry meant new
 * signals appeared in the supervisor feed before the leaderboard updated, and
 * the cumulative PnL ribbon could drift versus per-bot signal counts for up
 * to 5 seconds.  This hook drives both stores from a single interval so the
 * two panes are always frame-aligned.
 *
 * Usage:
 *   useBotEcosystemPolling();              // 10s default
 *   useBotEcosystemPolling(5_000);         // override
 *
 * Each mount installs its own interval; cleanup runs on unmount.  The hook
 * fires once immediately so panes don't have to wait for the first tick.
 */
import { useEffect } from "react";
import { useBotsSupervisionStore } from "./bots-supervision-store";
import { usePerformanceStore } from "./performance-store";

export const BOT_ECOSYSTEM_POLL_MS = 10_000;

export function useBotEcosystemPolling(intervalMs: number = BOT_ECOSYSTEM_POLL_MS): void {
  useEffect(() => {
    const tick = () => {
      void useBotsSupervisionStore.getState().loadAll();
      void usePerformanceStore.getState().loadLeaderboard();
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
