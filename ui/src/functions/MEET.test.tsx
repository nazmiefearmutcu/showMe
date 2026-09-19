/**
 * MEET (Meeting Briefings — World Events) pane tests.
 *
 * Covers the world-events contract:
 *   - pure countdown formatting (`formatCountdown`),
 *   - spot-alert dedupe (`dueAlert` fires once per row+lead),
 *   - UPCOMING / PAST grouping from the payload,
 *   - the country follow filter (sidebar click narrows rows + persists),
 *   - the SPOT pin on rate decisions,
 *   - honest empty / provider_unavailable states,
 *   - the lead-time toast + in-pane alert history.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MEETPane } from "./MEET";
import {
  dueAlert,
  flagOf,
  formatAge,
  formatCountdown,
  formatPrint,
  dayKey,
  groupCalendarByDay,
  groupRows,
  isSpotFor,
  leadLabel,
  loadMeetAlerts,
  normalizeMeetAlerts,
  parsePrintNumber,
  polarityOf,
  surpriseOf,
  type MeetRow,
} from "./meet/helpers";

/* ── mocks ─────────────────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
  lastParams?: Record<string, unknown>;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const mockRefetch = vi.fn();
const mockTick = { current: 0 };

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    mockFn.lastParams = args.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockRefetch,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

vi.mock("@/lib/market-data", () => ({
  useLiveQuote: () => ({ price: 100, changePct: 1.5, loading: false, stale: false }),
}));

const toastWarn = vi.fn();
vi.mock("@/lib/toast", () => ({
  toast: {
    info: vi.fn(),
    success: vi.fn(),
    warn: (title: string, body?: string) => toastWarn(title, body),
    error: vi.fn(),
  },
}));

/* ── fixtures (mirror a live /api/fn/MEET world-events payload) ────── */

const NOW = Date.now();

function row(overrides: Partial<MeetRow>): MeetRow {
  return {
    id: `economic:${overrides.title ?? "row"}`,
    kind: "economic",
    title: "Event",
    countries: ["US"],
    country_names: ["United States"],
    when_utc: new Date(NOW + 3 * 3600_000).toISOString(),
    impact: "high",
    pairs: [],
    source: "forex_factory",
    spot: false,
    pinned: false,
    seconds_to_event: 10800,
    ...overrides,
  };
}

