/**
 * RPAR pane wiring (WC1-G19 RPAR#6).
 *
 * The Risk Parity pane must default to the equal-risk-contribution method so the
 * default view matches its title; inverse-vol stays available as the second mode.
 */
import { cleanup, render } from "@testing-library/react";
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

function mockOk(payload: Record<string, unknown>) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: payload,
      metadata: { live: true },
      sources: ["showme engine"],
      warnings: [],
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

describe("RPAR pane default method", () => {
  it("defaults RPAR to the equal-risk-contribution method, matching the Risk Parity title", () => {
    mockOk({ status: "ok", rows: [] });
    render(<PortfolioAnalyticsPane code="RPAR" symbol="" />);
    expect(mockArgs.current?.params?.method).toBe("erc");
  });
});
