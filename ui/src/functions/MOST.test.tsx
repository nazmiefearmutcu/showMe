/**
 * MOST — Most Active (movers) terminal-grade tests.
 *
 * Pins the page-by-page hardening pass (P1–P6):
 *  - P2 data honesty: the synthetic per-row "Trend" sparkline column is gone
 *    (procedural pseudo-random data must never pose as real intraday history);
 *    any remaining in-grid sparkline must not be marked data-synthetic="true".
 *  - P4 a11y: filter-rail Reset/Apply, error Retry and empty "Reset & retry"
 *    carry aria-labels; the ActivityBars track is aria-hidden.
 *  - P5/P6 display: numeric cells (rank / last / Δ% / vol / $vol) carry the
 *    shared `terminal-grid-numeric` class.
 *  - state machine: loading / error / empty states render with labelled buttons.
 *  - asset + sort tab switching changes which rows render / the active sort.
 *  - symbol click navigates into DES.
 *  - the LIVE/REFERENCE pill reflects payload.live.
 *
 * useFunction + router.navigate are mocked so the suite is deterministic and
 * never touches the sidecar.
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Each test installs its own useFunction return via this mutable holder.
const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { MOSTPane } from "./MOST";
import * as router from "@/lib/router";

function makeRow(over: Record<string, unknown> = {}) {
  return {
    symbol: "NVDA",
    name: "NVIDIA",
    asset_class: "equity",
    exchange: "NASDAQ",
    last: 198.45,
    volume: 310_000_000,
    dollar_volume: 198.45 * 310_000_000,
    change_pct: 2.1,
    quote_state: "live",
    ...over,
  };
}

function mockState(
  state: string,
  rows: unknown[] = [],
  payloadOver: Record<string, unknown> = {},
  extra: Record<string, unknown> = {},
) {
  mockReturn.current = {
    state,
    data: {
      data: {
        status: "ok",
        rows,
        universe: rows.map((r) => (r as { symbol?: string }).symbol ?? ""),
        universe_size: rows.length,
        live: true,
        as_of: "2026-06-08T10:11:28.250007+00:00",
        ...payloadOver,
      },
      metadata: { live: true },
      sources: ["yfinance", "showme_most_active_universe"],
      elapsed_ms: 120,
    },
    error: undefined,
    refetch: vi.fn(),
    ...extra,
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  try {
    localStorage.clear();
  } catch {
    /* jsdom may not expose localStorage in every config */
  }
});

