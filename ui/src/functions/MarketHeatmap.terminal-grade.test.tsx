/**
 * MarketHeatmap (MAP / SECT) terminal-grade tests.
 *
 * The market-heatmap pane serves BOTH the MAP (world country-ETF) and SECT
 * (S&P sector-ETF) function codes. The grid is visually a treemap, but the
 * tile SIZE is driven by the |% change| magnitude, NOT market cap — and in
 * SECT live mode the backend only ships intraday (1D) changes even when the
 * user picked MTD/QTD/YTD. These tests pin the honesty + a11y contract:
 *
 *  H1 — a sizing note says tile size = |Δ%| magnitude, NOT market cap.
 *  H2 — when the delivered period (`change_pct_period`) differs from the
 *       requested WINDOW, a role=status notice discloses it + surfaces
 *       `data.warnings`, and the change column is labelled with the DELIVERED
 *       period (1D), not the requested one (MTD).
 *  H3 — a model/fallback payload renders a prominent role=status badge above
 *       the grid; an all-live payload does NOT.
 *  A1 — heatmap tiles are real <button>s with an aria-label (name/etf/signed
 *       %/period) that navigate to the ETF in DES on click.
 *  A3 — loading → aria-busy region; error → role=status.
 *
 * `useFunction` + the router/workspace side-effects are mocked so each test
 * drives the pane into a branch without the real sidecar transport.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

// Each test installs its own useFunction return via this mutable holder.
const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));

// Router navigate + workspace focus are observable side-effects.
const navigateSpy = vi.fn();
vi.mock("@/lib/router", () => ({ navigate: (...a: unknown[]) => navigateSpy(...a) }));
const setFocusedTargetSpy = vi.fn();
vi.mock("@/lib/workspace", () => ({
  useWorkspace: (sel: (s: unknown) => unknown) =>
    sel({ setFocusedTarget: setFocusedTargetSpy }),
}));

import { MarketHeatmapPane } from "./MarketHeatmap";

/* ── fixtures ──────────────────────────────────────────────────────── */

function sectorRow(over: Record<string, unknown> = {}) {
  return {
    sector: "Technology",
    etf: "XLK",
    last: 210.5,
    change_pct: 1.23,
    change_pct_period: "1D",
    period: "MTD",
    quote_type: "live",
    ...over,
  };
}

function countryRow(over: Record<string, unknown> = {}) {
  return {
    country: "US",
    etf: "SPY",
    last: 530.25,
    change_pct: 0.84,
    period: "1D",
    quote_type: "live",
    ...over,
  };
}

function mockOk(
  payload: Record<string, unknown>,
  envelope: Record<string, unknown> = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: { status: "ok", ...payload },
      metadata: {},
      sources: ["yfinance"],
      warnings: [],
      fetched_at: "2026-06-08T10:11:28.250007+00:00",
      elapsed_ms: 120,
      ...envelope,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  navigateSpy.mockReset();
  setFocusedTargetSpy.mockReset();
});

/* ── A1: interactive, labelled tiles ──────────────────────────────────── */

describe("MarketHeatmap — interactive labelled tiles (A1)", () => {
  it("renders each tile as a button whose aria-label has etf + signed % + period and navigates to DES on click", () => {
    mockOk({ period: "1D", rows: [countryRow()] });
    render(<MarketHeatmapPane code="MAP" />);
    // Scope to the heatmap grid (the same row also appears in the legend rail).
    const grid = screen.getByRole("region", { name: /ETF performance heatmap/i });
    const tile = within(grid).getByRole("button", {
      name: /US \(SPY\) \+0\.84% 1D/,
    });
    expect(tile.tagName).toBe("BUTTON");
    fireEvent.click(tile);
    expect(navigateSpy).toHaveBeenCalledWith("/symbol/SPY/DES");
    expect(setFocusedTargetSpy).toHaveBeenCalledWith("DES", "SPY");
  });

  it("marks synthetic tiles as model in the aria-label", () => {
    mockOk(
      { status: "model", period: "1D", rows: [countryRow({ quote_type: "model" })] },
      { metadata: { degraded: true } },
    );
    render(<MarketHeatmapPane code="MAP" />);
    const grid = screen.getByRole("region", { name: /ETF performance heatmap/i });
    expect(
      within(grid).getByRole("button", { name: /US \(SPY\).*model/i }),
    ).toBeInTheDocument();
  });
});

/* ── H1: sizing honesty note ──────────────────────────────────────────── */

describe("MarketHeatmap — sizing honesty (H1)", () => {
  it("renders a note stating tile size is the % change magnitude, NOT market cap", () => {
    mockOk({ period: "1D", rows: [countryRow()] });
    render(<MarketHeatmapPane code="MAP" />);
    const note = screen.getByTestId("map-sizing-note");
    expect(note).toBeInTheDocument();
    expect(note.textContent).toMatch(/değişim/i);
    expect(note.textContent).toMatch(/piyasa değeri DEĞİL/i);
  });
});

/* ── H2: SECT period mismatch ─────────────────────────────────────────── */

