/**
 * EQS pane — dividend yield unit (UI-6).
 *
 * `dividend_yield` is a decimal fraction per the backend contract (unit
 * "ratio"), so 0.0123 must render as 1.23%, never as a bare decimal or 0.01%.
 * Kept in its own file so the existing EQS.test.tsx stays untouched.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runFunctionMock = vi.fn();
vi.mock("@/lib/functions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/functions")>();
  return {
    ...actual,
    runFunction: (...args: unknown[]) => runFunctionMock(...args),
  };
});
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { EQSPane } from "./EQS";

beforeEach(() => {
  localStorage.clear();
  runFunctionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("EQS pane — dividend yield unit (UI-6)", () => {
  it("renders the decimal dividend_yield as a percent, not a bare decimal", async () => {
    runFunctionMock.mockResolvedValue({
      code: "EQS",
      data: {
        rows: [{ symbol: "AAA", sector: "Utilities", dividend_yield: 0.0123, change_pct: 1.5 }],
      },
      metadata: { matched: 1, scanned: 1 },
      sources: ["yfinance"],
      elapsed_ms: 5,
    });
    render(<EQSPane code="EQS" />);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));

    expect(await screen.findByText("1.23%")).toBeInTheDocument();
    expect(screen.queryByText("0.01")).toBeNull();
    expect(screen.queryByText("0.01%")).toBeNull();
    expect(screen.getByText("dividend_yield (%)")).toBeInTheDocument();
  });
});
