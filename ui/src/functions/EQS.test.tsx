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

describe("EQS pane — query editor a11y (C9)", () => {
  it("gives the DSL query editor an English accessible name", () => {
    render(<EQSPane code="EQS" />);
    // C9 A11Y-1: the query textarea carried zero naming attributes; the
    // accessible name now mirrors the visible "DSL query" field label with
    // the pane code for screen-reader context. (Not "natural-language":
    // the EQS editor takes the screener's DSL, not free text.)
    const editor = screen.getByRole("textbox", { name: "EQS DSL query" });
    expect(editor.tagName).toBe("TEXTAREA");
    expect(editor).toHaveValue('sector = "Technology" AND marketCap > 50000000000');
  });
});

describe("EQS pane — result honesty (F6)", () => {
  it("renders a true empty state on zero matches (no fabricated head(3) rows)", async () => {
    runFunctionMock.mockResolvedValue({
      code: "EQS",
      data: { status: "no_matches", rows: [], query: 'symbol = "ZZZZ"', matched: 0, scanned: 5 },
      metadata: { matched: 0, scanned: 5 },
      sources: ["equity_screener_model"],
      elapsed_ms: 3,
    });
    const { container } = render(<EQSPane code="EQS" />);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));

    expect(
      await screen.findByText(/No matches with current filters/i),
    ).toBeInTheDocument();
    // The MATCHED pill tells the truth and no result table is rendered.
    expect(screen.getByText(/MATCHED 0 \/ 5/i)).toBeInTheDocument();
    expect(container.querySelector("table")).toBeNull();
  });

  it("surfaces dsl_parse_error with the parser message verbatim", async () => {
    runFunctionMock.mockResolvedValue({
      code: "EQS",
      data: {
        rows: [],
        status: "dsl_parse_error",
        error: "Invalid query segment at position 0: expected 'field operator value'",
        query: "?? broken",
        matched: 0,
        scanned: 5,
      },
      metadata: { matched: 0, scanned: 5 },
      sources: [],
      elapsed_ms: 2,
    });
    render(<EQSPane code="EQS" />);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));

    expect(await screen.findByText(/DSL parse error/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Invalid query segment at position 0/i),
    ).toBeInTheDocument();
  });

  it("renders the backend's real universe label, not the requested one", async () => {
    runFunctionMock.mockResolvedValue({
      ...okResult(),
      metadata: {
        matched: 2,
        scanned: 15,
        universe: "MEGA15 (stub for SP500/NDX/DOW until constituents bundle)",
        universe_size: 15,
      },
    });
    render(<EQSPane code="EQS" />);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));

    expect(
      await screen.findAllByText(/MEGA15 \(stub for SP500\/NDX\/DOW/i),
    ).not.toHaveLength(0);
  });

  it("shows a live-screen-unavailable empty state with the backend reason", async () => {
    runFunctionMock.mockResolvedValue({
      code: "EQS",
      data: {
        status: "provider_unavailable",
        rows: [],
        query: "marketCap > 0",
        matched: 0,
        scanned: 3,
        reason:
          "Live screen produced no symbol rows; the template stub is not substituted on the live path.",
      },
      metadata: { matched: 0, scanned: 3, fallback: true, live: false },
      sources: [],
      elapsed_ms: 4,
    });
    render(<EQSPane code="EQS" />);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));

    expect(
      await screen.findByText(/Live screen unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/template stub is not substituted/i),
    ).toBeInTheDocument();
  });

  it("marks model-template rows with a visible model notice", async () => {
    runFunctionMock.mockResolvedValue({
      ...okResult(),
      metadata: { matched: 2, scanned: 5, template: true, live: false },
    });
    render(<EQSPane code="EQS" />);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));

    expect(await screen.findByTestId("eqs-model-notice")).toHaveTextContent(
      /model template/i,
    );
  });
});
