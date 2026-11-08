/**
 * PORTX MGN cash input (MGN#5).
 *
 * The MGN pane has a Cash and a Cash account control. Only what the user types is sent:
 * a blank keeps the backend's recorded or PORT cash.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  mockArgs.current = null;
});

describe("PORTX MGN cash input (MGN#5)", () => {
  it("sends the stated cash and its account, and nothing while blank", () => {
    mockReturn.current = {
      state: "ok",
      data: { data: { status: "ok", rows: [] }, metadata: { live: true }, sources: ["margin_engine"], warnings: [] },
    };
    render(<PortfolioAnalyticsPane code="MGN" symbol="" />);
    expect(mockArgs.current?.params).toEqual({});
    fireEvent.change(screen.getByLabelText("Cash"), { target: { value: "2500" } });
    fireEvent.change(screen.getByLabelText("Cash account"), { target: { value: "a" } });
    expect(mockArgs.current?.params).toEqual({ cash: 2500, account: "a" });
  });
});
