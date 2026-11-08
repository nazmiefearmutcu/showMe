/**
 * WC2-G05 / UI-14 residual: BOTS feed and last-tick timestamps follow the app
 * timezone setting (24-hour), not the system zone in en-US 12-hour form.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOTSPane } from "./BOTS";
import { useBotsSupervisionStore } from "@/lib/bots-supervision-store";
import { usePerformanceStore } from "@/lib/performance-store";

const TZ_KEY = "showme.timezone.v1";

beforeEach(() => {
  useBotsSupervisionStore.setState({
    stats: { total: 1, enabled: 1, live: 0, signals_today: 1 },
    bots: [
      { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: true,
        created_at: "", updated_at: "" },
    ],
    feed: [
      { bar_index: 1, bar_time: "2026-05-22T10:00:00Z", kind: "entry", price: 100,
        action: "shadow", timestamp: "2026-05-22T10:00:00Z", bot_id: "a",
        bot_symbol: "BTC/USDT", bot_strategy_id: "s", bot_exchange_id: "binance",
        bot_mode: "shadow" },
    ],
    generatedAt: "x",
    loading: false,
    error: null,
    loadAll: vi.fn(async () => {}),
  } as never);
  usePerformanceStore.setState({
    leaderboard: [], selected: null, loading: false, error: null,
    loadLeaderboard: vi.fn(async () => {}),
  } as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  try {
    localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe("BOTS timestamps follow the app timezone (UI-14 residual)", () => {
  it("shows feed times in the manual app timezone, 24-hour", () => {
    localStorage.setItem(
      TZ_KEY,
      JSON.stringify({ mode: "manual", manualTz: "America/New_York" }),
    );
    // 10:00 UTC on 2026-05-22 is 06:00 in New York (EDT, UTC-4).
    render(<BOTSPane />);

    expect(screen.queryAllByText(/06:00:00/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/\b(AM|PM)\b/)).toBeNull();
  });
});
