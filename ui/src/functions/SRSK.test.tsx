/**
 * SRSK pane — render-contract + data-honesty tests.
 *
 * The backend SRSK ranks sovereigns by a 0-100 World Bank macro composite
 * and converts it into a CDS-proxy spread + Hull 1Y PD. These tests pin:
 *
 *  - the load states (loading / error / provider_unavailable / ok) render;
 *  - rows are ranked worst-first by risk_score, unranked rows sink;
 *  - the table caps at 10 rows with an honest showing-note;
 *  - the universe control changes the countries fetch param (persisted);
 *  - backend warnings (e.g. unset FRED key) surface as a status banner;
 *  - live_official payloads advertise the live source, modeled ones don't.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) plus a
 * `lastParams` capture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SRSKPane } from "./SRSK";
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
  useFunction: (args: { code: string; params?: Record<string, unknown> }) => {
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

/* ── fixtures ──────────────────────────────────────────────────────── */

function srskRow(overrides: Record<string, unknown>) {
  return {
    country: "TR",
    debt_to_gdp: 26.6,
    reserves_months: 4.7,
    current_account_gdp: -0.77,
    inflation_pct: 34.9,
    risk_score: 54.88,
    proxy_spread_pct: 6.63,
    pd_1y_pct: 11.05,
    recovery: 0.4,
    source_mode: "worldbank",
    as_of: "2024",
    note: null,
    ...overrides,
  };
}

const CORE_ROWS = [
  srskRow({ country: "TR", risk_score: 90.1, pd_1y_pct: 26.9 }),
  srskRow({ country: "US", risk_score: 55.76, pd_1y_pct: 11.23 }),
  srskRow({ country: "DE", risk_score: 30.2, pd_1y_pct: 4.7 }),
];

function livePayload(rows: Record<string, unknown>[] = CORE_ROWS) {
  return {
    data: {
      data: {
        status: "ok",
        rows,
        cards: {
          highest_pd_country: "TR",
          highest_pd: 26.9,
          recovery: 0.4,
          data_mode: "live_official",
          as_of: "2024",
        },
        data_mode: "live_official",
        summary: {
          countries: rows.length,
          recovery: 0.4,
          formula: "PD ~= spread / (1 - recovery)",
          worldbank_countries: rows.length,
          fallback_countries: 0,
          highest_risk_country: "TR",
        },
      },
      sources: ["worldbank"],
      elapsed_ms: 320,
      warnings: ["fred DGS10: FRED_API_KEY not set"],
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

describe("SRSK pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<SRSKPane code="SRSK" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<SRSKPane code="SRSK" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the provider_unavailable empty state with the backend reason", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "World Bank Open Data unreachable and no FRED key configured",
          rows: [],
        },
      },
    });
    render(<SRSKPane code="SRSK" />);
    expect(screen.getByText(/Sovereign data unavailable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/World Bank Open Data unreachable/i),
    ).toBeInTheDocument();
  });
});

describe("SRSK pane — ranked table", () => {
  it("ranks rows worst-first by risk score", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<SRSKPane code="SRSK" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(3);
    const texts = rows.map((r) => r.textContent ?? "");
    expect(texts[0]).toContain("TR");
    expect(texts[1]).toContain("US");
    expect(texts[2]).toContain("DE");
    // Rank column is 1-based worst-first.
    expect(texts[0]).toContain("1");
    expect(texts[2]).toContain("3");
  });

  it("sinks rows without a risk score to the bottom, unranked", () => {
    setMockFn({
      state: "ok",
      ...livePayload([
        srskRow({ country: "XX", risk_score: null, source_mode: "sovereign_risk_model" }),
        ...CORE_ROWS,
      ]),
    });
    const { container } = render(<SRSKPane code="SRSK" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(4);
    const last = rows[rows.length - 1].textContent ?? "";
    expect(last).toContain("XX");
    expect(last).toContain("sovereign_risk_model");
  });

  it("caps the table at 10 rows with an honest showing-note", () => {
    const wide = Array.from({ length: 12 }, (_, i) =>
      srskRow({ country: `C${i}`, risk_score: 90 - i, pd_1y_pct: 20 - i }),
    );
    setMockFn({ state: "ok", ...livePayload(wide) });
    const { container } = render(<SRSKPane code="SRSK" />);
    expect(container.querySelectorAll("tbody tr").length).toBe(10);
    expect(
      screen.getByText(/riskiest of 12 countries/i),
    ).toBeInTheDocument();
  });

  it("renders the KPI ribbon with the worst sovereign", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<SRSKPane code="SRSK" />);
    expect(screen.getByText("Highest risk")).toBeInTheDocument();
    // TR appears in the table and in the "Highest risk" card.
    expect(screen.getAllByText("TR").length).toBeGreaterThan(0);
    expect(screen.getByText("Ranked countries")).toBeInTheDocument();
  });
});

describe("SRSK pane — controls + honesty", () => {
  it("sends the Core 4 universe by default", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<SRSKPane code="SRSK" />);
    expect(lastParams?.countries).toEqual(["TR", "US", "DE", "JP"]);
  });

  it("switches to the Wide 12 universe on click and persists it", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<SRSKPane code="SRSK" />);
    fireEvent.click(screen.getByText("Wide 12"));
    expect(lastParams?.countries).toHaveLength(12);
    expect(localStorage.getItem("showme.srsk.universe")).toBe("wide");
  });

  it("surfaces backend warnings as a status banner", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<SRSKPane code="SRSK" />);
    expect(
      screen.getByText(/FRED_API_KEY not set/i),
    ).toBeInTheDocument();
  });

  it("advertises the live source for live_official payloads only", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<SRSKPane code="SRSK" />);
    expect(screen.getByText("live worldbank")).toBeInTheDocument();
    cleanup();

    setMockFn({
      state: "ok",
      data: {
        data: {
          ...livePayload().data.data,
          data_mode: "modeled",
          cards: {
            ...livePayload().data.data.cards,
            data_mode: "modeled",
          },
        },
      },
    });
    render(<SRSKPane code="SRSK" />);
    expect(screen.queryByText("live worldbank")).toBeNull();
  });
});

describe("SRSK pane — grid CSV export", () => {
  it("exports the ranked sovereign table with RAW numbers via the CSV button", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<SRSKPane code="SRSK" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^srsk-core-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(csv).toContain(
      "Rank,Country,Risk score,CDS-proxy %,1Y PD %,Debt/GDP %,Reserves months,CA %GDP,CPI %,Recovery,As of,Source,Note",
    );
    expect(csv).toContain(
      "1,TR,90.1,6.63,26.9,26.6,4.7,-0.77,34.9,0.4,2024,worldbank,",
    );
  });

  it("exports the full ranked set beyond the 10-row render cap", () => {
    const wide = Array.from({ length: 12 }, (_, i) =>
      srskRow({ country: `C${i}`, risk_score: 90 - i, pd_1y_pct: 20 - i }),
    );
    setMockFn({ state: "ok", ...livePayload(wide) });
    render(<SRSKPane code="SRSK" />);
    // The table shows 10 of 12 …
    expect(screen.getByText(/riskiest of 12 countries/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Download CSV"));
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    const [, csv] = mock.mock.calls[0] as [string, string];
    // … the export carries all 12 data rows + header.
    expect(csv.trim().split("\n").length).toBe(13);
    expect(csv).toContain("12,C11,");
  });

  it("disables the CSV button when no sovereign rows are returned", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "World Bank Open Data unreachable and no FRED key configured",
          rows: [],
        },
      },
    });
    render(<SRSKPane code="SRSK" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
