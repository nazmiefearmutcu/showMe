/**
 * ALLQ pane — render-contract + data-honesty tests.
 *
 * The backend ALLQ builds an INDICATIVE composite ladder anchored to a
 * real reference price (Treasury FiscalData for sovereign aliases). These
 * tests pin:
 *
 *  - the load states (loading / error / ok) render;
 *  - provider_unavailable renders the honest empty state with the
 *    backend's next-action, never fabricated quotes;
 *  - best-bid / best-ask / inside-spread cards compute from the rows;
 *  - the dealer table shows the ladder with spread-bps tints;
 *  - the indicative honesty note is always present with the anchor;
 *  - the WIDTH control drives params.spread + persists under
 *    `showme.allq.spread`.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) with
 * lastParams capture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ALLQPane } from "./ALLQ";
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

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { code: string; symbol?: string; params?: Record<string, unknown> }) => {
    lastParams = args.params;
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

/* ── fixtures: mirror the FiscalData-anchored live probe shape ─────── */

const ROWS = [
  {
    bond: "US10Y",
    dealer: "Composite A",
    bid: 106.2081,
    ask: 106.3881,
    size: 1_000_000,
    quote_time: "2026-09-07T19:23:41+00:00",
    mid: 106.2981,
    spread_points: 0.18,
    spread_bps_of_price: 16.934,
    reference: "avg Treasury coupon 3.345% on 2026-08-31",
  },
  {
    bond: "US10Y",
    dealer: "Composite B",
    bid: 106.1721,
    ask: 106.4421,
    size: 750_000,
    quote_time: "2026-09-07T19:23:41+00:00",
    mid: 106.3071,
    spread_points: 0.27,
    spread_bps_of_price: 25.398,
    reference: "avg Treasury coupon 3.345% on 2026-08-31",
  },
  {
    bond: "US10Y",
    dealer: "Composite C",
    bid: 106.1181,
    ask: 106.4781,
    size: 500_000,
    quote_time: "2026-09-07T19:23:41+00:00",
    mid: 106.2981,
    spread_points: 0.36,
    spread_bps_of_price: 33.867,
    reference: "avg Treasury coupon 3.345% on 2026-08-31",
  },
];

function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: ROWS,
        spread_curve: ROWS.map((r) => ({
          dealer: r.dealer,
          spread_bps_of_price: r.spread_bps_of_price,
        })),
        summary: {
          bond: "US10Y",
          mid: 106.2981,
          best_bid: 106.2081,
          best_ask: 106.3881,
          reference: "avg Treasury coupon 3.345% on 2026-08-31",
          source_mode: "indicative_anchored_to_real_reference",
        },
        methodology: "ALLQ builds an INDICATIVE dealer-quote ladder.",
      },
      sources: ["treasury_fiscaldata"],
      elapsed_ms: 3200,
      warnings: [
        "ALLQ rows are INDICATIVE composite quotes anchored to a real reference price, not executable dealer prices.",
      ],
    },
  };
}

function unavailablePayload() {
  return {
    data: {
      data: {
        status: "provider_unavailable",
        rows: [],
        spread_curve: [],
        summary: { bond: "US10Y", source_mode: "treasury_fiscaldata" },
        next_actions: [
          "Retry when the reference price source is reachable, or pass an explicit ``mid``.",
        ],
      },
      sources: ["treasury_fiscaldata"],
      warnings: ["No live reference price for 'US10Y'."],
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

describe("ALLQ pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state on provider_unavailable (no fabricated quotes)", () => {
    setMockFn({ state: "ok", ...unavailablePayload() });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    expect(screen.getByText(/No dealer quotes/i)).toBeInTheDocument();
    expect(
      screen.getByText(/pass an explicit/i),
    ).toBeInTheDocument();
    // No dealer table exists in this state.
    expect(screen.queryByText(/Composite B/)).toBeNull();
  });
});

describe("ALLQ pane — top of book + table", () => {
  it("renders best bid / best ask / inside spread cards from the rows", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    // Best bid = Composite A 106.2081; best ask = Composite A 106.3881.
    expect(screen.getAllByText("106.2081").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("106.3881").length).toBeGreaterThanOrEqual(1);
    // Inside spread: 0.18 pts on ~106.30 mid ≈ 16.9 bps (same value also
    // shows on Composite A's table row, hence getAllByText).
    expect(screen.getAllByText("16.9").length).toBeGreaterThanOrEqual(1);
    // Composite A is best on BOTH sides → the caption appears twice.
    expect(screen.getAllByText(/DEALER Composite A/i).length).toBe(2);
  });

  it("renders the dealer ladder with all composites and quote times", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(3);
    expect(container.textContent).toContain("Composite B");
    expect(container.textContent).toContain("19:23:41Z");
    // Widest composite (C, 33.9 bps) is present.
    expect(container.textContent).toContain("33.9");
  });
});

describe("ALLQ pane — data honesty", () => {
  it("always shows the INDICATIVE note with the anchor reference", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    expect(screen.getByText(/Indicative quotes/i)).toBeInTheDocument();
    expect(
      screen.getByText(/NOT executable dealer prices/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/avg Treasury coupon 3.345%/)).toBeInTheDocument();
  });

  it("labels the pane indicative even when status is ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    expect(screen.getByText("indicative")).toBeInTheDocument();
  });
});

describe("ALLQ pane — width control", () => {
  it("sends the default 0.18 spread width", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    expect(lastParams).toMatchObject({ spread: 0.18 });
  });

  it("switches width via the segmented control and persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    fireEvent.click(screen.getByText("0.36"));
    expect(lastParams?.spread).toBe(0.36);
    expect(localStorage.getItem("showme.allq.spread")).toBe("36");
  });
});

describe("ALLQ pane — grid CSV export", () => {
  it("exports the raw dealer ladder via the toolbar CSV button", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^allq-US10Y-\d{4}-\d{2}-\d{2}\.csv$/);
    // Header row + RAW payload numbers (not formatted price strings).
    expect(csv).toContain(
      "Dealer,Bond,Bid,Ask,Mid,Spread bps,Size,Quote time,Reference",
    );
    expect(csv).toContain(
      "Composite A,US10Y,106.2081,106.3881,106.2981,16.934,1000000",
    );
  });

  it("disables the CSV button when the ladder is empty", () => {
    setMockFn({ state: "ok", ...unavailablePayload() });
    render(<ALLQPane code="ALLQ" symbol="US10Y" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
