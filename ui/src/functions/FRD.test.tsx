/**
 * FRD pane — render-contract + data-honesty tests.
 *
 * The backend FRD builds a covered-interest-parity forward grid from a
 * live yfinance spot (or, on failure, a labelled reference spot). These
 * tests pin:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - tenor rows render forward, F−S and annualized carry correctly;
 *  - the pair control changes the fetch param and persists it;
 *  - an explicit FX-pair symbol overrides the stored pair;
 *  - the spot-overlay SVG is present with an accessible label;
 *  - reference_model payloads show the degraded banner + muted pills,
 *    live payloads advertise the live spot.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) plus a
 * `lastParams` capture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FRDPane } from "./FRD";
import { downloadGridCsv } from "@/design-system/grid-csv";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    elapsed_ms?: number;
    warnings?: string[];
  };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

let lastParams: Record<string, unknown> | undefined;
let lastSymbol: string | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: {
    code: string;
    symbol?: string;
    params?: Record<string, unknown>;
  }) => {
    lastParams = args.params;
    lastSymbol = args.symbol;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

// Keep the real CSV builder, but capture the download call so the export
// payload can be asserted (jsdom has no Blob download).
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

/* ── fixtures: live-probed EURUSD CIP grid ─────────────────────────── */

function frdRow(overrides: Record<string, unknown>) {
  return {
    pair: "EURUSD",
    spot: 1.1624,
    base_rate: 0.035,
    quote_rate: 0.045,
    source_mode: "live_yfinance_quote",
    ...overrides,
  };
}

const LIVE_ROWS = [
  frdRow({ tenor: "1W", tenor_years: 0.019178, forward: 1.162626, forward_points: 0.000226 }),
  frdRow({ tenor: "1M", tenor_years: 0.083333, forward: 1.163379, forward_points: 0.000979 }),
  frdRow({ tenor: "3M", tenor_years: 0.25, forward: 1.165319, forward_points: 0.002919 }),
  frdRow({ tenor: "6M", tenor_years: 0.5, forward: 1.168191, forward_points: 0.005791 }),
  frdRow({ tenor: "1Y", tenor_years: 1, forward: 1.173792, forward_points: 0.011392 }),
];

function payload(sourceMode: string) {
  return {
    data: {
      data: {
        pair: "EURUSD",
        base: "EUR",
        quote: "USD",
        S: 1.1624,
        F: 1.165319,
        r_base: 0.035,
        r_quote: 0.045,
        rows: LIVE_ROWS.map((r) => ({ ...r, source_mode: sourceMode })),
        methodology: "Covered interest parity.",
      },
      sources: ["yfinance", "covered_interest_parity_formula"],
      elapsed_ms: 210,
      warnings:
        sourceMode === "live_yfinance_quote"
          ? []
          : ["live spot unavailable; using labelled reference spot"],
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
  (downloadGridCsv as ReturnType<typeof vi.fn>).mockClear();
});
afterEach(() => {
  cleanup();
});

describe("FRD pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FRDPane code="FRD" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FRDPane code="FRD" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no tenors come back", () => {
    setMockFn({
      state: "ok",
      data: { data: { pair: "EURUSD", rows: [] } },
    });
    render(<FRDPane code="FRD" />);
    expect(screen.getByText(/No forward tenors returned/i)).toBeInTheDocument();
  });
});

