import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PERFPane } from "./PERF";
import { usePerformanceStore, type LeaderboardEntry } from "@/lib/performance-store";
import { useBotsSupervisionStore } from "@/lib/bots-supervision-store";

const _entry = (over: Partial<LeaderboardEntry>): LeaderboardEntry => ({
  bot_id: "x", symbol: "X", strategy_id: "s", mode: "shadow", enabled: true,
  total_pnl: 0, win_rate: 0, trade_count: 0, avg_pnl: 0, max_drawdown: 0,
  ...over,
});

beforeEach(() => {
  // Stub Promise-returning store actions so the unified ecosystem polling
  // tick doesn't fan out to the network in jsdom.
  usePerformanceStore.setState({
    leaderboard: [], selected: null, loading: false, error: null,
    loadLeaderboard: vi.fn(async () => {}),
  } as never);
  useBotsSupervisionStore.setState({
    stats: { total: 0, enabled: 0, live: 0, signals_today: 0 },
    bots: [], feed: [], generatedAt: null, loading: false, error: null,
    loadAll: vi.fn(async () => {}),
  } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PERF pane", () => {
  it("shows empty state when no leaderboard", () => {
    render(<PERFPane />);
    expect(screen.getByText(/no performance/i)).toBeInTheDocument();
  });

  it("renders leaderboard rows", () => {
    usePerformanceStore.setState({
      leaderboard: [
        _entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 50,
                 win_rate: 0.8, trade_count: 10, avg_pnl: 5, max_drawdown: 3 }),
        _entry({ bot_id: "b", symbol: "ETH/USDT", total_pnl: -10, mode: "live",
                 win_rate: 0.3, trade_count: 5, avg_pnl: -2, max_drawdown: 12 }),
      ],
    });
    render(<PERFPane />);
    expect(screen.getByText("BTC/USDT")).toBeInTheDocument();
    expect(screen.getByText("ETH/USDT")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
  });

  it("clicking row calls loadBot", () => {
    const calls: string[] = [];
    usePerformanceStore.setState({
      leaderboard: [_entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 50,
                              win_rate: 1, trade_count: 1, avg_pnl: 50 })],
      loadBot: async (id: string) => { calls.push(id); },
    } as never);
    render(<PERFPane />);
    fireEvent.click(screen.getByText("BTC/USDT").closest("tr")!);
    expect(calls).toEqual(["a"]);
  });

  it("renders detail view when selected", () => {
    usePerformanceStore.setState({
      leaderboard: [],
      selected: {
        bot_id: "a", symbol: "BTC/USDT", strategy_id: "s",
        metrics: { total_pnl: 50, win_rate: 0.8, trade_count: 10, avg_pnl: 5, max_drawdown: 3 },
        trades: [{ entry_time: "2026-05-22T10:00:00Z", exit_time: "2026-05-22T11:00:00Z",
                   entry_price: 100, exit_price: 110, qty: 100, pnl: 10, pnl_pct: 10 }],
        equity_curve: [{ t: "start", equity: 10000 }, { t: "x", equity: 10050 }],
      },
    });
    render(<PERFPane />);
    expect(screen.getAllByText(/equity curve/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/^Close$/)).toBeInTheDocument();
  });

  // ─── H-SUP-1 — KPI strip semantic ────────────────────────────────────
  it("test_kpi_strip_all_positive_shows_no_loss_pill", () => {
    // All-positive portfolio: "Top gainer" + "Leader" visible, "Top loser"
    // absent. "Laggard" = lowest but still positive → muted tone.
    usePerformanceStore.setState({
      leaderboard: [
        _entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 50, trade_count: 5 }),
        _entry({ bot_id: "b", symbol: "ETH/USDT", total_pnl: 20, trade_count: 5 }),
        _entry({ bot_id: "c", symbol: "SOL/USDT", total_pnl: 5,  trade_count: 5 }),
      ],
    });
    render(<PERFPane />);
    // Leader (always shown):
    const leader = screen.getByTestId("perf-kpi-leader");
    expect(leader.textContent).toMatch(/BTC\/USDT/);
    // Top gainer (positive exists):
    const topGainer = screen.getByTestId("perf-kpi-top-gainer");
    expect(topGainer.textContent).toMatch(/BTC\/USDT/);
    // Laggard (always shown when >1 bot):
    const laggard = screen.getByTestId("perf-kpi-laggard");
    expect(laggard.textContent).toMatch(/SOL\/USDT/);
    // Top loser — none of the bots is negative, pill must be absent.
    expect(screen.queryByTestId("perf-kpi-top-loser")).toBeNull();
  });

  it("test_kpi_strip_mixed_shows_both_best_and_worst", () => {
    // Mixed sign: all four pills present and distinct.
    usePerformanceStore.setState({
      leaderboard: [
        _entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 100, trade_count: 5 }),
        _entry({ bot_id: "b", symbol: "ETH/USDT", total_pnl: 20,  trade_count: 5 }),
        _entry({ bot_id: "c", symbol: "SOL/USDT", total_pnl: -30, trade_count: 5 }),
      ],
    });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-kpi-leader").textContent).toMatch(/BTC\/USDT/);
    expect(screen.getByTestId("perf-kpi-top-gainer").textContent).toMatch(/BTC\/USDT/);
    expect(screen.getByTestId("perf-kpi-laggard").textContent).toMatch(/SOL\/USDT/);
    expect(screen.getByTestId("perf-kpi-top-loser").textContent).toMatch(/SOL\/USDT/);
  });

  it("all-negative portfolio still shows Leader (top-ranked, even if negative)", () => {
    usePerformanceStore.setState({
      leaderboard: [
        _entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: -5,  trade_count: 5 }),
        _entry({ bot_id: "b", symbol: "ETH/USDT", total_pnl: -50, trade_count: 5 }),
      ],
    });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-kpi-leader").textContent).toMatch(/BTC\/USDT/);
    expect(screen.getByTestId("perf-kpi-top-loser").textContent).toMatch(/ETH\/USDT/);
    // Top gainer pill absent (no positive bot).
    expect(screen.queryByTestId("perf-kpi-top-gainer")).toBeNull();
  });

  // ─── BUG #7 / F1 — simulated equity disclosure on the curve ──────────
  // The header-level badge moved into the detail view, next to the equity
  // curve it actually describes (more honest: the disclosure sits with the
  // simulated curve, not the always-on toolbar).
  it("discloses the simulated starting equity next to the curve", () => {
    usePerformanceStore.setState({
      leaderboard: [],
      selected: {
        bot_id: "a", symbol: "BTC/USDT", strategy_id: "s",
        metrics: { total_pnl: 50, win_rate: 0.8, trade_count: 10, avg_pnl: 5, max_drawdown: 3 },
        trades: [],
        equity_curve: [{ t: "start", equity: 10000 }, { t: "x", equity: 10050 }],
        starting_equity: 10000,
      },
    });
    render(<PERFPane />);
    const disclaimer = screen.getByTestId("perf-equity-disclaimer");
    expect(disclaimer.textContent).toMatch(/Simulated/i);
    expect(disclaimer.textContent).toMatch(/10,?000/);
    expect(disclaimer.textContent).toMatch(/not the real account balance/i);
  });
});
