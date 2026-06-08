import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePerformanceStore } from "./performance-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  usePerformanceStore.setState({
    leaderboard: [], selected: null, loading: false, error: null, generatedAt: null,
  });
  mock.mockReset();
});

describe("performance-store", () => {
  it("loadLeaderboard populates", async () => {
    mock.mockResolvedValueOnce({ records: [
      { bot_id: "a", symbol: "BTC/USDT", strategy_id: "s", mode: "shadow", enabled: true,
        total_pnl: 10, win_rate: 1, trade_count: 1, avg_pnl: 10, max_drawdown: 0 },
    ] });
    await usePerformanceStore.getState().loadLeaderboard();
    expect(usePerformanceStore.getState().leaderboard).toHaveLength(1);
  });

  it("loadLeaderboard captures generated_at freshness stamp", async () => {
    mock.mockResolvedValueOnce({ records: [], generated_at: "2026-06-08T12:00:00Z" });
    await usePerformanceStore.getState().loadLeaderboard();
    expect(usePerformanceStore.getState().generatedAt).toBe("2026-06-08T12:00:00Z");
  });

  it("loadLeaderboard tolerates a missing records array (no throw)", async () => {
    mock.mockResolvedValueOnce({ generated_at: "2026-06-08T12:00:00Z" } as never);
    await usePerformanceStore.getState().loadLeaderboard();
    expect(usePerformanceStore.getState().leaderboard).toEqual([]);
    expect(usePerformanceStore.getState().error).toBeNull();
  });

  it("loadBot populates detail", async () => {
    mock.mockResolvedValueOnce({
      bot_id: "a", symbol: "BTC/USDT", strategy_id: "s",
      metrics: { total_pnl: 10, win_rate: 1, trade_count: 1, avg_pnl: 10, max_drawdown: 0 },
      trades: [{ entry_time: "t1", exit_time: "t2", entry_price: 100, exit_price: 110,
                 qty: 100, pnl: 10, pnl_pct: 10 }],
      equity_curve: [{ t: "start", equity: 10000 }, { t: "t2", equity: 10010 }],
    });
    await usePerformanceStore.getState().loadBot("a");
    expect(usePerformanceStore.getState().selected?.metrics.trade_count).toBe(1);
  });

  it("loadLeaderboard surfaces errors", async () => {
    mock.mockRejectedValueOnce(new Error("500"));
    await usePerformanceStore.getState().loadLeaderboard();
    expect(usePerformanceStore.getState().error).toContain("500");
  });

  it("clearSelected wipes detail", () => {
    usePerformanceStore.setState({ selected: { bot_id: "a" } as never });
    usePerformanceStore.getState().clearSelected();
    expect(usePerformanceStore.getState().selected).toBeNull();
  });
});
