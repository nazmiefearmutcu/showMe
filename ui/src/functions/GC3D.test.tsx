/**
 * GC3D pane — render-contract + data-honesty tests.
 *
 * The backend GC3D serves a labelled yield-curve model template (rolling
 * dates anchored to today, fixed reference levels) unless a FRED key is
 * configured. These tests pin:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - the surface renders as a date × tenor heat grid with tinted cells;
 *  - cell tooltips + the range caption carry the payload values;
 *  - a yield_curve_model payload shows the MODEL FIXTURE pill + notice;
 *  - a fred payload does not;
 *  - the look-back days control drives params + persists under
 *    `showme.gc3d.days`.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) with
 * lastParams capture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { GC3DPane, deriveCurveSlope } from "./GC3D";

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

/* ── fixtures: 3 dates × 4 tenors, same shape as bond/gc3d.py ──────── */

const TENORS = ["3M", "2Y", "10Y", "30Y"];
const TENOR_YEARS: Record<string, number> = { "3M": 0.25, "2Y": 2, "10Y": 10, "30Y": 30 };
const DATES = ["2026-07-24", "2026-08-08", "2026-09-07"];
// date → per-tenor levels (each date shifted by +0.015 like the template).
const LEVELS: Record<string, Record<string, number>> = {
  "2026-07-24": { "3M": 5.28, "2Y": 4.62, "10Y": 4.45, "30Y": 4.67 },
  "2026-08-08": { "3M": 5.295, "2Y": 4.635, "10Y": 4.465, "30Y": 4.685 },
  "2026-09-07": { "3M": 5.31, "2Y": 4.65, "10Y": 4.48, "30Y": 4.7 },
};

const SURFACE = DATES.flatMap((date) =>
  TENORS.map((tenor) => ({
    date,
    tenor,
    tenor_years: TENOR_YEARS[tenor],
    yield: LEVELS[date][tenor],
  })),
);

function modelPayload() {
  return {
    data: {
      data: {
        surface: SURFACE,
        rows: SURFACE,
        tenors: TENORS,
        dates: DATES,
        summary: {
          source_mode: "yield_curve_model",
          dates: 3,
          tenors: 4,
          points: 12,
          days: 365,
        },
        methodology: "GC3D builds a date-by-tenor yield surface.",
      },
      sources: ["yield_curve_model"],
      elapsed_ms: 2,
    },
  };
}

function fredPayload() {
  const payload = modelPayload();
  payload.data.data.summary.source_mode = "fred";
  payload.data.sources = ["fred"];
  return payload;
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("GC3D pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when the surface is empty", () => {
    setMockFn({ state: "ok", data: { data: { surface: [], rows: [] } } });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(screen.getByText(/No surface returned/i)).toBeInTheDocument();
  });
});

describe("GC3D pane — surface grid", () => {
  it("renders one row per tenor and one column per date", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    const { container } = render(<GC3DPane code="GC3D" symbol="US10Y" />);
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(4);
    // Date columns are headed by MM-DD.
    expect(screen.getByText("07-24")).toBeInTheDocument();
    expect(screen.getByText("09-07")).toBeInTheDocument();
  });

  it("renders every cell value with a full-context tooltip", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    const { container } = render(<GC3DPane code="GC3D" symbol="US10Y" />);
    const cells = Array.from(container.querySelectorAll('span[title]'));
    const tenYearLatest = cells.find((c) =>
      (c.getAttribute("title") ?? "").includes("10Y 2026-09-07"),
    );
    expect(tenYearLatest?.getAttribute("title")).toContain("4.480%");
    // All 12 data cells carry titles.
    expect(cells.filter((c) => /20Y|30Y|10Y|2Y|3M /.test(c.getAttribute("title") ?? "")).length).toBe(12);
  });

  it("shows the yield range from the surface min/max", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    // min 4.45 (10Y earliest) … max 5.31 (3M latest).
    expect(screen.getByText("4.450–5.310%")).toBeInTheDocument();
  });
});

