/**
 * OVDV pane — ATM term-structure wire truth + poll hygiene.
 *
 * The backend ships `series[]` rows as `{tenor, atm_vol_pct}` (percent).
 * The pane used to read `p.vol` from them, so the ATM term structure always
 * collapsed to "No ATM term points." / an em-dash slope even with a full
 * surface. These tests pin:
 *
 *  - the term structure renders from `atm_vol_pct` (sparkline + bars + slope);
 *  - a visibility tick refetches WITHOUT entering the fetch params;
 *  - the surface grid carries an accessible name.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchMock = vi.fn();
const mockTick = { current: 0 };
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    recordedCalls.push(opts);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

import { OVDVPane } from "./OVDV";

function cell(tenor: string, delta: string, vol: number) {
  return {
    pair: "EURUSD",
    tenor,
    delta,
    vol,
    vol_decimal: vol / 100,
    source_mode: "live_realized_vol",
  };
}

function okPayload() {
  return {
    data: {
      data: {
        pair: "EURUSD",
        as_of: "2026-09-11T00:00:00+00:00",
        vol_source: "live_realized_vol",
        data_mode: "delayed_reference",
        tenors: ["1W", "1M"],
        surface: [
          cell("1W", "10P", 6.9),
          cell("1W", "25P", 6.6),
          cell("1W", "ATM", 6.45),
          cell("1W", "25C", 6.5),
          cell("1W", "10C", 6.85),
          cell("1M", "10P", 7.7),
          cell("1M", "25P", 7.4),
          cell("1M", "ATM", 7.2),
          cell("1M", "25C", 7.3),
          cell("1M", "10C", 7.6),
        ],
        series: [
          { tenor: "1W", atm_vol_pct: 6.45 },
          { tenor: "1M", atm_vol_pct: 7.2 },
        ],
        cards: {
          atm_vol_pct: 7.2,
          risk_reversal_25d_pct: 0.43,
          butterfly_25d_pct: 0.11,
          vol_source: "live_realized_vol",
        },
        methodology: "test",
      },
      sources: ["yfinance", "model:fx_vol_smile"],
      elapsed_ms: 12,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "ok";
  mockFn.data = okPayload().data;
  mockFn.error = null;
  refetchMock.mockReset();
  mockTick.current = 0;
  recordedCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

describe("OVDV pane — ATM term structure wire truth", () => {
  it("renders term points from series[].atm_vol_pct", () => {
    render(<OVDVPane code="OVDV" />);
    // Old behaviour: p.vol was undefined -> "No ATM term points." everywhere.
    expect(screen.queryByText("No ATM term points.")).toBeNull();
    const termPanel = screen.getByLabelText("ATM term structure");
    expect(within(termPanel).getByText("6.45%")).toBeInTheDocument();
    expect(within(termPanel).getByText("7.20%")).toBeInTheDocument();
  });

  it("computes the term slope from the front/back ATM anchors", () => {
    render(<OVDVPane code="OVDV" />);
    // 7.20 - 6.45 = +0.75 pp (old behaviour: "—").
    expect(screen.getByText("+0.75 pp")).toBeInTheDocument();
  });

  it("names the surface grid for assistive tech", () => {
    render(<OVDVPane code="OVDV" />);
    expect(
      screen.getByRole("table", { name: "OVDV vol surface grid" }),
    ).toBeInTheDocument();
  });
});

describe("OVDV pane — visibility poll (live adoption)", () => {
  it("refetches on a visibility tick without feeding it into the params", () => {
    const { rerender } = render(<OVDVPane code="OVDV" />);
    expect(refetchMock).not.toHaveBeenCalled();
    const snapshot = () =>
      JSON.stringify(recordedCalls[recordedCalls.length - 1]?.params ?? null);

    const before = snapshot();
    mockTick.current = 3;
    rerender(<OVDVPane code="OVDV" />);
    expect(refetchMock).toHaveBeenCalledTimes(1);
    expect(snapshot()).toBe(before);
    expect(snapshot()).not.toContain("tick");
  });
});
