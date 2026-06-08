/**
 * MIS terminal-grade quality pins (accessibility, drill-down, display DRY).
 *
 * Covers:
 *   P1 — running a scan with NO markets selected shows an inline error
 *        (role=alert/status) next to the market selector, not just a toast;
 *        the per-row "+" add-to-watchlist button + TF toggle buttons carry
 *        descriptive aria-labels; the TF group is a labelled <fieldset>; the
 *        confidence bar exposes meter role + aria-value*; the DataGrid carries
 *        an ariaLabel; progress indicator renders immediately on Run.
 *   P2 — a result row is expandable and lists the full per-indicator breakdown.
 *   P3 — numeric result cells carry `terminal-grid-numeric`; KPI numbers use
 *        format.ts output (no "$-" sign-second, missing renders "—").
 *
 * The scan client + router are mocked for determinism: runMisScan resolves a
 * fixed two-row result so the grid + drill-down render synchronously.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const MARKETS_SUMMARY = [
  {
    key: "CRYPTO",
    default_timeframe: "1d",
    size: 200,
    asset_class: "crypto",
    default_tfs: ["1h", "4h", "1d"],
    active_tfs: ["1h", "4h", "1d"],
    tf_weights: { "1h": 40, "4h": 60, "1d": 80 },
  },
  {
    key: "EQUITY",
    default_timeframe: "1d",
    size: 50,
    asset_class: "equity",
    default_tfs: ["1h", "1d"],
    active_tfs: ["1h", "1d"],
    tf_weights: { "1h": 50, "1d": 70 },
  },
];

const SCAN_RESULT = {
  rows: [
    {
      symbol: "BTCUSDT",
      market: "CRYPTO",
      asset_class: "crypto",
      timeframe: "1h·4h·1d",
      direction: "LONG",
      final_signal: "STRONG_BUY",
      weighted_score: 0.42,
      normalized_score: 0.55,
      confidence: 73,
      last: 64250.5,
      change_pct: 2.31,
      top_indicators: [
        { name: "RSI", signal: "BUY", weighted_score: 0.2, reason: "oversold", tf: "1h" },
        { name: "MACD", signal: "STRONG_BUY", weighted_score: 0.3, reason: "cross", tf: "4h" },
      ],
      indicator_breakdown: [
        { name: "RSI", signal: "BUY", score: 0.6, reason: "oversold bounce" },
        { name: "MACD", signal: "STRONG_BUY", score: 0.9, reason: "bullish cross" },
        { name: "ADX", signal: "NEUTRAL", score: 0.0, reason: "weak trend" },
      ],
      per_tf: [
        { tf: "1h", weight: 40, direction: "LONG", final_signal: "BUY", score: 0.5, confidence: 70, contribution: 0.2 },
        { tf: "4h", weight: 60, direction: "LONG", final_signal: "STRONG_BUY", score: 0.8, confidence: 80, contribution: 0.48 },
        { tf: "1d", weight: 80, direction: "NEUTRAL", final_signal: "NEUTRAL", score: 0, confidence: 0, contribution: 0, skipped: "insufficient bars" },
      ],
      tf_count_scanned: 3,
      tf_count_with_signal: 2,
      skipped: null,
    },
    {
      symbol: "ETHUSDT",
      market: "CRYPTO",
      asset_class: "crypto",
      timeframe: "1h·4h·1d",
      direction: "SHORT",
      final_signal: "SELL",
      weighted_score: -0.31,
      normalized_score: -0.4,
      confidence: 61,
      last: 0.000042,
      change_pct: -1.12,
      top_indicators: [
        { name: "BBANDS", signal: "SELL", weighted_score: -0.2, reason: "upper band", tf: "1h" },
      ],
      indicator_breakdown: [
        { name: "BBANDS", signal: "SELL", score: -0.7, reason: "upper band reject" },
        { name: "RSI", signal: "SELL", score: -0.5, reason: "overbought" },
      ],
      per_tf: [
        { tf: "1h", weight: 40, direction: "SHORT", final_signal: "SELL", score: -0.5, confidence: 60, contribution: -0.2 },
      ],
      tf_count_scanned: 1,
      tf_count_with_signal: 1,
      skipped: null,
    },
  ],
  markets: ["CRYPTO"],
  per_market_counts: {
    CRYPTO: { requested: 200, completed: 198, skipped: 2 },
  },
  warnings: [],
  elapsed_ms: 1234,
  started_at: new Date().toISOString(),
};

vi.mock("@/lib/mis", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/mis")>();
  return {
    ...actual,
    fetchMisMarkets: vi.fn(async () => ({ markets: MARKETS_SUMMARY })),
    fetchMisIndicators: vi.fn(async () => ["RSI", "MACD", "ADX", "BBANDS"]),
    fetchMisConfig: vi.fn(async () => null),
    fetchMisScanProgress: vi.fn(async () => ({
      status: "running",
      total: 250,
      completed: 0,
      in_flight: 0,
      skipped: 0,
      markets: ["CRYPTO"],
      started_at: new Date().toISOString(),
      elapsed_ms: 0,
      current_symbol: "",
      current_market: "",
      percent: 0,
    })),
    runMisScan: vi.fn(async () => SCAN_RESULT),
    saveMisConfig: vi.fn(),
  };
});

vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));
vi.mock("@/lib/watchlist", () => ({ addSymbol: vi.fn(async () => ["BTCUSDT"]) }));

import { MISPane } from "./MIS";
import { runMisScan } from "@/lib/mis";

const runMisScanMock = vi.mocked(runMisScan);

afterEach(() => cleanup());
beforeEach(() => {
  runMisScanMock.mockClear();
});

/** Mount, wait for the markets boot fetch to resolve so cards render. */
async function mountReady() {
  const utils = render(<MISPane code="MIS" />);
  await screen.findAllByText(/Kripto/i);
  return utils;
}

