/**
 * DES smoke test — Agent J test-coverage initiative.
 *
 * Catches import/render regressions in `<DESPane/>`. Doesn't try to
 * assert feature behaviour (other DES.*.test.tsx files do that). The
 * single contract this file pins: mounting the component with a
 * symbol does not crash, and the symbol shows up somewhere.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DESPane } from "./DES";

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "idle",
    data: undefined,
    error: undefined,
    refetch: vi.fn(),
  }),
}));

// The engine fetches /api/bars and paints a canvas — stub it out.
vi.mock("@/chart/Chart", () => ({
  Chart: () => <div data-testid="chart-engine" />,
}));

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => ({
      transportState: "idle",
      lastTick: null,
      lastTickAt: null,
      snapshot: null,
      freshnessMs: null,
      stale: false,
      refreshing: false,
    }),
  };
});

afterEach(() => cleanup());

describe("DES smoke", () => {
  it("mounts with a symbol and renders without throwing", () => {
    render(<DESPane code="DES" symbol="AAPL" />);
    // SymbolBar surfaces the symbol; multiple matches OK.
    expect(screen.getAllByText(/AAPL/i).length).toBeGreaterThanOrEqual(1);
  });
});
