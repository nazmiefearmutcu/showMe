/**
 * OVDV pane — redesign contract tests (L3, options family).
 *
 * Pins the new DOM/behaviour:
 *  - the primary tenor×delta grid is drawn with the design-system `HeatCell`
 *    (class `showme-heat-cell`) — no local heat implementation;
 *  - the ATM term structure reads the REAL `series[].atm_vol_pct` (the old
 *    `p.vol` misread collapsed it to "—");
 *  - roving-focus keyboard navigation: one tabbable cell, arrows move the
 *    active cell and the compact readout follows;
 *  - pair selection is a single segmented control with persistence;
 *  - the reference-model context + provider warnings share ONE notice panel;
 *  - a visibility tick refetches WITHOUT entering the fetch params;
 *  - KPI strip stays ≤4 cards and the footer provenance is stated once.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?:
    | {
        data?: unknown;
        sources?: string[];
        elapsed_ms?: number;
        status?: string;
      }
    | undefined;
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
        warnings: [],
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
  vi.restoreAllMocks();
});

describe("OVDV pane — ATM term structure wire truth", () => {
  it("renders term points from series[].atm_vol_pct", () => {
    render(<OVDVPane code="OVDV" />);
    // Old behaviour: p.vol was undefined -> "No ATM term points." everywhere.
    expect(screen.queryByText("No ATM term points.")).toBeNull();
    const termPanel = screen.getByLabelText("ATM term structure");
    const chart = within(termPanel).getByRole("img");
    expect(chart.getAttribute("aria-label")).toMatch(/1W 6\.45/);
    expect(chart.getAttribute("aria-label")).toMatch(/1M 7\.20/);
  });

  it("computes the term slope from the front/back ATM anchors", () => {
    render(<OVDVPane code="OVDV" />);
    // 7.20 - 6.45 = +0.75 pp (old behaviour: "—").
    expect(screen.getByText("+0.75 pp")).toBeInTheDocument();
  });

  it("names the surface grid for assistive tech", () => {
    render(<OVDVPane code="OVDV" />);
    expect(
      screen.getByRole("grid", { name: "OVDV vol surface grid" }),
    ).toBeInTheDocument();
  });
});

describe("OVDV pane — design-system HeatCell adoption", () => {
  it("renders every surface cell with the kit HeatCell", () => {
    const { container } = render(<OVDVPane code="OVDV" />);
    // 2 tenors × 5 deltas. The local HeatCell implementation is gone.
    expect(container.querySelectorAll(".showme-heat-cell").length).toBe(10);
    expect(
      screen.getByRole("button", {
        name: "1W × 10P implied vol 6.90 percent",
      }),
    ).toBeInTheDocument();
  });

  it("omits the grid when the surface is empty (PaneState empty branch)", () => {
    const payload = okPayload();
    (payload.data.data as { surface: unknown[] }).surface = [];
    mockFn.data = payload.data;
    const { container } = render(<OVDVPane code="OVDV" />);
    expect(container.querySelector('[data-testid="pane-state-empty"]')).not.toBeNull();
    expect(container.querySelectorAll(".showme-heat-cell").length).toBe(0);
  });

  it("keeps the minimum-vol cell visible (no transparent heat hole)", () => {
    render(<OVDVPane code="OVDV" />);
    // FIX R2-#4: min cell (6.45) mapped to intensity 0 → `transparent`.
    const minCell = screen.getByRole("button", {
      name: "1W × ATM implied vol 6.45 percent",
    });
    const minStyle = minCell.getAttribute("style") ?? "";
    expect(minStyle).toMatch(/--heat-pos-/);
    expect(minStyle).not.toMatch(/transparent/);
    // The span still drives the top of the scale.
    const maxCell = screen.getByRole("button", {
      name: "1M × 10P implied vol 7.70 percent",
    });
    expect(maxCell.getAttribute("style")).toMatch(/--heat-pos-5/);
  });
});

describe("OVDV pane — keyboard grid", () => {
  it("keeps one roving tab stop on the kit buttons and moves it with the arrow keys", () => {
    const { container } = render(<OVDVPane code="OVDV" />);
    expect(container.querySelectorAll("td[data-cell]").length).toBe(10);
    // FIX R1-F2: the kit HeatCell button owns the tab stop — the wrapper
    // <td> must not add a second one (10 cells → exactly 1 tab stop).
    expect(container.querySelectorAll('.showme-heat-cell[tabindex="0"]').length).toBe(1);
    expect(container.querySelectorAll('.showme-heat-cell[tabindex="-1"]').length).toBe(9);
    expect(container.querySelectorAll('td[data-cell][tabindex="0"]').length).toBe(0);
    const readout = screen.getByTestId("ovdv-readout");
    // Default active cell = first tenor × ATM.
    expect(readout.textContent).toBe("1W × ATM · 6.45%");

    fireEvent.keyDown(container.querySelector('[data-cell="0-2"]')!, {
      key: "ArrowRight",
    });
    const next = container.querySelector(
      '[data-cell="0-3"] .showme-heat-cell',
    )!;
    expect(next.getAttribute("tabindex")).toBe("0");
    expect(document.activeElement).toBe(next);
    expect(readout.textContent).toBe("1W × 25C · 6.50%");

    fireEvent.keyDown(container.querySelector('[data-cell="0-3"]')!, {
      key: "ArrowDown",
    });
    expect(readout.textContent).toBe("1M × 25C · 7.30%");
  });

  it("snaps the roving tab stop to a present cell on a ragged surface (R3-N2)", () => {
    const payload = okPayload();
    // Remove the fallback cell (tenor 0 × ATM) so the preferred active cell
    // has no value; without the snap the grid would have ZERO tab stops.
    payload.data.data.surface = payload.data.data.surface.filter(
      (cell) => !(cell.tenor === "1W" && cell.delta === "ATM"),
    );
    mockFn.data = payload.data;
    const { container } = render(<OVDVPane code="OVDV" />);
    const tabbable = container.querySelectorAll('.showme-heat-cell[tabindex="0"]');
    expect(tabbable.length).toBe(1);
    expect(tabbable[0].getAttribute("aria-label")).not.toMatch(/1W × ATM/);
  });

  it("updates the compact readout on cell click", () => {
    render(<OVDVPane code="OVDV" />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "1M × 25P implied vol 7.40 percent",
      }),
    );
    expect(screen.getByTestId("ovdv-readout").textContent).toBe(
      "1M × 25P · 7.40%",
    );
  });
});

describe("OVDV pane — pair segmentation + poll hygiene", () => {
  it("re-issues the query with the chosen pair and persists it", () => {
    render(<OVDVPane code="OVDV" />);
    expect(recordedCalls[recordedCalls.length - 1]?.params).toEqual({
      pair: "EURUSD",
    });
    fireEvent.click(screen.getByRole("button", { name: "USD/JPY" }));
    expect(recordedCalls[recordedCalls.length - 1]?.params).toEqual({
      pair: "USDJPY",
    });
    expect(localStorage.getItem("showme.ovdv-pair")).toBe("USDJPY");
  });

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

describe("OVDV pane — provider failure honesty (FIX R1-H/R2-#1)", () => {
  it("reads the envelope status, never a green ok pill, and keeps the reason", () => {
    mockFn.data = {
      data: {
        status: "provider_unavailable",
        reason:
          "yfinance outage: could not reach the FX vol endpoint after repeated retries",
        surface: [],
        rows: [],
      },
      status: "provider_unavailable",
      sources: ["yfinance"],
      elapsed_ms: 9,
    };
    const { container } = render(<OVDVPane code="OVDV" />);
    // No green `ok` pill anywhere.
    const pillTexts = Array.from(container.querySelectorAll(".ds-pill")).map(
      (p) => p.textContent,
    );
    expect(pillTexts).not.toContain("ok");
    expect(pillTexts).toContain("provider_unavailable");
    // The provider reason is shown verbatim (clamped, full text on title).
    const reason = screen.getByText(/yfinance outage: could not reach/i);
    expect(reason.getAttribute("title")).toMatch(/repeated retries/);
    // Footer mode is truthful (the call never reached a mode).
    const footer = container.querySelector(".ds-pane-footer");
    expect(footer?.textContent).toContain("provider_unavailable");
    expect(footer?.textContent).not.toContain("modeled");
  });

  it("prefers the envelope status over a payload-provided mode label", () => {
    const payload = okPayload();
    mockFn.data = {
      ...payload.data,
      status: "provider_unavailable",
    };
    const { container } = render(<OVDVPane code="OVDV" />);
    const pillTexts = Array.from(container.querySelectorAll(".ds-pill")).map(
      (p) => p.textContent,
    );
    expect(pillTexts).toContain("provider_unavailable");
    expect(pillTexts).not.toContain("ok");
  });
});

describe("OVDV pane — duplicate counts/captions collapse (FIX R2-#8)", () => {
  it("states the cell count only in the footer and the tenor range only once", () => {
    const { container } = render(<OVDVPane code="OVDV" />);
    const subtitle = container.querySelector(".ds-pane-header__subtitle");
    expect(subtitle?.textContent).toBe("EURUSD · poll 60s");
    expect(subtitle?.textContent).not.toMatch(/cells/);
    const footer = container.querySelector(".ds-pane-footer");
    expect(footer?.textContent).toContain("cells");
    // KPI caption is now `back − front`; the range survives once on the term head.
    expect(screen.queryByText("back − front")).toBeInTheDocument();
    expect(screen.getAllByText("1W → 1M").length).toBe(1);
  });
});

describe("OVDV pane — responsive term sparkline (FIX R2-#2)", () => {
  it("fills the measured panel width instead of a fixed 280px", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 640,
      height: 90,
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 640,
      bottom: 90,
      toJSON: () => ({}),
    } as DOMRect);
    render(<OVDVPane code="OVDV" />);
    const svg = screen.getByTestId("ovdv-term-measure").querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("640");
  });
});

describe("OVDV pane — honesty notices + KPI budget", () => {
  it("collapses the reference context and provider warnings into ONE notice", () => {
    const payload = okPayload();
    const data = payload.data.data as Record<string, unknown>;
    data.vol_source = "reference_fx_vol_model";
    data.data_mode = "modeled";
    data.warnings = ["live spot unavailable; using labelled reference spot"];
    mockFn.data = payload.data;
    const { container } = render(<OVDVPane code="OVDV" />);
    const notice = screen.getByTestId("ovdv-notice");
    expect(notice).toBeInTheDocument();
    expect(notice.textContent).toMatch(/Reference vol model/);
    expect(notice.textContent).toMatch(
      /live spot unavailable; using labelled reference spot/,
    );
    expect(container.querySelectorAll('[data-testid="ovdv-notice"]').length).toBe(1);
    expect(screen.getAllByRole("status").length).toBe(1);
  });

  it("keeps the KPI strip at four cards and states provenance once", () => {
    const { container } = render(<OVDVPane code="OVDV" />);
    expect(container.querySelectorAll(".stat-card").length).toBe(4);
    const footer = container.querySelector(".ds-pane-footer");
    expect(footer?.textContent).toMatch(/yfinance/);
    expect(footer?.textContent).toMatch(/delayed_reference/);
    // No live notice when the payload is anchored to realized vol.
    expect(screen.queryByTestId("ovdv-notice")).toBeNull();
  });

  it("renders the error branch with Retry", () => {
    mockFn.state = "error";
    mockFn.data = undefined;
    mockFn.error = new Error("sidecar exploded");
    const { container } = render(<OVDVPane code="OVDV" />);
    expect(container.querySelector('[data-testid="pane-state-error"]')).not.toBeNull();
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("offers a CSV export of the surface", () => {
    render(<OVDVPane code="OVDV" />);
    const csv = screen.getByRole("button", {
      name: /download 10 surface cells as csv/i,
    });
    expect(csv).toBeEnabled();
  });
});
