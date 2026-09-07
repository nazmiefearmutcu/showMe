/**
 * ISIN pane — data-honesty + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern). Pins:
 *
 *  - loading / error / provider_unavailable / empty / ok states render;
 *  - the ok state renders cross-ID match cards with FIGI identifiers;
 *  - successful lookups persist to the last-5 history in localStorage;
 *  - clicking a history chip re-runs that lookup (input interaction).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ISINPane } from "./ISIN";

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

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload(input: string) {
  return {
    data: {
      sources: ["openfigi"],
      elapsed_ms: 640,
      data: {
        status: "ok",
        rows: [
          {
            input,
            id_type: "ID_ISIN",
            rank: "#1",
            figi: "BBG000B9XRY4",
            ticker: "AAPL",
            name: "APPLE INC",
            exchange: "US",
          },
        ],
        match_groups: [
          {
            input,
            id_type: "ID_ISIN",
            matches: [
              {
                figi: "BBG000B9XRY4",
                ticker: "AAPL",
                name: "APPLE INC",
                marketSector: "Equity",
                securityType: "Common Stock",
                securityType2: "Common Stock",
                exchCode: "US",
                compositeFIGI: "BBG000B9XRY4",
                shareClassFIGI: "BBG001S5N8V8",
              },
              {
                figi: "BBG000B9XSK7",
                ticker: "AAPL",
                name: "APPLE INC",
                marketSector: "Equity",
                securityType: "Common Stock",
                securityType2: "Common Stock",
                exchCode: "UA",
                compositeFIGI: "BBG000B9XRY4",
                shareClassFIGI: "BBG001S5N8V8",
              },
            ],
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
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("ISIN pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(
      <ISINPane code="ISIN" symbol="US0378331005" />,
    );
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest provider_unavailable state", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          rows: [],
          reason: "OpenFIGI adapter is not configured.",
        },
      },
    });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    expect(screen.getByText(/OpenFIGI unavailable/i)).toBeInTheDocument();
  });

  it("renders the empty state with guidance when there are no matches", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          rows: [],
          match_groups: [{ input: "ZZZZ", id_type: "TICKER", matches: [] }],
          next_actions: ["Try ID Type TICKER for common symbols."],
        },
      },
    });
    render(<ISINPane code="ISIN" symbol="ZZZZ" />);
    expect(screen.getByText(/No OpenFIGI matches/i)).toBeInTheDocument();
    expect(screen.getByText(/Try ID Type TICKER/i)).toBeInTheDocument();
  });
});

describe("ISIN pane — match cards", () => {
  it("renders one card per exchange-level match with FIGI identifiers", () => {
    setMockFn({ state: "ok", ...okPayload("US0378331005") });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    expect(screen.getAllByText("BBG000B9XRY4").length).toBe(3); // figi + composite x2 (same share class)
    expect(screen.getByText("BBG000B9XSK7")).toBeInTheDocument();
    expect(
      screen.getByLabelText(
        /Match 1 for US0378331005: AAPL on US/i,
      ),
    ).toBeInTheDocument();
  });

  it("badges the detected id type on the match group", () => {
    setMockFn({ state: "ok", ...okPayload("US0378331005") });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    expect(screen.getByText("ID_ISIN")).toBeInTheDocument();
  });
});

describe("ISIN pane — lookup history", () => {
  it("persists a successful lookup as the most recent history entry", () => {
    localStorage.setItem(
      "showme.isin.history",
      JSON.stringify(["MSFT", "AAPL"]),
    );
    setMockFn({ state: "ok", ...okPayload("US0378331005") });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    const stored: unknown = JSON.parse(
      localStorage.getItem("showme.isin.history") ?? "[]",
    );
    expect(stored).toEqual(["US0378331005", "MSFT", "AAPL"]);
  });

  it("caps persisted history at 5 entries without duplicates", () => {
    localStorage.setItem(
      "showme.isin.history",
      JSON.stringify(["A", "B", "C", "D", "E"]),
    );
    setMockFn({ state: "ok", ...okPayload("US0378331005") });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    const stored: unknown = JSON.parse(
      localStorage.getItem("showme.isin.history") ?? "[]",
    );
    expect(stored).toEqual(["US0378331005", "A", "B", "C", "D"]);
  });

  it("re-runs a lookup when a history chip is clicked", () => {
    localStorage.setItem(
      "showme.isin.history",
      JSON.stringify(["MSFT", "AAPL"]),
    );
    setMockFn({ state: "ok", ...okPayload("US0378331005") });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    const chip = screen.getByTitle("Re-run lookup MSFT");
    fireEvent.click(chip);
    const input = screen.getByLabelText(
      "Identifier to cross-reference",
    ) as HTMLInputElement;
    expect(input.value).toBe("MSFT");
  });
});
