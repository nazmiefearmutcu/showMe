/**
 * EQS pane — KPI sparkline honesty.
 *
 * The screener payload carries ranked rows only (no history series), so the
 * KPI strip sparklines are procedural. These tests pin the WEI honesty
 * contract: every procedural line is de-emphasized, tagged SYNTH, marked
 * data-synthetic="true" and carries the explanatory title. A fabricated
 * series must never render unlabeled.
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

function okResult() {
  return {
    code: "EQS",
    data: {
      rows: [
        { symbol: "AAPL", sector: "Technology", marketCap: 3_000_000_000_000, change_pct: 1.25 },
        { symbol: "MSFT", sector: "Technology", marketCap: 2_800_000_000_000, change_pct: 0.5 },
      ],
    },
    metadata: { matched: 2, scanned: 500 },
    sources: ["yfinance"],
    elapsed_ms: 42,
  };
}

beforeEach(() => {
  localStorage.clear();
  runFunctionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("EQS pane — KPI sparkline honesty", () => {
  it("labels every procedural KPI sparkline as synthetic (no unlabeled fake series)", async () => {
    runFunctionMock.mockResolvedValue(okResult());
    const { container } = render(<EQSPane code="EQS" />);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));

    // KPI strip renders four cards, each with a procedural sparkline.
    expect(await screen.findAllByText("SYNTH")).toHaveLength(4);
    const synthetic = container.querySelectorAll('[data-synthetic="true"]');
    expect(synthetic.length).toBe(4);
    synthetic.forEach((el) => {
      expect(el.getAttribute("title")).toBe(
        "Illustrative trend — no real history available",
      );
      expect(el.querySelector("svg")).not.toBeNull();
    });
    // No sparkline in the KPI strip is left unmarked.
    const kpiSvgs = container.querySelectorAll(".stat-card svg");
    expect(kpiSvgs.length).toBe(4);
    kpiSvgs.forEach((svg) => {
      expect(svg.closest("[data-synthetic]")).not.toBeNull();
    });
    // A visible note spells the same thing out in prose.
    expect(screen.getByTestId("eqs-kpi-synth-note")).toHaveTextContent(
      /illustrative/i,
    );
  });
});
