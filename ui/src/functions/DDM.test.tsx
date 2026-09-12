/**
 * DDM pane — render-contract + honesty tests.
 *
 * Pins:
 *  - loading / error / ok render paths;
 *  - the fair-value headline and the 3x3 sensitivity surface with the
 *    current-assumption cell highlighted;
 *  - the r/g number inputs re-issue the function call with updated params
 *    (persisted assumption controls);
 *  - the backend r <= g error envelope renders as a validation state, not
 *    as a fabricated number;
 *  - a zero TTM dividend hides premium/discount and shows the honest
 *    "no dividend" note instead of a fake -100%.
 *
 * `useFunction` is mocked with a mutable shared state + an args recorder so
 * the interaction test can assert on the params the pane re-issues.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DDMPane } from "./DDM";

/* ── mocks ─────────────────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchMock = vi.fn();

interface RecordedArgs {
  code: string;
  symbol?: string;
  params?: Record<string, unknown>;
}

const lastArgs: RecordedArgs[] = [];

function lastCall(): RecordedArgs | undefined {
  return lastArgs[lastArgs.length - 1];
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: RecordedArgs) => {
    lastArgs.push(args);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

vi.mock("@/lib/market-data", () => ({
  useLiveQuote: () => ({
    price: 250,
    transportState: "ok",
    stale: false,
    loading: false,
  }),
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function surfaceCell(r: number, g: number, value: number | null) {
  return {
    required_return: r,
    growth: g,
    value,
    bucket: `r ${r} / g ${g}`,
  };
}

function okPayload() {
  return {
    data: {
      status: "ok",
      dividend_ttm: 1.0,
      next_dividend: 1.03,
      growth: 0.03,
      required_return: 0.09,
      fair_value_per_share: 17.17,
      rows: [
        { metric: "Dividend TTM", value: 1.0, formula: "D0" },
        { metric: "Fair value/share", value: 17.17, formula: "P = D1 / (r - g)" },
      ],
      surface: [
        surfaceCell(0.07, 0.02, 13.93),
        surfaceCell(0.07, 0.03, 17.17),
        surfaceCell(0.07, 0.04, 21.63),
        surfaceCell(0.09, 0.02, 14.71),
        surfaceCell(0.09, 0.03, 17.17),
        surfaceCell(0.09, 0.04, 21.46),
        surfaceCell(0.11, 0.02, 11.44),
        surfaceCell(0.11, 0.03, 12.71),
        surfaceCell(0.11, 0.04, 14.71),
      ],
    },
    warnings: [],
    sources: ["yfinance"],
    elapsed_ms: 12,
  };
}

beforeEach(() => {
  lastArgs.length = 0;
  refetchMock.mockClear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  localStorage.clear();
});
afterEach(() => {
  cleanup();
});

/* ── tests ─────────────────────────────────────────────────────────── */

describe("DDM pane — load states", () => {
  it("renders a skeleton while loading", () => {
    mockFn.state = "loading";
    const { container } = render(<DDMPane code="DDM" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    mockFn.state = "error";
    mockFn.error = new Error("sidecar exploded");
    render(<DDMPane code="DDM" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the r <= g validation envelope as a state, not a number", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: { error: "r must be > g for Gordon model", d0: 1, g: 0.09, r: 0.03 },
    };
    render(<DDMPane code="DDM" symbol="AAPL" />);
    expect(screen.getByText(/must be > g/i)).toBeInTheDocument();
    expect(screen.getByText("Model not applicable")).toBeInTheDocument();
  });
});

describe("DDM pane — ok payload", () => {
  it("renders the fair-value headline and the 3x3 surface", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<DDMPane code="DDM" symbol="AAPL" />);
    expect(container.textContent).toContain("$17.17");
    // 9 surface cells + 4 header cells (corner + 3 growth headers).
    const cells = container.querySelectorAll('[role="gridcell"]');
    expect(cells.length).toBe(9);
    // The current-assumption cell is highlighted and labelled.
    const centered = Array.from(cells).filter((c) =>
      (c.getAttribute("aria-label") ?? "").includes("current assumptions"),
    );
    expect(centered.length).toBe(1);
  });

  it("shows the live premium vs the mocked quote price", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<DDMPane code="DDM" symbol="AAPL" />);
    // (17.17 - 250) / 250 = -93.13%
    expect(screen.getByText("-93.13%")).toBeInTheDocument();
  });
});

describe("DDM pane — assumption controls", () => {
  it("re-issues the call with the committed r value", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<DDMPane code="DDM" symbol="AAPL" />);
    const rInput = screen.getByLabelText("Required return");
    fireEvent.change(rInput, { target: { value: "0.12" } });
    fireEvent.blur(rInput);
    const call = lastCall();
    expect(call?.params?.required_return).toBe(0.12);
    expect(call?.params?.growth_rate).toBe(0.03);
  });

  it("clamps out-of-range growth before committing", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<DDMPane code="DDM" symbol="AAPL" />);
    const gInput = screen.getByLabelText("Dividend growth rate");
    fireEvent.change(gInput, { target: { value: "5" } });
    fireEvent.blur(gInput);
    // max for g is 0.99
    expect(lastCall()?.params?.growth_rate).toBe(0.99);
  });

  it("commits the clamped minimum on an empty draft", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<DDMPane code="DDM" symbol="AAPL" />);
    const rInput = screen.getByLabelText("Required return") as HTMLInputElement;
    fireEvent.change(rInput, { target: { value: "" } });
    fireEvent.blur(rInput);
    // Number("") is 0 -> below min 0.001 -> clamped to min, committed.
    expect(lastCall()?.params?.required_return).toBe(0.001);
  });
});

describe("DDM pane — data honesty", () => {
  it("hides premium and shows the no-dividend note when TTM dividend is 0", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "ok",
        dividend_ttm: 0,
        next_dividend: 0,
        growth: 0.03,
        required_return: 0.09,
        fair_value_per_share: 0,
        rows: [],
        surface: okPayload().data.surface,
      },
      warnings: [
        "dividend_ttm: provider returned 0 or no dividend; DDM is not applicable for non-dividend payers.",
      ],
    };
    render(<DDMPane code="DDM" symbol="AAPL" />);
    expect(screen.getByText(/^no dividend$/i)).toBeInTheDocument();
    expect(
      screen.getByText(/not applicable for non-dividend payers/i),
    ).toBeInTheDocument();
    // Premium card never shows the fabricated -100.00% that 0-vs-price
    // arithmetic would produce.
    expect(screen.queryByText("-100.00%")).toBeNull();
  });
});

describe("DDM pane — step grid sort + keyboard (lane B4)", () => {
  it("defaults to value-descending (output first) with keyboard navigation", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<DDMPane code="DDM" symbol="AAPL" />);

    const grid = screen.getByRole("grid", { name: "DDM model steps" });
    expect(grid).toBeInTheDocument();
    // Roving keyboard cell: the first cell owns the tab stop.
    expect(
      grid.querySelector('td[data-cell="0-0"]')?.getAttribute("tabindex"),
    ).toBe("0");

    // Fixture: Dividend TTM 1.0 then Fair value/share 17.17 — value desc
    // lifts the model output to the top row.
    const rowsBefore = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsBefore[0]?.textContent).toContain("Fair value/share");

    // Activating the sort cycles desc -> none: backend step order returns.
    fireEvent.click(container.querySelector('th[aria-sort="descending"]')!);
    const rowsAfter = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsAfter[0]?.textContent).toContain("Dividend TTM");
  });
});