describe("GC3D pane — data honesty", () => {
  it("shows the MODEL FIXTURE pill + notice for yield_curve_model payloads", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(screen.getByText(/model fixture/i)).toBeInTheDocument();
    expect(screen.getByText(/NOT live Treasury observations/i)).toBeInTheDocument();
  });

  it("does NOT show the fixture notice for a fred payload", () => {
    setMockFn({ state: "ok", ...fredPayload() });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(screen.getByText(/FRED live/i)).toBeInTheDocument();
    expect(screen.queryByText(/model fixture/i)).toBeNull();
  });
});

describe("GC3D pane — look-back control", () => {
  it("sends the default 365-day look-back", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(lastParams).toMatchObject({ days: 365 });
  });

  it("switches look-back via the segmented control and persists it", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    fireEvent.click(screen.getByText("2y"));
    expect(lastParams?.days).toBe(730);
    expect(localStorage.getItem("showme.gc3d.days")).toBe("730");
  });
});

/* ── campaign C1: curve slope derived from the real surface ────────── */

describe("GC3D pane — curve-slope derivation (real surface math)", () => {
  it("derives 10Y−2Y per date from the surface points", () => {
    const slope = deriveCurveSlope(SURFACE);
    expect(slope).not.toBeNull();
    expect(slope?.shortTenor).toBe("2Y");
    expect(slope?.longTenor).toBe("10Y");
    expect(slope?.points.map((p) => p.date)).toEqual(DATES);
    // 4.45−4.62, 4.465−4.635, 4.48−4.65 → −0.17 on every snapshot.
    for (const point of slope?.points ?? []) {
      expect(point.slope).toBeCloseTo(-0.17, 10);
    }
  });

  it("falls back to the nearest maturities and never collapses to one leg", () => {
    const surface = [
      { date: "2026-09-07", tenor: "5Y", tenor_years: 5, yield: 4.0 },
      { date: "2026-09-07", tenor: "30Y", tenor_years: 30, yield: 4.9 },
    ];
    const slope = deriveCurveSlope(surface);
    expect(slope?.shortTenor).toBe("5Y");
    expect(slope?.longTenor).toBe("30Y");
    expect(slope?.points[0].slope).toBeCloseTo(0.9, 10);
  });

  it("returns null (honest drop) without two distinct maturities", () => {
    expect(
      deriveCurveSlope([
        { date: "2026-09-07", tenor: "10Y", tenor_years: 10, yield: 4.45 },
        { date: "2026-08-08", tenor: "10Y", tenor_years: 10, yield: 4.465 },
      ]),
    ).toBeNull();
    // Two maturities, but no date carries both legs → no interpolated slope.
    expect(
      deriveCurveSlope([
        { date: "2026-09-07", tenor: "2Y", tenor_years: 2, yield: 4.65 },
        { date: "2026-08-08", tenor: "10Y", tenor_years: 10, yield: 4.465 },
      ]),
    ).toBeNull();
  });

  it("renders the slope panel with the latest readout + sparkline", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    const panel = screen.getByLabelText("GC3D curve slope");
    expect(within(panel).getByText(/10Y − 2Y slope/)).toBeInTheDocument();
    expect(within(panel).getByText(/latest -0\.170 pp/)).toBeInTheDocument();
    expect(within(panel).getByText(/inverted/)).toBeInTheDocument();
    expect(
      within(panel).getByRole("img", {
        name: "10Y-minus-2Y curve slope across 3 snapshots",
      }),
    ).toBeInTheDocument();
  });

  it("renders no slope panel when the surface cannot derive a pair", () => {
    const payload = modelPayload();
    const singleTenor = SURFACE.filter((p) => p.tenor === "10Y");
    (payload.data.data as Record<string, unknown>).surface = singleTenor;
    (payload.data.data as Record<string, unknown>).rows = singleTenor;
    setMockFn({ state: "ok", ...payload });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(screen.queryByLabelText("GC3D curve slope")).toBeNull();
  });
});