function worldPayload() {
  const tcmb = row({
    id: "economic:tcmb",
    title: "TCMB Interest Rate Decision",
    countries: ["TR"],
    country_names: ["Turkey"],
    pairs: ["USDTRY", "EURTRY"],
    spot: true,
    pinned: true,
    when_utc: new Date(NOW + 2 * 3600_000 + 30_000).toISOString(),
    seconds_to_event: 7230,
  });
  const us = row({
    id: "economic:us-cpi",
    title: "CPI y/y",
    when_utc: new Date(NOW + 30 * 3600_000).toISOString(),
    seconds_to_event: 108000,
    pinned: true,
  });
  const war = row({
    id: "world:war",
    kind: "world",
    title: "Missile strikes hit power grid after escalation",
    countries: ["RU", "UA"],
    country_names: ["Russia", "Ukraine"],
    impact: "high",
    source: "gdelt",
    spot: true,
    when_utc: new Date(NOW - 2 * 3600_000 - 300_000).toISOString(),
    seconds_to_event: -7500,
    age_minutes: 125,
  });
  const rows = [tcmb, us, war];
  return {
    status: "ok",
    as_of: new Date(NOW).toISOString(),
    rows,
    upcoming: [tcmb, us],
    past: [war],
    row_count: rows.length,
    upcoming_count: 2,
    past_count: 1,
    window: {
      days_ahead: 90,
      days_back: 7,
      upcoming_count: 2,
      past_count: 1,
      next_high_impact: {
        id: tcmb.id,
        title: tcmb.title,
        when_utc: tcmb.when_utc,
        country_names: ["Turkey"],
      },
    },
    country_index: [
      {
        iso: "TR",
        name: "Turkey",
        upcoming_count: 1,
        past_count: 0,
        state: "imminent",
        next_event: { id: tcmb.id, title: tcmb.title, when_utc: tcmb.when_utc, seconds_to_event: 7200, impact: "high", spot: true, kind: "economic" },
      },
      {
        iso: "US",
        name: "United States",
        upcoming_count: 1,
        past_count: 0,
        state: "scheduled",
        next_event: { id: us.id, title: us.title, when_utc: us.when_utc, seconds_to_event: 108000, impact: "high", spot: false, kind: "economic" },
      },
      {
        iso: "RU",
        name: "Russia",
        upcoming_count: 0,
        past_count: 1,
        state: "quiet",
        next_event: null,
      },
      {
        iso: "UA",
        name: "Ukraine",
        upcoming_count: 0,
        past_count: 1,
        state: "quiet",
        next_event: null,
      },
    ],
    country_catalog: [
      { iso: "TR", name: "Turkey" },
      { iso: "US", name: "United States" },
      { iso: "RU", name: "Russia" },
      { iso: "UA", name: "Ukraine" },
    ],
    alerts: [],
    alert_default_lead_minutes: [1440, 60, 5],
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
  toastWarn.mockClear();
  mockRefetch.mockClear();
  mockTick.current = 0;
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/* ── pure helpers ──────────────────────────────────────────────────── */

describe("formatCountdown — adaptive resolution", () => {
  it("uses days+hours above 2 days", () => {
    expect(formatCountdown(3 * 86400 + 4 * 3600 + 12)).toBe("3d 4h");
  });
  it("uses hours+minutes above 2 hours", () => {
    expect(formatCountdown(3 * 3600 + 23 * 60 + 5)).toBe("3h 23m");
  });
  it("adds seconds between 10 minutes and 2 hours", () => {
    expect(formatCountdown(23 * 60 + 45)).toBe("23m 45s");
  });
  it("drops to seconds under 10 minutes", () => {
    expect(formatCountdown(45)).toBe("45s");
  });
  it("never claims time that is not there (floors)", () => {
    expect(formatCountdown(23 * 60 + 45.9)).toBe("23m 45s");
    expect(formatCountdown(3 * 3600 + 23 * 60 + 59.9)).toBe("3h 23m");
  });
  it("handles passed / missing values honestly", () => {
    expect(formatCountdown(0)).toBe("now");
    expect(formatCountdown(-12)).toBe("now");
    expect(formatCountdown(null)).toBe("—");
    expect(formatCountdown(Number.NaN)).toBe("—");
  });
});

describe("formatAge — past rows", () => {
  it("renders a compact age for passed events", () => {
    expect(formatAge(-3 * 86400)).toBe("3d ago");
    expect(formatAge(-4 * 3600)).toBe("4h ago");
    expect(formatAge(-12 * 60)).toBe("12m ago");
    expect(formatAge(-45)).toBe("45s ago");
  });
  it("is honest for future / missing values", () => {
    expect(formatAge(60)).toBe("—");
    expect(formatAge(null)).toBe("—");
  });
});

describe("dueAlert — lead-time dedupe", () => {
  const config = normalizeMeetAlerts({ leadMinutes: [1440, 60, 5] });
  const spot = row({ id: "e1", spot: true, countries: ["TR"] });

  it("fires the smallest crossed lead exactly once", () => {
    const nowMs = Date.parse(spot.when_utc ?? "") - 3 * 60_000; // 3 min out
    const first = dueAlert(spot, config, nowMs, new Set());
    expect(first?.lead).toBe(5);
    const fired = new Set([first!.key]);
    expect(dueAlert(spot, config, nowMs + 1000, fired)).toBeNull();
    // It does not back-fill the larger leads after the imminent one fired.
    expect(dueAlert(spot, config, Date.parse(spot.when_utc ?? "") - 60_000, fired)).toBeNull();
  });

  it("moves to the next lead as the event approaches", () => {
    const t60 = Date.parse(spot.when_utc ?? "") - 30 * 60_000; // 30 min out → only 60/1440 crossed
    const hit = dueAlert(spot, config, t60, new Set());
    expect(hit?.lead).toBe(60);
    const fired = new Set([hit!.key]);
    const later = dueAlert(spot, config, Date.parse(spot.when_utc ?? "") - 4 * 60_000, fired);
    expect(later?.lead).toBe(5);
  });

  it("ignores non-spot low-impact rows", () => {
    const calm = row({ id: "e2", impact: "low", spot: false, pinned: false });
    expect(dueAlert(calm, config, Date.parse(calm.when_utc ?? "") - 60_000, new Set())).toBeNull();
  });

  it("respects the disabled toggle", () => {
    const off = { ...config, enabled: false };
    expect(dueAlert(spot, off, Date.parse(spot.when_utc ?? "") - 60_000, new Set())).toBeNull();
  });
});

describe("isSpotFor — follow list raises a country's high-impact events", () => {
  it("tracks provider spots and pinned high prints", () => {
    const cfg = normalizeMeetAlerts(null);
    expect(isSpotFor(row({ id: "a", spot: true }), cfg)).toBe(true);
    expect(isSpotFor(row({ id: "b", pinned: true, impact: "high" }), cfg)).toBe(true);
    expect(isSpotFor(row({ id: "c", impact: "low" }), cfg)).toBe(false);
  });

  it("tracks followed countries (Türkiye ⇒ TCMB always spot)", () => {
    const cfg = normalizeMeetAlerts({ spotCountries: ["TR"] });
    const tcmb = row({ id: "tcmb", countries: ["TR"], impact: "high", spot: false, pinned: false });
    expect(isSpotFor(tcmb, cfg)).toBe(true);
    expect(leadLabel(1440)).toBe("1d");
  });
});

describe("groupRows — upcoming/past split", () => {
  it("splits on the live clock and keeps undated wire copy in the past", () => {
    const payload = worldPayload();
    const { upcoming, past } = groupRows(payload.rows as MeetRow[], NOW);
    // Hourglass around NOW: upcoming runs farthest → nearest.
    expect(upcoming.map((r) => r.id)).toEqual(["economic:us-cpi", "economic:tcmb"]);
    expect(past.map((r) => r.id)).toEqual(["world:war"]);
    const undated = row({ id: "u", undated: true });
    expect(groupRows([undated], NOW).past).toHaveLength(1);
  });

  it("re-sorts both sides of the clock when rows cross into the past", () => {
    const early = row({ id: "early", when_utc: new Date(NOW + 1_000).toISOString() });
    const late = row({ id: "late", when_utc: new Date(NOW + 3_000).toISOString() });
    const old = row({ id: "old", when_utc: new Date(NOW - 5_000).toISOString() });

    // Upcoming: farthest first, the soonest event last (just above NOW).
    expect(groupRows([late, old, early], NOW).upcoming.map((r) => r.id)).toEqual([
      "late",
      "early",
    ]);
    // Past: freshest first (just below NOW), older last.
    expect(groupRows([late, old, early], NOW + 2_000).past.map((r) => r.id)).toEqual([
      "early",
      "old",
    ]);
  });

  it("converges both groups on NOW (hourglass layout)", () => {
    const rows = [
      row({ id: "far-future", when_utc: new Date(NOW + 10 * 86400_000).toISOString() }),
      row({ id: "near-future", when_utc: new Date(NOW + 60_000).toISOString() }),
      row({ id: "near-past", when_utc: new Date(NOW - 60_000).toISOString() }),
      row({ id: "far-past", when_utc: new Date(NOW - 10 * 86400_000).toISOString() }),
    ];
    const { upcoming, past } = groupRows(rows, NOW);
    // Above the divider: far future → soonest (nearest to NOW at the bottom).
    expect(upcoming.map((r) => r.id)).toEqual(["far-future", "near-future"]);
    // Below the divider: freshest (nearest to NOW at the top) → far past.
    expect(past.map((r) => r.id)).toEqual(["near-past", "far-past"]);
  });
});

describe("alert config persistence", () => {
  it("preserves an explicitly empty valid lead-time list", () => {
    expect(normalizeMeetAlerts({ leadMinutes: [] }).leadMinutes).toEqual([]);
    localStorage.setItem(
      "showme.meet.alerts",
      JSON.stringify({ enabled: true, leadMinutes: [], history: [] }),
    );
    expect(loadMeetAlerts().leadMinutes).toEqual([]);
    expect(normalizeMeetAlerts({ leadMinutes: [0, "bad"] }).leadMinutes).toEqual([
      1440,
      60,
      5,
    ]);
  });
});

describe("calendar helpers — MQL5 parity", () => {
  it("parses exact FF-style prints but treats bounded prints as non-exact", () => {
    expect(parsePrintNumber("180K")).toBe(180000);
    expect(parsePrintNumber("1.40M")).toBe(1400000);
    expect(parsePrintNumber("<1.25%")).toBeNull();
    expect(parsePrintNumber(">2.0%")).toBeNull();
    expect(parsePrintNumber("3.9%")).toBe(3.9);
    expect(parsePrintNumber(4.2)).toBe(4.2);
    expect(parsePrintNumber("3-0-6")).toBeNull();
    expect(parsePrintNumber(null)).toBeNull();
    expect(parsePrintNumber("")).toBeNull();
  });

  it("computes surprise only when both prints are numeric", () => {
    expect(surpriseOf({ actual: "3.9%", forecast: "3.8%" })).toBeCloseTo(0.1);
    expect(surpriseOf({ actual: null, forecast: "3.8%" })).toBeNull();
    expect(surpriseOf({ actual: "3.9%", forecast: null })).toBeNull();
    expect(surpriseOf(null)).toBeNull();
    expect(surpriseOf({ actual: "<1.25%", forecast: "1.0%" })).toBeNull();
  });

  it("flags inverse polarity for labour-market pain gauges", () => {
    expect(polarityOf("Unemployment Rate")).toBe("inverse");
    expect(polarityOf("Initial Jobless Claims")).toBe("inverse");
    expect(polarityOf("CPI y/y")).toBe("normal");
    expect(polarityOf(null)).toBe("normal");
  });

  it("formats prints honestly without inventing values", () => {
    expect(formatPrint("3.9", "%")).toBe("3.9%");
    expect(formatPrint("180K")).toBe("180K");
    expect(formatPrint(null)).toBe("—");
    expect(formatPrint("")).toBe("—");
  });

  it("buckets days into Today / Tomorrow / date", () => {
    const today = new Date(NOW).toISOString();
    expect(dayKey(today, NOW)).toBe("Today");
    expect(dayKey(new Date(NOW + 86400_000).toISOString(), NOW)).toBe("Tomorrow");
    expect(dayKey(new Date(NOW + 5 * 86400_000).toISOString(), NOW)).toBe(
      new Date(NOW + 5 * 86400_000).toISOString().slice(0, 10),
    );
    expect(dayKey(null, NOW)).toBe("Undated");
  });

  it("labels past days honestly (Yesterday / date, never Today)", () => {
    expect(dayKey(new Date(NOW - 86400_000).toISOString(), NOW)).toBe("Yesterday");
    const fiveBack = new Date(NOW - 5 * 86400_000).toISOString();
    expect(dayKey(fiveBack, NOW)).toBe(fiveBack.slice(0, 10));
  });

  it("maps fiat codes to flag emoji, bare code otherwise", () => {
    expect(flagOf("USD")).toBe("🇺🇸");
    expect(flagOf("TRY")).toBe("🇹🇷");
    expect(flagOf("EUR")).not.toBe("");
    expect(flagOf("XAU")).toBe("");
    expect(flagOf("BTC")).toBe("");
    // A country ISO is not a fiat quote — no invented flag.
    expect(flagOf("TR")).toBe("");
    expect(flagOf(null)).toBe("");
  });

  it("groups calendar rows by day preserving order", () => {
    const a = row({ id: "a", when_utc: new Date(NOW + 3600_000).toISOString() });
    const b = row({ id: "b", when_utc: new Date(NOW + 2 * 86400_000).toISOString() });
    const groups = groupCalendarByDay([a, b], NOW);
    expect(groups.map((g) => g.key)).toEqual([
      "Today",
      new Date(NOW + 2 * 86400_000).toISOString().slice(0, 10),
    ]);
    expect(groups[0]?.rows.map((r) => r.id)).toEqual(["a"]);
  });
});

/* ── pane rendering ────────────────────────────────────────────────── */

describe("MEET pane — states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<MEETPane code="MEET" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", error: new Error("sidecar exploded") });
    render(<MEETPane code="MEET" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an honest provider_unavailable state without invented rows", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "No world-events provider responded (forex_factory calendar + news).",
          rows: [],
          upcoming: [],
          past: [],
        },
      },
    });
    render(<MEETPane code="MEET" />);
    expect(
      screen.getAllByText(/No world-events provider responded/i).length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.queryByLabelText(/UPCOMING/)).toBeNull();
  });
});

