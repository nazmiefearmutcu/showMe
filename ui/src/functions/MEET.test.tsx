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
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MEETPane } from "./MEET";
import {
  dueAlert,
  formatAge,
  formatCountdown,
  groupRows,
  isSpotFor,
  leadLabel,
  normalizeMeetAlerts,
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
      refetch: vi.fn(),
    };
  },
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
    const nowMs = Date.parse(spot.when_utc) - 3 * 60_000; // 3 min out
    const first = dueAlert(spot, config, nowMs, new Set());
    expect(first?.lead).toBe(5);
    const fired = new Set([first!.key]);
    expect(dueAlert(spot, config, nowMs + 1000, fired)).toBeNull();
    // It does not back-fill the larger leads after the imminent one fired.
    expect(dueAlert(spot, config, Date.parse(spot.when_utc) - 60_000, fired)).toBeNull();
  });

  it("moves to the next lead as the event approaches", () => {
    const t60 = Date.parse(spot.when_utc) - 30 * 60_000; // 30 min out → only 60/1440 crossed
    const hit = dueAlert(spot, config, t60, new Set());
    expect(hit?.lead).toBe(60);
    const fired = new Set([hit!.key]);
    const later = dueAlert(spot, config, Date.parse(spot.when_utc) - 4 * 60_000, fired);
    expect(later?.lead).toBe(5);
  });

  it("ignores non-spot low-impact rows", () => {
    const calm = row({ id: "e2", impact: "low", spot: false, pinned: false });
    expect(dueAlert(calm, config, Date.parse(calm.when_utc) - 60_000, new Set())).toBeNull();
  });

  it("respects the disabled toggle", () => {
    const off = { ...config, enabled: false };
    expect(dueAlert(spot, off, Date.parse(spot.when_utc) - 60_000, new Set())).toBeNull();
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
    expect(upcoming.map((r) => r.id)).toEqual(["economic:tcmb", "economic:us-cpi"]);
    expect(past.map((r) => r.id)).toEqual(["world:war"]);
    const undated = row({ id: "u", undated: true });
    expect(groupRows([undated], NOW).past).toHaveLength(1);
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
});
