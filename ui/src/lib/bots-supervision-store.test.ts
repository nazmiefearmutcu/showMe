import { beforeEach, describe, expect, it, vi } from "vitest";
import { useBotsSupervisionStore } from "./bots-supervision-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useBotsSupervisionStore.setState({
    stats: { total: 0, enabled: 0, live: 0, signals_today: 0 },
    bots: [], feed: [], generatedAt: null, loading: false, error: null,
  });
  mock.mockReset();
});

describe("bots-supervision-store", () => {
  it("loadAll populates stats from bots+feed", async () => {
    mock.mockResolvedValueOnce({ records: [
      { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", mode: "live", enabled: true,
        created_at: "", updated_at: "" },
      { id: "b", strategy_id: "s", credential_id: "c", exchange_id: "binance",
        symbol: "ETH/USDT", timeframe: "1h", mode: "shadow", enabled: true,
        created_at: "", updated_at: "" },
      { id: "c", strategy_id: "s", credential_id: "c", exchange_id: "binance",
        symbol: "SOL/USDT", timeframe: "1h", mode: "shadow", enabled: false,
        created_at: "", updated_at: "" },
    ] });
    const today = new Date().toISOString().slice(0, 10);
    mock.mockResolvedValueOnce({
      generated_at: `${today}T12:00:00Z`,
      signals: [
        { bar_index: 1, bar_time: `${today}T11:00:00Z`, kind: "entry",
          price: 100, action: "shadow", timestamp: `${today}T11:00:00Z`,
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "live" },
        { bar_index: 2, bar_time: "2026-05-21T11:00:00Z", kind: "exit",
          price: 105, action: "placed", timestamp: "2026-05-21T11:00:00Z",
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "live" },
      ],
    });
    await useBotsSupervisionStore.getState().loadAll();
    const s = useBotsSupervisionStore.getState();
    expect(s.stats.total).toBe(3);
    expect(s.stats.enabled).toBe(2);
    expect(s.stats.live).toBe(1);
    expect(s.stats.signals_today).toBe(1);  // only today's signal
    expect(s.feed.length).toBe(2);
  });

  it("loadAll surfaces errors", async () => {
    mock.mockRejectedValueOnce(new Error("503"));
    await useBotsSupervisionStore.getState().loadAll();
    expect(useBotsSupervisionStore.getState().error).toContain("503");
  });

  it("empty inputs produce zero stats", async () => {
    mock.mockResolvedValueOnce({ records: [] });
    mock.mockResolvedValueOnce({ generated_at: "x", signals: [] });
    await useBotsSupervisionStore.getState().loadAll();
    const s = useBotsSupervisionStore.getState();
    expect(s.stats.total).toBe(0);
    expect(s.stats.enabled).toBe(0);
    expect(s.stats.live).toBe(0);
    expect(s.stats.signals_today).toBe(0);
  });
});
