/**
 * COUN pane — render-contract + dedupe-defect tests.
 *
 * Known backend defect: with live data the `cards` payload lists the Policy
 * rate TWICE — the live value prepended first, then the stale reference
 * value from the curated profile. These tests pin that the pane dedupes
 * cards by label keeping the FIRST (live) occurrence, plus:
 *
 *  - the load states (loading / error / empty / ok);
 *  - an OK payload renders indicator cards and the metrics table with
 *    as-of dates and source-mode stamps;
 *  - reference/baseline source modes render muted (NOT accent) so
 *    reference fallback rows are visually distinct from live ones;
 *  - the country segmented-control interaction persists the choice.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { COUNPane } from "./COUN";
import { downloadGridCsv } from "@/design-system/grid-csv";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number | null };
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

// Keep the real CSV builder, but capture the download call so the export
// payload can be asserted (jsdom has no Blob download).
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

/* ── fixtures ──────────────────────────────────────────────────────── */

// Mirrors the live TR probe: rows are deduped server-side (one live Policy
// rate), but cards carry the duplicate Policy rate defect (37.0 live + 50.0
// reference).
function livePayload() {
  return {
    state: "ok" as const,
    data: {
      data: {
        country: "TR",
        rows: [
          {
            section: "rates",
            metric: "Policy rate",
            value: 37.0,
            unit: "%",
            as_of: "2026-08-28",
            country: "TR",
            source_mode: "BIS CBPOL",
          },
          {
            section: "prices",
            metric: "Inflation",
            value: 55.0,
            unit: "% y/y",
            source_mode: "country_reference_profile",
          },
          {
            section: "growth",
            metric: "Real GDP",
            value: 1.0,
            unit: "index",
            as_of: "2026-06-01",
            series_id: "TURGDPRQDSMEI",
            source_mode: "macro_series_baseline",
          },
        ],
        cards: [
          { label: "Country", value: "TR" },
          { label: "Policy rate", value: 37.0 },
          { label: "Currency", value: "TRY" },
          { label: "Policy rate", value: 50.0 },
          { label: "Inflation", value: 55.0 },
        ],
        source_mode: "live_macro",
        country_known: true,
      },
      sources: ["btmm", "fred", "country_reference_profile"],
      elapsed_ms: 812,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.removeItem("showme.coun.country");
  setMockFn({ state: "idle", data: undefined });
  (downloadGridCsv as ReturnType<typeof vi.fn>).mockClear();
});
afterEach(() => {
  cleanup();
});

describe("COUN pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<COUNPane code="COUN" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("sidecar exploded") });
    render(<COUNPane code="COUN" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an honest empty state when no rows return", () => {
    setMockFn({ state: "ok", data: { data: { rows: [], country: "US" } } });
    render(<COUNPane code="COUN" />);
    expect(screen.getByText(/No country metrics returned/i)).toBeInTheDocument();
  });

  it("renders indicator cards + the metrics table when ok", () => {
    setMockFn(livePayload());
    const { container } = render(<COUNPane code="COUN" />);
    expect(screen.getAllByText("Policy rate").length).toBeGreaterThan(0);
    expect(screen.getByText("BIS CBPOL")).toBeInTheDocument();
    expect(screen.getByText("2026-08-28")).toBeInTheDocument();
    expect(container.querySelectorAll("table tbody tr").length).toBe(3);
  });
});

describe("COUN pane — duplicate card defect", () => {
  it("keeps the FIRST (live) Policy rate card and drops the stale duplicate", () => {
    setMockFn(livePayload());
    const { container } = render(<COUNPane code="COUN" />);
    const policyCards = container.querySelectorAll('[aria-label="COUN indicator cards"] .stat-card');
    const labels = Array.from(policyCards).map((el) => el.textContent ?? "");
    const policyCount = labels.filter((t) => t.includes("Policy rate")).length;
    expect(policyCount).toBe(1);
    // The surviving card is the LIVE 37 value, not the 50 reference.
    expect(labels.find((t) => t.includes("Policy rate"))).toContain("37");
    expect(labels.find((t) => t.includes("Policy rate"))).not.toContain("50");
  });
});

describe("COUN pane — source honesty", () => {
  it("stamps reference/baseline rows muted and live rows accent", () => {
    setMockFn(livePayload());
    const { container } = render(<COUNPane code="COUN" />);
    const refPill = Array.from(container.querySelectorAll(".ds-pill")).find((el) =>
      (el.textContent ?? "").includes("country_reference_profile"),
    );
    const livePill = Array.from(container.querySelectorAll(".ds-pill")).find((el) =>
      (el.textContent ?? "").includes("BIS CBPOL"),
    );
    expect(refPill).toBeTruthy();
    expect(livePill).toBeTruthy();
    expect(refPill?.className).not.toBe(livePill?.className);
  });

  it("labels the pane reference-only when every row is a reference mode", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          country: "US",
          rows: [
            {
              section: "rates",
              metric: "Policy rate",
              value: 5.25,
              unit: "%",
              source_mode: "country_reference_profile",
            },
          ],
          cards: [{ label: "Policy rate", value: 5.25 }],
          source_mode: "country_reference_profile",
        },
      },
    });
    render(<COUNPane code="COUN" />);
    expect(screen.getByText("reference")).toBeInTheDocument();
  });
});

describe("COUN pane — country interaction", () => {
  it("switches country via the segmented control and persists it", () => {
    setMockFn(livePayload());
    render(<COUNPane code="COUN" />);
    const trButton = screen.getByRole("button", { name: "TR" });
    fireEvent.click(trButton);
    expect(trButton.getAttribute("class")).toContain("fn-segmented__opt--active");
    expect(localStorage.getItem("showme.coun.country")).toBe("TR");
  });
});

describe("COUN pane — grid upgrade (L7)", () => {
  it("sorts metrics by value from the header", () => {
    setMockFn(livePayload());
    const { container } = render(<COUNPane code="COUN" />);
    // Values: Policy rate 37, Inflation 55, Real GDP 1 → ascending promotes GDP.
    fireEvent.click(screen.getByRole("columnheader", { name: /Value/i }));
    expect(container.querySelector("tbody tr")?.textContent).toContain("Real GDP");
  });
});

describe("COUN pane — grid CSV export", () => {
  it("exports the raw country metrics table via the CSV button", () => {
    localStorage.setItem("showme.coun.country", "TR");
    setMockFn(livePayload());
    render(<COUNPane code="COUN" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^coun-TR-\d{4}-\d{2}-\d{2}\.csv$/);
    // Header row + RAW payload values (37, not "37 %").
    expect(csv).toContain("Section,Metric,Value,Unit,As of,Series ID,Source");
    expect(csv).toContain("rates,Policy rate,37,%,2026-08-28,,BIS CBPOL");
    expect(csv).toContain(
      "growth,Real GDP,1,index,2026-06-01,TURGDPRQDSMEI,macro_series_baseline",
    );
  });

  it("disables the CSV button when no rows are returned", () => {
    setMockFn({ state: "ok", data: { data: { rows: [], country: "US" } } });
    render(<COUNPane code="COUN" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
