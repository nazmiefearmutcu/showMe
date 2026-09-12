/**
 * MOSS pane — data-honesty + render-contract tests.
 *
 * Follows the FORM4/GEX mock pattern: `useFunction` is mocked via a mutable
 * shared state so each test drives the pane into a specific branch without
 * the real sidecar transport.
 *
 * Pins:
 *  - the load states (loading / empty-provider / error / ok) render;
 *  - a live payload shows the live pill, the ranked leaderboard rows, the
 *    top-symbol sparkline and the TOP-N cap note;
 *  - SORT chips actually reorder rows (vol vs samples);
 *  - a provider_unavailable payload surfaces the upstream reason, never a
 *    fabricated ranking.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MOSSPane } from "./MOSS";
import * as router from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch,
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function row(over: Record<string, unknown>) {
  return {
    symbol: "X",
    asset_class: "CRYPTO",
    vol_annualized: 0.5,
    vol: 0.5,
    vol_pct: 50,
    samples: 100,
    last_close: 10,
    start: "2026-06-10",
    end: "2026-09-07",
    ...over,
  };
}

function livePayload() {
  return {
    data: {
      sources: ["yfinance"],
      elapsed_ms: 123.4,
      data: {
        status: "ok",
        live: true,
        rows: [
          row({ symbol: "HIGHVOL", vol_pct: 61.2, samples: 90, last_close: 10 }),
          row({ symbol: "MANYPTS", vol_pct: 47.5, samples: 119, last_close: 2515.35 }),
        ],
        history: [
          { date: "2026-09-05", symbol: "HIGHVOL", vol: 0.6, vol_pct: 60, window: 20 },
          { date: "2026-09-06", symbol: "HIGHVOL", vol: 0.61, vol_pct: 61, window: 20 },
          { date: "2026-09-07", symbol: "HIGHVOL", vol: 0.612, vol_pct: 61.2, window: 20 },
        ],
        universe: ["HIGHVOL", "MANYPTS"],
        lookback_days: 90,
        top_symbol: "HIGHVOL",
        methodology: "std(daily returns) * sqrt(252)",
      },
    },
  };
}

function cappedPayload() {
  const payload = livePayload();
  const rows = Array.from({ length: 12 }, (_, i) =>
    row({ symbol: `SYM${i}`, vol_pct: 50 - i, samples: 100 - i, last_close: 10 + i }),
  );
  (
    payload.data.data as { rows: unknown[]; universe: unknown[]; top_symbol: string }
  ).rows = rows;
  return payload;
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("MOSS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<MOSSPane code="MOSS" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
      refetch,
    });
    render(<MOSSPane code="MOSS" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("surfaces the provider reason when the provider is unavailable", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          live: false,
          rows: [],
          history: [],
          reason: "yfinance provider is unavailable",
        },
      },
    });
    render(<MOSSPane code="MOSS" />);
    expect(
      screen.getByText(/No volatility rows returned/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/yfinance provider is unavailable/i),
    ).toBeInTheDocument();
    // No rows are fabricated while degraded.
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("MOSS pane — live payload", () => {
  it("renders the live pill, ranked rows and the top-symbol sparkline", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<MOSSPane code="MOSS" />);
    expect(screen.getByText("live")).toBeInTheDocument();
    // HIGHVOL appears in the table row, the history card and the subtitle.
    expect(screen.getAllByText("HIGHVOL").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("MANYPTS")).toBeInTheDocument();
    // Vol formatted from the payload (one decimal + %), not invented.
    expect(screen.getByText("61.2%")).toBeInTheDocument();
    expect(screen.getByText("47.5%")).toBeInTheDocument();
    // Top-symbol sparkline present with an honest label.
    expect(
      screen.getByRole("img", { name: /Rolling volatility history for HIGHVOL/i }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("tbody tr").length).toBe(2);
  });

  it("caps rows at TOP-N with a showing note", () => {
    setMockFn({ state: "ok", ...cappedPayload() });
    const { container } = render(<MOSSPane code="MOSS" />);
    expect(container.querySelectorAll("tbody tr").length).toBe(10);
    expect(screen.getByText(/Showing 10 of 12 rows \(TOP cap\)/i)).toBeInTheDocument();
  });

  it("reorders rows when a column header is clicked", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<MOSSPane code="MOSS" />);
    // Default sort = vol descending: HIGHVOL (61.2%) ranks first.
    const firstRow = () =>
      container.querySelector("tbody tr")?.textContent ?? "";
    expect(firstRow()).toContain("HIGHVOL");
    fireEvent.click(screen.getByRole("columnheader", { name: /Samples/i }));
    // New key → descending: MANYPTS (119 samples) ranks first.
    expect(firstRow()).toContain("MANYPTS");
    // A second click flips to ascending: HIGHVOL (90 samples) first again.
    fireEvent.click(screen.getByRole("columnheader", { name: /Samples/i }));
    expect(firstRow()).toContain("HIGHVOL");
  });

  it("navigates to DES when a symbol cell is activated", async () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<MOSSPane code="MOSS" />);
    const nav = vi.spyOn(router, "navigate").mockImplementation(() => undefined);
    fireEvent.click(screen.getByLabelText("Open DES for HIGHVOL"));
    expect(nav).toHaveBeenCalledWith("/symbol/HIGHVOL/DES");
    nav.mockRestore();
  });

  it("DES launcher focuses the security, not just the route (B2)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<MOSSPane code="MOSS" />);
    const nav = vi.spyOn(router, "navigate").mockImplementation(() => undefined);
    const button = screen.getByRole("button", { name: "Open DES for HIGHVOL" });
    expect(button.tagName).toBe("BUTTON");
    fireEvent.click(button);
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
    if (tree.kind === "leaf") {
      expect(tree.code).toBe("DES");
      expect(tree.symbol).toBe("HIGHVOL");
    }
    nav.mockRestore();
  });
});

describe("MOSS pane — controls", () => {
  it("switches the TOP-N cap on click", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<MOSSPane code="MOSS" />);
    const top20 = screen.getByRole("button", { name: "20" });
    expect(top20).not.toBeDisabled();
    fireEvent.click(top20);
    // The newly selected option becomes the active (disabled) one.
    expect(screen.getByRole("button", { name: "20" })).toBeDisabled();
  });
});

describe("MOSS pane — empty symbol (R1-2)", () => {
  it("renders a non-focusable dash instead of a 'No symbol' dead button", () => {
    const payload = livePayload();
    const inner = payload.data.data as { rows: unknown[]; top_symbol: string };
    inner.rows = [row({ symbol: undefined })];
    inner.top_symbol = "";
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<MOSSPane code="MOSS" />);

    expect(screen.queryByRole("button", { name: /No symbol/i })).toBeNull();
    const rowEl = container.querySelector("tbody tr");
    expect(rowEl?.textContent).toContain("—");
    expect(rowEl?.querySelector("button")).toBeNull();
  });
});
