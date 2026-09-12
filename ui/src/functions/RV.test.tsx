/**
 * RV pane — comp-table + data-honesty tests.
 *
 * The backend RV returns target+peer multiples from yfinance refdata with a
 * PE rank/percentile; when the provider is down it returns a single null
 * provider_unavailable row. These tests pin:
 *
 *  - the load states (loading / provider-unavailable) render honestly;
 *  - an OK payload renders peer rows plus a client-side computed median row;
 *  - per-metric best-value tint marks the cheapest P/E peer;
 *  - refresh interaction triggers a refetch.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { RVPane } from "./RV";
import * as router from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
  refetch?: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  mockFn.refetch = next.refetch ?? vi.fn();
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch ?? vi.fn(),
  }),
}));

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function okRow(symbol: string, pe: number, isTarget: boolean) {
  return {
    symbol,
    marketCap: 2_500_000_000_000,
    pe,
    fwd_pe: pe * 0.9,
    pb: 40,
    ps: 8,
    ev_ebitda: 22,
    roe: 1.5,
    roa: 0.28,
    debt_equity: 145,
    div_yield: 0.005,
    rank_pe: isTarget ? 2 : 1,
    percentile_pe: isTarget ? 50 : 0,
    is_target: isTarget,
    source_mode: "live_yfinance",
  };
}

function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: [okRow("AAPL", 30.5, true), okRow("MSFT", 25.0, false), okRow("GOOGL", 40.2, false)],
        peers: ["MSFT", "GOOGL"],
        methodology: "RV compares the target against a peer set.",
      },
    },
  };
}

function providerDownPayload() {
  return {
    data: {
      data: {
        status: "provider_unavailable",
        rows: [
          {
            symbol: "AAPL",
            marketCap: null,
            pe: null,
            fwd_pe: null,
            pb: null,
            ps: null,
            ev_ebitda: null,
            roe: null,
            roa: null,
            debt_equity: null,
            div_yield: null,
            status: "provider_unavailable",
            source_mode: "provider_unavailable",
            is_target: true,
          },
        ],
        peers: ["MSFT", "GOOGL", "NVDA"],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("RV pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<RVPane code="RV" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<RVPane code="RV" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an honest provider-unavailable state listing the resolved peers", () => {
    setMockFn({ state: "ok", ...providerDownPayload() });
    render(<RVPane code="RV" symbol="AAPL" />);
    expect(screen.getByText(/Provider unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/MSFT, GOOGL, NVDA/)).toBeInTheDocument();
  });
});

describe("RV pane — comp table", () => {
  it("renders peer rows plus the computed median row", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<RVPane code="RV" symbol="AAPL" />);
    expect(container.textContent).toContain("Median (peer set, computed)");
    // Median P/E of [25.0, 30.5, 40.2] = 30.50.
    expect(container.textContent).toContain("30.50");
  });

  it("tints the cheapest P/E as the best value in the peer set", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<RVPane code="RV" symbol="AAPL" />);
    const bestCells = Array.from(container.querySelectorAll(".rv-best"));
    expect(bestCells.length).toBeGreaterThan(0);
    // MSFT P/E 25.00 is the lowest multiple in the set.
    const peBest = bestCells.find((cell) => cell.textContent === "25.00");
    expect(peBest).toBeDefined();
    expect(peBest?.getAttribute("title")).toMatch(/lowest/i);
  });
});

describe("RV pane — interaction", () => {
  it("triggers a refetch when the refresh button is clicked", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...okPayload(), refetch });
    render(<RVPane code="RV" symbol="AAPL" />);
    fireEvent.click(screen.getByTitle(/Refresh comp table/i));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe("RV pane — DES cross-link (B2)", () => {
  it("renders each peer ticker as a button named 'Open DES for <sym>'", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<RVPane code="RV" symbol="AAPL" />);
    const btn = screen.getByRole("button", { name: "Open DES for MSFT" });
    expect(btn.tagName).toBe("BUTTON");
    expect(btn.textContent).toBe("MSFT");
    // The computed median row is not a security — it must stay plain text.
    expect(screen.queryByRole("button", { name: /Median/ })).toBeNull();
  });

  it("R2: the peer link carries the u-symbol-link class with no inline color override", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<RVPane code="RV" symbol="AAPL" />);
    const btn = screen.getByRole("button", { name: "Open DES for MSFT" });
    expect(btn.classList.contains("u-symbol-link")).toBe(true);
    expect((btn as HTMLElement).style.color).toBe("");
  });

  it("clicking a peer ticker focuses DES and routes to /symbol/MSFT/DES", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const nav = vi.spyOn(router, "navigate").mockImplementation(() => undefined);
    render(<RVPane code="RV" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "Open DES for MSFT" }));
    expect(nav).toHaveBeenCalledWith("/symbol/MSFT/DES");
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
    if (tree.kind === "leaf") {
      expect(tree.code).toBe("DES");
      expect(tree.symbol).toBe("MSFT");
    }
    nav.mockRestore();
  });
});