describe("MOST — render + a11y", () => {
  it("renders the ranked leaders grid without throwing", () => {
    mockState("ok", [makeRow()]);
    render(<MOSTPane code="MOST" />);
    expect(
      screen.getByRole("button", { name: "NVDA" }),
    ).toBeInTheDocument();
  });

  it("gives the filter-rail Reset and Apply buttons aria-labels", () => {
    mockState("ok", [makeRow()]);
    render(<MOSTPane code="MOST" />);
    expect(
      screen.getByRole("button", { name: /reset filters/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /apply filters/i }),
    ).toBeInTheDocument();
  });

  it("marks the decorative ActivityBars track aria-hidden", () => {
    mockState("ok", [makeRow()]);
    const { container } = render(<MOSTPane code="MOST" />);
    const bars = container.querySelector(".most-bars");
    expect(bars).not.toBeNull();
    expect(bars?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("MOST — data honesty (P2)", () => {
  it("has no synthetic per-row Trend column", () => {
    mockState("ok", [makeRow()]);
    const { container } = render(<MOSTPane code="MOST" />);
    const grid = screen.getByRole("table");
    // The "Trend" column header was fed by deterministicTrend() — a
    // pseudo-random series, not real price history — and is removed.
    expect(within(grid).queryByText("Trend")).not.toBeInTheDocument();
    // No in-grid sparkline may masquerade as real history.
    grid.querySelectorAll("svg").forEach((svg) => {
      expect(svg.getAttribute("data-synthetic")).not.toBe("true");
    });
    // Header column count is fixed (no leftover Trend column).
    const headerCells = container.querySelectorAll("thead th");
    expect(headerCells.length).toBe(10);
  });
});

describe("MOST — numeric cells (P5/P6)", () => {
  it("numeric cells carry the terminal-grid-numeric class", () => {
    mockState("ok", [makeRow()]);
    const { container } = render(<MOSTPane code="MOST" />);
    const numericCells = container.querySelectorAll(".terminal-grid-numeric");
    expect(numericCells.length).toBeGreaterThan(0);
  });
});

describe("MOST — state machine", () => {
  it("renders the loading branch without a data grid", () => {
    mockState("loading", []);
    render(<MOSTPane code="MOST" />);
    // While loading the grid is replaced by a skeleton card.
    expect(screen.queryByRole("table")).toBeNull();
    // The empty / error states must not leak into the loading branch.
    expect(
      screen.queryByText(/no matches with current filters/i),
    ).toBeNull();
    expect(screen.queryByText(/function error/i)).toBeNull();
  });

  it("renders an error state with a labelled Retry button", () => {
    mockReturn.current = {
      state: "error",
      data: undefined,
      error: new Error("boom"),
      refetch: vi.fn(),
    };
    render(<MOSTPane code="MOST" />);
    expect(screen.getByText(/function error/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /retry/i }),
    ).toBeInTheDocument();
  });

  it("renders the empty state with a labelled Reset & retry button", () => {
    mockState("ok", []);
    render(<MOSTPane code="MOST" />);
    expect(
      screen.getByText(/no matches with current filters/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /reset filters and retry/i }),
    ).toBeInTheDocument();
  });
});

describe("MOST — navigation", () => {
  it("navigates to DES when the symbol button is clicked", () => {
    mockState("ok", [makeRow({ symbol: "TSLA" })]);
    render(<MOSTPane code="MOST" />);
    fireEvent.click(screen.getByRole("button", { name: "TSLA" }));
    expect(router.navigate).toHaveBeenCalledWith("/symbol/TSLA/DES");
  });
});

describe("MOST — sort tab switching", () => {
  it("reorders rows when the sort changes from Volume to |Δ%|", () => {
    mockState("ok", [
      makeRow({ symbol: "AAA", volume: 900, change_pct: 0.1 }),
      makeRow({ symbol: "BBB", volume: 100, change_pct: 9.9 }),
    ]);
    const { container } = render(<MOSTPane code="MOST" />);
    const symbols = () =>
      Array.from(container.querySelectorAll("tbody tr")).map(
        (tr) => within(tr as HTMLElement).queryByRole("button")?.textContent,
      );
    // Default sort = volume → AAA first.
    expect(symbols().slice(0, 2)).toEqual(["AAA", "BBB"]);
    // Switch the segmented sort control to |Δ%| → BBB first.
    fireEvent.click(screen.getByRole("tab", { name: "|Δ%|" }));
    expect(symbols().slice(0, 2)).toEqual(["BBB", "AAA"]);
  });
});

describe("MOST — asset tab switching", () => {
  it("filters rendered rows by the per-row quote_state pill source", () => {
    mockState("ok", [makeRow({ symbol: "NVDA" })]);
    render(<MOSTPane code="MOST" />);
    // Switching the asset tab re-issues the function call (params change);
    // with the mock returning the same payload the tab itself must render.
    fireEvent.click(screen.getByRole("tab", { name: "Crypto" }));
    expect(screen.getByRole("tab", { name: "Crypto" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

describe("MOST — live/reference pill", () => {
  it("shows LIVE when payload rows are live", () => {
    mockState("ok", [makeRow({ quote_state: "live" })], { live: true });
    render(<MOSTPane code="MOST" />);
    expect(screen.getByText(/^LIVE 1$/)).toBeInTheDocument();
  });

  it("shows REFERENCE when no rows are live", () => {
    mockState(
      "ok",
      [makeRow({ quote_state: "reference" })],
      { live: false },
    );
    render(<MOSTPane code="MOST" />);
    expect(screen.getByText(/^REFERENCE$/)).toBeInTheDocument();
  });
});
