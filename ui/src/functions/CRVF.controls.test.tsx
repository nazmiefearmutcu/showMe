/**
 * CRVF#5 follow-up: the pane exposes the country and live-curve inputs the
 * backend declares (crvf_seed.py), not only the tenor chips.
 *
 * Defaults send no params (the backend serves US live). A non-US country is
 * requested explicitly and shows the backend's honest unavailable state; the
 * live switch sends live_curve=false and labels the model curve.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CRVFPane } from "./CRVF";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number; warnings?: string[] };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
let lastParams: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    lastParams = args.params;
    return { state: mockFn.state, data: mockFn.data, error: mockFn.error ?? null, refetch: vi.fn() };
  },
}));

beforeEach(() => {
  mockFn.state = "idle";
  mockFn.data = undefined;
  lastParams = undefined;
});

afterEach(() => {
  cleanup();
});

describe("CRVF pane — country and live controls", () => {
  it("offers the backend's country list", () => {
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    const select = screen.getByRole("combobox", { name: "Country" }) as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["US", "DE", "JP", "GB", "FR", "IT", "ES", "AU", "CA", "TR"]);
  });

  it("requests the chosen non-US country and shows the honest unavailable state", () => {
    render(<CRVFPane code="CRVF" symbol="DE10Y" />);
    fireEvent.change(screen.getByRole("combobox", { name: "Country" }), { target: { value: "DE" } });
    expect(lastParams).toEqual({ country: "DE" });
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "provider_unavailable",
        reason: "No curve is wired for DE.",
        rows: [],
        curve: [],
        summary: { country: "DE", tenors: 0, source_mode: "provider_unavailable" },
      },
      sources: [],
    };
    cleanup();
    render(<CRVFPane code="CRVF" symbol="DE10Y" />);
    expect(screen.getByText(/Curve unavailable — DE/)).toBeInTheDocument();
  });

  it("turns the live FRED switch off and sends live_curve=false", () => {
    render(<CRVFPane code="CRVF" symbol="US10Y" />);
    const live = screen.getByRole("button", { name: "Live FRED" });
    expect(live).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(live);
    expect(lastParams).toEqual({ live_curve: false });
    expect(screen.getByRole("button", { name: "Live FRED" })).toHaveAttribute("aria-pressed", "false");
  });
});
