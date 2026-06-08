/**
 * BOTS — terminal-grade upgrade tests.
 *
 * Covers the NEW supervision behaviours added in the terminal-grade pass:
 *  F1 — health-aware status Pill (OFF / STUCK / DEGRADED / LIVE / SHADOW)
 *       with an accessible name; STUCK when enabled+!is_running; DEGRADED
 *       when alive + last_action === "skipped".
 *  F2 — last-tick freshness ("Nm ago"), "—" when null. Time is frozen.
 *  F3 — feed fallback-equity badge shown ONLY when
 *       equity_source === "fallback_10k".
 *  F4 — Empty for empty bot/feed tables; Skeleton when loading + empty;
 *       error region is a polite live region (role=status) and renders even
 *       with no bots/feed.
 *  F5 — both tables have caption + scope columns + aria-label.
 *  F6 — KPI strip shows a Stuck/Degraded count reflecting a stuck bot.
 *
 * Follows the store-setState render style of BOTS.test.tsx +
 * BOT.terminal-grade.test.tsx. Existing BOTS + store + backend tests stay
 * green; the date-frozen store test is untouched.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOTSPane } from "./BOTS";
import { useBotsSupervisionStore } from "@/lib/bots-supervision-store";
import { usePerformanceStore } from "@/lib/performance-store";

// Freeze the clock so the F2 relative-age assertions are deterministic on
// any machine (relativeTickAge derives from Date.now()).
const FROZEN_NOW = new Date("2026-06-08T12:00:00Z");

type BotOverrides = Partial<{
  id: string; symbol: string; timeframe: string; mode: string;
  enabled: boolean; is_running: boolean;
  last_event_at: string | null; last_action: string | null;
  permission_revoked: boolean; signal_count: number;
}>;

function bot(o: BotOverrides = {}) {
  return {
    id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
    symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: true,
    created_at: "", updated_at: "", ...o,
  };
}

function seedBots(bots: ReturnType<typeof bot>[], feed: unknown[] = []) {
  useBotsSupervisionStore.setState({
    stats: { total: bots.length, enabled: bots.filter((b) => b.enabled).length,
             live: bots.filter((b) => b.enabled && b.mode === "live").length,
             signals_today: 0 },
    bots: bots as never, feed: feed as never, generatedAt: "x",
    loading: false, error: null,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FROZEN_NOW);
  useBotsSupervisionStore.setState({
    stats: { total: 0, enabled: 0, live: 0, signals_today: 0 },
    bots: [], feed: [], generatedAt: null, loading: false, error: null,
    loadAll: vi.fn(async () => {}),
  } as never);
  usePerformanceStore.setState({
    leaderboard: [], selected: null, loading: false, error: null,
    loadLeaderboard: vi.fn(async () => {}),
  } as never);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("BOTS F1 — health-aware status with accessible name", () => {
  // P2-A — per-row status pills are no longer role="status" live regions
  // (that re-announced all N rows on every 10s poll). They keep their
  // accessible name via aria-label, so getByLabelText still finds them.
  it("shows STUCK (negative) when enabled but is_running === false", () => {
    seedBots([bot({ enabled: true, mode: "shadow", is_running: false })]);
    render(<BOTSPane />);
    const stuck = screen.getByLabelText(/durum: stuck/i);
    expect(stuck.textContent).toMatch(/STUCK/);
    expect(stuck.querySelector(".ds-pill--tone-negative")).not.toBeNull();
  });

  it("shows DEGRADED (warn) when alive and last_action === 'skipped'", () => {
    seedBots([bot({ enabled: true, mode: "live", is_running: true, last_action: "skipped" })]);
    render(<BOTSPane />);
    const deg = screen.getByLabelText(/durum: degraded/i);
    expect(deg.textContent).toMatch(/DEGRADED/);
    expect(deg.querySelector(".ds-pill--tone-warn")).not.toBeNull();
  });

  it("shows LIVE (negative) when alive + live + last tick acted", () => {
    seedBots([bot({ enabled: true, mode: "live", is_running: true, last_action: "placed" })]);
    render(<BOTSPane />);
    const live = screen.getByLabelText(/durum: live/i);
    expect(live.querySelector(".ds-pill--tone-negative")).not.toBeNull();
  });

  it("shows SHADOW (warn) when alive + shadow", () => {
    seedBots([bot({ enabled: true, mode: "shadow", is_running: true, last_action: "shadow" })]);
    render(<BOTSPane />);
    const shadow = screen.getByLabelText(/durum: shadow/i);
    expect(shadow.querySelector(".ds-pill--tone-warn")).not.toBeNull();
  });

  it("shows OFF (muted) when disabled", () => {
    seedBots([bot({ enabled: false, mode: "live", is_running: false })]);
    render(<BOTSPane />);
    const off = screen.getByLabelText(/durum: off/i);
    expect(off.querySelector(".ds-pill--tone-muted")).not.toBeNull();
  });

  it("falls back to legacy LIVE/SHADOW when is_running is undefined", () => {
    // Older payload without is_running: must not crash and must not show STUCK.
    seedBots([bot({ enabled: true, mode: "live" /* no is_running */ })]);
    render(<BOTSPane />);
    expect(screen.getByLabelText(/durum: live/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/durum: stuck/i)).toBeNull();
  });

  it("falls back to legacy LIVE/SHADOW when is_running is null (P2-B unknown)", () => {
    // P2-B — backend reports null on a transient runner-introspection error;
    // the UI must treat null identically to undefined (NO false STUCK).
    seedBots([bot({ enabled: true, mode: "live", is_running: null as never })]);
    render(<BOTSPane />);
    expect(screen.getByLabelText(/durum: live/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/durum: stuck/i)).toBeNull();
  });
});

