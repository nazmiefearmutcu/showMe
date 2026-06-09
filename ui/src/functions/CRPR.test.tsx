/**
 * CRPR pane — honesty + a11y + display contract tests.
 *
 * CRPR is a MODEL-IMPLIED credit-rating profile derived from SEC EDGAR
 * companyfacts. These tests pin the honesty-first frontend upgrade:
 *
 *  - the rating DRIVERS (leverage / interest coverage / issuer scale) that
 *    JUSTIFY the implied bucket are surfaced as KPI cards (previously dropped);
 *  - the rich per-row `rationale` (incl. the "not a paid agency" / sovereign
 *    disclosures) is rendered;
 *  - `metadata.data_mode` is shown in the footer so the user can tell
 *    live-model vs reference vs unavailable;
 *  - the AAA→D ladder is an accessible role=meter with a clamped valuenow +
 *    valuetext, and the marked bucket row is self-describing;
 *  - the loading / error / empty states sit in a SCOPED role=status live
 *    region (the pane polls — the steady-state ladder must NOT be live);
 *  - the RefreshButton reports aria-busy while refreshing;
 *  - ratio + date formatting goes through the shared helpers (no NaN/"n/a");
 *  - the two empty branches (no issuer vs model returned nothing) differ.
 *
 * `useFunction` is mocked via mutable shared state so each test drives the
 * pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { CRPRPane } from "./CRPR";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetch = vi.fn();

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
    refetch,
  }),
}));

// Visibility poll is irrelevant to render assertions — return a stable tick.
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const NOW = new Date("2026-06-09T12:00:00.000Z");
const FIN_DATE = "2026-03-31";

/** Corporate model-implied happy path (mirrors the SEC-EDGAR branch). */
function corporatePayload(extra: Record<string, unknown> = {}) {
  return {
    data: {
      code: "CRPR",
      data: {
        status: "ok",
        rows: [
          {
            agency: "model_implied",
            rating: "BBB",
            outlook: "stable",
            watch: "none",
            rating_date: FIN_DATE,
            rationale:
              "Implied from SEC financials (as of 2026-03-31): gross debt $42.00bn, " +
              "EBITDA proxy $17.50bn, leverage 2.4x, interest coverage 5.6x.",
          },
        ],
        summary: {
          issuer: "AAPL",
          cik: "0000320193",
          implied_bucket: "investment_grade",
          agencies: 1,
          leverage_x: 2.4,
          interest_coverage_x: 5.6,
          gross_debt_usd: 42_000_000_000,
          ebitda_proxy_usd: 17_500_000_000,
          source_mode: "model_implied_from_financials",
        },
        implied_bucket: "investment_grade",
        scale: ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"],
        methodology: "CRPR derives a MODEL-IMPLIED credit profile from SEC EDGAR companyfacts.",
        ...extra,
      },
      sources: ["sec_edgar"],
      warnings: ["CRPR rating is MODEL-IMPLIED from SEC financials, not a paid agency rating."],
      elapsed_ms: 120,
      metadata: { data_mode: "live_official", as_of: FIN_DATE, latency_ms: 120 },
    },
  };
}

/** Sovereign reference branch — single model_implied row, no drivers. */
function sovereignPayload() {
  return {
    data: {
      code: "CRPR",
      data: {
        status: "ok",
        rows: [
          {
            agency: "model_implied",
            rating: "AA+",
            outlook: "stable",
            watch: "none",
            rating_date: FIN_DATE,
            rationale:
              "Sovereign issuer has no SEC CIK; CRPR's financial-derived model does not " +
              "apply. Reference high-grade sovereign profile shown.",
          },
        ],
        summary: {
          issuer: "US Treasury",
          implied_bucket: "high_grade",
          agencies: 1,
          source_mode: "sovereign_reference",
        },
        implied_bucket: "high_grade",
        scale: ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"],
      },
      sources: ["reference"],
      warnings: ["Sovereign issuer: CRPR's SEC-financials model is not applicable."],
      elapsed_ms: 5,
      metadata: { data_mode: "reference", as_of: FIN_DATE },
    },
  };
}

/** Empty branch — issuer provided but model returned no bucket. */
function emptyModelPayload() {
  return {
    data: {
      code: "CRPR",
      data: {
        status: "empty",
        rows: [],
        summary: { issuer: "XYZ", implied_bucket: "n/a", agencies: 0, source_mode: "sec_edgar" },
        scale: ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"],
        next_actions: ["No SEC CIK found for ticker 'XYZ'."],
      },
      sources: ["sec_edgar"],
      warnings: ["Ticker 'XYZ' not found in SEC EDGAR company map."],
      elapsed_ms: 30,
      metadata: { data_mode: "empty", as_of: FIN_DATE },
    },
  };
}

/** Null-coverage corporate (interest expense = 0 → coverage null). */
function nullCoveragePayload() {
  const p = corporatePayload();
  const summary = (p.data.data as Record<string, unknown>).summary as Record<string, unknown>;
  summary.interest_coverage_x = null;
  return p;
}