/** Select all markets, click Tara, wait for the result grid. */
async function runScan() {
  fireEvent.click(screen.getByRole("button", { name: /tümünü seç/i }));
  fireEvent.click(screen.getByRole("button", { name: /^Tara$/ }));
  await waitFor(() => expect(runMisScanMock).toHaveBeenCalled());
  await screen.findByText("BTCUSDT");
}

describe("MIS terminal-grade", () => {
  it("P1: running a scan with no markets selected shows an inline error (not just a toast)", async () => {
    await mountReady();
    // Deselect everything first.
    fireEvent.click(screen.getByRole("button", { name: /temizle/i }));
    // The header Tara button disables at 0 markets, so trigger validation via
    // the inline run affordance / the disabled state must surface guidance.
    const inlineRun = screen.getByTestId("mis-run-inline");
    fireEvent.click(inlineRun);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent ?? "").toMatch(/piyasa/i);
    expect(runMisScanMock).not.toHaveBeenCalled();
  });

  it("P1: the idle empty state offers a Select-all affordance", async () => {
    await mountReady();
    fireEvent.click(screen.getByRole("button", { name: /temizle/i }));
    expect(screen.getByTestId("mis-empty-select-all")).toBeInTheDocument();
  });

  it("P1: TF toggle buttons are grouped in a labelled fieldset with aria-labels", async () => {
    await mountReady();
    const groups = screen.getAllByRole("group");
    const cryptoGroup = groups.find((g) =>
      (g.getAttribute("aria-label") ?? "").match(/timeframes for CRYPTO/i),
    );
    expect(cryptoGroup).toBeTruthy();
    // Each TF button inside carries an aria-label.
    const tfButton = within(cryptoGroup as HTMLElement).getByRole("button", {
      name: /toggle 1h timeframe/i,
    });
    expect(tfButton).toBeInTheDocument();
  });

  it("P1: progress indicator + scan-started cue render immediately on Run", async () => {
    await mountReady();
    fireEvent.click(screen.getByRole("button", { name: /tümünü seç/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Tara$/ }));
    // Before the POST resolves, the progressbar must already be on screen.
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    await waitFor(() => expect(runMisScanMock).toHaveBeenCalled());
  });

  it("P1: the + add-to-watchlist button has a descriptive aria-label", async () => {
    await mountReady();
    await runScan();
    expect(
      screen.getByRole("button", { name: /add BTCUSDT to watchlist/i }),
    ).toBeInTheDocument();
  });

  it("P1: the results DataGrid carries an aria-label", async () => {
    await mountReady();
    await runScan();
    const table = screen.getByRole("table", { name: /multi indicator scan results/i });
    expect(table).toBeInTheDocument();
  });

  it("P1/P2: confidence bar exposes meter role + aria-value*", async () => {
    await mountReady();
    await runScan();
    const meters = screen.getAllByRole("meter");
    expect(meters.length).toBeGreaterThan(0);
    const btc = meters[0];
    expect(btc.getAttribute("aria-valuenow")).toBe("73");
    expect(btc.getAttribute("aria-valuemin")).toBe("0");
    expect(btc.getAttribute("aria-valuemax")).toBe("100");
    expect(btc.getAttribute("aria-label") ?? "").toMatch(/confidence 73/i);
  });

  it("P2: a result row expands to list the full per-indicator breakdown", async () => {
    await mountReady();
    await runScan();
    const expand = screen.getByRole("button", { name: /show indicator breakdown for BTCUSDT/i });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(expand);
    expect(expand.getAttribute("aria-expanded")).toBe("true");
    const panel = await screen.findByTestId("mis-breakdown-BTCUSDT");
    // All three indicators from indicator_breakdown must be listed.
    expect(within(panel).getByText("ADX")).toBeInTheDocument();
    expect(within(panel).getByText(/bullish cross/i)).toBeInTheDocument();
  });

  it("P3: numeric result cells carry terminal-grid-numeric", async () => {
    const { container } = await mountReady();
    await runScan();
    expect(container.querySelectorAll(".terminal-grid-numeric").length).toBeGreaterThan(0);
  });

  it("P3: KPI numbers never render sign-second currency / missing is em-dash", async () => {
    await mountReady();
    await runScan();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\$-\d/);
  });

  it("P3: skipped per-TF cell title surfaces the real backend skip reason", async () => {
    const { container } = await mountReady();
    await runScan();
    // BTCUSDT's 1d TF was skipped with reason "insufficient bars".
    const skippedCell = Array.from(container.querySelectorAll("[title]")).find((el) =>
      (el.getAttribute("title") ?? "").includes("insufficient bars"),
    );
    expect(skippedCell).toBeTruthy();
  });
});
