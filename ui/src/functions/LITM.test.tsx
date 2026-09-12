/**
 * LITM pane — honest-empty, matters table + item-filter interaction tests.
 *
 * The backend LITM filters recent SEC 8-K events to litigation/governance
 * items 1.03 / 1.04 / 3.03 / 5.02 / 5.03. The probe honestly returns
 * "empty" for most symbols (0 matches) with a sentinel
 * "no_litigation_event_found" row; the pane must show that as an explicit
 * no-matters state with the scan count, never as a fake legal case. These
 * tests pin:
 *
 *  - the load states (loading / error / honest empty / provider down);
 *  - an OK payload with real matters renders item + severity + source;
 *  - the ITEM chips filter the table to a single 8-K item code.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { LITMPane } from "./LITM";
import { downloadGridCsv } from "@/design-system/grid-csv";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

// Keep the real CSV builder, but capture the download call so the export
// payload can be asserted (jsdom has no Blob download).
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

/* ── fixtures ──────────────────────────────────────────────────────── */

function mattersPayload() {
  return {
    data: {
      sources: ["sec_edgar"],
      elapsed_ms: 31,
      data: {
        status: "ok",
        rows: [
          {
            symbol: "XYZ",
            event_type: "bankruptcy_or_receivership",
            item_code: "1.03",
            filing_date: "2026-08-14",
            severity: "review",
            source_mode: "sec_edgar_8k",
            accession: "0001193125-26-111111",
            document: "d8k.htm",
          },
          {
            symbol: "XYZ",
            event_type: "submission_of_matters_to_a_vote",
            item_code: "5.07",
            filing_date: "2026-06-30",
            severity: "none",
            source_mode: "sec_edgar_8k",
            accession: "0001193125-26-222222",
          },
          {
            symbol: "XYZ",
            event_type: "officer_departure",
            item_code: "5.02",
            filing_date: "2026-05-21",
            severity: "review",
            source_mode: "sec_edgar_8k",
            accession: "0001193125-26-333333",
          },
        ],
        litigation_filings: [],
        kept_item_codes: ["1.03", "1.04", "3.03", "5.02", "5.03"],
        all_8k_events: 12,
        methodology: "LITM filters recent SEC 8-K event rows.",
      },
    },
  };
}

function emptyPayload() {
  return {
    data: {
      sources: ["sec_edgar"],
      elapsed_ms: 12,
      data: {
        status: "empty",
        rows: [
          {
            symbol: "AAPL",
            event_type: "no_litigation_event_found",
            item_code: null,
            filing_date: null,
            severity: "none",
            source_mode: "sec_edgar_no_matching_8k_item",
            all_8k_events: 1,
          },
        ],
        litigation_filings: [],
        kept_item_codes: ["1.03", "1.04", "3.03", "5.02", "5.03"],
        all_8k_events: 1,
      },
    },
  };
}

function providerDownPayload() {
  return {
    data: {
      sources: ["litigation_monitor_model"],
      elapsed_ms: 3,
      data: {
        status: "provider_unavailable",
        rows: [
          {
            symbol: "AAPL",
            event_type: "provider_unavailable",
            item_code: null,
            filing_date: null,
            severity: "unknown",
            source_mode: "local_litigation_model",
          },
        ],
        all_8k_events: 0,
      },
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
  localStorage.clear();
});

describe("LITM pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<LITMPane code="LITM" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<LITMPane code="LITM" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest no-matters state for an empty scan (no fake cases)", () => {
    setMockFn({ state: "ok", ...emptyPayload() });
    const { container } = render(<LITMPane code="LITM" symbol="AAPL" />);
    expect(
      screen.getByText(/No litigation 8-K items found/i),
    ).toBeInTheDocument();
    expect(container.textContent).toContain("Scanned 1 recent 8-K events");
    // The sentinel row must NOT be rendered as a table case.
    expect(
      container.querySelector('[aria-label="LITM litigation matters table"]'),
    ).toBeNull();
    expect(screen.queryByText(/no_litigation_event_found/i)).toBeNull();
  });

  it("renders the honest provider-unavailable state", () => {
    setMockFn({ state: "ok", ...providerDownPayload() });
    render(<LITMPane code="LITM" symbol="AAPL" />);
    expect(
      screen.getByText(/Litigation monitor unavailable/i),
    ).toBeInTheDocument();
  });
});

describe("LITM pane — matters table", () => {
  it("renders matters with item codes, severity and source stamps", () => {
    setMockFn({ state: "ok", ...mattersPayload() });
    const { container } = render(<LITMPane code="LITM" symbol="XYZ" />);
    expect(container.textContent).toContain("bankruptcy_or_receivership");
    expect(container.textContent).toContain("8-K 1.03");
    expect(container.textContent).toContain("0001193125-26-111111");
    expect(container.textContent).toContain("review");
    // Non-monitored item codes are excluded from the matters table.
    const table = container.querySelector(
      '[aria-label="LITM litigation matters table"]',
    );
    expect(table?.textContent).not.toContain("5.07");
    // Review-flag disclaimer is shown, not legal advice.
    expect(screen.getByText(/not legal advice/i)).toBeInTheDocument();
  });
});

describe("LITM pane — item filter interaction", () => {
  it("filters the table to a single monitored item code", () => {
    setMockFn({ state: "ok", ...mattersPayload() });
    const { container } = render(<LITMPane code="LITM" symbol="XYZ" />);

    const itemGroup = container.querySelector(
      '[aria-label="Monitored 8-K item filter"]',
    );
    expect(itemGroup).not.toBeNull();
    const chip = Array.from(itemGroup!.querySelectorAll("button")).find(
      (b) => b.textContent === "1.03",
    );
    expect(chip).toBeDefined();
    fireEvent.click(chip!);

    const table = container.querySelector(
      '[aria-label="LITM litigation matters table"]',
    );
    expect(table?.textContent).toContain("bankruptcy_or_receivership");
    expect(table?.textContent).not.toContain("officer_departure");
  });
});

describe("LITM pane — grid CSV export", () => {
  it("exports the visible matters via the CSV button", () => {
    setMockFn({ state: "ok", ...mattersPayload() });
    render(<LITMPane code="LITM" symbol="XYZ" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^litm-XYZ-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(csv).toContain(
      "Symbol,Filed,Item,Event,Severity,Source,Accession,Document",
    );
    expect(csv).toContain(
      "XYZ,2026-08-14,1.03,bankruptcy_or_receivership,review,sec_edgar_8k,0001193125-26-111111,d8k.htm",
    );
  });

  it("exports only the matters matching the active ITEM filter", () => {
    setMockFn({ state: "ok", ...mattersPayload() });
    const { container } = render(<LITMPane code="LITM" symbol="XYZ" />);
    const itemGroup = container.querySelector(
      '[aria-label="Monitored 8-K item filter"]',
    );
    const chip = Array.from(itemGroup!.querySelectorAll("button")).find(
      (b) => b.textContent === "1.03",
    );
    fireEvent.click(chip!);
    fireEvent.click(screen.getByTitle("Download CSV"));
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    const [, csv] = mock.mock.calls[0] as [string, string];
    expect(csv).toContain("bankruptcy_or_receivership");
    expect(csv).not.toContain("officer_departure");
  });

  it("disables the CSV button when the scan found no matters", () => {
    setMockFn({ state: "ok", ...emptyPayload() });
    render(<LITMPane code="LITM" symbol="AAPL" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
