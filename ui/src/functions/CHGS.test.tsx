/**
 * CHGS pane — render-contract + honesty tests (CRVF/GEX pattern).
 *
 * The backend CHGS defers to the live TECH studies by default; only
 * `reference=true` serves the labelled synthetic template. Pins:
 *
 *  - the load states (loading / error / ok) render;
 *  - a LIVE payload renders summary cards, the close/study overlay chart,
 *    and the per-study latest-values table — with a "live studies" pill;
 *  - a SYNTHETIC template payload (status=reference / data_mode=modeled)
 *    gets the prominent "synthetic template" pill + warning and never
 *    renders as live data;
 *  - a PROVIDER OUTAGE envelope (provider_unavailable / no_price_history)
 *    renders an honest outage Empty with the backend reason — it is never
 *    labelled "synthetic template";
 *  - the study selector chip interaction re-labels the overlay.
 *
 * `useFunction` is mocked via a mutable shared state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CHGSPane } from "./CHGS";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    warnings?: string[];
    metadata?: Record<string, unknown>;
    elapsed_ms?: number;
  };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

/* ── fixtures: live shape mirrors chart/tech.py via CHGSFunction ───── */

function series(base: number, n: number) {
  return Array.from({ length: n }, (_, i) => ({
    time: `2026-09-0${(i % 9) + 1}T13:30:00+00:00`,
    value: base + i * 0.4,
  }));
}

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        bar_count: 6,
        bars: Array.from({ length: 6 }, (_, i) => ({
          date: `2026-09-0${i + 1}T13:30:00+00:00`,
          close: 120 + i,
        })),
        indicators: {
          sma_20: series(121, 6),
          sma_50: series(119, 6),
          ema_20: series(120.5, 6),
        },
        indicator_rows: [{ indicator: "RSI", value: 56.7, period: 14 }],
        summary: {
          last_price: 125,
          rsi: 56.7,
          atr: 3.1,
          adx: 18.2,
        },
      },
      sources: ["yfinance"],
      metadata: { alias_of: "TECH" },
      elapsed_ms: 55,
    },
  };
}

function syntheticPayload() {
  return {
    data: {
      data: {
        status: "reference",
        data_mode: "modeled",
        symbol: "AAPL",
        last: 123.45,
        rsi_14: 54.2,
        sma_20: 121.6,
        sma_50: 118.75,
      },
      sources: ["showme_chart_model"],
      metadata: { alias_of: "TECH", live: false },
      elapsed_ms: 1,
    },
  };
}

function outagePayload() {
  return {
    data: {
      data: {
        status: "provider_unavailable",
        rows: [],
        ohlcv: [],
        summary: { symbol: "AAPL", days: 180 },
        reason: "yfinance fetch failed: HTTP 503 from quote provider",
        next_actions: ["Try again later or check symbol support."],
      },
      sources: ["yfinance"],
      warnings: ["yfinance: HTTP 503 from quote provider"],
      metadata: { alias_of: "TECH" },
      elapsed_ms: 12,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("CHGS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no bars come back", () => {
    setMockFn({
      state: "ok",
      data: {
        data: { status: "ok", bars: [], indicators: { sma_20: [] } },
      },
    });
    render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(screen.getByText(/No chart bars returned/i)).toBeInTheDocument();
  });
});

describe("CHGS pane — live payload", () => {
  it("renders the summary cards (last price, RSI, ATR, ADX)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(container.textContent).toContain("125.00");
    expect(container.textContent).toContain("56.70");
    expect(container.textContent).toContain("3.10");
    expect(container.textContent).toContain("18.20");
    expect(container.textContent).toContain("RANGE-BOUND");
  });

  it("renders the close + study overlay chart", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<CHGSPane code="CHGS" symbol="AAPL" />);
    const svg = container.querySelector('svg[role="img"]');
    expect(svg?.getAttribute("aria-label")).toMatch(
      /Close with SMA 20 overlay, 6 bars and 6 study points/i,
    );
    expect(container.querySelectorAll("polyline").length).toBe(2);
  });

  it("renders the per-study latest-values table", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<CHGSPane code="CHGS" symbol="AAPL" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(3);
    expect(container.textContent).toContain("SMA 20");
    expect(container.textContent).toContain("SMA 50");
    expect(container.textContent).toContain("EMA 20");
    // Latest sma_20 = 121 + 5*0.4 = 123.00.
    expect(container.textContent).toContain("123.00");
  });

  it("shows the live-studies pill and no synthetic warning", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(screen.getByText(/live studies/i)).toBeInTheDocument();
    expect(screen.queryByText(/synthetic template/i)).toBeNull();
  });
});

describe("CHGS pane — synthetic honesty", () => {
  it("flags the synthetic template with a warning pill + alert", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(screen.getAllByText(/synthetic template/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/NOT live OHLCV data/i)).toBeInTheDocument();
  });

  it("does NOT render the study chart or table for synthetic payloads", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    const { container } = render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    expect(container.querySelector("tbody")).toBeNull();
  });
});

describe("CHGS pane — provider outage honesty", () => {
  it("renders the outage reason and never claims the synthetic template", () => {
    setMockFn({ state: "ok", ...outagePayload() });
    const { container } = render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(screen.getByText(/Chart studies unavailable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/yfinance fetch failed: HTTP 503/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/synthetic template/i)).toBeNull();
    expect(screen.queryByText(/NOT live OHLCV data/i)).toBeNull();
    expect(container.querySelector('svg[role="img"]')).toBeNull();
  });

  it("covers the no_price_history envelope with its backend reason", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "no_price_history",
          rows: [],
          ohlcv: [],
          reason:
            "provider returned no price history for ZZZZ (180d, interval 1d)",
        },
        sources: ["yfinance"],
        warnings: ["no price history"],
        metadata: { alias_of: "TECH" },
      },
    });
    render(<CHGSPane code="CHGS" symbol="ZZZZ" />);
    expect(screen.getByText(/no price history for ZZZZ/i)).toBeInTheDocument();
    expect(screen.queryByText(/synthetic template/i)).toBeNull();
  });

  it("falls back to the envelope warning for a keyless empty body", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {},
        warnings: ["no yfinance"],
        metadata: { alias_of: "TECH" },
      },
    });
    render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(screen.getByText(/no yfinance/i)).toBeInTheDocument();
    expect(screen.queryByText(/synthetic template/i)).toBeNull();
  });
});

describe("CHGS pane — interaction", () => {
  it("switches the overlay study via the chips", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<CHGSPane code="CHGS" symbol="AAPL" />);
    const group = screen.getByLabelText("Overlay study");
    const sma20 = group.querySelector('button[title="STUDY sma_20"]');
    const sma50 = group.querySelector('button[title="STUDY sma_50"]');
    expect(sma20?.className).toContain("fn-segmented__opt--active");
    if (sma50) fireEvent.click(sma50);
    expect(sma50?.className).toContain("fn-segmented__opt--active");
    expect(sma20?.className).not.toContain("fn-segmented__opt--active");
    // Caption re-labels to the selected study.
    expect(screen.getAllByText(/SMA 50/).length).toBeGreaterThanOrEqual(1);
  });
});
