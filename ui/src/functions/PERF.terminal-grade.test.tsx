/**
 * PERF — terminal-grade upgrade tests.
 *
 * Covers the NEW performance-pane behaviours added in the terminal-grade pass:
 *  F1 — equity curve disclosed as a SIMULATED relative curve seeded at the
 *       returned starting_equity; fallback-equity warn marker shows ONLY when
 *       equity_source === "fallback_10k".
 *  F2 — surfaced risk metrics (sharpe/sortino/profit_factor) rendered in the
 *       detail with the sample size N shown; "inf" → "∞"; small-N caveat.
 *  F3 — drawdown shown as a negative LOSS, red.
 *  F4 — both tables have caption + scope + aria-label; equity SVG has
 *       role="img" + aria-label; refresh button aria-busy/disabled; rows are
 *       keyboard-operable + aria-selected; single pane-level role=status.
 *  F5 — Empty when no data; Skeleton when loading + empty; last-updated
 *       freshness indicator from generated_at (frozen clock).
 *
 * Follows the store-setState render style of PERF.test.tsx /
 * BOTS.terminal-grade.test.tsx. Existing PERF + store + backend tests stay
 * green.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PERFPane } from "./PERF";
import {
  usePerformanceStore,
  type BotPerformanceDetail,
  type LeaderboardEntry,
  type PerformanceMetrics,
} from "@/lib/performance-store";
import { useBotsSupervisionStore } from "@/lib/bots-supervision-store";

const FROZEN_NOW = new Date("2026-06-08T12:00:00Z");

const _entry = (over: Partial<LeaderboardEntry>): LeaderboardEntry => ({
  bot_id: "x", symbol: "X", strategy_id: "s", mode: "shadow", enabled: true,
  total_pnl: 0, win_rate: 0, trade_count: 0, avg_pnl: 0, max_drawdown: 0,
  ...over,
});

const _metrics = (over: Partial<PerformanceMetrics> = {}): PerformanceMetrics => ({
  total_pnl: 50, win_rate: 0.6, trade_count: 30, avg_pnl: 1.7, max_drawdown: 8,
  net_pnl: 48, sharpe: 1.42, sortino: 2.1, profit_factor: 1.8,
  expectancy: 1.5, max_consecutive_losses: 3, ...over,
});

const _detail = (over: Partial<BotPerformanceDetail> = {}): BotPerformanceDetail => ({
  bot_id: "a", symbol: "BTC/USDT", strategy_id: "s",
  metrics: _metrics(),
  trades: [{ entry_time: "2026-05-22T10:00:00Z", exit_time: "2026-05-22T11:00:00Z",
             entry_price: 100, exit_price: 110, qty: 100, pnl: 10, pnl_pct: 10 }],
  equity_curve: [{ t: "start", equity: 10000 }, { t: "x", equity: 10050 }],
  starting_equity: 10000,
  equity_source: null,
  ...over,
});

function seedSelected(over: Partial<BotPerformanceDetail> = {}) {
  usePerformanceStore.setState({ leaderboard: [], selected: _detail(over) });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FROZEN_NOW);
  usePerformanceStore.setState({
    leaderboard: [], selected: null, loading: false, error: null, generatedAt: null,
    loadLeaderboard: vi.fn(async () => {}),
    loadBot: vi.fn(async () => {}),
  } as never);
  useBotsSupervisionStore.setState({
    stats: { total: 0, enabled: 0, live: 0, signals_today: 0 },
    bots: [], feed: [], generatedAt: null, loading: false, error: null,
    loadAll: vi.fn(async () => {}),
  } as never);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ─── F1 — simulated equity-curve honesty ─────────────────────────────────
describe("PERF F1 — equity-curve honesty", () => {
  it("discloses the curve is simulated + relative, using starting_equity", () => {
    seedSelected({ starting_equity: 10000 });
    render(<PERFPane />);
    const d = screen.getByTestId("perf-equity-disclaimer");
    expect(d.textContent).toMatch(/Simüle/i);
    expect(d.textContent).toMatch(/10,?000/);
    expect(d.textContent).toMatch(/gerçek hesap bakiyesi değildir/i);
  });

  it("shows the fallback-equity warn marker ONLY when equity_source === fallback_10k", () => {
    seedSelected({ equity_source: "fallback_10k" });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-equity-fallback-warning")).toBeInTheDocument();
  });

  it("hides the fallback marker when equity_source === broker", () => {
    seedSelected({ equity_source: "broker" });
    render(<PERFPane />);
    expect(screen.queryByTestId("perf-equity-fallback-warning")).toBeNull();
  });

  it("hides the fallback marker when equity_source is null", () => {
    seedSelected({ equity_source: null });
    render(<PERFPane />);
    expect(screen.queryByTestId("perf-equity-fallback-warning")).toBeNull();
  });
});

// ─── F2 — surfaced risk metrics with sample-size honesty ─────────────────
describe("PERF F2 — risk metrics + sample size", () => {
  it("renders sharpe / sortino / profit_factor in the detail", () => {
    seedSelected({ metrics: _metrics({ sharpe: 1.42, sortino: 2.1, profit_factor: 1.8, trade_count: 30 }) });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-sharpe").textContent).toBe("1.42");
    expect(screen.getByTestId("perf-sortino").textContent).toBe("2.10");
    expect(screen.getByTestId("perf-profit-factor").textContent).toBe("1.80");
  });

  it("shows the sample size N prominently", () => {
    seedSelected({ metrics: _metrics({ trade_count: 30 }) });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-sample-size").textContent).toMatch(/N=30/);
  });

  it("renders a small-N caveat when trade_count < 20 (de-emphasised ratios)", () => {
    seedSelected({ metrics: _metrics({ trade_count: 4 }) });
    render(<PERFPane />);
    const warn = screen.getByTestId("perf-low-sample-warning");
    expect(warn.textContent).toMatch(/Küçük örneklem/i);
    expect(warn.textContent).toMatch(/N=4/);
    // ratios de-emphasised
    expect(screen.getByTestId("perf-sharpe").className).toMatch(/u-text-secondary/);
  });

  it("does NOT render the small-N caveat when trade_count >= 20", () => {
    seedSelected({ metrics: _metrics({ trade_count: 30 }) });
    render(<PERFPane />);
    expect(screen.queryByTestId("perf-low-sample-warning")).toBeNull();
  });

  it("renders profit_factor 'inf' as ∞ (no crash / NaN)", () => {
    seedSelected({ metrics: _metrics({ profit_factor: "inf", trade_count: 30 }) });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-profit-factor").textContent).toBe("∞");
  });

  it("renders sharpe 'inf' as ∞", () => {
    seedSelected({ metrics: _metrics({ sharpe: "inf", trade_count: 30 }) });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-sharpe").textContent).toBe("∞");
  });
});

// ─── F3 — drawdown display correctness ───────────────────────────────────
describe("PERF F3 — drawdown reads as a negative loss", () => {
  it("renders Max DD as a negative, red value in the detail KPI strip", () => {
    seedSelected({ metrics: _metrics({ max_drawdown: 8 }) });
    render(<PERFPane />);
    // Detail KPI strip "Max DD" → -$8 sign-coloured.
    const dd = screen.getByText(/-\$8/);
    expect(dd).toBeInTheDocument();
    expect(dd.className).toMatch(/u-text-negative/);
  });

  it("renders leaderboard Max DD column as negative + red", () => {
    usePerformanceStore.setState({
      leaderboard: [_entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 5, max_drawdown: 12 })],
    });
    render(<PERFPane />);
    const cell = screen.getByTestId("perf-row-dd-a");
    expect(cell.textContent).toMatch(/-\$12/);
    expect(cell.className).toMatch(/u-text-negative/);
  });
});

// ─── F4 — accessibility ──────────────────────────────────────────────────
describe("PERF F4 — a11y", () => {
  it("leaderboard table has caption + scope columns + aria-label", () => {
    usePerformanceStore.setState({
      leaderboard: [_entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 5 })],
    });
    render(<PERFPane />);
    const table = screen.getByRole("table", { name: /leaderboard/i });
    expect(table.querySelector("caption")).not.toBeNull();
    expect(table.querySelectorAll("th[scope='col']").length).toBe(5);
  });

  it("trades table has caption + scope columns + aria-label", () => {
    seedSelected();
    render(<PERFPane />);
    const table = screen.getByRole("table", { name: /son işlemler/i });
    expect(table.querySelector("caption")).not.toBeNull();
    expect(table.querySelectorAll("th[scope='col']").length).toBe(6);
  });

  it("equity SVG has role=img and a descriptive aria-label", () => {
    seedSelected();
    render(<PERFPane />);
    const svg = screen.getByTestId("perf-equity-svg");
    expect(svg.getAttribute("role")).toBe("img");
    expect(svg.getAttribute("aria-label")).toMatch(/Simüle equity eğrisi/i);
    expect(svg.getAttribute("aria-label")).toMatch(/başlangıç/i);
  });

  it("refresh button has aria-label, aria-busy + disabled while loading", () => {
    usePerformanceStore.setState({ loading: true, leaderboard: [_entry({ bot_id: "a" })] });
    render(<PERFPane />);
    const btn = screen.getByTestId("perf-refresh");
    expect(btn.getAttribute("aria-label")).toBeTruthy();
    expect(btn.getAttribute("aria-busy")).toBe("true");
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("KPI pills carry an accessible name", () => {
    usePerformanceStore.setState({
      leaderboard: [_entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 50 })],
    });
    render(<PERFPane />);
    expect(screen.getByLabelText(/Lider: BTC\/USDT/)).toBeInTheDocument();
  });

  it("leaderboard rows are keyboard-operable and mark aria-selected", () => {
    const loadBot = vi.fn(async () => {});
    usePerformanceStore.setState({
      leaderboard: [_entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 5 })],
      selected: _detail({ bot_id: "a", symbol: "BTC/USDT" }),
      loadBot,
    } as never);
    render(<PERFPane />);
    const row = screen.getByRole("button", { name: /BTC\/USDT performans detayını aç/i });
    expect(row.getAttribute("tabindex")).toBe("0");
    expect(row.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(loadBot).toHaveBeenCalledWith("a");
  });

  it("renders exactly one pane-level role=status summary (no error)", () => {
    usePerformanceStore.setState({
      leaderboard: [_entry({ bot_id: "a", symbol: "BTC/USDT", total_pnl: 5 })],
    });
    render(<PERFPane />);
    const summary = screen.getByTestId("perf-summary");
    expect(summary.getAttribute("role")).toBe("status");
    expect(screen.getAllByRole("status").length).toBe(1);
  });

  it("close button has an aria-label", () => {
    seedSelected();
    render(<PERFPane />);
    expect(screen.getByLabelText(/BTC\/USDT detayını kapat/i)).toBeInTheDocument();
  });

  it("error region is role=status with no redundant aria-live", () => {
    usePerformanceStore.setState({ error: "Yükleme başarısız", leaderboard: [] });
    render(<PERFPane />);
    const err = screen.getByTestId("perf-pane-error");
    expect(err.getAttribute("role")).toBe("status");
    expect(err.getAttribute("aria-live")).toBeNull();
    expect(err.className).toMatch(/u-text-negative/);
  });
});

// ─── F5 — states + freshness ─────────────────────────────────────────────
describe("PERF F5 — states + freshness", () => {
  it("shows a Skeleton while loading + empty leaderboard", () => {
    usePerformanceStore.setState({ loading: true, leaderboard: [] });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("perf-empty")).toBeNull();
  });

  it("shows design-system Empty when there is no data and not loading", () => {
    usePerformanceStore.setState({ loading: false, leaderboard: [] });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-empty")).toBeInTheDocument();
  });

  it("shows the equity-curve Empty when there are < 2 points", () => {
    seedSelected({ equity_curve: [{ t: "start", equity: 10000 }] });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-equity-empty")).toBeInTheDocument();
  });

  it("renders a last-updated indicator from generated_at", () => {
    usePerformanceStore.setState({
      leaderboard: [_entry({ bot_id: "a" })],
      generatedAt: "2026-06-08T11:59:30Z",
    });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-last-updated").textContent).toMatch(/Son güncelleme:/);
    // honest non-em-dash when present
    expect(screen.getByTestId("perf-last-updated").textContent).not.toMatch(/—/);
  });

  it("renders honest — for last-updated when generated_at is absent", () => {
    usePerformanceStore.setState({ leaderboard: [_entry({ bot_id: "a" })], generatedAt: null });
    render(<PERFPane />);
    expect(screen.getByTestId("perf-last-updated").textContent).toMatch(/—/);
  });
});
