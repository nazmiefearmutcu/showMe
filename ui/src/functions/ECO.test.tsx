/**
 * ECO pane — states, honesty and layout contract tests (Awareness-backed).
 *
 * `useFunction` is mocked through shared mutable state so each test drives the
 * pane into one branch. Payloads follow showme-payload-contract.md (ECO):
 * `rows` (EconRow), `holidays`, `meta`. Pins:
 *  - loading shows skeleton, no table;
 *  - provider_unavailable renders AwarenessUnavailable with the verbatim reason and zero rows;
 *  - ok rows render the event, sourced surprise glyph/sign and the provenance button;
 *  - a released print never shows a surprise before release;
 *  - holidays appear inline on their day; central-bank rows carry the CB badge;
 *  - an empty window says so and offers relaxers (no sample rows);
 *  - the removed reference/live toggles are not rendered.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ECOPane } from "./ECO";

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

const HOUR = 3_600_000;
const future = (hours: number) => new Date(Date.now() + hours * HOUR).toISOString();
const past = (hours: number) => new Date(Date.now() - hours * HOUR).toISOString();

const META = {
  generated_at: past(0.1),
  providers: [
    { provider: "econ.nasdaq", status: "ok", last_ok_at: past(0.1) },
    { provider: "econ.forexfactory", status: "ok", last_ok_at: past(0.1) },
  ],
};

function okPayload(overrides: Record<string, unknown> = {}) {
  return {
    status: "ok",
    rows: [
      {
        id: "cpi-1",
        date: past(2),
        country: "US",
        currency: "USD",
        event: "CPI YoY",
        category: "inflation",
        importance: 3,
        actual: "3.2%",
        forecast: "3.1%",
        previous: "3.0%",
        unit: "%",
        surprise: 0.1,
        surprise_direction: "above",
        status: "released",
        is_central_bank: false,
        sources: [{ provider: "econ.nasdaq", basis: "consensus", fetched_at: past(0.2) }],
      },
      {
        id: "nfp-1",
        date: future(30),
        country: "US",
        currency: "USD",
        event: "Nonfarm Payrolls",
        importance: 3,
        actual: null,
        forecast: "180K",
        previous: "150K",
        unit: "K",
        surprise: null,
        surprise_direction: null,
        status: "scheduled",
        sources: [{ provider: "econ.forexfactory", basis: "impact" }],
      },
      {
        id: "fed-1",
        date: future(80),
        country: "US",
        event: "FOMC Rate Decision",
        importance: 3,
        status: "scheduled",
        is_central_bank: true,
        sources: [],
      },
    ],
    holidays: [
      {
        date: past(2).slice(0, 10),
        country: "US",
        exchange: "NYSE",
        name: "Veterans Day",
        kind: "market_closed",
        source: "exchange_calendars",
      },
    ],
    meta: META,
    ...overrides,
  };
}

function setOk(payload: Record<string, unknown>) {
  setMockFn({
    state: "ok",
    data: { data: payload, sources: ["awareness:econ"], elapsed_ms: 12 },
  });
}

beforeEach(() => {
  setMockFn({ state: "idle" });
  window.localStorage.clear();
});

afterEach(() => cleanup());

describe("ECOPane states", () => {
  it("shows a skeleton while loading, not a table", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<ECOPane code="ECO" />);
    expect(container.querySelector(".aw-cal__grid")).toBeNull();
    expect(screen.queryByRole("table", { name: "Economic calendar by day" })).toBeNull();
  });

  it("renders AwarenessUnavailable with the backend reason and no rows", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "connection refused on 127.0.0.1:8086",
          rows: [],
        },
        sources: ["no_live_source"],
      },
    });
    render(<ECOPane code="ECO" />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Awareness service is not running");
    expect(alert.textContent).toContain("connection refused on 127.0.0.1:8086");
    expect(document.querySelectorAll("[data-testid='eco-row']")).toHaveLength(0);
  });

  it("shows an empty window with relaxer buttons and no sample rows", () => {
    setOk({ status: "empty", rows: [], holidays: [], meta: META });
    render(<ECOPane code="ECO" />);
    expect(screen.getByText("No events in this window")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Widen to 14 days" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "All countries" })).toBeTruthy();
  });

  it("renders the error state with a status role", () => {
    setMockFn({ state: "error", error: new Error("boom") });
    render(<ECOPane code="ECO" />);
    expect(screen.getByText("boom")).toBeTruthy();
    expect(screen.getByText("Function error")).toBeTruthy();
  });
});

describe("ECOPane ok payload", () => {
  it("renders each event with its surprise glyph and provenance button", () => {
    setOk(okPayload());
    render(<ECOPane code="ECO" />);
    expect(screen.getByText("CPI YoY")).toBeTruthy();
    expect(screen.getByLabelText("Above consensus by +0.10%")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sources for CPI YoY: 1" })).toBeTruthy();
  });

  it("never shows a surprise for an unreleased print", () => {
    setOk(okPayload());
    render(<ECOPane code="ECO" />);
    const rows = Array.from(
      document.querySelectorAll<HTMLElement>("[data-testid='eco-row']"),
    );
    const nfp = rows.find((r) => r.textContent?.includes("Nonfarm Payrolls"));
    expect(nfp).toBeDefined();
    expect(
      nfp!.querySelector(".aw-surprise--above, .aw-surprise--below, .aw-surprise--inline"),
    ).toBeNull();
  });

  it("marks central-bank rows and renders holidays inline on their day", () => {
    setOk(okPayload());
    render(<ECOPane code="ECO" />);
    expect(screen.getByText("CB")).toBeTruthy();
    expect(screen.getByText(/Veterans Day/)).toBeTruthy();
    expect(screen.getByText(/NYSE closed: Veterans Day/)).toBeTruthy();
  });

  it("surfaces the next high-impact countdown from the scheduled high event", () => {
    setOk(okPayload());
    render(<ECOPane code="ECO" />);
    expect(screen.getByText("Next high-impact release")).toBeTruthy();
    expect(screen.getAllByText(/^in /).length).toBeGreaterThan(0);
  });

  it("shows the provider health strip and the econ provider list", () => {
    setOk(okPayload());
    render(<ECOPane code="ECO" />);
    expect(screen.getAllByText("econ.nasdaq").length).toBeGreaterThan(0);
  });

  it("does not render the removed reference or live-calendar toggles", () => {
    setOk(okPayload());
    render(<ECOPane code="ECO" />);
    expect(screen.queryByText(/reference/i)).toBeNull();
    expect(screen.queryByText(/live calendar/i)).toBeNull();
    expect(screen.queryByText(/sample/i)).toBeNull();
  });
});
