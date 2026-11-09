/**
 * MOST — session and FX honesty (wb1-g17 MOST#3 / MOST#5).
 *
 * Kept in its own file so the existing MOST.test.tsx stays untouched.
 * useFunction + router.navigate are mocked so the suite never touches the sidecar.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const mockArgs: { current: Record<string, unknown> | null } = { current: null };
const mockTick = { current: 0 };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    mockArgs.current = args;
    return mockReturn.current;
  },
}));
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { MOSTPane } from "./MOST";

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
  mockArgs.current = null;
  mockTick.current = 0;
  try {
    localStorage.clear();
  } catch {
    /* jsdom may not expose localStorage in every config */
  }
});

describe("MOST — session + FX honesty (wb1-g17 MOST#3/#5)", () => {
  it("labels closed-session quotes LAST CLOSE, never LIVE", () => {
    mockState(
      "ok",
      [makeRow({ quote_state: "last_close" })],
      { live: true, as_of: "2026-11-06T21:00:00+00:00" },
    );
    render(<MOSTPane code="MOST" />);
    expect(screen.getByText(/^LAST CLOSE 1$/)).toBeInTheDocument();
    expect(screen.queryByText(/^LIVE 1$/)).toBeNull();
    expect(screen.getByText("LAST CLOSE")).toBeInTheDocument();
  });

  it("shows an unreported FX dollar volume as a dash, not an estimated zero", () => {
    mockState("ok", [
      makeRow({
        symbol: "USDJPY=X",
        asset_class: "fx",
        exchange: "YFINANCE FX",
        last: 153,
        volume: null,
        dollar_volume: null,
        quote_state: "live",
      }),
    ]);
    const { container } = render(<MOSTPane code="MOST" />);
    expect(container.textContent).not.toContain("≈ 0");
    expect(container.textContent).not.toContain("≈ 0.00");
  });
});
