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

// Keep the real CSV builder (so the exported document can be asserted) but
// capture the download call — jsdom has no Blob download.
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

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

/** Large-payload fixture mirroring the live AAPL shape (272 exchange rows). */
function manyMatchesPayload(count: number, input = "US0378331005") {
  const matches = Array.from({ length: count }, (_, i) => ({
    figi: `BBG${String(i).padStart(7, "0")}`,
    ticker: "AAPL",
    name: "APPLE INC",
    marketSector: "Equity",
    securityType: "Common Stock",
    securityType2: "Common Stock",
    exchCode: `X${i}`,
    compositeFIGI: "BBG000B9XRY4",
    shareClassFIGI: "BBG001S5N8V8",
  }));
  return {
    data: {
      data: {
        status: "ok",
        match_groups: [{ input, id_type: "ID_ISIN", matches }],
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

describe("ISIN pane — large payload: render cap + CSV export", () => {
  it("caps the rendered match cards at 100 and shows an honest 'Showing 100 of 272' note", () => {
    setMockFn({ state: "ok", ...manyMatchesPayload(272) });
    const { container } = render(
      <ISINPane code="ISIN" symbol="US0378331005" />,
    );
    expect(container.querySelectorAll('[aria-label^="Match "]').length).toBe(100);
    const note = screen.getByTestId("isin-cap-note");
    expect(note).toHaveTextContent("Showing 100 of 272");
  });

  it("renders no cap note when the payload fits the cap", () => {
    setMockFn({ state: "ok", ...okPayload("US0378331005") });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    expect(screen.queryByTestId("isin-cap-note")).toBeNull();
  });

  it("honestly reports the true exchange-level count from groups, not the backend's limited rows", () => {
    // Live probe: data.rows=6 (limit_per_input) while match_groups[0].matches=272.
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          rows: [1, 2, 3, 4, 5, 6],
          match_groups: manyMatchesPayload(272).data.data.match_groups,
        },
      },
    });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    expect(screen.getByText(/272 exchange-level match\(es\)/i)).toBeInTheDocument();
  });

  it("exports ALL 272 matches to CSV, including rows beyond the render cap", () => {
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    mock.mockClear();
    setMockFn({ state: "ok", ...manyMatchesPayload(272) });
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    fireEvent.click(
      screen.getByRole("button", {
        name: /download 272 exchange-level match\(es\) as csv/i,
      }),
    );
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^isin-US0378331005-\d{4}-\d{2}-\d{2}\.csv$/);
    const lines = csv.split("\n");
    expect(lines.length).toBe(273); // header + all 272 rows
    expect(lines[0]).toContain("FIGI");
    expect(csv).toContain("BBG0000000"); // match 1 (rendered)
    expect(csv).toContain("BBG0000271"); // match 272 — beyond the 100-card cap
  });

  it("keeps the CSV export disabled when the lookup returned no matches", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          rows: [],
          match_groups: [{ input: "ZZZZ", id_type: "TICKER", matches: [] }],
          next_actions: [],
        },
      },
    });
    render(<ISINPane code="ISIN" symbol="ZZZZ" />);
    expect(
      screen.getByRole("button", { name: /download 0 exchange-level match\(es\) as csv/i }),
    ).toBeDisabled();
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