describe("MEET pane — world-events body", () => {
  function okFixture() {
    setMockFn({
      state: "ok",
      data: { data: worldPayload(), sources: ["forex_factory", "gdelt"], elapsed_ms: 42 },
    });
  }

  it("groups rows into UPCOMING and PAST with countdowns and SPOT pins", () => {
    okFixture();
    const { container } = render(<MEETPane code="MEET" />);
    expect(screen.getByLabelText(/UPCOMING/)).toBeInTheDocument();
    expect(screen.getByLabelText(/PAST/)).toBeInTheDocument();
    expect(screen.getAllByText("TCMB Interest Rate Decision").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Missile strikes hit power grid after escalation")).toBeInTheDocument();
    // Live countdown for the 2h-out TCMB decision (2h 0m adaptively).
    expect(container.textContent).toContain("2h 0m");
    // Past rows show how long ago they printed (never a countdown "now").
    expect(container.textContent).toContain("2h ago");
    // Spot pin on the central-bank decision.
    expect(screen.getAllByText("SPOT").length).toBeGreaterThanOrEqual(1);
    // Affected pairs are visible on the row.
    expect(container.textContent).toContain("USDTRY, EURTRY");
    // Next high-impact banner.
    expect(screen.getByLabelText("Next high-impact event").textContent).toContain(
      "TCMB Interest Rate Decision",
    );
  });

  it("narrows the list when a country is followed from the sidebar", () => {
    okFixture();
    const { container } = render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: /Follow Turkey/ }));
    expect(container.textContent).toContain("TCMB Interest Rate Decision");
    expect(container.textContent).not.toContain("CPI y/y");
    // The follow list is sent to the backend as the countries filter…
    expect(mockFn.lastParams?.countries).toBe("TR");
    // …and persists for the next session.
    const stored = JSON.parse(localStorage.getItem("showme.meet.alerts") ?? "{}");
    expect(stored.spotCountries).toContain("TR");
  });

  it("fires the lead-time toast once and records it in the alert history", () => {
    const payload = worldPayload();
    // TCMB 3 minutes out → the 5m lead crosses at mount.
    const soon = new Date(Date.now() + 3 * 60_000).toISOString();
    payload.rows = payload.rows.map((r) =>
      r.id === "economic:tcmb" ? { ...r, when_utc: soon } : r,
    );
    payload.upcoming = payload.rows.filter((r) => r.id !== "world:war");
    setMockFn({ state: "ok", data: { data: payload, sources: [], elapsed_ms: 1 } });
    render(<MEETPane code="MEET" />);
    expect(toastWarn).toHaveBeenCalledTimes(1);
    expect(String(toastWarn.mock.calls[0]?.[0])).toContain("MEET spot");
    const stored = JSON.parse(localStorage.getItem("showme.meet.alerts") ?? "{}");
    expect(stored.history.length).toBeGreaterThanOrEqual(1);
    expect(stored.history[0].lead).toBe(5);
  });

  it("shows the detail card with affected pairs and source on row click", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    fireEvent.click(
      screen.getByRole("button", { name: /TCMB Interest Rate Decision/ }),
    );
    const detail = screen.getByLabelText("Event detail");
    expect(detail.textContent).toContain("USDTRY");
    expect(detail.textContent).toContain("forex_factory");
    expect(detail.textContent).toContain("Turkey (TR)");
  });

  it("shows the alert-settings popover with lead times", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: "MEET alert settings" }));
    expect(screen.getByTestId("meet-alerts-popover")).toBeInTheDocument();
    expect(screen.getByText(/LEAD TIMES/i)).toBeInTheDocument();
  });

  it("keeps the follow list usable when a catalog country has no events", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    const sidebar = screen.getByLabelText("Country status");
    expect(sidebar.textContent).toContain("quiet");
    expect(screen.getByRole("button", { name: /Follow Ukraine/ })).toBeInTheDocument();
  });

  it("names filter-excluded upcoming events instead of claiming none exist", () => {
    // Regression: the rail (unfiltered country_index) showed EU SOON while
    // the follow-filtered list said "No upcoming events in the window".
    const base = worldPayload();
    const quiet = (iso: string, name: string) => ({
      iso,
      name,
      upcoming_count: 0,
      past_count: 1,
      state: "quiet",
      next_event: null,
    });
    const payload = {
      ...base,
      rows: base.past,
      upcoming: [],
      past: base.past,
      row_count: base.past.length,
      upcoming_count: 0,
      past_count: base.past.length,
      unfiltered_upcoming_count: 1,
      window: {
        ...base.window,
        upcoming_count: 0,
        past_count: base.past.length,
        earliest_upcoming_utc: null,
        next_high_impact: null,
      },
      country_index: [
        quiet("TR", "Turkey"),
        quiet("US", "United States"),
        quiet("RU", "Russia"),
        quiet("UA", "Ukraine"),
        {
          iso: "EU",
          name: "Euro Area",
          upcoming_count: 1,
          past_count: 0,
          state: "soon",
          next_event: {
            id: "economic:ecofin",
            title: "ECOFIN Meetings",
            when_utc: new Date(NOW + 13 * 3600_000).toISOString(),
            seconds_to_event: 46800,
            impact: "low",
            spot: false,
            kind: "economic",
          },
        },
      ],
    };
    setMockFn({
      state: "ok",
      data: { data: payload, sources: ["forex_factory"], elapsed_ms: 80 },
    });
    const { container } = render(<MEETPane code="MEET" />);
    expect(container.textContent).toContain("outside your filters");
    expect(container.textContent).toContain("ECOFIN Meetings");
  });
});

