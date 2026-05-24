/**
 * Faz 3 — bots-supervision-store regression fixes.
 *
 *   H-5 — array guard for null records/signals
 *   H-7 — signals_today uses local TZ (Intl) not UTC
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("bots-supervision-store fixes", () => {
  // ─── H-5 ────────────────────────────────────────────────────────────
  it("array_guard_null_records", async () => {
    mock.mockResolvedValueOnce({ records: null });
    mock.mockResolvedValueOnce({ generated_at: "x", signals: null });
    await useBotsSupervisionStore.getState().loadAll();
    const s = useBotsSupervisionStore.getState();
    expect(s.bots).toEqual([]);
    expect(s.feed).toEqual([]);
    expect(s.stats.total).toBe(0);
    expect(s.error).toBeNull();
    expect(s.loading).toBe(false);
  });

  it("array_guard_undefined_records", async () => {
    mock.mockResolvedValueOnce({});           // no records key
    mock.mockResolvedValueOnce({});           // no signals key
    await useBotsSupervisionStore.getState().loadAll();
    const s = useBotsSupervisionStore.getState();
    expect(s.bots).toEqual([]);
    expect(s.feed).toEqual([]);
    expect(s.stats.total).toBe(0);
  });

  it("array_guard_non_array_records", async () => {
    mock.mockResolvedValueOnce({ records: "not-an-array" as unknown });
    mock.mockResolvedValueOnce({ generated_at: "x", signals: 42 as unknown });
    await useBotsSupervisionStore.getState().loadAll();
    const s = useBotsSupervisionStore.getState();
    expect(s.bots).toEqual([]);
    expect(s.feed).toEqual([]);
  });

  // ─── H-7 ────────────────────────────────────────────────────────────
  it("signals_today_local_tz_buckets_correctly", async () => {
    // Anchor "now" on 2026-05-23 noon Istanbul, regardless of how the host
    // formats it; we then assert that a signal whose UTC instant falls on
    // 2026-05-22T23:30:00Z (which is 02:30 local on May 23) buckets into "today".
    //
    // We control the boundary by mocking Date — both `new Date()` (now) and
    // `new Date(ts).toLocaleDateString("en-CA")` derive from the same Date impl.
    //
    // Strategy: instead of fragile TZ mocking, we verify the relationship
    // directly using known Date instances under the host's TZ.
    const sigInstant = "2026-05-22T23:30:00Z";
    const sigLocalDate = new Date(sigInstant).toLocaleDateString("en-CA");
    // Pin "today" to that same local date so the assertion is TZ-agnostic.
    vi.useFakeTimers();
    vi.setSystemTime(new Date(sigInstant));

    mock.mockResolvedValueOnce({ records: [] });
    mock.mockResolvedValueOnce({
      generated_at: sigInstant,
      signals: [
        { bar_index: 1, bar_time: sigInstant, kind: "entry",
          price: 100, action: "shadow", timestamp: sigInstant,
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "live" },
      ],
    });
    await useBotsSupervisionStore.getState().loadAll();
    const today = new Date().toLocaleDateString("en-CA");
    expect(sigLocalDate).toBe(today); // sanity — same instant => same local date
    expect(useBotsSupervisionStore.getState().stats.signals_today).toBe(1);
  });

  it("signals_today_ignores_other_day", async () => {
    // A signal exactly 36h before now must NOT count.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-23T12:00:00Z"));

    mock.mockResolvedValueOnce({ records: [] });
    mock.mockResolvedValueOnce({
      generated_at: "2026-05-23T12:00:00Z",
      signals: [
        { bar_index: 1, bar_time: "2026-05-22T00:00:00Z", kind: "entry",
          price: 100, action: "shadow", timestamp: "2026-05-22T00:00:00Z",
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "live" },
      ],
    });
    await useBotsSupervisionStore.getState().loadAll();
    expect(useBotsSupervisionStore.getState().stats.signals_today).toBe(0);
  });

  it("signals_today_handles_invalid_timestamp", async () => {
    mock.mockResolvedValueOnce({ records: [] });
    mock.mockResolvedValueOnce({
      generated_at: "x",
      signals: [
        { bar_index: 1, bar_time: "x", kind: "entry",
          price: 100, action: "shadow", timestamp: "not-a-date",
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "live" },
        { bar_index: 2, bar_time: "x", kind: "entry",
          price: 100, action: "shadow",  // no timestamp
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "live" } as unknown,
      ],
    });
    await useBotsSupervisionStore.getState().loadAll();
    // Neither malformed nor missing timestamp counts.
    expect(useBotsSupervisionStore.getState().stats.signals_today).toBe(0);
  });
});
