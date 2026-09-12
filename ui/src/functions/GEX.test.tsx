/**
 * GEX pane — render-contract + data-honesty tests (options-family redesign
 * 2026-09-12: ladder + cumulative strip + keyboard roving selection).
 *
 * The backend GEX function degrades to a synthetic 3-strike reference model
 * (hardcoded OI, constant IV) when the live yfinance options chain is
 * unavailable, and returns a `provider_unavailable` envelope (empty rows)
 * when the symbol cannot be resolved at all. These tests pin:
 *
 *  - the load states (loading / empty / provider_unavailable / error / ok);
 *  - ONE synthetic notice + ONE mode pill, never the old double warning;
 *  - a live payload is labeled "live chain" and stays warning-free;
 *  - `net_gex: null` renders a NEUTRAL StatCard tone;
 *  - exactly four KPI cards (decoration budget);
 *  - the per-row `cumulative_gex` trace is rendered (strip polyline);
 *  - roving keyboard selection (ArrowUp/Down/Home/End) + compact readout;
 *  - provider_unavailable never renders seeded numbers;
 *  - table-grade formatting via `@/lib/format` (compact currency + price).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GEXPane } from "./GEX";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
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

const liveRows = [
  { strike: 580, gex: -8.0e8, value: -8.0e8, cumulative_gex: -8.0e8 },
  { strike: 590, gex: -2.0e8, value: -2.0e8, cumulative_gex: -1.0e9 },
  { strike: 600, gex: 1.2e8, value: 1.2e8, cumulative_gex: -8.8e8 },
  { strike: 610, gex: 4.5e8, value: 4.5e8, cumulative_gex: -4.3e8 },
  { strike: 620, gex: 2.4e8, value: 2.4e8, cumulative_gex: -1.9e8 },
];

const liveSummary = {
  net_gex: -1.9e8,
  call_gex_total: -2.5e8,
  put_gex_total: 6.0e7,
  gamma_flip: 600,
  call_wall: 610,
  put_wall: 580,
  n_strikes: 5,
  source_mode: "live_chain",
  synthetic: false,
  degraded: false,
};

function envelope(payload: Record<string, unknown>) {
  return {
    data: {
      data: payload,
      sources: ["yfinance_options"],
      elapsed_ms: 1066,
    },
  };
}

function livePayload() {
  return envelope({
    status: "ok",
    symbol: "SPY",
    spot: 610,
    expiries: ["2026-07-17"],
    rows: liveRows,
    curve: liveRows,
    summary: liveSummary,
    call_wall: { strike: 610, gex: 4.5e8 },
    put_wall: { strike: 580, gex: -8.0e8 },
  });
}

function syntheticPayload() {
  return envelope({
    status: "ok",
    symbol: "SPY",
    spot: 610,
    expiries: ["30d"],
    rows: liveRows,
    curve: liveRows,
    summary: {
      ...liveSummary,
      source_mode: "synthetic_reference_chain",
      synthetic: true,
      degraded: true,
    },
    warning:
      "Live options chain unavailable — showing a synthetic reference model, NOT real dealer positioning.",
    reason:
      "Live options chain unavailable — showing a synthetic reference model, NOT real dealer positioning.",
  });
}

function providerUnavailablePayload() {
  return envelope({
    status: "provider_unavailable",
    symbol: "NOTAREAL",
    reason: "function timed out after 14s",
    rows: [],
  });
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("GEX pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the empty state when there are no rows", () => {
    setMockFn({
      state: "ok",
      data: envelope({ status: "ok", rows: [], curve: [], summary: {} }),
    });
    render(<GEXPane code="GEX" symbol="SPY" />);
    expect(screen.getByText(/No options chain/i)).toBeInTheDocument();
  });

  it("renders provider_unavailable as an honest empty state, never seeded rows", () => {
    setMockFn({ state: "ok", ...providerUnavailablePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(
      screen.getByText(/Options chain unavailable/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/timed out after 14s/i)).toBeInTheDocument();
    expect(screen.queryByTestId("gex-ladder-row")).toBeNull();
    expect(container.querySelectorAll(".stat-card").length).toBe(0);
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<GEXPane code="GEX" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the ladder rows when ok", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(container.querySelectorAll(".gex-ladder__row").length).toBe(5);
  });
});

describe("GEX pane — data honesty", () => {
  it("renders exactly ONE synthetic notice + ONE mode pill (no double warning, no emoji)", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(screen.getAllByTestId("gex-synthetic-notice").length).toBe(1);
    expect(container.querySelectorAll(".gex-synthetic-note").length).toBe(1);
    // Mode pill says what the data is; the notice says what it means.
    expect(screen.getByText("synthetic")).toBeInTheDocument();
    expect(
      screen.getAllByText(/NOT real dealer positioning/i).length,
    ).toBe(1);
    // The deceptive subtle "reference" pill is gone for synthetic data.
    expect(screen.queryByText("reference")).toBeNull();
    // FIX R2-#10: no green "ok" chip beside the synthetic pill + notice.
    const pills = Array.from(container.querySelectorAll(".ds-pill")).map(
      (pill) => pill.textContent,
    );
    expect(pills).toEqual(["synthetic"]);
    // Emoji glyphs removed from the honesty surface.
    expect(container.textContent ?? "").not.toContain("⚠");
  });

  it("does NOT render the synthetic warning for a live payload", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(screen.queryByTestId("gex-synthetic-notice")).toBeNull();
    expect(screen.queryByText(/NOT real dealer positioning/i)).toBeNull();
    expect(screen.getByText("live chain")).toBeInTheDocument();
    const pills = Array.from(container.querySelectorAll(".ds-pill")).map(
      (pill) => pill.textContent,
    );
    expect(pills).toEqual(["live chain"]);
  });

  it("renders a neutral Net GEX tone when net_gex is null", () => {
    const payload = livePayload();
    (payload.data.data as Record<string, unknown>).summary = {
      ...liveSummary,
      net_gex: null,
    };
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const netCard = Array.from(container.querySelectorAll(".stat-card")).find(
      (card) => card.textContent?.includes("Net GEX"),
    );
    expect(netCard?.className).toContain("stat-card--neutral");
  });

  it("tones the Net GEX card negative for a negative net exposure", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const netCard = Array.from(container.querySelectorAll(".stat-card")).find(
      (card) => card.textContent?.includes("Net GEX"),
    );
    expect(netCard?.className).toContain("stat-card--negative");
  });
});

describe("GEX pane — KPI + primary ladder", () => {
  it("renders exactly four KPI cards", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(container.querySelectorAll(".stat-card").length).toBe(4);
  });

  it("labels the ladder sides by sign (net GEX encoding, not call/put)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<GEXPane code="GEX" symbol="SPY" />);
    // FIX R2-#5: the wire carries one signed `gex` number per row.
    expect(screen.getByText("Net Γ −")).toBeInTheDocument();
    expect(screen.getByText("Net Γ +")).toBeInTheDocument();
    expect(screen.queryByText("Put Γ")).toBeNull();
    expect(screen.queryByText("Call Γ")).toBeNull();
  });

  it("positions wall tags on the bar's sign side (negative call wall)", () => {
    // Probe-shaped all-negative payload: the call wall strike carries a
    // NEGATIVE net GEX, so its bar + tag must sit on the minus side.
    const payload = livePayload();
    (payload.data.data as Record<string, unknown>).call_wall = {
      strike: 580,
      gex: -8.0e8,
    };
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const row = Array.from(
      container.querySelectorAll(".gex-ladder__row"),
    ).find((el) => (el.getAttribute("aria-label") ?? "").includes("580.00"))!;
    const leftCell = row.children[0];
    expect(leftCell.querySelector('[data-testid="gex-bar-neg"]')).not.toBeNull();
    expect(leftCell.querySelector('[data-testid="gex-row-tags"]')?.textContent).toContain(
      "CALL WALL",
    );
  });

  it("renders a missing strike value as an em-dash, never a fabricated $0.00 bar", () => {
    const payload = livePayload();
    (payload.data.data.rows as Array<Record<string, unknown>>)[2] = {
      strike: 600,
      cumulative_gex: -8.8e8,
    };
    (payload.data.data.curve as Array<Record<string, unknown>>)[2] = {
      strike: 600,
      cumulative_gex: -8.8e8,
    };
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const row = Array.from(
      container.querySelectorAll(".gex-ladder__row"),
    ).find((el) => (el.getAttribute("aria-label") ?? "").includes("600.00"))!;
    expect(row.querySelector('[data-testid="gex-bar-missing"]')).not.toBeNull();
    expect(row.querySelector('[data-testid="gex-bar-neg"]')).toBeNull();
    expect(row.querySelector('[data-testid="gex-bar-pos"]')).toBeNull();
    expect(container.textContent ?? "").not.toContain("$0.00");
  });

  it("renders the per-row cumulative_gex trace as a strip polyline", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const points = container
      .querySelector('[data-testid="gex-cum-strip"] polyline')
      ?.getAttribute("points");
    expect(points).toBeTruthy();
    expect(points?.split(" ").length).toBe(5);
  });

  it("moves the selected strike with Arrow/Home/End and echoes it in the readout", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<GEXPane code="GEX" symbol="SPY" />);
    // Spot 610 is the default selection (roving tabindex lands there).
    expect(screen.getByTestId("gex-ladder-readout").textContent).toContain(
      "610.00",
    );
    let rows = screen.getAllByTestId("gex-ladder-row");
    expect(rows[3].getAttribute("aria-selected")).toBe("true");
    expect(rows[3].getAttribute("tabindex")).toBe("0");

    fireEvent.keyDown(rows[3], { key: "ArrowDown" });
    expect(screen.getByTestId("gex-ladder-readout").textContent).toContain(
      "620.00",
    );
    rows = screen.getAllByTestId("gex-ladder-row");
    expect(rows[4].getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(rows[4], { key: "Home" });
    expect(screen.getByTestId("gex-ladder-readout").textContent).toContain(
      "580.00",
    );

    fireEvent.keyDown(rows[0], { key: "ArrowUp" });
    expect(screen.getByTestId("gex-ladder-readout").textContent).toContain(
      "580.00",
    );

    fireEvent.keyDown(rows[0], { key: "End" });
    expect(screen.getByTestId("gex-ladder-readout").textContent).toContain(
      "620.00",
    );
  });

  it("labels the selected strike's role in the readout (call wall / cumulative)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<GEXPane code="GEX" symbol="SPY" />);
    const readout = screen.getByTestId("gex-ladder-readout");
    expect(readout.textContent).toContain("CALL WALL");
    expect(readout.textContent).toContain("cum");
  });

  it("renders a single provenance footer with sources + strike count", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const footer = container.querySelector(".ds-pane-footer");
    expect(footer).not.toBeNull();
    expect(footer?.textContent).toContain("yfinance_options");
    expect(footer?.textContent).toContain("strikes");
    expect(footer?.textContent).toContain("1066 ms");
  });

  it("formats net GEX with compact currency and strikes as prices", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    expect(screen.getByText("-$190M")).toBeInTheDocument();
    expect(container.textContent).toContain("610.00");
  });

  it("gives every ladder row a descriptive aria-label", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const rows = Array.from(container.querySelectorAll(".gex-ladder__row"));
    expect(rows.length).toBe(5);
    for (const row of rows) {
      const label = row.getAttribute("aria-label");
      expect(label).toBeTruthy();
      expect(label).toMatch(/gamma/i);
    }
    // FIX R2-#5: the sign of the net-GEX value, not a call/put side.
    const posRow = rows.find((row) =>
      (row.getAttribute("aria-label") ?? "").includes("610.00"),
    );
    expect(posRow?.getAttribute("aria-label")).toMatch(/positive net gamma/i);
    expect(posRow?.getAttribute("aria-label")).toMatch(/call wall/i);
    const negRow = rows.find((row) =>
      (row.getAttribute("aria-label") ?? "").includes("580.00"),
    );
    expect(negRow?.getAttribute("aria-label")).toMatch(/negative net gamma/i);
  });

  it("states the strike count only in the footer (R2-#8 dedup)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<GEXPane code="GEX" symbol="SPY" />);
    const subtitle = container.querySelector(".ds-pane-header__subtitle");
    expect(subtitle?.textContent).toContain("spot 610.00");
    expect(subtitle?.textContent).not.toMatch(/strikes/);
    const footer = container.querySelector(".ds-pane-footer");
    expect(footer?.textContent).toContain("strikes");
  });
});