describe("MEET pane — mode tabs (calendar / wire)", () => {
  function calendarPayload() {
    // Anchor CPI to tomorrow 12:00 UTC: a fixed "+26h" offset lands on the
    // day after tomorrow when the suite runs after 22:00 UTC and the
    // "Tomorrow" bucket assertion flakes by time of day.
    const nowMs = Date.now();
    const nowDate = new Date(nowMs);
    const dayStart = Date.UTC(
      nowDate.getUTCFullYear(),
      nowDate.getUTCMonth(),
      nowDate.getUTCDate(),
    );
    const tomorrowNoon = dayStart + 36 * 3600_000;
    const cpi = row({
      id: "economic:us-cpi",
      title: "CPI y/y",
      currencies: ["USD"],
      when_utc: new Date(tomorrowNoon).toISOString(),
      seconds_to_event: Math.round((tomorrowNoon - nowMs) / 1000),
      details: { actual: "3.9%", forecast: "3.8%", previous: "3.7%", unit: "" },
    });
    const pending = row({
      id: "economic:us-nfp",
      title: "Nonfarm Payrolls",
      currencies: ["USD"],
      when_utc: new Date(Date.now() + 50 * 3600_000).toISOString(),
      seconds_to_event: 50 * 3600,
      details: { actual: null, forecast: "180K", previous: "175K", unit: "" },
    });
    const unemp = row({
      id: "economic:us-unemp",
      title: "Unemployment Rate",
      currencies: ["USD"],
      when_utc: new Date(Date.now() + 74 * 3600_000).toISOString(),
      seconds_to_event: 74 * 3600,
      details: { actual: "4.2%", forecast: "4.0%", previous: "4.0%", unit: "" },
    });
    const btcWire = row({
      id: "world:btc",
      kind: "world",
      title: "Bitcoin ETF inflows hit record",
      countries: [],
      country_names: [],
      impact: "medium",
      source: "rss",
      pairs: ["BTCUSD"],
      when_utc: new Date(Date.now() - 3600_000).toISOString(),
      seconds_to_event: -3600,
      details: { asset_tags: ["BTC", "ETF"], topic_tags: [], summary: "ETF inflows" },
      summary: "ETF inflows",
    });
    return { ...worldPayload(), rows: [cpi, pending, unemp, btcWire] };
  }

  function okCalendarFixture() {
    setMockFn({
      state: "ok",
      data: { data: calendarPayload(), sources: ["forex_factory", "rss"], elapsed_ms: 7 },
    });
  }

  it("sends mode/tags/data_filter params and persists the mode tab", () => {
    okCalendarFixture();
    render(<MEETPane code="MEET" />);
    expect(mockFn.lastParams?.mode).toBe("all");
    expect(mockFn.lastParams?.data_filter).toBe("all");
    expect(mockFn.lastParams).toHaveProperty("tags");
    // All mode keeps the mixed list with no asset chips and no table.
    expect(screen.queryByLabelText(/^asset tags:/)).toBeNull();
    expect(screen.queryByText("Forecast")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Wire" }));
    expect(mockFn.lastParams?.mode).toBe("wire");
    expect(localStorage.getItem("showme.meet.mode")).toBe("wire");
  });

  it("calendar mode renders the MQL5-parity table with pending rows", () => {
    localStorage.setItem("showme.meet.mode", "calendar");
    okCalendarFixture();
    const { container } = render(<MEETPane code="MEET" />);
    for (const header of ["Actual", "Forecast", "Previous", "Surprise"]) {
      expect(screen.getAllByText(header).length).toBeGreaterThanOrEqual(1);
    }
    // Printed values land in their columns; the pending release is honest.
    expect(container.textContent).toContain("3.9%");
    expect(container.textContent).toContain("180K");
    expect(screen.getAllByText("pending").length).toBeGreaterThanOrEqual(1);
    // Day buckets group the upcoming releases.
    expect(container.textContent).toContain("Tomorrow");
    // Surprise chips: CPI beats (▲) while the unemployment beat flips (▼).
    const chips = screen.getAllByRole("status");
    expect(chips.some((c) => c.textContent?.includes("▲"))).toBe(true);
    expect(chips.some((c) => c.textContent?.includes("▼"))).toBe(true);
  });

  it("calendar row click opens the detail card with the Actual print", () => {
    localStorage.setItem("showme.meet.mode", "calendar");
    okCalendarFixture();
    render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByText("CPI y/y"));
    const detail = screen.getByLabelText("Event detail");
    expect(detail.textContent).toContain("3.9%");
  });

  it("wire mode shows asset chips on world rows", () => {
    localStorage.setItem("showme.meet.mode", "wire");
    okCalendarFixture();
    render(<MEETPane code="MEET" />);
    expect(screen.getByLabelText("asset tags: BTC, ETF")).toBeInTheDocument();
    // The mixed list is kept — wire only adds the chips.
    expect(screen.getByLabelText(/UPCOMING/)).toBeInTheDocument();
  });

  it("tags input and data filter narrow the request and persist", () => {
    okCalendarFixture();
    render(<MEETPane code="MEET" />);
    fireEvent.change(screen.getByLabelText("Filter by asset tags"), {
      target: { value: "BTC" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));
    expect(mockFn.lastParams?.tags).toBe("BTC");
    expect(localStorage.getItem("showme.meet.tags")).toBe("BTC");
    fireEvent.change(screen.getByLabelText("Data filter"), {
      target: { value: "with_actual" },
    });
    expect(mockFn.lastParams?.data_filter).toBe("with_actual");
    expect(localStorage.getItem("showme.meet.data-filter")).toBe("with_actual");
  });

  it("empty tags submit clears the persisted filter", () => {
    okCalendarFixture();
    render(<MEETPane code="MEET" />);
    const input = screen.getByLabelText("Filter by asset tags");
    const button = screen.getByRole("button", { name: "Tag" });
    // Nothing applied and draft empty → no-op submit stays disabled.
    expect(button).toBeDisabled();
    fireEvent.change(input, { target: { value: "BTC" } });
    fireEvent.click(button);
    expect(mockFn.lastParams?.tags).toBe("BTC");
    expect(localStorage.getItem("showme.meet.tags")).toBe("BTC");
    // Clearing the box must NOT trap the filter: the button stays active…
    fireEvent.change(input, { target: { value: "" } });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    // …and the empty submit clears the applied tags + persist.
    expect(mockFn.lastParams?.tags).toBe("");
    expect(localStorage.getItem("showme.meet.tags")).toBe("");
  });
});

describe("MEET pane — realtime delta (Faz 5)", () => {
  // Far-future rows keep the lead-time toast motor quiet so the delta
  // cursor and the new_rows toast are isolated.
  function deltaFixture() {
    const base = worldPayload();
    const far = (days: number) => new Date(Date.now() + days * 86400_000).toISOString();
    const a = row({
      id: "economic:delta-a",
      title: "Delta CPI y/y",
      impact: "medium",
      spot: false,
      pinned: false,
      when_utc: far(30),
      seconds_to_event: 30 * 86400,
    });
    const b = row({
      id: "world:delta-b",
      kind: "world",
      title: "Delta wire headline",
      countries: [],
      country_names: [],
      impact: "low",
      source: "rss",
      pairs: [],
      spot: false,
      pinned: false,
      when_utc: far(31),
      seconds_to_event: 31 * 86400,
    });
    return {
      ...base,
      as_of: new Date().toISOString(),
      rows: [a, b],
      upcoming: [a, b],
      past: [],
      row_count: 2,
      upcoming_count: 2,
      past_count: 0,
      hash: "hash-1",
      new_rows: [],
      removed_ids: [],
      since_echo: "",
    };
  }

  it("poll tick sends since/known_ids and adopts non-row changes on identical hash", () => {
    mockTick.current = 0;
    localStorage.setItem(
      "showme.meet.alerts",
      JSON.stringify({ symbols: ["BTC"], leadMinutes: [], history: [] }),
    );
    const first = deltaFixture();
    setMockFn({
      state: "ok",
      data: { data: first, sources: ["forex_factory"], elapsed_ms: 1 },
    });
    const { container, rerender } = render(<MEETPane code="MEET" />);
    expect(screen.getByLabelText(/UPCOMING/)).toBeInTheDocument();
    // First load carries no delta cursor (backend backward-compat path).
    expect(mockFn.lastParams?.since).toBeUndefined();
    expect(mockFn.lastParams?.known_ids).toBeUndefined();
    const refreshed = {
      ...first,
      status: "degraded",
      reason: "fresh provider warning",
      as_of: new Date(Date.parse(first.as_of) + 30_000).toISOString(),
      rows: first.rows.map((item) =>
        item.id === "economic:delta-a"
          ? {
              ...item,
              details: {
                ...item.details,
                actual: "4.1%",
                forecast: "4.0%",
                previous: "3.8%",
              },
            }
          : item,
      ),
      country_index: first.country_index.map((entry) =>
        entry.iso === "TR" ? { ...entry, state: "live" } : entry,
      ),
      alerts: [
        {
          id: "economic:server-refresh",
          kind: "economic",
          title: "Fresh server alert",
          when_utc: new Date(Date.now() + 3600_000).toISOString(),
          seconds_to_event: 3600,
          countries: ["TR"],
          country_names: ["Turkey"],
          pairs: ["USDTRY"],
          impact: "high",
          spot: true,
          pinned: false,
          source: "forex_factory",
          lead_minutes: [60],
        },
      ],
      symbol_rows: [
        row({
          id: "world:symbol-refresh",
          kind: "world",
          title: "Fresh symbol-only headline",
          countries: [],
          country_names: [],
          source: "rss",
          symbol_matches: ["BTC"],
        }),
      ],
    };
    mockTick.current = 1;
    setMockFn({
      state: "ok",
      data: { data: refreshed, sources: ["forex_factory"], elapsed_ms: 1 },
    });
    rerender(<MEETPane code="MEET" />);
    expect(mockRefetch).toHaveBeenCalled();
    expect(mockFn.lastParams?.since).toBe(first.as_of);
    expect(String(mockFn.lastParams?.known_ids)).toContain("economic:delta-a");
    expect(String(mockFn.lastParams?.known_ids)).toContain("world:delta-b");
    // Identical row hash still carries fresh mutable fields and side sections.
    expect(toastWarn).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Fresh symbol-only headline");
    expect(container.textContent).toContain("degraded");
    expect(container.textContent).toContain(refreshed.as_of.slice(11, 19));
    expect(screen.getByRole("button", { name: "Follow Turkey" }).textContent).toContain("live");
    fireEvent.click(screen.getByRole("button", { name: /Delta CPI y\/y/ }));
    const detail = screen.getByLabelText("Event detail");
    expect(detail.textContent).toContain("4.1%");
    expect(detail.textContent).toContain("4.0%");
    expect(detail.textContent).toContain("3.8%");
    fireEvent.click(screen.getByRole("button", { name: "MEET alert settings" }));
    expect(screen.getByTestId("meet-alerts-popover").textContent).toContain(
      "Fresh server alert",
    );

    setMockFn({
      state: "ok",
      data: {
        data: {
          ...refreshed,
          status: "provider_unavailable",
          reason: "Fresh provider reason",
        },
        sources: [],
        elapsed_ms: 1,
      },
    });
    rerender(<MEETPane code="MEET" />);
    expect(screen.getAllByText("Fresh provider reason").length).toBeGreaterThan(0);
  });

  it("toasts a fresh SPOT row arriving in new_rows", () => {
    mockTick.current = 0;
    const first = deltaFixture();
    setMockFn({
      state: "ok",
      data: { data: first, sources: ["forex_factory"], elapsed_ms: 1 },
    });
    const { rerender } = render(<MEETPane code="MEET" />);
    expect(toastWarn).not.toHaveBeenCalled();
    const spot = row({
      id: "world:delta-war",
      kind: "world",
      title: "Delta invasion escalation",
      countries: ["RU"],
      country_names: ["Russia"],
      impact: "high",
      source: "gdelt",
      spot: true,
      when_utc: new Date(Date.now() + 2 * 86400_000).toISOString(),
      seconds_to_event: 2 * 86400,
    });
    const second = {
      ...first,
      hash: "hash-2",
      rows: [...first.rows, spot],
      upcoming: [...first.upcoming, spot],
      upcoming_count: 3,
      row_count: 3,
      new_rows: [spot],
      removed_ids: [],
    };
    setMockFn({
      state: "ok",
      data: { data: second, sources: ["forex_factory"], elapsed_ms: 1 },
    });
    rerender(<MEETPane code="MEET" />);
    expect(toastWarn).toHaveBeenCalledTimes(1);
    expect(String(toastWarn.mock.calls[0]?.[0])).toContain("MEET spot");
    expect(String(toastWarn.mock.calls[0]?.[0])).toContain("Delta invasion escalation");
    expect(screen.getByText("Delta invasion escalation")).toBeInTheDocument();
  });

  it("persists delta arrivals as arrival history and dedupes them after remount", () => {
    const first = deltaFixture();
    setMockFn({
      state: "ok",
      data: { data: first, sources: ["forex_factory"], elapsed_ms: 1 },
    });
    const mounted = render(<MEETPane code="MEET" />);
    const spot = row({
      id: "world:persistent-arrival",
      kind: "world",
      title: "Persistent arrival",
      countries: ["UA"],
      country_names: ["Ukraine"],
      source: "gdelt",
      impact: "high",
      spot: true,
      when_utc: new Date(Date.now() + 3 * 86400_000).toISOString(),
    });
    const second = {
      ...first,
      hash: "hash-arrival",
      rows: [...first.rows, spot],
      upcoming: [...first.upcoming, spot],
      new_rows: [spot],
    };
    setMockFn({
      state: "ok",
      data: { data: second, sources: ["forex_factory"], elapsed_ms: 1 },
    });
    mounted.rerender(<MEETPane code="MEET" />);
    expect(toastWarn).toHaveBeenCalledTimes(1);
    const stored = JSON.parse(localStorage.getItem("showme.meet.alerts") ?? "{}");
    expect(stored.history[0]).toMatchObject({
      key: "delta:world:persistent-arrival",
      lead: null,
      title: "Persistent arrival",
    });

    mounted.unmount();
    setMockFn({
      state: "ok",
      data: { data: first, sources: ["forex_factory"], elapsed_ms: 1 },
    });
    const remounted = render(<MEETPane code="MEET" />);
    setMockFn({
      state: "ok",
      data: { data: second, sources: ["forex_factory"], elapsed_ms: 1 },
    });
    remounted.rerender(<MEETPane code="MEET" />);
    expect(toastWarn).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "MEET alert settings" }));
    expect(screen.getByTestId("meet-alerts-popover").textContent).toContain("arrival");
  });

  it("does not toast delta rows while establishing a changed filter baseline", () => {
    const first = deltaFixture();
    setMockFn({ state: "ok", data: { data: first, sources: [], elapsed_ms: 1 } });
    const { rerender } = render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: "high" }));
    const spot = row({ id: "world:rebaseline", title: "Rebaseline row", spot: true });
    setMockFn({
      state: "ok",
      data: {
        data: { ...first, hash: "hash-filter", rows: [spot], upcoming: [spot], new_rows: [spot] },
        sources: [],
        elapsed_ms: 1,
      },
    });
    rerender(<MEETPane code="MEET" />);
    expect(toastWarn).not.toHaveBeenCalled();
  });
});

