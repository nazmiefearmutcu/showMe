/**
 * FRD pane — rate-source honesty and units (FRD#1 / FRD#4 pane side).
 *
 *  - the rate-diff card says where each policy rate came from (live FRED
 *    series with its name, or a labelled 2024-06 reference constant);
 *  - a `provider_unavailable` payload shows an explicit state with the
 *    backend reason instead of an empty "no tenors" grid;
 *  - the pips column renders forward_points_pips;
 *  - a missing rate is shown as an em dash, not a zero rate differential.
 *
 * `useFunction` is mocked with a mutable shared state, as in FRD.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FRDPane } from "./FRD";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

function row(overrides: Record<string, unknown>) {
  return {
    pair: "EURUSD",
    tenor: "3M",
    tenor_years: 0.25,
    spot: 1.1624,
    forward: 1.165319,
    forward_points: 0.002919,
    forward_points_pips: 29.19,
    base_rate: 0.025,
    quote_rate: 0.0388,
    source_mode: "live_yfinance_quote",
    ...overrides,
  };
}

function okPayload(overrides: Record<string, unknown> = {}, rowOverrides: Record<string, unknown> = {}) {
  const data: Record<string, unknown> = {
    pair: "EURUSD",
    base: "EUR",
    quote: "USD",
    S: 1.1624,
    F: 1.165319,
    r_base: 0.025,
    r_quote: 0.0388,
    rate_sources: { base: "fred:ECBDFR", quote: "fred:DFF" },
    rows: [row(rowOverrides)],
    methodology: "Covered interest parity.",
    ...overrides,
  };
  return { data: { data, sources: ["yfinance"], warnings: [], elapsed_ms: 1 } };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

function rateDiffText(container: HTMLElement): string {
  const text = container.textContent ?? "";
  const idx = text.indexOf("Rate diff");
  expect(idx, "Rate diff card not rendered").toBeGreaterThanOrEqual(0);
  return text.slice(idx, idx + 120);
}

describe("FRD pane — rate-source honesty (FRD#1)", () => {
  it("names the live FRED series behind each policy rate", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload()?.data as MockFnState["data"];
    const { container } = render(<FRDPane code="FRD" />);
    const card = rateDiffText(container);
    expect(card).toContain("ECBDFR");
    expect(card).toContain("DFF");
    expect(card).not.toContain("REF 2024-06");
  });

  it("labels a reference-constant rate as a 2024-06 reference, not live", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload({
      r_base: 0.035,
      r_quote: 0.045,
      rate_sources: {
        base: "reference_policy_rate_constant",
        quote: "reference_policy_rate_constant",
      },
    })?.data as MockFnState["data"];
    const { container } = render(<FRDPane code="FRD" />);
    const card = rateDiffText(container);
    expect(card).toContain("REF 2024-06");
    expect(card).not.toContain("ECBDFR");
  });

  it("shows an em dash, not a zero differential, when a rate is missing", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload({ r_base: undefined, r_quote: 0.0388 })?.data as MockFnState["data"];
    const { container } = render(<FRDPane code="FRD" />);
    expect(rateDiffText(container)).toMatch(/^Rate diff—/);
  });
});

describe("FRD pane — provider_unavailable is an explicit state (FRD#1)", () => {
  it("shows the backend reason instead of an empty tenor grid", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "provider_unavailable",
        reason: "a currency leg has no live policy rate and no labelled reference rate",
        pair: "XYZUSD",
        rows: [],
      },
      sources: [],
      warnings: ["XYZ policy rate unavailable"],
    } as MockFnState["data"];
    render(<FRDPane code="FRD" />);
    expect(screen.getByText(/Forward not computed/i)).toBeInTheDocument();
    expect(screen.getByText(/no labelled reference rate/i)).toBeInTheDocument();
    expect(screen.queryByText(/No forward tenors returned/i)).toBeNull();
  });
});

describe("FRD pane — pips column (FRD#4 pane side)", () => {
  it("renders forward_points_pips with a pips header", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload()?.data as MockFnState["data"];
    const { container } = render(<FRDPane code="FRD" />);
    expect(container.textContent).toContain("F − S (pips)");
    const first = container.querySelector("tbody tr")?.textContent ?? "";
    expect(first).toContain("+29.19");
  });
});