describe("BOTS P2-A — single summary live region (no per-row SR-spam)", () => {
  it("per-row status pills are NOT role=status but keep their aria-label", () => {
    seedBots([bot({ id: "a", enabled: true, is_running: false })]); // STUCK
    render(<BOTSPane />);
    // The accessible name is still reachable...
    expect(screen.getByLabelText(/durum: stuck/i)).toBeInTheDocument();
    // ...but no status role is attached to the per-row pill. The only
    // role="status" nodes are the single summary region (+ error when shown),
    // none of which carry a per-row "Durum:" accessible name.
    const statuses = screen.queryAllByRole("status");
    for (const node of statuses) {
      expect(node.getAttribute("aria-label") ?? "").not.toMatch(/durum:/i);
    }
  });

  it("renders exactly one summary live region reflecting the unhealthy count", () => {
    seedBots([
      bot({ id: "a", enabled: true, is_running: false }),                       // STUCK
      bot({ id: "b", enabled: true, is_running: true, last_action: "skipped" }), // DEGRADED
      bot({ id: "c", enabled: true, is_running: true, last_action: "shadow" }),  // healthy
    ]);
    render(<BOTSPane />);
    const summary = screen.getByTestId("bots-supervision-summary");
    expect(summary.getAttribute("role")).toBe("status");
    expect(summary.textContent).toBe("3 bot, 2 stuck/degraded");
    // No error region here, so the summary is the ONLY status live region.
    expect(screen.getAllByRole("status").length).toBe(1);
  });
});

describe("BOTS F2 — last-tick freshness", () => {
  it("renders a relative age for a recent tick", () => {
    // 5 minutes before frozen now.
    const ts = new Date(FROZEN_NOW.getTime() - 5 * 60 * 1000).toISOString();
    seedBots([bot({ id: "a", is_running: true, last_event_at: ts, last_action: "shadow" })]);
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-last-tick-a").textContent).toBe("5m ago");
  });

  it("renders '—' honestly when last_event_at is null", () => {
    seedBots([bot({ id: "a", is_running: true, last_event_at: null })]);
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-last-tick-a").textContent).toBe("—");
  });

  it("de-emphasises a stale tick (older than threshold)", () => {
    const ts = new Date(FROZEN_NOW.getTime() - 60 * 60 * 1000).toISOString(); // 1h ago
    seedBots([bot({ id: "a", is_running: true, last_event_at: ts })]);
    render(<BOTSPane />);
    const cell = screen.getByTestId("bots-last-tick-a");
    expect(cell.textContent).toBe("1h ago");
    expect(cell.className).toMatch(/u-text-secondary/);
  });
});