describe("MEET pane - filter bar fixes", () => {
  function okFixture() {
    setMockFn({
      state: "ok",
      data: { data: worldPayload(), sources: ["forex_factory"], elapsed_ms: 5 },
    });
  }

  it("query Find submits and empty submit clears the filter", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    const input = screen.getByLabelText("Search world events");
    expect(screen.getByRole("button", { name: "Find" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "cpi" } });
    fireEvent.click(screen.getByRole("button", { name: "Find" }));
    expect(mockFn.lastParams?.query).toBe("cpi");
    // Clearing the draft must NOT disable Find while a query is applied,
    // otherwise the filter is a trap with no way out.
    fireEvent.change(input, { target: { value: "" } });
    const findAgain = screen.getByRole("button", { name: "Find" });
    expect(findAgain).not.toBeDisabled();
    fireEvent.click(findAgain);
    expect(mockFn.lastParams?.query).toBe("");
  });

  it("disables KIND while MODE overrides it", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: "Wire" }));
    expect(mockFn.lastParams?.mode).toBe("wire");
    expect(screen.getByRole("button", { name: "World" })).toBeDisabled();
  });

  it("alert settings popover has an explicit close button", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: "MEET alert settings" }));
    expect(screen.getByTestId("meet-alerts-popover")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close alert settings" }));
    expect(screen.queryByTestId("meet-alerts-popover")).toBeNull();
  });
});

