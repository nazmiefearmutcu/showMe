/**
 * PORT_OPT — the LIVE/MODEL toggle must describe what MODEL really does (wc3-g06).
 *
 * MODEL no longer optimises on labelled template returns: with LIVE off the
 * backend returns status needs_input and no weights. The toggle therefore must
 * not promise "template returns"; its title says that no weights are computed.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioOptimizerPane } from "./PortfolioOptimizer";

function ok(payload: Record<string, unknown>) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "PORT_OPT",
      instrument: null,
      data: payload,
      metadata: { mode: "all" },
      fetched_at: "2026-11-08T00:00:00Z",
      sources: [],
      warnings: [],
      elapsed_ms: 12,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

describe("PORT_OPT LIVE/MODEL toggle (wc3-g06)", () => {
  it("MODEL title says no weights are computed and never mentions template returns", () => {
    ok({
      status: "needs_input",
      reason: "PORT_OPT optimises on live yfinance daily returns, and LIVE is off, so no weights were computed.",
      symbols: ["SPY", "QQQ"],
      next_actions: ["Turn LIVE on to optimise on yfinance daily closes for the universe."],
    });
    render(<PortfolioOptimizerPane code="PORT_OPT" />);
    const liveToggle = screen.getByRole("button", { name: "LIVE" });
    expect(liveToggle.getAttribute("title") ?? "").not.toMatch(/template/i);

    fireEvent.click(liveToggle);
    const modelToggle = screen.getByRole("button", { name: "MODEL" });
    const title = modelToggle.getAttribute("title") ?? "";
    expect(title).not.toMatch(/template/i);
    expect(title).toMatch(/no weights/i);
  });
});
