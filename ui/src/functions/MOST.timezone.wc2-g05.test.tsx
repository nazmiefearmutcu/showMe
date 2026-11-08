/**
 * WC2-G05 / UI-14: MOST's as-of time follows the app timezone setting in 24-hour
 * form, not the system zone in en-US 12-hour form.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { MOSTPane } from "./MOST";

const TZ_KEY = "showme.timezone.v1";

function mockState(asOf: string) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: {
        status: "ok",
        rows: [
          {
            symbol: "NVDA",
            name: "NVIDIA",
            asset_class: "equity",
            exchange: "NASDAQ",
            last: 198.45,
            volume: 1000,
            dollar_volume: 198450,
            change_pct: 2.1,
            quote_state: "live",
          },
        ],
        universe: ["NVDA"],
        universe_size: 1,
        live: true,
        as_of: asOf,
      },
      metadata: { live: true },
      sources: ["yfinance"],
      elapsed_ms: 120,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  try {
    localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe("MOST as-of timezone (UI-14)", () => {
  it("formats the as-of time in the manual app timezone, 24-hour", () => {
    localStorage.setItem(
      TZ_KEY,
      JSON.stringify({ mode: "manual", manualTz: "America/New_York" }),
    );
    // 12:00 UTC on 2026-11-08 is 07:00 in New York (EST, UTC-5).
    mockState("2026-11-08T12:00:00Z");

    render(<MOSTPane code="MOST" />);

    expect(screen.getByText(/AS OF 07:00:00/)).toBeTruthy();
    expect(screen.queryByText(/AM|PM/)).toBeNull();
  });
});