describe("MEET pane — Task C UI parity", () => {
  function okFixture() {
    setMockFn({
      state: "ok",
      data: { data: worldPayload(), sources: ["forex_factory"], elapsed_ms: 5 },
    });
  }

  function serverAlert(overrides: Record<string, unknown> = {}) {
    return {
      id: "economic:tcmb",
      kind: "economic",
      title: "TCMB Interest Rate Decision",
      when_utc: new Date(NOW + 2 * 3600_000).toISOString(),
      seconds_to_event: 7200,
      countries: ["TR"],
      country_names: ["Turkey"],
      pairs: ["USDTRY", "EURTRY"],
      impact: "high",
      spot: true,
      pinned: true,
      source: "forex_factory",
      lead_minutes: [1440, 60, 5],
      ...overrides,
    };
  }

  it("shows the read-only SERVER SPOT section when the backend ships alerts", () => {
    const payload = worldPayload();
    (payload as Record<string, unknown>).alerts = [serverAlert()];
    setMockFn({
      state: "ok",
      data: { data: payload, sources: ["forex_factory"], elapsed_ms: 5 },
    });
    render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: "MEET alert settings" }));
    const popover = screen.getByTestId("meet-alerts-popover");
    expect(popover.textContent).toContain("SERVER SPOT (upcoming)");
    expect(popover.textContent).toContain("TCMB Interest Rate Decision");
    expect(popover.textContent).toContain("Turkey");
    expect(popover.textContent).toContain("USDTRY");
    // Lead minutes ride along read-only (1d · 1h · 5m).
    expect(popover.textContent).toContain("1d");
  });

  it("hides the SERVER SPOT section when the backend ships no alerts", () => {
    okFixture(); // worldPayload() carries alerts: []
    render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: "MEET alert settings" }));
    expect(screen.getByTestId("meet-alerts-popover")).toBeInTheDocument();
    expect(screen.queryByText(/SERVER SPOT/)).toBeNull();
  });

  it("shows event_type and provider tags in the detail card audit row", () => {
    const tagged = row({
      id: "world:btc-etf",
      kind: "world",
      title: "Bitcoin ETF inflows hit record",
      countries: [],
      country_names: [],
      impact: "medium",
      source: "rss",
      pairs: ["BTCUSD"],
      when_utc: new Date(NOW - 3600_000).toISOString(),
      seconds_to_event: -3600,
      details: {
        event_type: "etf_flow",
        provider_tags: ["ETF", "BTC"],
        asset_tags: ["BTC", "ETF"],
        topic_tags: [],
        summary: "ETF inflows",
      },
      summary: "ETF inflows",
    });
    const payload = { ...worldPayload(), rows: [tagged] };
    setMockFn({
      state: "ok",
      data: { data: payload, sources: ["rss"], elapsed_ms: 5 },
    });
    render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: /Bitcoin ETF inflows/ }));
    const detail = screen.getByLabelText("Event detail");
    expect(detail.textContent).toContain("etf_flow");
    expect(detail.textContent).toContain("ETF");
    expect(detail.textContent).toContain("BTC");
  });

  it("shows RSS publisher and article provenance while keeping an undated row undated", () => {
    const undated = row({
      id: "world:undated:wire",
      kind: "world",
      title: "Undated wire item",
      source: "rss",
      undated: true,
      when_utc: null,
      details: {
        publisher: "Example Wire",
        feed_url: "https://example.test/feed.xml",
        article_url: "https://example.test/story",
      },
    });
    setMockFn({
      state: "ok",
      data: { data: { ...worldPayload(), rows: [undated] }, sources: ["rss"], elapsed_ms: 5 },
    });
    render(<MEETPane code="MEET" />);
    fireEvent.click(screen.getByRole("button", { name: /Undated wire item/ }));
    const detail = screen.getByLabelText("Event detail");
    expect(detail.textContent).toContain("undated wire");
    expect(detail.textContent).toContain("Example Wire");
    expect(screen.getByRole("link", { name: /open source/i })).toHaveAttribute(
      "href",
      "https://example.test/story",
    );
  });

  it("renders observable quality counts and required FinanceCalendar attribution", () => {
    const payload = {
      ...worldPayload(),
      data_quality: {
        row_count: 3,
        timed_count: 2,
        undated_count: 1,
        source_traceable_count: 3,
        url_traceable_count: 1,
        attribution_required_count: 1,
        attribution_covered_count: 1,
        duplicate_rows_dropped: 2,
        rows_dropped_no_time: 1,
        active_source_tiers: ["keyless_fallback", "future_supplement"],
        measures: "observable_completeness_not_factual_accuracy",
      },
      attributions: [{
        name: "FinanceCalendar.com",
        url: "https://www.financecalendar.com/",
        text: "Economic calendar data by FinanceCalendar.com",
      }],
    };
    setMockFn({ state: "ok", data: { data: payload, sources: ["forex_factory", "financecalendar"], elapsed_ms: 5 } });
    render(<MEETPane code="MEET" />);
    const quality = screen.getByLabelText("MEET data quality");
    expect(quality.textContent).toContain("3 rows");
    expect(quality.textContent).toContain("1 undated");
    expect(quality.textContent).toContain("2 duplicates dropped");
    expect(screen.getByRole("link", { name: /FinanceCalendar\.com/i })).toHaveAttribute(
      "href",
      "https://www.financecalendar.com/",
    );
  });

  it("explains per-row why a headline rides in YOUR SYMBOLS", () => {
    localStorage.setItem("showme.meet.alerts", JSON.stringify({ symbols: ["BTC"] }));
    const matched = row({
      id: "world:btc",
      kind: "world",
      title: "Bitcoin ETF inflows hit record",
      countries: [],
      country_names: [],
      impact: "medium",
      source: "rss",
      pairs: ["BTCUSD"],
      when_utc: new Date(NOW - 3600_000).toISOString(),
      seconds_to_event: -3600,
      symbol_matches: ["BTC"],
    });
    const marketWide = row({
      id: "economic:fomc",
      title: "FOMC Interest Rate Decision",
      impact: "high",
      when_utc: new Date(NOW + 5 * 86400_000).toISOString(),
      seconds_to_event: 5 * 86400,
      symbol_matches: ["all markets"],
      symbol_relevance: "market_wide",
    });
    const payload = { ...worldPayload(), symbol_rows: [matched, marketWide] };
    setMockFn({
      state: "ok",
      data: { data: payload, sources: ["forex_factory", "rss"], elapsed_ms: 5 },
    });
    const { container } = render(<MEETPane code="MEET" />);
    expect(container.textContent).toContain("why here: BTC");
    expect(container.textContent).toContain("why here: all markets · market_wide");
  });

  it("opens and toggles the detail card for a symbol-only row", () => {
    localStorage.setItem(
      "showme.meet.alerts",
      JSON.stringify({ symbols: ["BTC"], leadMinutes: [], history: [] }),
    );
    const symbolOnly = row({
      id: "world:symbol-only",
      kind: "world",
      title: "Symbol-only detail headline",
      countries: [],
      country_names: [],
      source: "rss",
      pairs: ["BTCUSD"],
      symbol_matches: ["BTC"],
      summary: "Only present in symbol_rows.",
    });
    const payload = { ...worldPayload(), symbol_rows: [symbolOnly] };
    setMockFn({ state: "ok", data: { data: payload, sources: ["rss"], elapsed_ms: 5 } });
    render(<MEETPane code="MEET" />);
    const rowButton = screen.getByRole("button", { name: /Symbol-only detail headline/ });
    fireEvent.click(rowButton);
    expect(screen.getByLabelText("Event detail").textContent).toContain("BTCUSD");
    fireEvent.click(rowButton);
    expect(screen.queryByLabelText("Event detail")).toBeNull();
  });

  it("shows bounded actual text without an exact surprise direction", () => {
    localStorage.setItem("showme.meet.mode", "calendar");
    const bounded = row({
      id: "economic:bounded",
      title: "Bounded release",
      when_utc: new Date(Date.now() + 86400_000).toISOString(),
      details: { actual: "<1.25%", forecast: "1.00%", previous: "1.10%", unit: "" },
    });
    const payload = { ...worldPayload(), rows: [bounded], upcoming: [bounded], past: [] };
    setMockFn({ state: "ok", data: { data: payload, sources: [], elapsed_ms: 5 } });
    const { container } = render(<MEETPane code="MEET" />);
    expect(container.textContent).toContain("<1.25%");
    expect(container.textContent).not.toMatch(/[▲▼]/);
  });

  it("uses backend event totals for the outside-filter count without country duplication", () => {
    const base = worldPayload();
    const shared = {
      id: "economic:shared",
      title: "Shared multi-country event",
      when_utc: new Date(Date.now() + 3600_000).toISOString(),
      seconds_to_event: 3600,
      impact: "high",
      kind: "economic",
    };
    const payload = {
      ...base,
      rows: [],
      upcoming: [],
      past: [],
      upcoming_count: 0,
      unfiltered_upcoming_count: 1,
      window: { ...base.window, upcoming_count: 0, next_high_impact: null },
      country_index: [
        { iso: "US", name: "United States", upcoming_count: 1, past_count: 0, state: "soon", next_event: shared },
        { iso: "CA", name: "Canada", upcoming_count: 1, past_count: 0, state: "soon", next_event: shared },
      ],
      country_catalog: [
        { iso: "US", name: "United States" },
        { iso: "CA", name: "Canada" },
      ],
    };
    setMockFn({ state: "ok", data: { data: payload, sources: [], elapsed_ms: 5 } });
    const { container } = render(<MEETPane code="MEET" />);
    expect(container.textContent).toContain("1 upcoming outside your filters");
    expect(container.textContent).not.toContain("2 upcoming outside your filters");
  });

  it("expires next-high, country state, and server alerts from the live clock", () => {
    vi.useFakeTimers();
    try {
      const baseNow = new Date("2026-09-19T12:00:00.000Z");
      vi.setSystemTime(baseNow);
      localStorage.setItem(
        "showme.meet.alerts",
        JSON.stringify({ leadMinutes: [], history: [] }),
      );
      const first = row({
        id: "economic:first",
        title: "First high event",
        when_utc: new Date(baseNow.getTime() + 1_000).toISOString(),
        impact: "high",
      });
      const second = row({
        id: "economic:second",
        title: "Second high event",
        when_utc: new Date(baseNow.getTime() + 5_000).toISOString(),
        impact: "high",
      });
      const payload = {
        ...worldPayload(),
        as_of: baseNow.toISOString(),
        rows: [second, first],
        upcoming: [second, first],
        past: [],
        window: {
          upcoming_count: 2,
          past_count: 0,
          next_high_impact: {
            id: first.id,
            title: first.title,
            when_utc: first.when_utc,
            impact: "high",
            country_names: ["United States"],
          },
        },
        country_index: [
          {
            iso: "US",
            name: "United States",
            upcoming_count: 1,
            past_count: 0,
            state: "imminent",
            next_event: { id: first.id, title: first.title, when_utc: first.when_utc, impact: "high" },
          },
        ],
        country_catalog: [{ iso: "US", name: "United States" }],
        alerts: [
          {
            id: first.id,
            kind: "economic",
            title: first.title,
            when_utc: first.when_utc,
            seconds_to_event: 1,
            countries: ["US"],
            country_names: ["United States"],
            pairs: [],
            impact: "high",
            spot: true,
            pinned: false,
            source: "forex_factory",
            lead_minutes: [5],
          },
        ],
      };
      setMockFn({ state: "ok", data: { data: payload, sources: [], elapsed_ms: 5 } });
      render(<MEETPane code="MEET" />);
      expect(screen.getByLabelText("Next high-impact event").textContent).toContain(first.title);
      fireEvent.click(screen.getByRole("button", { name: "MEET alert settings" }));
      expect(screen.getByTestId("meet-alerts-popover").textContent).toContain("SERVER SPOT");

      act(() => vi.advanceTimersByTime(2_000));

      expect(screen.getByLabelText("Next high-impact event").textContent).toContain(second.title);
      expect(screen.getByLabelText("Next high-impact event").textContent).not.toContain(first.title);
      expect(screen.getByLabelText("UPCOMING · 1")).toBeInTheDocument();
      expect(screen.getByLabelText("PAST · 1")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Follow United States" }).textContent).toContain("quiet");
      expect(screen.getByTestId("meet-alerts-popover").textContent).not.toContain("SERVER SPOT");
    } finally {
      vi.useRealTimers();
    }
  });

  it("discloses untimed drops, window coverage and methodology in the footer", () => {
    const payload = {
      ...worldPayload(),
      dropped_no_time: 2,
      unfiltered_upcoming_count: 5,
      methodology: "Keyless calendar plus gazetteer-tagged wire.",
    };
    setMockFn({
      state: "ok",
      data: { data: payload, sources: ["forex_factory"], elapsed_ms: 5 },
    });
    render(<MEETPane code="MEET" />);
    expect(screen.getByText("2 untimed rows hidden")).toBeInTheDocument();
    expect(screen.getByText("showing 2 of 5 upcoming")).toBeInTheDocument();
    const info = screen.getByLabelText("Methodology");
    expect(info.getAttribute("title")).toContain("gazetteer-tagged wire");
  });

  it("offers a persisted limit select defaulting to 400", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    const select = screen.getByLabelText("Result limit") as HTMLSelectElement;
    expect(select.value).toBe("400");
    for (const n of ["100", "250", "400", "1000"]) {
      expect(select.querySelector(`option[value="${n}"]`)).not.toBeNull();
    }
    expect(mockFn.lastParams?.limit).toBe(400);
    fireEvent.change(select, { target: { value: "1000" } });
    expect(mockFn.lastParams?.limit).toBe(1000);
    expect(localStorage.getItem("showme.meet.limit")).toBe("1000");
  });

  it("no longer sends include_world (backend defaults it true)", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    expect(mockFn.lastParams).not.toHaveProperty("include_world");
  });

  it("offers major_only as an honestly-labelled majors-only cut", () => {
    okFixture();
    render(<MEETPane code="MEET" />);
    const select = screen.getByLabelText("Data filter") as HTMLSelectElement;
    const values = Array.from(select.querySelectorAll("option")).map((o) => o.value);
    expect(values).toEqual([
      "all",
      "spot",
      "pinned",
      "major_only",
      "with_forecast",
      "with_actual",
      "surprise_only",
    ]);
    const option = select.querySelector('option[value="major_only"]');
    expect(option).not.toBeNull();
    expect(option?.textContent).toContain("majors-only cut");
    expect(select.title).toContain("majors-only cut");
    expect(select.title).toContain("spot/pinned rows survive");
    fireEvent.change(select, { target: { value: "major_only" } });
    expect(mockFn.lastParams?.data_filter).toBe("major_only");
    expect(localStorage.getItem("showme.meet.data-filter")).toBe("major_only");
  });
});