describe("FRD pane — forward grid", () => {
  it("renders the tenor ladder with forward, F−S and carry", () => {
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    const { container } = render(<FRDPane code="FRD" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(5);
    const first = rows[0].textContent ?? "";
    expect(first).toContain("1W");
    // Spot column: 1.1624 at FX precision.
    expect(first).toContain("1.16240");
    // Forward column: 1.162626 at FX precision.
    expect(first).toContain("1.16263");
    // F−S: signed rate difference.
    expect(first).toContain("+0.000226");
    // Annualized carry for 1W: ((1.162626/1.1624−1)/0.019178)·100 ≈ +1.01%.
    expect(first).toContain("+1.01%");
  });

  it("renders the forward-curve SVG with a spot overlay and accessible label", () => {
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    const { container } = render(<FRDPane code="FRD" />);
    const fig = container.querySelector('figure[role="img"]');
    expect(fig?.getAttribute("aria-label")).toMatch(/forward curve/i);
    expect(fig?.querySelector("polyline")).not.toBeNull();
    // Dashed spot overlay line.
    expect(fig?.querySelector("line")).not.toBeNull();
  });

  it("shows the KPI ribbon with spot and 1Y F−S", () => {
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    render(<FRDPane code="FRD" />);
    expect(screen.getByText("Spot EURUSD")).toBeInTheDocument();
    expect(screen.getByText("1Y F − S")).toBeInTheDocument();
  });
});

describe("FRD pane — pair control", () => {
  it("sends the persisted pair by default", () => {
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    render(<FRDPane code="FRD" />);
    expect(lastParams?.pair).toBe("EURUSD");
    expect(lastSymbol).toBe("EURUSD");
  });

  it("switches pair on click and persists the choice", () => {
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    render(<FRDPane code="FRD" />);
    fireEvent.click(screen.getByText("USDJPY"));
    expect(lastParams?.pair).toBe("USDJPY");
    expect(localStorage.getItem("showme.frd.pair")).toBe("USDJPY");
  });

  it("lets an explicit FX-pair symbol override the stored pair", () => {
    localStorage.setItem("showme.frd.pair", "USDJPY");
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    render(<FRDPane code="FRD" symbol="GBPUSD" />);
    expect(lastParams?.pair).toBe("GBPUSD");
  });

  it("ignores non-pair symbols and keeps the stored pair", () => {
    localStorage.setItem("showme.frd.pair", "EURGBP");
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    render(<FRDPane code="FRD" symbol="SPY" />);
    expect(lastParams?.pair).toBe("EURGBP");
  });
});

describe("FRD pane — data honesty", () => {
  it("advertises the live spot for live payloads", () => {
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    render(<FRDPane code="FRD" />);
    expect(screen.getByText("live spot")).toBeInTheDocument();
    expect(screen.queryByText(/reference spot unavailable/i)).toBeNull();
  });

  it("shows the degraded banner + muted pills for reference-model payloads", () => {
    setMockFn({ state: "ok", ...payload("reference_model") });
    const { container } = render(<FRDPane code="FRD" />);
    expect(
      screen.getByText(/live spot unavailable/i),
    ).toBeInTheDocument();
    expect(screen.getByText("reference spot")).toBeInTheDocument();
    expect(screen.queryByText("live spot")).toBeNull();
    // Row source pills are rendered as muted "reference_model".
    expect(
      Array.from(container.querySelectorAll("tbody tr")).every((tr) =>
        (tr.textContent ?? "").includes("reference_model"),
      ),
    ).toBe(true);
  });
});

describe("FRD pane — grid CSV export", () => {
  it("exports the raw CIP tenor grid via the CSV button", () => {
    setMockFn({ state: "ok", ...payload("live_yfinance_quote") });
    render(<FRDPane code="FRD" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^frd-EURUSD-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(csv).toContain(
      "Tenor,Years,Spot,Forward,Forward points,Ann. carry %,Base rate,Quote rate,Source",
    );
    expect(csv).toContain(
      "1W,0.019178,1.1624,1.162626,0.000226,",
    );
    // The carry cell is a raw NUMBER, not the formatted "+1.01%" string.
    const firstRow = csv.split("\n")[1];
    expect(firstRow).toContain(",0.035,0.045,live_yfinance_quote");
    expect(firstRow).not.toContain("%");
  });

  it("disables the CSV button when no tenors come back", () => {
    setMockFn({
      state: "ok",
      data: { data: { pair: "EURUSD", rows: [] } },
    });
    render(<FRDPane code="FRD" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
