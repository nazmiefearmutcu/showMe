/**
 * HFS pane — search interaction + data-honesty tests.
 *
 * HFS is a 13F reverse lookup: an issuer/CUSIP search lists the filers that
 * held it. The backend reads the LOCAL DuckDB store; when it is empty the
 * rows are labelled public-reference holders (reference_13f_public) and
 * provider failures return source_mode holder_search_unavailable. These
 * tests pin:
 *
 *  - the load states (loading / error / empty-issuer) render;
 *  - a search submit updates the useFunction params (issuer) and is
 *    persisted into the `showme.hfs.recent` recents;
 *  - a reference payload renders the "Reference data" badge + note;
 *  - a provider_unavailable payload renders the honest no-match state;
 *  - clicking a recent chip re-runs the lookup for that issuer.
 *
 * `useFunction` is mocked via a mutable shared state; the mock captures the
 * latest call args so search interactions can be asserted.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { HFSPane } from "./HFS";
import * as router from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

interface CapturedArgs {
  code?: string;
  params?: Record<string, unknown>;
  enabled?: boolean;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
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

const referenceRows = [
  {
    filer: "Vanguard Group",
    issuer: "AAPL",
    shares: 1_318_000_000,
    pct_outstanding: 0.087,
    quarter: "latest public 13F reference",
    source_mode: "reference_13f_public",
  },
  {
    filer: "BlackRock",
    issuer: "AAPL",
    shares: 1_040_000_000,
    pct_outstanding: 0.069,
    quarter: "latest public 13F reference",
    source_mode: "reference_13f_public",
  },
];

function referencePayload() {
  return {
    data: {
      data: {
        status: "ok",
        issuer: "AAPL",
        quarter: "latest",
        rows: referenceRows,
        next_actions: ["Run scripts/ingest_13f.py to populate local 13F reverse lookup."],
      },
    },
  };
}

function unavailablePayload() {
  return {
    data: {
      data: {
        status: "provider_unavailable",
        issuer: "AAPL",
        quarter: "latest",
        rows: [
          {
            filer: "No local 13F match",
            issuer: "AAPL",
            shares: 0,
            market_value: 0,
            source_mode: "holder_search_unavailable",
          },
        ],
        next_actions: ["Run scripts/ingest_13f.py or retry the local SEC 13F store."],
      },
    },
  };
}

/**
 * F14 [H] regression fixture: the REAL columns of the populated SEC 13F
 * DuckDB path (`sec_13f_adapter.query_holdings_by_security` returns
 * `filer_cik / report_date / value_usd / shares`). Pre-fix the pane read
 * `filer / market_value / quarter`, so this payload rendered "—" for
 * Filer / Notional and fell back to quarter="latest".
 */
