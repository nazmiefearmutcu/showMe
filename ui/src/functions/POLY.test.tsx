/**
 * POLY pane — honesty states + poll contract tests.
 *
 * Pins the fixes from the 2026-09-11 audit:
 *  - the keyless Gamma live path (`delayed_reference`) is recognized as the
 *    live label it is (no dead `dataMode === "live"` branch, no "fallback
 *    mode" banner over real Gamma rows);
 *  - a network outage (`status=provider_unavailable`) shows the backend
 *    reason and NEVER the old (false) keyring-credential story — the path
 *    is keyless;
 *  - the visibility tick stays OUT of the fetch params (GLCO pattern) while
 *    still triggering a refetch.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { POLYPane } from "./POLY";

/* ── mocks ─────────────────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number; warnings?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

const { useFunctionSpy, refetchSpy } = vi.hoisted(() => ({
  useFunctionSpy: vi.fn(),
  refetchSpy: vi.fn(),
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    useFunctionSpy(args);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchSpy,
    };
  },
}));

let visibilityTick = 0;
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => visibilityTick,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function delayedLivePayload() {
  return {
    state: "ok" as const,
    data: {
      status: "ok",
      sources: ["polymarket"],
      elapsed_ms: 312,
      data: {
        status: "ok",
        data_mode: "delayed_reference",
        as_of: "2026-09-11T12:00:00Z",
        rows: [
          {
            market_id: "fed-cut",
            question: "Will the Fed cut rates in 2026?",
            outcome: "Yes",
            price: 0.62,
            implied_prob: 62,
            liquidity_usd: 50_000,
            end_date: "2099-01-01T00:00:00Z",
          },
          {
            market_id: "fed-cut",
            question: "Will the Fed cut rates in 2026?",
            outcome: "No",
            price: 0.38,
            implied_prob: 38,
            liquidity_usd: 50_000,
            end_date: "2099-01-01T00:00:00Z",
          },
        ],
      },
    },
  };
}

function outagePayload() {
  return {
    state: "ok" as const,
    data: {
      status: "provider_unavailable",
      sources: ["polymarket"],
      elapsed_ms: 8002,
      warnings: ["Polymarket Gamma feed unavailable; showing no markets rather than fabricated odds."],
      data: {
        status: "provider_unavailable",
        data_mode: "not_configured",
        reason:
          "Prediction market feed unavailable for election: ConnectionError gamma-api.polymarket.com",
        rows: [],
        warnings: [
          "Polymarket Gamma feed unavailable; showing no markets rather than fabricated odds.",
        ],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  visibilityTick = 0;
  useFunctionSpy.mockClear();
  refetchSpy.mockClear();
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
});

describe("POLY pane — keyless Gamma honesty", () => {
  it("labels delayed_reference as the live path and shows no fallback banner", () => {
    setMockFn(delayedLivePayload());
    render(<POLYPane code="POLY" />);
    expect(screen.getByText("delayed reference")).toBeInTheDocument();
    expect(
      screen.queryByText(/Provider returned a labelled fallback mode/i),
    ).toBeNull();
    expect(screen.queryByText(/keyring/i)).toBeNull();
  });

  it("outage shows the backend reason and NEVER the keyring-credential story", () => {
    setMockFn(outagePayload());
    render(<POLYPane code="POLY" />);
    expect(
      screen.getByText(/^Prediction market feed unavailable$/),
    ).toBeInTheDocument();
    expect(screen.getByText(/ConnectionError gamma-api\.polymarket\.com/)).toBeInTheDocument();
    expect(screen.queryByText(/keyring/i)).toBeNull();
    expect(screen.queryByText(/credential/i)).toBeNull();
  });
});

describe("POLY pane — poll contract", () => {
  it("keeps the visibility tick OUT of the fetch params", () => {
    setMockFn(delayedLivePayload());
    render(<POLYPane code="POLY" />);
    const last = useFunctionSpy.mock.calls.at(-1)?.[0] as {
      params?: Record<string, unknown>;
    };
    expect(last?.params).toEqual({ status: "open", min_liquidity_usd: 10_000 });
    expect(last?.params).not.toHaveProperty("tick");
  });

  it("refetches when the visibility tick advances", () => {
    visibilityTick = 3;
    setMockFn(delayedLivePayload());
    render(<POLYPane code="POLY" />);
    expect(refetchSpy).toHaveBeenCalled();
  });
});