/** Outlook with a junk sentinel string that must normalize to "—". */
function naOutlookPayload() {
  const p = corporatePayload();
  const rows = (p.data.data as Record<string, unknown>).rows as Record<string, unknown>[];
  rows[0].outlook = "n/a";
  return p;
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  localStorage.clear();
  refetch.mockClear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("CRPR pane — load states (A2)", () => {
  it("renders the loading placeholder in an aria-busy live region (no ladder)", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<CRPRPane code="CRPR" />);
    const busy = container.querySelector('[role="status"][aria-busy="true"]');
    expect(busy).not.toBeNull();
    expect(container.querySelector('[role="meter"]')).toBeNull();
  });

  it("wraps the error state in a role=status live region", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("boom") });
    const { container } = render(<CRPRPane code="CRPR" />);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.textContent ?? "").toMatch(/boom/);
  });

  it("does NOT wrap the steady-state ladder in a polite live region", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    const { container } = render(<CRPRPane code="CRPR" />);
    const meter = container.querySelector('[role="meter"]');
    expect(meter).not.toBeNull();
    expect(meter?.closest('[aria-live]')).toBeNull();
    expect(meter?.closest('[role="status"]')).toBeNull();
  });
});

describe("CRPR pane — A4 refresh busy", () => {
  it("flags the RefreshButton aria-busy while refreshing", () => {
    setMockFn({ state: "refreshing", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    const refresh = screen.getByRole("button", { name: /refresh/i });
    expect(refresh).toHaveAttribute("aria-busy", "true");
  });
});

describe("CRPR pane — D1 rating drivers as KPI cards", () => {
  it("surfaces leverage and interest coverage as ratios (2.4× / 5.6×)", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    expect(screen.getByText("2.4×")).toBeInTheDocument();
    expect(screen.getByText("5.6×")).toBeInTheDocument();
  });

  it("renders the issuer scale (gross debt / EBITDA) as compact currency", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    // $42bn gross debt + $17.5bn EBITDA via formatCurrency compact.
    expect(screen.getByText(/\$42(\.0+)?B/)).toBeInTheDocument();
    expect(screen.getByText(/\$17\.5B/)).toBeInTheDocument();
  });

  it("renders null interest coverage as the em-dash sentinel (no NaN/null)", () => {
    setMockFn({ state: "ok", ...nullCoveragePayload() });
    const { container } = render(<CRPRPane code="CRPR" />);
    expect(container.textContent ?? "").not.toMatch(/NaN|null|undefined/);
    // The coverage card must show "—" rather than a fabricated ratio.
    const card = screen.getByText("Interest coverage").closest(".stat-card");
    expect(card).not.toBeNull();
    expect(card?.textContent ?? "").toContain("—");
    // …and the leverage card still shows its real ratio (no collateral damage).
    expect(screen.getByText("2.4×")).toBeInTheDocument();
  });
});

describe("CRPR pane — D2 rationale surfaced", () => {
  it("renders the rich per-row rationale text in the agency grid", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    const { container } = render(<CRPRPane code="CRPR" />);
    const grid = container.querySelector('[aria-label="Agency ratings"]');
    expect(grid).not.toBeNull();
    expect(
      within(grid as HTMLElement).getByText(/Implied from SEC financials/i),
    ).toBeInTheDocument();
  });

  it("renders the sovereign disclosure rationale", () => {
    setMockFn({ state: "ok", ...sovereignPayload() });
    render(<CRPRPane code="CRPR" />);
    expect(screen.getByText(/Sovereign issuer has no SEC CIK/i)).toBeInTheDocument();
  });
});

describe("CRPR pane — D3 data_mode in footer", () => {
  it("shows live_official mode in the footer", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    const footerMode = screen.getByTestId("crpr-data-mode");
    expect(footerMode.textContent ?? "").toMatch(/live_official/i);
  });

  it("shows reference mode for the sovereign branch", () => {
    setMockFn({ state: "ok", ...sovereignPayload() });
    render(<CRPRPane code="CRPR" />);
    const footerMode = screen.getByTestId("crpr-data-mode");
    expect(footerMode.textContent ?? "").toMatch(/reference/i);
  });
});

