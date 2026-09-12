/**
 * ICX pane — data-honesty + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) so
 * each test drives the pane into a specific branch without the real
 * sidecar transport. Pins:
 *
 *  - the load states (loading / empty / error / ok) render;
 *  - the ok state renders constituents + the count note;
 *  - the pane is index-CODE addressed: a symbol prop that maps to a
 *    supported code wins, otherwise the persisted selector is used;
 *  - quote honesty: rows without a provider quote show the missing
 *    dash and the note says quotes are unavailable (never fabricated);
 *  - the change-sort is a real interaction (DOM order changes) and the
 *    Chg% cells carry tint-bar tracks;
 *  - an unknown index code payload renders the supported-codes hint.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ICXPane } from "./ICX";
import * as router from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const mockTick = { current: 0 };
const refetchMock = vi.fn();
let lastFnArgs: Record<string, unknown> | undefined;

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload() {
  return {
    data: {
      sources: ["showme_index_reference", "yfinance"],
      elapsed_ms: 1900,
      data: {
        status: "ok",
        index: "SPX",
        constituents: 3,
        rows: [
          {
            symbol: "NVDA",
            company: "NVIDIA Corporation",
            index: "SPX",
            last: 230.36,
            change_pct: 5.89,
          },
          {
            symbol: "AMZN",
            company: "Amazon.com, Inc.",
            index: "SPX",
            last: 258.51,
            change_pct: -2.97,
          },
          {
            symbol: "AAPL",
            company: "Apple Inc.",
            index: "SPX",
            last: null,
            change_pct: null,
          },
        ],
        methodology: "curated members + best-effort quotes",
        summary: { index: "SPX", constituent_count: 3 },
      },
    },
  };
}

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
  mockTick.current = 0;
  lastFnArgs = undefined;
  refetchMock.mockReset();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("ICX pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<ICXPane code="ICX" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<ICXPane code="ICX" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the unknown-index state with the supported codes hint", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          index: "BOGUS",
          constituents: 0,
          rows: [],
          note: "Unknown index code: BOGUS",
          available_indexes: ["BIST", "CAC", "DAX", "DJIA", "FTSE"],
          next_actions: ["Pick a supported index code."],
        },
      },
    });
    render(<ICXPane code="ICX" />);
    expect(screen.getAllByText(/Unknown index code/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Supported codes:/i)).toBeInTheDocument();
  });

  it("renders constituents + count note when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ICXPane code="ICX" />);
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA Corporation")).toBeInTheDocument();
    expect(screen.getAllByText(/3 constituents/i).length).toBeGreaterThan(0);
  });
});

describe("ICX pane — index code addressing", () => {
  it("uses the symbol prop as the effective index when it maps to a code", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ICXPane code="ICX" symbol="NDX" />);
    // Footer echoes the effective index.
    expect(screen.getAllByText("NDX").length).toBeGreaterThan(0);
  });

  it("falls back to the persisted selector for a non-index symbol prop", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ICXPane code="ICX" symbol="AAPL" />);
    expect(screen.getAllByText("SPX").length).toBeGreaterThan(0);
  });

  it("switches the effective index when a selector chip is clicked", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ICXPane code="ICX" />);
    fireEvent.click(screen.getByTitle("Index DAX"));
    expect(screen.getAllByText("DAX").length).toBeGreaterThan(0);
  });
});

describe("ICX pane — quote honesty", () => {
  it("shows the missing-quote dash and the unavailable-quotes note", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ICXPane code="ICX" />);
    // The AAPL row has no provider quote — Last must be the dash.
    const aaplCell = screen.getByText("AAPL").closest("tr");
    expect(aaplCell?.textContent).toContain("—");
    expect(screen.getByText(/1 without live quote/i)).toBeInTheDocument();
  });
});

describe("ICX pane — quote snapshot refresh (audit A3 M)", () => {
  it("refetches on a visibility tick and keeps tick out of params", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { rerender } = render(<ICXPane code="ICX" />);
    expect(refetchMock).not.toHaveBeenCalled();
    const before = JSON.stringify(lastFnArgs?.params ?? null);
    expect(before).not.toContain("tick");

    mockTick.current = 1;
    rerender(<ICXPane code="ICX" />);
    expect(refetchMock).toHaveBeenCalledTimes(1);
    // A tick inside params would flip the fetch key and re-skeleton the pane.
    expect(JSON.stringify(lastFnArgs?.params ?? null)).toBe(before);
  });

  it("sinks no-quote rows below real decliners when sorting by change (audit A3 L)", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          index: "SPX",
          constituents: 2,
          rows: [
            { symbol: "DOWN", company: "Down Co", last: 10, change_pct: -8 },
            { symbol: "MISS", company: "Missing Co", last: null, change_pct: null },
          ],
        },
      },
    });
    const { container } = render(<ICXPane code="ICX" />);
    const symbols = Array.from(
      container.querySelectorAll("tbody tr td:first-child"),
    ).map((td) => td.textContent);
    expect(symbols).toEqual(["DOWN", "MISS"]);
  });
});

describe("ICX pane — sort + tint bars", () => {
  it("reorders rows by day change when the CHG% sort is active", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<ICXPane code="ICX" />);
    const symbols = () =>
      Array.from(
        container.querySelectorAll("tbody tr td:first-child"),
      ).map((td) => td.textContent);
    // Default CHG% sort: NVDA (+5.89) first, AAPL (null → 0) last.
    expect(symbols()[0]).toBe("NVDA");
    // A-Z sort: AAPL first.
    fireEvent.click(screen.getByTitle("Sort by ticker"));
    expect(symbols()[0]).toBe("AAPL");
  });

  it("renders a tint-bar track for every quoted Chg% cell", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<ICXPane code="ICX" />);
    const tracks = container.querySelectorAll("[data-testid^='chg-track-']");
    // NVDA + AMZN have quotes; AAPL's cell renders the dash instead.
    expect(tracks.length).toBe(2);
  });
});

describe("ICX pane — DES cross-link (B2)", () => {
  it("renders each member ticker as a button named 'Open DES for <sym>'", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ICXPane code="ICX" />);
    const btn = screen.getByRole("button", { name: "Open DES for NVDA" });
    expect(btn.tagName).toBe("BUTTON");
    expect(btn.textContent).toBe("NVDA");
  });

  it("R2: the symbol link carries the u-symbol-link class with no inline color override", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ICXPane code="ICX" />);
    const btn = screen.getByRole("button", { name: "Open DES for NVDA" });
    expect(btn.classList.contains("u-symbol-link")).toBe(true);
    // An inline color would defeat the class accent (and its hover state).
    expect((btn as HTMLElement).style.color).toBe("");
  });

  it("clicking a member ticker focuses DES and routes to /symbol/NVDA/DES", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const nav = vi.spyOn(router, "navigate").mockImplementation(() => undefined);
    render(<ICXPane code="ICX" />);
    fireEvent.click(screen.getByRole("button", { name: "Open DES for NVDA" }));
    expect(nav).toHaveBeenCalledWith("/symbol/NVDA/DES");
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
    if (tree.kind === "leaf") {
      expect(tree.code).toBe("DES");
      expect(tree.symbol).toBe("NVDA");
    }
    nav.mockRestore();
  });
});