describe("BOTS F3 — feed fallback-equity honesty badge", () => {
  const feedRow = (extra: Record<string, unknown>) => ({
    bar_index: 1, bar_time: "2026-05-22T10:00:00Z", kind: "entry", price: 100,
    action: "placed", timestamp: "2026-05-22T10:00:00Z", bot_id: "a",
    bot_symbol: "BTC/USDT", bot_strategy_id: "s", bot_exchange_id: "binance",
    bot_mode: "live", ...extra,
  });

  it("shows the badge when equity_source === 'fallback_10k'", () => {
    seedBots([bot()], [feedRow({ equity_source: "fallback_10k" })]);
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-feed-fallback-equity")).toBeInTheDocument();
  });

  it("hides the badge when equity_source === 'broker'", () => {
    seedBots([bot()], [feedRow({ equity_source: "broker" })]);
    render(<BOTSPane />);
    expect(screen.queryByTestId("bots-feed-fallback-equity")).toBeNull();
  });

  it("hides the badge when equity_source is absent", () => {
    seedBots([bot()], [feedRow({})]);
    render(<BOTSPane />);
    expect(screen.queryByTestId("bots-feed-fallback-equity")).toBeNull();
  });
});

describe("BOTS F4 — states (Empty / Skeleton / error region)", () => {
  it("shows Empty for the bot table when there are no bots", () => {
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-empty")).toBeInTheDocument();
  });

  it("shows Empty for the feed when there are no signals", () => {
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-feed-empty")).toBeInTheDocument();
  });

  it("shows a Skeleton while loading + empty (no rows yet)", () => {
    useBotsSupervisionStore.setState({ loading: true, bots: [], feed: [] });
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-loading")).toBeInTheDocument();
    // Skeleton replaces the empty bot table while first-loading.
    expect(screen.queryByTestId("bots-empty")).toBeNull();
  });

  it("error region is a polite live region and renders with no bots/feed", () => {
    useBotsSupervisionStore.setState({ error: "Yükleme başarısız", bots: [], feed: [] });
    render(<BOTSPane />);
    const err = screen.getByTestId("bots-pane-error");
    // P3-A — role="status" already implies aria-live="polite"; the redundant
    // explicit aria-live was removed, so it must NOT be present anymore.
    expect(err.getAttribute("role")).toBe("status");
    expect(err.getAttribute("aria-live")).toBeNull();
    expect(err.className).toMatch(/u-text-negative/);
    expect(err.textContent).toMatch(/başarısız/);
  });
});

describe("BOTS F5 — table semantics", () => {
  it("bot table has a caption and scope columns", () => {
    seedBots([bot()]);
    render(<BOTSPane />);
    const table = screen.getByRole("table", { name: /denetim tablosu/i });
    expect(table.querySelector("caption")).not.toBeNull();
    expect(table.querySelectorAll("th[scope='col']").length).toBe(6);
  });

  it("feed table has a caption and scope columns", () => {
    seedBots([bot()], [{
      bar_index: 1, bar_time: "2026-05-22T10:00:00Z", kind: "entry", price: 100,
      action: "shadow", timestamp: "2026-05-22T10:00:00Z", bot_id: "a",
      bot_symbol: "BTC/USDT", bot_strategy_id: "s", bot_exchange_id: "binance",
      bot_mode: "shadow",
    }]);
    render(<BOTSPane />);
    const table = screen.getByRole("table", { name: /sinyal akışı/i });
    expect(table.querySelector("caption")).not.toBeNull();
    expect(table.querySelectorAll("th[scope='col']").length).toBe(5);
  });
});

describe("BOTS F6 — KPI unhealthy count", () => {
  it("counts a stuck bot in the Stuck/Degraded KPI", () => {
    seedBots([
      bot({ id: "a", enabled: true, is_running: false }),                 // STUCK
      bot({ id: "b", enabled: true, is_running: true, last_action: "shadow" }), // healthy
    ]);
    render(<BOTSPane />);
    const kpi = screen.getByTestId("bots-kpi-unhealthy");
    expect(kpi.textContent).toMatch(/Stuck\/Degraded/);
    expect(kpi.textContent).toMatch(/1/);
  });

  it("counts both stuck and degraded bots", () => {
    seedBots([
      bot({ id: "a", enabled: true, is_running: false }),                       // STUCK
      bot({ id: "b", enabled: true, is_running: true, last_action: "skipped" }), // DEGRADED
      bot({ id: "c", enabled: true, is_running: true, last_action: "shadow" }),  // healthy
    ]);
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-kpi-unhealthy").textContent).toMatch(/2/);
  });

  it("shows 0 honestly when all bots are healthy", () => {
    seedBots([bot({ id: "a", enabled: true, is_running: true, last_action: "shadow" })]);
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-kpi-unhealthy").textContent).toMatch(/0/);
  });
});
