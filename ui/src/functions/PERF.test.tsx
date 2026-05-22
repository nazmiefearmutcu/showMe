import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { PERFPane } from "./PERF";
import { usePerformanceStore } from "@/lib/performance-store";

beforeEach(() => {
  usePerformanceStore.setState({ leaderboard: [], selected: null, loading: false, error: null });
});

describe("PERF pane", () => {
  it("shows empty state when no leaderboard", () => {
    render(<PERFPane />);
    expect(screen.getByText(/henüz performans/i)).toBeInTheDocument();
  });

  it("renders leaderboard rows", () => {
    usePerformanceStore.setState({
      leaderboard: [
        { bot_id: "a", symbol: "BTC/USDT", strategy_id: "s", mode: "shadow", enabled: true,
          total_pnl: 50, win_rate: 0.8, trade_count: 10, avg_pnl: 5, max_drawdown: 3 },
        { bot_id: "b", symbol: "ETH/USDT", strategy_id: "s", mode: "live", enabled: true,
          total_pnl: -10, win_rate: 0.3, trade_count: 5, avg_pnl: -2, max_drawdown: 12 },
      ],
    });
    render(<PERFPane />);
    expect(screen.getByText("BTC/USDT")).toBeInTheDocument();
    expect(screen.getByText("ETH/USDT")).toBeInTheDocument();
    // 50.00 appears in row + 50.00 in KPI strip; just check leaderboard cells contain numbers
    expect(screen.getByText("80%")).toBeInTheDocument();
  });

  it("clicking row calls loadBot", () => {
    const calls: string[] = [];
    usePerformanceStore.setState({
      leaderboard: [{ bot_id: "a", symbol: "BTC/USDT", strategy_id: "s", mode: "shadow",
                      enabled: true, total_pnl: 50, win_rate: 1, trade_count: 1,
                      avg_pnl: 50, max_drawdown: 0 }],
    });
    // Spy on loadBot:
    const original = usePerformanceStore.getState().loadBot;
    usePerformanceStore.setState({
      loadBot: async (id: string) => { calls.push(id); },
    } as never);
    render(<PERFPane />);
    fireEvent.click(screen.getByText("BTC/USDT").closest("tr")!);
    expect(calls).toEqual(["a"]);
    // Restore (not strictly needed, beforeEach resets)
    usePerformanceStore.setState({ loadBot: original } as never);
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
    expect(screen.getByText(/equity curve/i)).toBeInTheDocument();
    expect(screen.getByText(/^Kapat$/)).toBeInTheDocument();
  });
});