function liveStorePayload() {
  return {
    data: {
      sources: ["sec_13f"],
      elapsed_ms: 31,
      data: {
        status: "ok",
        issuer: "AAPL",
        quarter: "latest",
        rows: [
          {
            filer_cik: "0001067983",
            report_date: "2026-06-30",
            value_usd: 123_456_789_000,
            shares: 1_318_000_000,
          },
          {
            filer_cik: "1364742",
            report_date: "2026-06-30",
            value_usd: 98_000_000_000,
            shares: 1_040_000_000,
          },
        ],
        next_actions: [],
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

describe("HFS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<HFSPane code="HFS" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<HFSPane code="HFS" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the issuer-required state when the search box is empty", () => {
    render(<HFSPane code="HFS" symbol="" />);
    expect(screen.getByText(/Issuer required/i)).toBeInTheDocument();
  });
});

describe("HFS pane — search interaction", () => {
  it("submits a new issuer and persists it into recent searches", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    render(<HFSPane code="HFS" symbol="AAPL" />);

    fireEvent.change(screen.getByLabelText("ISSUER"), {
      target: { value: "msft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    // The lookup was re-issued with the normalized issuer.
    expect(lastArgs?.params?.issuer).toBe("MSFT");
    // OK result persisted the search into showme.hfs.recent.
    const recents: unknown = JSON.parse(
      localStorage.getItem("showme.hfs.recent") ?? "[]",
    );
    expect(recents).toContain("MSFT");
  });

  it("re-runs the lookup when a recent-search chip is clicked", () => {
    localStorage.setItem(
      "showme.hfs.recent",
      JSON.stringify(["NVDA", "AAPL"]),
    );
    setMockFn({ state: "ok", ...referencePayload() });
    render(<HFSPane code="HFS" symbol="AAPL" />);

    fireEvent.click(screen.getByRole("button", { name: "NVDA" }));
    expect(lastArgs?.params?.issuer).toBe("NVDA");
  });
});

describe("HFS pane — data honesty", () => {
  it("renders a prominent Reference data badge for reference rows", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    render(<HFSPane code="HFS" symbol="AAPL" />);
    expect(screen.getByText(/Reference data/i)).toBeInTheDocument();
    expect(screen.getByText(/NOT live 13F filings/i)).toBeInTheDocument();
    expect(screen.getAllByText("Vanguard Group").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the honest no-match state for provider_unavailable payloads", () => {
    setMockFn({ state: "ok", ...unavailablePayload() });
    render(<HFSPane code="HFS" symbol="AAPL" />);
    expect(screen.getByText(/No local 13F match/i)).toBeInTheDocument();
    expect(
      screen.getByText(/ingest_13f\.py or retry the local SEC 13F store/i),
    ).toBeInTheDocument();
  });

  it("renders populated SEC 13F store columns (filer_cik/value_usd/report_date)", () => {
    // F14 [H]: pre-fix this payload blanked Filer / Notional / Quarter.
    setMockFn({ state: "ok", ...liveStorePayload() });
    const { container } = render(<HFSPane code="HFS" symbol="AAPL" />);

    // Filer column: CIK fallback (zero-padded), never blank.
    expect(
      screen.getAllByText(/CIK 0001067983/).length,
    ).toBeGreaterThanOrEqual(1);
    // Notional column: value_usd rendered as compact USD, never "—".
    expect(container.textContent).toContain("123.46B");
    // Quarter column: report_date, not the payload-level "latest" fallback.
    expect(container.textContent).toContain("2026-06-30");
    // A real store never raises the reference banner and reads live.
    expect(screen.queryByLabelText("Reference data notice")).toBeNull();
    expect(screen.getByText("live")).toBeInTheDocument();
  });
});

describe("HFS pane — DES cross-link (B2)", () => {
  it("renders the resolved issuer as a button named 'Open DES for AAPL'", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    render(<HFSPane code="HFS" symbol="AAPL" />);
    const buttons = screen.getAllByRole("button", { name: "Open DES for AAPL" });
    expect(buttons.length).toBe(2); // one per holder row
    expect(buttons[0].tagName).toBe("BUTTON");
    expect(buttons[0].textContent).toBe("AAPL");
  });

  it("R2: the issuer link carries the u-symbol-link class with no inline color override", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    render(<HFSPane code="HFS" symbol="AAPL" />);
    const btn = screen.getAllByRole("button", { name: "Open DES for AAPL" })[0];
    expect(btn.classList.contains("u-symbol-link")).toBe(true);
    expect((btn as HTMLElement).style.color).toBe("");
  });

  it("clicking the issuer focuses DES and routes to /symbol/AAPL/DES", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    const nav = vi.spyOn(router, "navigate").mockImplementation(() => undefined);
    render(<HFSPane code="HFS" symbol="AAPL" />);
    fireEvent.click(
      screen.getAllByRole("button", { name: "Open DES for AAPL" })[0],
    );
    expect(nav).toHaveBeenCalledWith("/symbol/AAPL/DES");
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
    if (tree.kind === "leaf") {
      expect(tree.code).toBe("DES");
      expect(tree.symbol).toBe("AAPL");
    }
    nav.mockRestore();
  });
});
