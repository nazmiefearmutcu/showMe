/**
 * SPLC pane — load states, reference honesty, relationship chips.
 *
 * The backend SPLC regex-mines recent 10-K sections for customer/supplier
 * concentration language and serves labelled reference rows (plus reference
 * sector peers as competitors, ticker when available) when extraction finds
 * nothing. These tests pin:
 *
 *  - the load states (loading / error / provider down);
 *  - a reference payload renders rows + the "Reference data" banner + the
 *    approximate-methodology note (never presented as a verified chain);
 *  - an extraction payload does NOT raise the reference banner;
 *  - the RELATIONSHIP chips filter the table to one relationship type.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { SPLCPane } from "./SPLC";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

interface CapturedArgs {
  code?: string;
  symbol?: string;
  params?: Record<string, unknown>;
  enabled?: boolean;
}

let lastArgs: CapturedArgs | null = null;

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: CapturedArgs) => {
    lastArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function referencePayload() {
  return {
    data: {
      sources: ["sec_edgar", "supply_chain_reference"],
      elapsed_ms: 44,
      data: {
        status: "reference_relationships",
        rows: [
          {
            symbol: "AAPL",
            relationship: "customer/channel",
            counterparty: "Consumer direct and retail channels",
            confidence: 0.72,
            source_mode: "reference_supply_chain_10k_language",
          },
          {
            symbol: "AAPL",
            relationship: "supplier/partner",
            counterparty: "Assembly and logistics partners",
            confidence: 0.62,
            source_mode: "reference_supply_chain_10k_language",
          },
          {
            symbol: "AAPL",
            relationship: "competitor",
            counterparty: "MSFT",
            ticker: "MSFT",
            confidence: 0.35,
            source_mode: "reference_sector_peer_list",
          },
        ],
        customers: [],
        suppliers: [],
        debt_maturity_section: "",
        methodology: "SPLC approximates supply-chain relationships.",
      },
    },
  };
}

function extractedPayload() {
  return {
    data: {
      sources: ["sec_edgar"],
      elapsed_ms: 120,
      data: {
        status: "ok",
        rows: [
          {
            symbol: "XYZ",
            relationship: "customer",
            counterparty: "Acme Distribution Co",
            confidence: 0.81,
            source_mode: "sec_10k_customer_extraction",
          },
          {
            symbol: "XYZ",
            relationship: "competitor",
            counterparty: "GLOB",
            ticker: "GLOB",
            confidence: 0.35,
            source_mode: "reference_sector_peer_list",
          },
        ],
        debt_maturity_section:
          "The company's long-term debt maturities over the next five fiscal years are summarized below.",
        methodology: "SPLC approximates supply-chain relationships.",
      },
    },
  };
}

function providerDownPayload() {
  return {
    data: {
      sources: ["supply_chain_model"],
      elapsed_ms: 4,
      data: {
        status: "provider_unavailable",
        reason: "SEC EDGAR feed unavailable.",
        rows: [
          {
            symbol: "AAPL",
            relationship: "provider_unavailable",
            counterparty: null,
            confidence: null,
            source_mode: "supply_chain_unavailable",
          },
        ],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  lastArgs = null;
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("SPLC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<SPLCPane code="SPLC" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<SPLCPane code="SPLC" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest provider-unavailable state with the backend reason", () => {
    setMockFn({ state: "ok", ...providerDownPayload() });
    render(<SPLCPane code="SPLC" symbol="AAPL" />);
    expect(
      screen.getByText(/Supply-chain relationships unavailable/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/SEC EDGAR feed unavailable/i)).toBeInTheDocument();
    expect(
      screen.queryByLabelText("SPLC supply-chain relationships table"),
    ).toBeNull();
  });
});

describe("SPLC pane — request shape (F14 L)", () => {
  it("sends no dead `live` param (backend is live-by-default)", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    render(<SPLCPane code="SPLC" symbol="AAPL" />);
    expect(lastArgs?.symbol).toBe("AAPL");
    expect(lastArgs?.params).toBeUndefined();
  });
});

describe("SPLC pane — reference honesty", () => {
  it("renders labelled reference rows with the reference banner + approximate note", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    const { container } = render(<SPLCPane code="SPLC" symbol="AAPL" />);
    expect(screen.getByLabelText("Reference data notice")).toBeInTheDocument();
    expect(container.textContent).toContain("Consumer direct and retail channels");
    expect(container.textContent).toContain("Assembly and logistics partners");
    // Reference competitor row carries its ticker.
    expect(container.textContent).toContain("MSFT");
    expect(container.textContent).toContain("reference_sector_peer_list");
    // The approximate-methodology honesty note is always present.
    expect(screen.getByText(/Approximate by construction/i)).toBeInTheDocument();
    // Header carries the REFERENCE extraction-state pill.
    expect(screen.getByText("REFERENCE")).toBeInTheDocument();
  });

  it("does not raise the reference banner for an extracted payload", () => {
    setMockFn({ state: "ok", ...extractedPayload() });
    const { container } = render(<SPLCPane code="SPLC" symbol="XYZ" />);
    expect(screen.queryByLabelText("Reference data notice")).toBeNull();
    expect(container.textContent).toContain("Acme Distribution Co");
    expect(screen.getByText("10-K EXTRACT")).toBeInTheDocument();
    // The extracted debt-maturity excerpt is shown as raw evidence.
    expect(
      screen.getByLabelText("SPLC debt maturity excerpt"),
    ).toBeInTheDocument();
  });
});

describe("SPLC pane — relationship filter interaction", () => {
  it("filters the table to competitor rows when the COMPETITORS chip is active", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    const { container } = render(<SPLCPane code="SPLC" symbol="AAPL" />);

    // The plain chip label also appears nowhere else in this payload, but
    // scope to the control group like the other pane tests do.
    const relGroup = container.querySelector(
      '[aria-label="Relationship type filter"]',
    );
    expect(relGroup).not.toBeNull();
    const chip = Array.from(relGroup!.querySelectorAll("button")).find(
      (b) => b.textContent === "COMPETITORS",
    );
    expect(chip).toBeDefined();
    fireEvent.click(chip!);

    const table = container.querySelector(
      '[aria-label="SPLC supply-chain relationships table"]',
    );
    expect(table?.textContent).toContain("MSFT");
    expect(table?.textContent).not.toContain("Consumer direct and retail channels");
    expect(table?.textContent).not.toContain("Assembly and logistics partners");
  });
});
