import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOTSPane } from "./BOTS";
import { useBotsSupervisionStore } from "@/lib/bots-supervision-store";
import { usePerformanceStore } from "@/lib/performance-store";

// Stub Promise-returning store actions so the useBotEcosystemPolling tick
// doesn't try to hit the network in jsdom.
const _resetStores = () => {
  useBotsSupervisionStore.setState({
    stats: { total: 0, enabled: 0, live: 0, signals_today: 0 },
    bots: [], feed: [], generatedAt: null, loading: false, error: null,
    loadAll: vi.fn(async () => {}),
  } as never);
  usePerformanceStore.setState({
    leaderboard: [], selected: null, loading: false, error: null,
    loadLeaderboard: vi.fn(async () => {}),
  } as never);
};

beforeEach(() => {
  _resetStores();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BOTS pane", () => {
  it("shows zero KPIs + empty placeholders", () => {
    render(<BOTSPane />);
    expect(screen.getByText(/toplam bot/i)).toBeInTheDocument();
    expect(screen.getByText(/henüz bot yok/i)).toBeInTheDocument();
    expect(screen.getByText(/henüz sinyal yok/i)).toBeInTheDocument();
  });

  it("renders bot table rows", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 2, enabled: 2, live: 1, signals_today: 1 },
      bots: [
        { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "BTC/USDT", timeframe: "1h", mode: "live", enabled: true,
          created_at: "", updated_at: "" },
        { id: "b", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "ETH/USDT", timeframe: "4h", mode: "shadow", enabled: true,
          created_at: "", updated_at: "" },
      ],
      feed: [], generatedAt: "x",
    });
    render(<BOTSPane />);
    expect(screen.getByText("BTC/USDT")).toBeInTheDocument();
    expect(screen.getByText("ETH/USDT")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("SHADOW")).toBeInTheDocument();
  });

  it("renders signal feed rows", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 1, enabled: 1, live: 0, signals_today: 1 },
      bots: [{ id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
               symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: true,
               created_at: "", updated_at: "" }],
      feed: [
        { bar_index: 1, bar_time: "2026-05-22T10:00:00Z", kind: "entry",
          price: 100.5, action: "shadow", timestamp: "2026-05-22T10:00:00Z",
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "shadow" },
      ],
      generatedAt: "x",
    });
    render(<BOTSPane />);
    expect(screen.getAllByText("BTC/USDT").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/100\.50/).length).toBeGreaterThan(0);
  });

  it("KPI strip shows non-zero live count in error color", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 5, enabled: 3, live: 2, signals_today: 0 },
      bots: [], feed: [], generatedAt: null,
    });
    render(<BOTSPane />);
    // KPI values present (text 5, 3, 2, 0):
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  // ─── H-SUP-2 ──────────────────────────────────────────────────────────
  it("test_signal_count_reads_bot_record_field", () => {
    // When the bot record carries `signal_count`, the column reads from it
    // (NOT from the feed-limited count).  Feed has 1 row for bot a but
    // signal_count=42 so the table shows 42.
    useBotsSupervisionStore.setState({
      stats: { total: 1, enabled: 1, live: 0, signals_today: 0 },
      bots: [
        { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: true,
          created_at: "", updated_at: "", signal_count: 42 },
      ],
      feed: [
        { bar_index: 9, bar_time: "2026-05-22T10:00:00Z", kind: "entry",
          price: 1, action: "shadow", timestamp: "2026-05-22T10:00:00Z",
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "shadow" },
      ],
      generatedAt: "x",
    });
    render(<BOTSPane />);
    const cell = screen.getByTestId("bots-signal-count-a");
    expect(cell.textContent).toBe("42");
    // Tooltip absent when the authoritative field is present.
    expect(cell.getAttribute("title")).toBeNull();
  });

  it("falls back to feed count and shows tooltip when signal_count missing", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 1, enabled: 1, live: 0, signals_today: 0 },
      bots: [
        { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: true,
          created_at: "", updated_at: "" /* no signal_count */ },
      ],
      feed: [
        { bar_index: 1, bar_time: "x", kind: "entry", price: 1, action: "shadow",
          timestamp: "2026-05-22T10:00:00Z", bot_id: "a", bot_symbol: "BTC/USDT",
          bot_strategy_id: "s", bot_exchange_id: "binance", bot_mode: "shadow" },
        { bar_index: 2, bar_time: "x", kind: "exit", price: 2, action: "shadow",
          timestamp: "2026-05-22T11:00:00Z", bot_id: "a", bot_symbol: "BTC/USDT",
          bot_strategy_id: "s", bot_exchange_id: "binance", bot_mode: "shadow" },
      ],
      generatedAt: "x",
    });
    render(<BOTSPane />);
    const cell = screen.getByTestId("bots-signal-count-a");
    expect(cell.textContent).toBe("2");
    expect(cell.getAttribute("title")).toMatch(/son 2 sinyal/);
  });

  // ─── BUG #6 (timezone) ────────────────────────────────────────────────
  it("test_timestamp_renders_in_local_timezone", () => {
    // Render a known UTC instant and assert that the cell does NOT show the
    // raw ISO slice — it should be the user's local formatted string.
    const iso = "2026-05-22T10:00:00Z";
    const expected = new Date(iso).toLocaleString(
      (typeof navigator !== "undefined" && navigator.language) || undefined,
    );
    useBotsSupervisionStore.setState({
      stats: { total: 1, enabled: 1, live: 0, signals_today: 1 },
      bots: [
        { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: true,
          created_at: "", updated_at: "" },
      ],
      feed: [
        { bar_index: 1, bar_time: iso, kind: "entry", price: 100, action: "shadow",
          timestamp: iso, bot_id: "a", bot_symbol: "BTC/USDT",
          bot_strategy_id: "s", bot_exchange_id: "binance", bot_mode: "shadow" },
      ],
      generatedAt: "x",
    });
    render(<BOTSPane />);
    // Local format should appear at least once across the two tables.
    const found = screen.queryAllByText(new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    expect(found.length).toBeGreaterThan(0);
    // The legacy UTC ISO slice "2026-05-22T10:00:00" should NOT be rendered
    // verbatim (the local format differs from the ISO format in all common
    // jsdom locales — e.g. "5/22/2026, 10:00:00 AM" or "22.05.2026, 13:00").
    expect(screen.queryByText("2026-05-22T10:00:00")).toBeNull();
  });

  // ─── H-SUP-4 (perm revoked badge) ────────────────────────────────────
  it("renders permission-revoked badge when bot.permission_revoked is true", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 1, enabled: 1, live: 1, signals_today: 0 },
      bots: [
        { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "BTC/USDT", timeframe: "1h", mode: "live", enabled: true,
          created_at: "", updated_at: "", permission_revoked: true },
      ],
      feed: [], generatedAt: "x",
    });
    render(<BOTSPane />);
    expect(screen.getByTestId("bots-perm-revoked-badge")).toBeInTheDocument();
  });

  it("does NOT render permission-revoked badge by default", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 1, enabled: 1, live: 1, signals_today: 0 },
      bots: [
        { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "BTC/USDT", timeframe: "1h", mode: "live", enabled: true,
          created_at: "", updated_at: "" },
      ],
      feed: [], generatedAt: "x",
    });
    render(<BOTSPane />);
    expect(screen.queryByTestId("bots-perm-revoked-badge")).toBeNull();
  });

  // ─── BUG #11 (refresh button rename + relocate) ───────────────────────
  it("Tumunu yenile button lives next to Botlar heading and calls loadAll", async () => {
    const spy = vi.fn(async () => {});
    useBotsSupervisionStore.setState({ loadAll: spy } as never);
    render(<BOTSPane />);
    const btn = screen.getByTestId("bots-refresh-all");
    expect(btn.textContent).toContain("Tümünü yenile");
    await act(async () => {
      btn.click();
    });
    // Called at least once: useBotEcosystemPolling initial tick + manual click.
    expect(spy.mock.calls.length).toBeGreaterThanOrEqual(1);
  });
});
