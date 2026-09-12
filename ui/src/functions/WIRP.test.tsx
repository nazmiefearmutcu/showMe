/**
 * WIRP pane — data-honesty + poll-contract tests (F4 macro lane).
 *
 * Pins:
 *  - a live FRED/^IRX payload (`source_mode=live_fed_funds_futures`) shows the
 *    green "live" pill and NOT the false "reference table" notice;
 *  - a `reference_rate_probability_table` payload shows the amber reference
 *    pill + notice;
 *  - a provider outage renders the honest empty state;
 *  - the visibility poll refetches via `refetch()` with stable params (no
 *    `tick` key in the fetch params).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { WIRPPane, anchorEntries, cumulativeBpPath } from "./WIRP";

/* ── useFunction / tick mocks ─────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

const mockTick = { current: 0 };
let lastFnArgs: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockFn.refetch,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        central_bank: "FED",
        source_mode: "live_fed_funds_futures",
        data_mode: "live_official",
        rows: [
          {
            central_bank: "FED",
            date: "2026-09-16",
            cut_25bp: 0.1,
            hold: 0.85,
            hike_25bp: 0.05,
            implied_change_bp: -1.25,
            source_mode: "live_fed_funds_futures",
          },
          {
            central_bank: "FED",
            date: "2026-10-28",
            cut_25bp: 0.2,
            hold: 0.7,
            hike_25bp: 0.1,
            implied_change_bp: -2.5,
            source_mode: "live_fed_funds_futures",
          },
        ],
        anchor: {
          current_target_mid: 3.625,
          current_target_upper: 3.75,
          current_target_lower: 3.5,
          implied_near_term_rate: 3.5,
          implied_near_term_source: "^IRX 13-week T-bill",
          effr: 3.63,
          as_of: "2026-09-12",
        },
        cards: [],
        methodology: "live method",
        field_dictionary: {},
      },
    },
    sources: ["fred", "yfinance"],
    warnings: [],
    elapsed_ms: 12,
  };
}

function referencePayload() {
  return {
    data: {
      data: {
        status: "ok",
        central_bank: "FED",
        source_mode: "reference_rate_probability_table",
        data_mode: "modeled",
        rows: [
          {
            central_bank: "FED",
            date: "2026-09-16",
            cut_25bp: 0.18,
            hold: 0.72,
            hike_25bp: 0.1,
            implied_change_bp: -2,
            source_mode: "reference_rate_probability_table",
          },
        ],
        cards: [],
        field_dictionary: {},
      },
    },
    sources: ["reference_rate_probability_table"],
    warnings: [],
  };
}

beforeEach(() => {
  localStorage.clear();
  mockTick.current = 0;
  lastFnArgs = undefined;
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("WIRP pane — source-mode honesty", () => {
  it("labels a live_fed_funds_futures payload as live, never reference", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<WIRPPane code="WIRP" />);
    const pill = screen.getByTestId("wirp-mode-pill");
    expect(within(pill).getByText("live")).toBeInTheDocument();
    expect(screen.queryByText(/Reference probability table/i)).toBeNull();
    expect(screen.getByText("2026-09-16")).toBeInTheDocument();
  });

  it("labels cme_fedwatch as live too", () => {
    const payload = livePayload();
    (payload.data.data as Record<string, unknown>).source_mode = "cme_fedwatch";
    setMockFn({ state: "ok", ...payload });
    render(<WIRPPane code="WIRP" />);
    expect(within(screen.getByTestId("wirp-mode-pill")).getByText("live")).toBeInTheDocument();
  });

  it("shows the amber reference pill + notice for a reference table", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    render(<WIRPPane code="WIRP" />);
    const pill = screen.getByTestId("wirp-mode-pill");
    expect(within(pill).getByText("reference table")).toBeInTheDocument();
    expect(screen.getByText(/no live futures-implied/i)).toBeInTheDocument();
  });

  it("keeps unknown/absent source modes on the honest reference side", () => {
    const payload = livePayload();
    delete (payload.data.data as Record<string, unknown>).source_mode;
    const rows = (payload.data.data as Record<string, unknown>).rows as Array<Record<string, unknown>>;
    for (const row of rows) delete row.source_mode;
    setMockFn({ state: "ok", ...payload });
    render(<WIRPPane code="WIRP" />);
    expect(
      within(screen.getByTestId("wirp-mode-pill")).getByText("reference table"),
    ).toBeInTheDocument();
  });

  it("renders the honest empty state on a provider outage", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          source_mode: "provider_unavailable",
          rows: [],
          warnings: ["live source unavailable"],
        },
        sources: ["provider_unavailable"],
        warnings: ["live source unavailable"],
      },
    });
    render(<WIRPPane code="WIRP" />);
    expect(screen.getByText(/No meetings/i)).toBeInTheDocument();
  });
});

describe("WIRP pane — visibility poll (F4 refetch contract)", () => {
  it("refetches on a visibility tick but not on mount, params stay tick-free", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...livePayload(), refetch });
    const { rerender } = render(<WIRPPane code="WIRP" />);
    expect(refetch).not.toHaveBeenCalled();
    expect(lastFnArgs?.params).toEqual({ central_bank: "FED", meetings: 6 });

    mockTick.current = 1;
    rerender(<WIRPPane code="WIRP" />);
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(lastFnArgs?.params).toEqual({ central_bank: "FED", meetings: 6 });
  });

  it("switching the bank control changes the params without a tick key", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<WIRPPane code="WIRP" />);
    fireEvent.click(screen.getByRole("tab", { name: "ECB" }));
    expect(lastFnArgs?.params).toEqual({ central_bank: "ECB", meetings: 6 });
  });
});

/* ── campaign C1: implied path + anchor labels ─────────────────────── */

