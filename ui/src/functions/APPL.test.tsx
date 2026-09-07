/**
 * APPL pane — load states, synthetic honesty, breadcrumb chain, view filter.
 *
 * The backend APPL serves the bundled taxonomy model (status
 * "reference_taxonomy") whenever the live refdata provider is unavailable —
 * and the survey probe confirmed it returns that even with live=true. These
 * tests pin:
 *
 *  - the load states (loading / error / no rows);
 *  - a reference payload raises the prominent "Synthetic / reference data"
 *    banner, re-stamps template "live_yfinance" row labels as
 *    "reference_taxonomy_model", renders the GICS breadcrumb chain and the
 *    honest no-peers note;
 *  - a live "ok" payload raises no banner and renders peer chips;
 *  - the TABLE chips filter between all levels and crosswalk rows only.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { APPLPane } from "./APPL";

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

/* ── fixtures (shapes mirror a live sidecar probe) ─────────────────── */

function referencePayload() {
  return {
    data: {
      sources: ["taxonomy_model"],
      elapsed_ms: 1,
      data: {
        status: "reference_taxonomy",
        sector: "Equity",
        industry: "Listed Security",
        exchange: "Exchange",
        exchange_name: "Exchange",
        rows: [
          { level: "Provider sector", classification: "Equity", source_mode: "live_yfinance" },
          { level: "Provider industry", classification: "Listed Security", source_mode: "live_yfinance" },
          { level: "Exchange", classification: "Exchange", raw_code: "Exchange", source_mode: "live_yfinance" },
          { level: "Country", classification: "Global", source_mode: "live_yfinance" },
          { level: "Currency", classification: "USD", source_mode: "live_yfinance" },
          { level: "GICS sector", classification: "Information Technology", source_mode: "reference_taxonomy_crosswalk" },
          { level: "GICS industry group", classification: "Technology Hardware & Equipment", source_mode: "reference_taxonomy_crosswalk" },
          { level: "GICS industry", classification: "Technology Hardware, Storage & Peripherals", source_mode: "reference_taxonomy_crosswalk" },
          { level: "GICS sub-industry", classification: "Technology Hardware, Storage & Peripherals", source_mode: "reference_taxonomy_crosswalk" },
          { level: "NAICS", classification: "334220 - Radio and Television Broadcasting and Wireless Communications Equipment Manufacturing", source_mode: "reference_taxonomy_crosswalk" },
          { level: "ICB", classification: "1010 - Technology", source_mode: "reference_taxonomy_crosswalk" },
        ],
        methodology: "Fallback taxonomy is labelled as a reference model.",
      },
    },
  };
}

function livePayload() {
  return {
    data: {
      sources: ["yfinance"],
      elapsed_ms: 210,
      data: {
        status: "ok",
        sector: "Technology",
        industry: "Consumer Electronics",
        exchange: "NMS",
        exchange_name: "Nasdaq Global Select Market",
        rows: [
          { level: "Provider sector", classification: "Technology", source_mode: "live_yfinance" },
          { level: "Provider industry", classification: "Consumer Electronics", source_mode: "live_yfinance" },
          { level: "GICS sector", classification: "Information Technology", source_mode: "reference_taxonomy_crosswalk" },
          { level: "GICS industry", classification: "Technology Hardware, Storage & Peripherals", source_mode: "reference_taxonomy_crosswalk" },
        ],
        peers: [
          { symbol: "MSFT", peer_set: "reference_sector_peer" },
          { symbol: "NVDA", peer_set: "reference_sector_peer" },
        ],
        methodology: "Live provider fields with a labelled crosswalk.",
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("APPL pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<APPLPane code="APPL" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<APPLPane code="APPL" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest no-rows state instead of guessing a classification", () => {
    setMockFn({
      state: "ok",
      data: { sources: ["taxonomy_model"], elapsed_ms: 1, data: { status: "reference_taxonomy", rows: [] } },
    });
    render(<APPLPane code="APPL" symbol="AAPL" />);
    expect(screen.getByText(/Taxonomy unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/will not guess a classification/i)).toBeInTheDocument();
  });
});

describe("APPL pane — synthetic honesty", () => {
  it("raises the synthetic banner, re-stamps row sources and shows the GICS chain", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    const { container } = render(<APPLPane code="APPL" symbol="AAPL" />);

    // Prominent synthetic/reference badge (survey probe: reference_taxonomy
    // is served even with live=true).
    expect(
      screen.getByLabelText("Synthetic taxonomy notice"),
    ).toBeInTheDocument();
    expect(screen.getByText("Synthetic / reference data")).toBeInTheDocument();
    expect(screen.getByText("SYNTHETIC")).toBeInTheDocument();

    // Template rows stamped "live_yfinance" must be re-stamped honestly.
    expect(container.textContent).not.toContain("live_yfinance");
    expect(container.textContent).toContain("reference_taxonomy_model");

    // GICS breadcrumb chain is rendered from the crosswalk rows.
    const chain = screen.getByLabelText("GICS breadcrumb");
    expect(chain.textContent).toContain("Information Technology");
    expect(chain.textContent).toContain("Technology Hardware & Equipment");
    expect(chain.textContent).toContain(
      "Technology Hardware, Storage & Peripherals",
    );

    // Honest absence note: the reference payload carries no peer list.
    expect(container.textContent).toContain("No peer list in this taxonomy payload");
  });

  it("raises no banner for a live payload and renders peer chips", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<APPLPane code="APPL" symbol="AAPL" />);

    expect(screen.queryByLabelText("Synthetic taxonomy notice")).toBeNull();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(container.textContent).toContain("MSFT");
    expect(container.textContent).toContain("NVDA");
    expect(container.textContent).toContain("reference_sector_peer");
    expect(container.textContent).toContain("live_yfinance");
  });
});

describe("APPL pane — table view interaction", () => {
  it("filters the table to crosswalk rows when the CROSSWALK chip is active", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    const { container } = render(<APPLPane code="APPL" symbol="AAPL" />);

    const viewGroup = container.querySelector(
      '[aria-label="Taxonomy table view filter"]',
    );
    expect(viewGroup).not.toBeNull();
    const chip = Array.from(viewGroup!.querySelectorAll("button")).find(
      (b) => b.textContent === "CROSSWALK",
    );
    expect(chip).toBeDefined();
    fireEvent.click(chip!);

    const table = container.querySelector('[aria-label="APPL taxonomy table"]');
    expect(table?.textContent).toContain("GICS sector");
    expect(table?.textContent).toContain("Information Technology");
    expect(table?.textContent).not.toContain("Provider sector");
    expect(table?.textContent).not.toContain("Currency");
  });
});