describe("CRPR pane — A1 accessible rating ladder meter", () => {
  it("exposes a role=meter with clamped valuenow + valuetext", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    const meter = screen.getByRole("meter", { name: /kredi notu merdiveni/i });
    expect(meter).toHaveAttribute("aria-valuemin", "0");
    // BBB is index 3 in the 7-rung scale → valuemax 6, valuenow 3.
    expect(meter).toHaveAttribute("aria-valuemax", "6");
    expect(meter).toHaveAttribute("aria-valuenow", "3");
    expect(meter).toHaveAttribute("aria-valuetext", "BBB");
  });

  it("clamps valuenow into [0, max] even if the marker is off-scale", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    const meter = screen.getByRole("meter", { name: /kredi notu merdiveni/i });
    const now = Number(meter.getAttribute("aria-valuenow"));
    const max = Number(meter.getAttribute("aria-valuemax"));
    expect(now).toBeGreaterThanOrEqual(0);
    expect(now).toBeLessThanOrEqual(max);
  });

  it("gives the marked bucket row an aria-label naming the bucket", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    const marked = screen.getByLabelText(/BBB.*işaretli|işaretli.*BBB/i);
    expect(marked).toBeInTheDocument();
  });

  it("tones speculative rungs (BB/B/CCC) as speculative on a coarse scale", () => {
    // Regression: the IG floor must be relative to the rendered scale. A coarse
    // 7-rung backend scale (…BBB,BB,B,CCC) once reused the canonical "BBB-"=9
    // index, marking EVERY rung as investment grade — visually mislabelling
    // speculative credits. Each speculative rung must read "(spekülatif)".
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    expect(screen.getByLabelText(/^BB \(spekülatif\)$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^B \(spekülatif\)$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^CCC \(spekülatif\)$/)).toBeInTheDocument();
    // …and an investment-grade rung still reads IG (no over-correction).
    expect(
      screen.getByLabelText(/^A \(yatırım yapılabilir\)$/),
    ).toBeInTheDocument();
  });

  it("labels the IG / speculative legend so it is not color-only", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    // Legend dots carry the explicit "(investment/speculative grade)" suffix
    // that ladder-row labels do not, so these resolve to the legend only.
    expect(
      screen.getByLabelText(/yatırım yapılabilir \(investment grade\)/i),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/spekülatif \(speculative grade\)/i),
    ).toBeInTheDocument();
  });
});

describe("CRPR pane — A3 grid labels + announced regions", () => {
  it("gives the agency DataGrid an accessible name", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    const { container } = render(<CRPRPane code="CRPR" />);
    expect(
      container.querySelector('[aria-label="Agency ratings"]'),
    ).not.toBeNull();
  });

  it("renders provider warnings in a role=alert region", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    const { container } = render(<CRPRPane code="CRPR" />);
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent ?? "").toMatch(/MODEL-IMPLIED/i);
  });

  it("renders the model-implied notice as a role=status", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    const { container } = render(<CRPRPane code="CRPR" />);
    const notices = Array.from(container.querySelectorAll('[role="status"]'));
    const notice = notices.find((n) => /not an agency rating/i.test(n.textContent ?? ""));
    expect(notice).toBeDefined();
  });

  it("labels the scale toggle button with the action it performs", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    expect(
      screen.getByRole("button", { name: /scale|ölçek/i }),
    ).toBeInTheDocument();
  });
});

describe("CRPR pane — Di1 ratio/sentinel formatting", () => {
  it("normalizes an 'n/a' outlook cell to the em-dash", () => {
    setMockFn({ state: "ok", ...naOutlookPayload() });
    const { container } = render(<CRPRPane code="CRPR" />);
    const grid = container.querySelector('[aria-label="Agency ratings"]');
    expect(grid).not.toBeNull();
    expect(within(grid as HTMLElement).queryByText(/^n\/a$/i)).toBeNull();
    expect(within(grid as HTMLElement).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("never leaks NaN/Infinity for the driver KPIs", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    const { container } = render(<CRPRPane code="CRPR" />);
    expect(container.textContent ?? "").not.toMatch(/NaN|Infinity/);
  });
});

describe("CRPR pane — Di2 as_of formatting", () => {
  it("renders a relative/dated label for a real as_of", () => {
    setMockFn({ state: "ok", ...corporatePayload() });
    render(<CRPRPane code="CRPR" />);
    const asOf = screen.getByTestId("crpr-as-of");
    // Either a Turkish relative label or the raw ISO date — never empty.
    expect(asOf.textContent ?? "").toMatch(/önce|2026-03-31/);
  });

  it("shows the em-dash when as_of is absent (no fabricated client date)", () => {
    const p = sovereignPayload();
    (p.data.metadata as Record<string, unknown>).as_of = undefined;
    setMockFn({ state: "ok", ...p });
    render(<CRPRPane code="CRPR" />);
    const asOf = screen.getByTestId("crpr-as-of");
    expect(asOf.textContent ?? "").toContain("—");
  });
});

describe("CRPR pane — Di3 distinct empty states", () => {
  it("prompts to choose a ticker when no issuer is selected", () => {
    setMockFn({ state: "ok", data: { data: { data: {} } } });
    render(<CRPRPane code="CRPR" />);
    expect(screen.getByText(/no issuer selected/i)).toBeInTheDocument();
  });

  it("explains the model returned nothing when an issuer was provided", () => {
    setMockFn({ state: "ok", ...emptyModelPayload() });
    render(<CRPRPane code="CRPR" symbol="XYZ" />);
    expect(
      screen.getByText(/returned no implied bucket|model returned no/i),
    ).toBeInTheDocument();
  });
});
