/**
 * DDIS pane — load-state + honesty tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton, error, and ok branches render;
 *  - a live SEC ladder renders bucket rows + % share bars;
 *  - an EMPTY schedule (the shipped no-data contract: status "empty",
 *    rows [], reason + next_actions) surfaces the backend's reason and
 *    next actions — no illustrative ladder is ever fabricated;
 *  - interaction: the refresh button triggers a refetch.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DDISPane } from "./DDIS";

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

/* ── fixtures (shape mirrors a live /api/fn/DDIS probe) ────────────── */

const secRows = [
  { bucket: "0-1Y", tenor_years: 0.5, amount_usd_bn: 12.393, currency: "USD", pct: 13.6 },
  { bucket: "1-3Y", tenor_years: 2.0, amount_usd_bn: 19.378, currency: "USD", pct: 21.2 },
  { bucket: "3-5Y", tenor_years: 4.0, amount_usd_bn: 10.207, currency: "USD", pct: 11.2 },
  { bucket: "5Y+", tenor_years: 7.0, amount_usd_bn: 49.303, currency: "USD", pct: 54.0 },
];

function secPayload() {
  return {
    status: "ok",
    rows: secRows,
    summary: {
      issuer: "AAPL",
      cik: "0000320193",
      total_debt_usd_bn: 91.281,
      currency: "USD",
      source_mode: "sec_edgar",
    },
  };
}

function emptySchedulePayload() {
  return {
    status: "empty",
    rows: [],
    summary: {
      issuer: "US10Y",
      total_debt_usd_bn: 0.0,
      currency: "USD",
      source_mode: "no_live_source",
    },
    reason:
      "Sovereign/unspecified issuer: SEC corporate maturity schedule does not apply; no debt ladder is shown.",
    next_actions: [
      "Pass an explicit ``maturities`` schedule for this issuer.",
      "Pick a tickerable US corporate issuer to read the SEC EDGAR maturity ladder.",
    ],
  };
}

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("DDIS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<DDISPane code="DDIS" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", error: new Error("sidecar exploded") });
    render(<DDISPane code="DDIS" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state without fabricating a ladder", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "provider_unavailable", rows: [], summary: {} } },
    });
    render(<DDISPane code="DDIS" symbol="AAPL" />);
    expect(screen.getByText(/No maturity ladder/i)).toBeInTheDocument();
    expect(screen.queryByText(/0-1Y/)).toBeNull();
  });
});

describe("DDIS pane — live ladder", () => {
  it("renders bucket rows, notionals and issuer headline when ok", () => {
    setMockFn({ state: "ok", data: { data: secPayload() } });
    const { container } = render(<DDISPane code="DDIS" symbol="AAPL" />);
    // Every bucket renders (5Y+ also appears as the largest-wall card).
    for (const bucket of ["0-1Y", "1-3Y", "3-5Y"]) {
      expect(screen.getByText(bucket)).toBeInTheDocument();
    }
    expect(screen.getAllByText("5Y+").length).toBeGreaterThanOrEqual(2);
    // Issuer headline: total + CIK (card formats 91.281 -> $91.28bn).
    expect(container.textContent).toContain("$91.28bn");
    expect(container.textContent).toContain("CIK 0000320193");
    // Largest wall = 5Y+ at 54.0%.
    expect(container.textContent).toContain("54.0%");
    // Live SEC pill (not the illustrative one).
    expect(screen.getByText(/SEC live/i)).toBeInTheDocument();
    expect(screen.queryByText(/Illustrative model/i)).toBeNull();
  });

  it("gives each share bar a descriptive aria-label", () => {
    setMockFn({ state: "ok", data: { data: secPayload() } });
    const { container } = render(<DDISPane code="DDIS" symbol="AAPL" />);
    const bars = Array.from(container.querySelectorAll('[aria-label*="share"]'));
    expect(bars.length).toBe(4);
    const wall = bars.find((b) => (b.getAttribute("aria-label") ?? "").includes("54.0"));
    expect(wall).toBeTruthy();
  });
});

describe("DDIS pane — empty-schedule honesty", () => {
  it("surfaces the backend reason + next actions and never fabricates a ladder", () => {
    setMockFn({ state: "ok", data: { data: emptySchedulePayload() } });
    const { container } = render(<DDISPane code="DDIS" symbol="AAPL" />);
    expect(screen.getByText(/No maturity ladder/i)).toBeInTheDocument();
    expect(
      screen.getByText(/SEC corporate maturity schedule does not apply/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Pass an explicit/i),
    ).toBeInTheDocument();
    // No illustrative badge vocabulary, no fabricated bucket row.
    expect(container.textContent).not.toMatch(/illustrative/i);
    expect(container.textContent).not.toMatch(/0-1Y/);
    expect(screen.queryByText(/SEC live/i)).toBeNull();
  });
});

describe("DDIS pane — interaction", () => {
  it("triggers a refetch when the refresh button is clicked", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", data: { data: secPayload() }, refetch });
    render(<DDISPane code="DDIS" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: /Refresh maturity ladder/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe("DDIS pane — ladder sort + keyboard (lane B4)", () => {
  it("pins nearest-tenor-first and enables keyboard grid navigation", () => {
    // Reverse the ladder so only the built-in sorter can restore 0-1Y first.
    setMockFn({
      state: "ok",
      data: { data: { ...secPayload(), rows: [...secRows].reverse() } },
    });
    const { container } = render(<DDISPane code="DDIS" symbol="AAPL" />);

    const grid = screen.getByRole("grid", { name: "DDIS maturity ladder" });
    expect(grid).toBeInTheDocument();
    // Roving keyboard cell: the first cell owns the tab stop.
    expect(
      grid.querySelector('td[data-cell="0-0"]')?.getAttribute("tabindex"),
    ).toBe("0");

    // tenor_years ascending -> 0-1Y first, 5Y+ last.
    const rowsBefore = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsBefore[0]?.textContent).toContain("0-1Y");
    expect(rowsBefore.at(-1)?.textContent).toContain("5Y+");

    // Activating the sort cycles asc -> desc: 5Y+ leads.
    fireEvent.click(container.querySelector('th[aria-sort="ascending"]')!);
    const rowsAfter = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsAfter[0]?.textContent).toContain("5Y+");
  });
});