/* ── contracts/meet.json consumer (Gate-3) ─────────────────────────── */

describe("MEET pane — contracts/meet.json consumer (Gate-3)", () => {
  interface MeetContract {
    data_filter_values: string[];
    mode_options: string[];
  }

  async function readMeetContract(): Promise<MeetContract> {
    // tsconfig'e dokunmadan (resolveJsonModule yok): fs + JSON.parse.
    const { readFileSync } = await import("node:fs");
    const { dirname, join } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const contractPath = join(
      dirname(fileURLToPath(import.meta.url)),
      "..",
      "..",
      "..",
      "contracts",
      "meet.json",
    );
    const raw = JSON.parse(readFileSync(contractPath, "utf-8")) as {
      data_filter_values?: unknown;
      inputs?: Array<{ name?: unknown; options?: unknown }>;
    };
    const dataFilterValues = Array.isArray(raw.data_filter_values)
      ? (raw.data_filter_values as unknown[]).map(String)
      : [];
    const modeInput = (Array.isArray(raw.inputs) ? raw.inputs : []).find(
      (entry) => entry?.name === "mode",
    );
    const modeOptions = Array.isArray(modeInput?.options)
      ? (modeInput.options as unknown[]).map(String)
      : [];
    return { data_filter_values: dataFilterValues, mode_options: modeOptions };
  }

  function okContractFixture() {
    setMockFn({
      state: "ok",
      data: { data: worldPayload(), sources: ["forex_factory"], elapsed_ms: 5 },
    });
  }

  it("DATA select options match contracts/meet.json data_filter_values (order-insensitive)", async () => {
    const contract = await readMeetContract();
    expect(contract.data_filter_values.length).toBeGreaterThan(0);
    okContractFixture();
    render(<MEETPane code="MEET" />);
    const select = screen.getByLabelText("Data filter") as HTMLSelectElement;
    const uiValues = Array.from(select.querySelectorAll("option")).map((o) => o.value);
    expect([...uiValues].sort()).toEqual([...contract.data_filter_values].sort());
  });

  it("mode options match contracts/meet.json inputs mode options", async () => {
    const contract = await readMeetContract();
    expect(contract.mode_options.length).toBeGreaterThan(0);
    okContractFixture();
    const { container } = render(<MEETPane code="MEET" />);
    const section = container.querySelector('section[aria-label="World-event filters"]');
    expect(section).not.toBeNull();
    // First filter row holds MODE (segmented buttons carry aria-pressed);
    // the Tag submit has no aria-pressed so it is excluded.
    const firstRow = section?.children[0];
    expect(firstRow?.textContent).toContain("MODE");
    const uiModes = Array.from(
      firstRow?.querySelectorAll("button[aria-pressed]") ?? [],
    ).map((b) => (b.textContent ?? "").trim().toLowerCase());
    expect([...uiModes].sort()).toEqual([...contract.mode_options].sort());
  });
});
