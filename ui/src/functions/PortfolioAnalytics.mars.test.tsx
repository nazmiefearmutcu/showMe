/**
 * PORTX — MARS live default (MARS#7). Kept in its own file so the original
 * PortfolioAnalytics.test.tsx stays untouched.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const mockArgs: {
  current: { code?: string; symbol?: string; params?: Record<string, unknown> } | null;
} = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    mockArgs.current = args as (typeof mockArgs)["current"];
    return mockReturn.current;
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioAnalyticsPane } from "./PortfolioAnalytics";

function mockOk(
  payload: Record<string, unknown>,
  envelope: {
    sources?: string[];
    warnings?: string[];
    metadata?: Record<string, unknown>;
  } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: payload,
      metadata: envelope.metadata ?? { live: true },
      sources: envelope.sources ?? ["showme engine"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 90,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  mockArgs.current = null;
});

const LIVE_ROWS = [
  { symbol: "SPY", weight_pct: 0.4, total_pnl: 1200, return: 0.08 },
  { symbol: "QQQ", weight_pct: 0.6, total_pnl: -800, return: -0.03 },
];

describe("PORTX MARS live default (MARS#7)", () => {
  it("shows no MODEL/LIVE toggle and sends no live key for MARS", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="MARS" symbol="" />);
    expect(screen.queryByRole("button", { name: "MODEL" })).toBeNull();
    expect(screen.queryByRole("button", { name: "LIVE" })).toBeNull();
    expect(mockArgs.current?.params).not.toHaveProperty("live");
  });
});