describe("WIRP pane — implied-path derivation (real fields only)", () => {
  it("builds a zero-baseline cumulative path from implied_change_bp", () => {
    const rows = [
      { implied_change_bp: -1.25 },
      { implied_change_bp: -2.5 },
      { implied_change_bp: 0 },
    ];
    expect(cumulativeBpPath(rows)).toEqual([0, -1.25, -3.75, -3.75]);
  });

  it("skips meetings without a finite implied move instead of zeroing them", () => {
    const rows = [
      { implied_change_bp: 5 },
      { implied_change_bp: undefined },
      { implied_change_bp: Number.NaN },
      { implied_change_bp: 2.5 },
    ];
    expect(cumulativeBpPath(rows)).toEqual([0, 5, 7.5]);
  });

  it("returns an empty path when no meeting carries an implied move", () => {
    expect(cumulativeBpPath([{ date: "2026-09-16" }])).toEqual([]);
  });

  it("derives anchor labels only from fields present on the wire", () => {
    expect(
      anchorEntries({
        current_target_mid: 3.625,
        current_target_upper: 3.75,
        current_target_lower: 3.5,
        implied_near_term_rate: 3.5,
        implied_near_term_source: "^IRX 13-week T-bill",
      }),
    ).toEqual([
      { key: "target", label: "Target", value: "3.50–3.75%" },
      { key: "mid", label: "Mid", value: "3.625%" },
      {
        key: "near",
        label: "Near-term",
        value: "3.500%",
        title: "^IRX 13-week T-bill",
      },
    ]);
    // Absent anchor → no fabricated labels.
    expect(anchorEntries(undefined)).toEqual([]);
    expect(anchorEntries({ as_of: "2026-09-12" })).toEqual([]);
  });

  it("renders the cumulative path sparkline + target-range anchor labels", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<WIRPPane code="WIRP" />);
    const panel = screen.getByLabelText("WIRP implied path");
    expect(
      within(panel).getByRole("img", {
        name: "Cumulative implied policy-rate path",
      }),
    ).toBeInTheDocument();
    expect(within(panel).getByText("3.50–3.75%")).toBeInTheDocument();
    expect(within(panel).getByText("3.625%")).toBeInTheDocument();
    expect(within(panel).getByText("3.500%")).toBeInTheDocument();
    expect(within(panel).getByText(/Σ implied Δ from the FED anchor/)).toBeInTheDocument();
  });

  it("keeps the anchor strip but drops the sparkline honestly when the series is absent", () => {
    const payload = livePayload();
    const rows = (payload.data.data as Record<string, unknown>).rows as Array<Record<string, unknown>>;
    for (const row of rows) delete row.implied_change_bp;
    setMockFn({ state: "ok", ...payload });
    render(<WIRPPane code="WIRP" />);
    const panel = screen.getByLabelText("WIRP implied path");
    expect(within(panel).queryByRole("img")).toBeNull();
    expect(within(panel).getByText(/No per-meeting implied series returned/)).toBeInTheDocument();
  });

  it("renders no path panel when neither the series nor the anchor is on the wire", () => {
    const payload = livePayload();
    const data = payload.data.data as Record<string, unknown>;
    delete data.anchor;
    const rows = data.rows as Array<Record<string, unknown>>;
    for (const row of rows) delete row.implied_change_bp;
    setMockFn({ state: "ok", ...payload });
    render(<WIRPPane code="WIRP" />);
    expect(screen.queryByLabelText("WIRP implied path")).toBeNull();
  });
});