describe("MarketHeatmap — SECT period-mismatch honesty (H2)", () => {
  it("discloses the delivered 1D period when the user requested MTD, with role=status, and labels the change column 1D", () => {
    mockReturn.current = {
      state: "ok",
      data: {
        data: {
          status: "ok",
          period: "MTD",
          change_pct_period: "1D",
          rows: [sectorRow()],
        },
        metadata: { live: true, requested_period: "MTD", live_period: "1D" },
        sources: ["yfinance"],
        warnings: [
          "SECT live mode currently delivers intraday 1D changes only; the MTD header reflects the request, not the change values",
        ],
        fetched_at: "2026-06-08T10:11:28.250007+00:00",
        elapsed_ms: 120,
      },
      error: undefined,
      refetch: vi.fn(),
    };
    // SECT defaults its window to MTD via the control before rendering.
    render(<MarketHeatmapPane code="SECT" />);
    // The pane opens in 1D by default; switch the WINDOW to MTD to create the
    // request-vs-delivered mismatch the backend reports.
    fireEvent.click(screen.getByRole("button", { name: "MTD", pressed: false }));

    const notice = screen.getByTestId("map-period-notice");
    expect(notice).toBeInTheDocument();
    expect(notice.getAttribute("role")).toBe("status");
    // Names the delivered + requested periods.
    expect(notice.textContent).toMatch(/1D/);
    expect(notice.textContent).toMatch(/MTD/);
    // Surfaces the backend warning text.
    expect(notice.textContent).toMatch(/intraday 1D changes only/i);

    // The change column header reflects the DELIVERED period (1D), not MTD.
    expect(
      screen.getByRole("columnheader", { name: /1D change/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: /MTD change/i }),
    ).toBeNull();
  });

  it("does NOT show the period notice when delivered period matches the request", () => {
    mockOk({
      status: "ok",
      period: "1D",
      change_pct_period: "1D",
      rows: [sectorRow({ period: "1D" })],
    });
    render(<MarketHeatmapPane code="SECT" />);
    expect(screen.queryByTestId("map-period-notice")).toBeNull();
  });
});

/* ── H3: model/fallback badge ─────────────────────────────────────────── */

describe("MarketHeatmap — model/fallback badge (H3)", () => {
  it("renders a prominent role=status model badge for degraded/fallback data", () => {
    mockOk(
      {
        status: "provider_unavailable",
        period: "1D",
        rows: [countryRow({ quote_type: "model" })],
      },
      { metadata: { degraded: true, fallback: true } },
    );
    render(<MarketHeatmapPane code="MAP" />);
    const badge = screen.getByTestId("map-model-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute("role")).toBe("status");
    expect(badge.textContent?.toLowerCase()).toMatch(/model/);
    expect(badge.textContent?.toLowerCase()).toMatch(/canlı/);
  });

  it("renders the model badge when every row is quote_type model (no metadata flag)", () => {
    mockOk({
      status: "model",
      period: "1D",
      rows: [countryRow({ quote_type: "model" })],
    });
    render(<MarketHeatmapPane code="MAP" />);
    expect(screen.getByTestId("map-model-badge")).toBeInTheDocument();
  });

  it("does NOT render the model badge for an all-live payload", () => {
    mockOk({ status: "ok", period: "1D", rows: [countryRow({ quote_type: "live" })] });
    render(<MarketHeatmapPane code="MAP" />);
    expect(screen.queryByTestId("map-model-badge")).toBeNull();
  });

  // P1 regression: a clean `status: "ok"` payload used to leak a spurious
  // StatusNotice warning box whose title was literally "ok" — UI noise that
  // implied a problem when there was none. The status notice must stay silent
  // for a healthy payload.
  it("does NOT render a spurious 'ok' status notice for an all-live payload", () => {
    mockOk({ status: "ok", period: "1D", rows: [countryRow({ quote_type: "live" })] });
    const { container } = render(<MarketHeatmapPane code="MAP" />);
    // The StatusNotice renders its title in a <strong>; a healthy payload must
    // not produce a notice whose title is literally "ok". (A bare /^ok$/ text
    // query is intentionally NOT used: the pane legitimately renders "ok" in
    // unrelated pill/status chips — only the warning-box <strong> title is the
    // regression we're locking out.)
    const okTitle = Array.from(container.querySelectorAll("strong")).find(
      (el) => el.textContent?.trim().toLowerCase() === "ok",
    );
    expect(okTitle).toBeUndefined();
  });
});

/* ── A3: async regions ────────────────────────────────────────────────── */

describe("MarketHeatmap — async a11y regions (A3)", () => {
  it("wraps the loading skeleton in an aria-busy live region", () => {
    mockReturn.current = {
      state: "loading",
      data: undefined,
      error: null,
      refetch: vi.fn(),
    };
    const { container } = render(<MarketHeatmapPane code="MAP" />);
    const busy = container.querySelector('[aria-busy="true"]');
    expect(busy).not.toBeNull();
    expect(busy?.getAttribute("aria-live")).toBe("polite");
  });

  it("announces the error state via role=status", () => {
    mockReturn.current = {
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
      refetch: vi.fn(),
    };
    const { container } = render(<MarketHeatmapPane code="MAP" />);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.textContent).toMatch(/sidecar exploded/i);
  });
});

/* ── A2: legend movers actionable ─────────────────────────────────────── */

describe("MarketHeatmap — legend movers (A2)", () => {
  it("renders top-mover legend rows as buttons that navigate to DES", () => {
    mockOk({
      period: "1D",
      rows: [
        countryRow({ country: "US", etf: "SPY", change_pct: 2.1 }),
        countryRow({ country: "JP", etf: "EWJ", change_pct: -1.4 }),
      ],
    });
    render(<MarketHeatmapPane code="MAP" />);
    // The legend rail lives inside an <aside>; pick a mover button there.
    const moverBtn = within(screen.getByRole("complementary")).getAllByRole(
      "button",
    )[0];
    expect(moverBtn.tagName).toBe("BUTTON");
    fireEvent.click(moverBtn);
    expect(navigateSpy).toHaveBeenCalled();
    expect(navigateSpy.mock.calls[0][0]).toMatch(/\/symbol\/.+\/DES/);
  });
});
