/**
 * ECO pane — data-honesty + a11y + formatting contract tests.
 *
 * The ECO backend fetches a real economic calendar from TradingEconomics /
 * Finnhub, but when BOTH providers fail it SILENTLY falls back to a hardcoded
 * synthetic calendar (`source_mode: "calendar_feed_model"`). Before the
 * honesty fix the fabricated schedule looked exactly like real prints. These
 * tests pin:
 *
 *  - a SYNTHETIC payload renders a prominent model badge ("SAMPLE CALENDAR")
 *    with role=status, and the footer source label reads the honest
 *    "Sample calendar (not live)" text;
 *  - a LIVE payload does NOT render that badge and shows the raw provider;
 *  - the importance badge carries a non-color cue (▲) + aria-label;
 *  - missing actual → "—" (formatMissing) and surprise "—" (no fake number);
 *  - the freshness "Data" indicator uses the server `as_of`, not client time;
 *  - the DataGrid exposes an aria-label; the error state is role=status.
 *
 * `useFunction` is mocked via mutable shared state so each test drives the
 * pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { ECOPane } from "./ECO";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
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

// A fixed "now" so relative time + window filtering are deterministic.
const NOW = new Date("2026-06-09T12:00:00.000Z");
const AS_OF = "2026-06-09T11:55:00.000Z";

function isoOffset(days: number, hh = 13, mm = 30): string {
  const d = new Date(NOW);
  d.setUTCDate(d.getUTCDate() + days);
  d.setUTCHours(hh, mm, 0, 0);
  return d.toISOString();
}

// Mixed events: one printed (actual present), one pending (actual absent).
const events = [
  {
    country: "US",
    event: "CPI YoY",
    date: isoOffset(0),
    importance: "high",
    forecast: 3.1,
    actual: 3.2,
    previous: 3.0,
    surprise: 0.1,
    unit: "%",
  },
  {
    country: "US",
    event: "Initial Jobless Claims",
    date: isoOffset(2),
    importance: "low",
    forecast: 215,
    actual: null,
    previous: 220,
    surprise: null,
    unit: "K",
  },
];

// `data` mirrors the `FunctionCallResult` envelope the pane consumes:
// `data.data` is the payload, `data.sources` / `data.elapsed_ms` the envelope.
function syntheticPayload() {
  return {
    data: {
      data: {
        events,
        rows: events,
        source_mode: "calendar_feed_model",
        as_of: AS_OF,
      },
      sources: ["calendar_feed_model"],
      elapsed_ms: 12,
    },
  };
}

function livePayload() {
  return {
    data: {
      data: {
        events,
        rows: events,
        source_mode: "tradingeconomics",
        as_of: AS_OF,
      },
      sources: ["tradingeconomics"],
      elapsed_ms: 12,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("ECO pane — synthetic-calendar honesty", () => {
  it("renders the prominent model badge (role=status) for a calendar_feed_model payload", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<ECOPane code="ECO" />);
    const badge = screen.getByTestId("eco-model-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("role", "status");
    expect(within(badge).getByText(/SAMPLE CALENDAR/i)).toBeInTheDocument();
    // Subtext explains the values are illustrative sample data, not live.
    expect(badge.textContent ?? "").toMatch(/live/i);
  });

  it("maps the footer source label to the honest 'Sample calendar (not live)' text", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<ECOPane code="ECO" />);
    expect(screen.getByText(/Sample calendar \(not live\)/i)).toBeInTheDocument();
    // The raw machine token must not be shown to the user.
    expect(screen.queryByText(/calendar_feed_model/)).toBeNull();
  });

  it("still renders the model badge when a synthetic calendar has zero events", () => {
    // Honesty: even if the synthetic calendar returns/filters to NO rows, the
    // empty state must keep disclosing that this is the unavailable-providers
    // sample — not let the user assume there's simply no calendar data.
    setMockFn({
      state: "ok",
      data: {
        data: {
          events: [],
          rows: [],
          source_mode: "calendar_feed_model",
          as_of: AS_OF,
        },
        sources: ["calendar_feed_model"],
        elapsed_ms: 12,
      },
    });
    render(<ECOPane code="ECO" />);
    // The empty state is shown…
    expect(screen.getByText(/Calendar empty/i)).toBeInTheDocument();
    // …but the synthetic disclosure badge is still present.
    const badge = screen.getByTestId("eco-model-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("role", "status");
  });

  it("does NOT render the model badge for a live (tradingeconomics) payload", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<ECOPane code="ECO" />);
    expect(screen.queryByTestId("eco-model-badge")).toBeNull();
    // Live source label is shown verbatim.
    expect(screen.getByText(/tradingeconomics/)).toBeInTheDocument();
  });
});

describe("ECO pane — accessibility", () => {
  it("exposes a non-color importance cue + aria-label", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<ECOPane code="ECO" />);
    // "high" importance → label keeps the word and adds a non-color symbol.
    const high = screen.getAllByLabelText(/importance: high/i);
    expect(high.length).toBeGreaterThan(0);
    expect(high[0].textContent ?? "").toMatch(/▲/);
  });

  it("gives the DataGrid an aria-label", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    const { container } = render(<ECOPane code="ECO" />);
    const grid = container.querySelector('[aria-label="Economic calendar"]');
    expect(grid).not.toBeNull();
  });

  it("wraps the error state in role=status", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("boom") });
    const { container } = render(<ECOPane code="ECO" />);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.textContent ?? "").toMatch(/boom/);
  });
});

describe("ECO pane — display honesty", () => {
  it("shows '—' for a missing actual and '—' surprise (no fabricated number)", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<ECOPane code="ECO" />);
    // The pending row (Initial Jobless Claims) has no actual.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
    // The printed CPI row shows its real actual value.
    expect(screen.getByText(/3\.2%/)).toBeInTheDocument();
  });

  it("derives the freshness 'Veri' indicator from as_of (server time, not client)", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<ECOPane code="ECO" />);
    // as_of = 11:55 UTC; client clock is frozen at 12:00 — must show 11:55.
    const veri = screen.getByText(/Data:/i);
    expect(veri.textContent ?? "").toContain("11:55");
    expect(veri.textContent ?? "").not.toContain("12:00");
  });

  it("labels the event timezone as UTC", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<ECOPane code="ECO" />);
    expect(screen.getByText(/Times UTC/i)).toBeInTheDocument();
  });

  it("C3 — derives the actual-vs-forecast bar from the fixture's real values", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    render(<ECOPane code="ECO" />);
    // Only the printed CPI row (forecast 3.1, actual 3.2) carries both values.
    const bars = screen.getAllByTestId("eco-afbar");
    expect(bars).toHaveLength(1);
    // Scaled against max(|3.1|, |3.2|) = 3.2 on a 44px track.
    expect(screen.getByTestId("eco-afbar-forecast").style.width).toBe("43px");
    expect(screen.getByTestId("eco-afbar-actual").style.width).toBe("44px");
    // Beat ⇒ positive tone (inline style, palette-var based); the label
    // carries the real numbers + unit for AT readers.
    expect(screen.getByTestId("eco-afbar-actual").getAttribute("style")).toContain(
      "var(--positive)",
    );
    expect(bars[0].getAttribute("role")).toBe("img");
    expect(bars[0].getAttribute("aria-label")).toBe("forecast 3.1% vs actual 3.2%");
  });

  it("C3 — tones the bar by the surprise sign and scales against the larger leg", () => {
    const miss = {
      country: "US",
      event: "GDP Growth Rate QoQ",
      date: isoOffset(0),
      importance: "high",
      forecast: 4,
      actual: 2,
      previous: 3,
      surprise: -2,
      unit: "%",
    };
    setMockFn({
      state: "ok",
      data: {
        data: {
          events: [miss],
          rows: [miss],
          source_mode: "tradingeconomics",
          as_of: AS_OF,
        },
        sources: ["tradingeconomics"],
        elapsed_ms: 5,
      },
    });
    render(<ECOPane code="ECO" />);
    expect(screen.getByTestId("eco-afbar-forecast").style.width).toBe("44px");
    expect(screen.getByTestId("eco-afbar-actual").style.width).toBe("22px");
    expect(screen.getByTestId("eco-afbar-actual").getAttribute("style")).toContain(
      "var(--negative)",
    );
    expect(screen.getByTestId("eco-afbar").getAttribute("aria-label")).toBe(
      "forecast 4% vs actual 2%",
    );
  });

  it("C3 — renders NO bar when the actual print is missing (honest pending state)", () => {
    const pending = events[1]; // forecast 215, actual null
    setMockFn({
      state: "ok",
      data: {
        data: {
          events: [pending],
          rows: [pending],
          source_mode: "tradingeconomics",
          as_of: AS_OF,
        },
        sources: ["tradingeconomics"],
        elapsed_ms: 9,
      },
    });
    render(<ECOPane code="ECO" />);
    expect(screen.queryByTestId("eco-afbar")).toBeNull();
    // The numeric actual cell keeps the honest em-dash.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("advances the Next prints rail as the clock passes a release (AUDIT A10 [L])", () => {
    setMockFn({ state: "ok", ...syntheticPayload() });
    const { container } = render(<ECOPane code="ECO" />);
    const rail = container.querySelector('[aria-label="Upcoming prints"]');
    expect(rail).not.toBeNull();
    // Both fixtures are in the future at NOW (12:00): CPI today 13:30, claims +2d.
    expect(within(rail as HTMLElement).getByText(/CPI YoY/)).toBeInTheDocument();
    expect(within(rail as HTMLElement).getByText(/Initial Jobless Claims/)).toBeInTheDocument();
    // Advance past the CPI release — the visibility minute-tick must recompute
    // "upcoming" without a refetch and drop the now-past print.
    act(() => {
      vi.advanceTimersByTime(121 * 60_000);
    });
    const railAfter = container.querySelector('[aria-label="Upcoming prints"]');
    expect(within(railAfter as HTMLElement).queryByText(/CPI YoY/)).toBeNull();
    expect(within(railAfter as HTMLElement).getByText(/Initial Jobless Claims/)).toBeInTheDocument();
  });
});
