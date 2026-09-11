/**
 * DCFS pane — render-contract + honesty tests.
 *
 * Pins:
 *  - loading / error / ok render paths;
 *  - the WACC × g heatmap renders one gridcell per (wacc, g) pair, tinted
 *    positive/negative versus the live spot (token-name assertion on the
 *    inline style, not a resolved color);
 *  - the ±20% tornado list renders spreads and shows invalid perturbation
 *    rows with their reason (never as a fabricated 0 spread);
 *  - status "needs_input" (no base fair value) renders an explicit empty
 *    state — no fabricated grid;
 *  - the persisted overrides re-issue the function call: years segmented
 *    control always present in params, wacc/fcfe only when > 0.
 *
 * `useFunction` is mocked with a mutable shared state + an args recorder;
 * the live quote is mocked to a fixed spot of 250.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DCFSPane } from "./DCFS";
import { downloadGridCsv } from "@/design-system/grid-csv";

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

// Keep the real CSV builder, but capture the download call so the export
// payload can be asserted (jsdom has no Blob download).
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

/* ── fixtures ──────────────────────────────────────────────────────── */

function gridCell(wacc: number, g: number, fv: number | null) {
  return {
    wacc,
    g_terminal: g,
    fair_value_per_share: fv,
    bucket: `WACC ${wacc} / g ${g}`,
  };
}

function okPayload() {
  return {
    data: {
      status: "ok",
      base_fair_value: 230,
      wacc_range: [0.08, 0.1],
      g_range: [0.02, 0.03],
      grid: [
        gridCell(0.08, 0.02, 300), // above spot 250 -> positive tint
        gridCell(0.08, 0.03, 260), // above spot -> positive tint
        gridCell(0.1, 0.02, 180), // below spot -> negative tint
        gridCell(0.1, 0.03, 150), // below spot -> negative tint
      ],
      tornado: [
        { input: "fcfe", low_value: 80, high_value: 120, low_fv: 200, high_fv: 300, value: 100, delta: 100 },
        { input: "wacc", low_value: 0.08, high_value: 0.12, low_fv: 280, high_fv: 240, value: 40, delta: -40 },
        {
          input: "g_terminal",
          low_value: 0.02,
          high_value: 0.03,
          low_fv: null,
          high_fv: null,
          value: null,
          delta: null,
          status: "invalid_perturbation",
          reason: "One side of the ±20% perturbation produced no fair value (e.g. WACC fell below terminal growth).",
        },
      ],
    },
    warnings: [],
    sources: ["yfinance"],
    elapsed_ms: 42,
  };
}

beforeEach(() => {
  lastArgs.length = 0;
  refetchMock.mockClear();
  (downloadGridCsv as ReturnType<typeof vi.fn>).mockClear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  localStorage.clear();
});
afterEach(() => {
  cleanup();
});

/* ── tests ─────────────────────────────────────────────────────────── */

describe("DCFS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    mockFn.state = "loading";
    const { container } = render(<DCFSPane code="DCFS" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    mockFn.state = "error";
    mockFn.error = new Error("sidecar exploded");
    render(<DCFSPane code="DCFS" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an explicit empty state when the base fair value is missing", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: { status: "needs_input", base_fair_value: null, grid: [], tornado: [] },
      warnings: [],
    };
    render(<DCFSPane code="DCFS" symbol="AAPL" />);
    expect(screen.getByText("Needs provider input")).toBeInTheDocument();
    // No fabricated numbers: no heatmap cells at all.
    expect(
      screen.queryByRole("grid", { name: /fair value heatmap/i }),
    ).toBeNull();
  });
});

describe("DCFS pane — ok payload", () => {
  it("renders the base fair-value headline and the full WACC x g grid", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<DCFSPane code="DCFS" symbol="AAPL" />);
    expect(container.textContent).toContain("$230.00");
    // 2 wacc rows x 2 g cols.
    const cells = container.querySelectorAll('[role="gridcell"]');
    expect(cells.length).toBe(4);
  });

  it("tints grid cells positive/negative versus the live spot", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<DCFSPane code="DCFS" symbol="AAPL" />);
    const cells = Array.from(
      container.querySelectorAll<HTMLElement>('[role="gridcell"]'),
    );
    const above = cells.filter((c) => (c.getAttribute("aria-label") ?? "").includes("above spot"));
    const below = cells.filter((c) => (c.getAttribute("aria-label") ?? "").includes("below spot"));
    expect(above.length).toBe(2);
    expect(below.length).toBe(2);
    for (const cell of above) {
      expect(cell.style.background).toContain("var(--positive-soft-hex)");
    }
    for (const cell of below) {
      expect(cell.style.background).toContain("var(--negative-soft-hex)");
    }
  });

  it("renders tornado spreads and shows the invalid perturbation reason", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<DCFSPane code="DCFS" symbol="AAPL" />);
    // fcfe spread |300 - 200| = $100.00.
    expect(screen.getByText("$100.00")).toBeInTheDocument();
    // wacc spread |240 - 280| = $40.00.
    expect(screen.getByText("$40.00")).toBeInTheDocument();
    // The invalid row surfaces its reason instead of a 0 spread.
    expect(
      screen.getByText(/invalid — one side of the ±20% perturbation/i),
    ).toBeInTheDocument();
  });
});

describe("DCFS pane — persisted overrides", () => {
  it("re-issues the call when the years control changes", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<DCFSPane code="DCFS" symbol="AAPL" />);
    fireEvent.click(screen.getByTitle("YRS 7y"));
    expect(lastCall()?.params?.years).toBe(7);
  });

  it("sends wacc/fcfe overrides only when > 0", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<DCFSPane code="DCFS" symbol="AAPL" />);
    // Fresh localStorage: no overrides -> params carry no wacc/fcfe keys.
    expect(lastCall()?.params?.wacc).toBeUndefined();
    expect(lastCall()?.params?.fcfe).toBeUndefined();
    const waccInput = screen.getByLabelText("WACC override");
    fireEvent.change(waccInput, { target: { value: "0.09" } });
    fireEvent.blur(waccInput);
    expect(lastCall()?.params?.wacc).toBe(0.09);
    const fcfeInput = screen.getByLabelText("FCFE override");
    fireEvent.change(fcfeInput, { target: { value: "100" } });
    fireEvent.blur(fcfeInput);
    expect(lastCall()?.params?.fcfe).toBe(100);
    expect(lastCall()?.symbol).toBe("AAPL");
  });
});

describe("DCFS pane — grid CSV export (audit A3 OPP)", () => {
  it("exports the raw sensitivity grid via the toolbar CSV button", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<DCFSPane code="DCFS" symbol="AAPL" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^dcfs-AAPL-\d{4}-\d{2}-\d{2}\.csv$/);
    // Header row + RAW payload numbers (not formatted currency strings).
    expect(csv).toContain(
      "WACC,Terminal growth,Fair value / share,Equity value,Bucket",
    );
    expect(csv).toContain("0.08,0.02,300");
    expect(csv).toContain("0.1,0.03,150");
  });

  it("disables the CSV button when the payload carries no grid", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: { status: "needs_input", base_fair_value: null, grid: [], tornado: [] },
      warnings: [],
    };
    render(<DCFSPane code="DCFS" symbol="AAPL" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
