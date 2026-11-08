/**
 * MSENT pane — states and honesty.
 *
 * `useFunction` is mocked per function code. Pins:
 *  - provider_unavailable shows the backend reason and no sections;
 *  - a null CNN block renders its own empty state, never a gauge value;
 *  - an ok payload renders the Fear & Greed score, rating and delta;
 *  - the VIX card shows the structure badge and the near-term warning;
 *  - the news card asks SOSC for the chosen ticker and shows series-empty copy.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MSENTPane } from "./MSENT";

interface Envelope {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | null;
  error?: unknown;
}

const byCode: Record<string, Envelope> = {};
const calls: Array<{ code: string; symbol?: string; params?: unknown }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { code: string; symbol?: string; params?: unknown }) => {
    calls.push(opts);
    const env = byCode[opts.code] ?? { state: "idle", data: null };
    return { ...env, refetch: vi.fn() };
  },
}));

let watchSymbols: string[] = [];
vi.mock("@/lib/watchlist", () => ({
  loadWatchlist: async () => watchSymbols.map((symbol) => ({ symbol })),
  subscribeWatchlist: () => () => undefined,
}));

const NOW = "2026-11-08T12:00:00Z";

function okMsent(overrides: Record<string, unknown> = {}) {
  return {
    status: "ok",
    cnn: {
      score: 22.4,
      rating: "Extreme Fear",
      as_of: NOW,
      previous_close: 24.6,
      previous_1_week: 30,
      previous_1_month: 45,
      previous_1_year: 60,
      components: [
        { key: "momentum", label: "Market momentum", score: 18, rating: "Extreme Fear" },
      ],
      history: [
        { ts: "2026-08-10T00:00:00Z", value: 40 },
        { ts: "2026-11-07T00:00:00Z", value: 22 },
      ],
    },
    crypto: null,
    vix: {
      vix: 17.1,
      vix9d: 21.5,
      vix3m: 18.2,
      as_of: "2026-11-07",
      term_ratio: 0.939,
      structure: "contango",
    },
    social: {
      stocks: [
        {
          ticker: "NVDA",
          rank: 1,
          mentions: 1200,
          mention_change_pct: 12.5,
          rank_change: 2,
        },
      ],
      crypto: [],
    },
    sources: ["awareness:sentiment"],
    meta: { providers: [], generated_at: NOW },
    ...overrides,
  };
}

function setFn(code: string, state: Envelope["state"], data?: unknown, error?: unknown) {
  byCode[code] = { state, data: data === undefined ? null : { data }, error };
}

beforeEach(() => {
  for (const k of Object.keys(byCode)) delete byCode[k];
  calls.length = 0;
  watchSymbols = [];
  setFn("SOSC", "idle");
});
afterEach(() => {
  cleanup();
});

describe("MSENT pane — load states", () => {
  it("shows the awareness-down state with the backend reason and no sections", () => {
    setFn("MSENT", "ok", {
      status: "provider_unavailable",
      reason: "awareness-markets not reachable at 127.0.0.1:8086",
      cnn: null,
      crypto: null,
      vix: null,
      social: { stocks: [], crypto: [] },
    });
    render(<MSENTPane code="MSENT" />);
    expect(screen.getByRole("alert").textContent).toMatch(
      /Awareness service is not running/,
    );
    expect(screen.getByText(/127\.0\.0\.1:8086/)).toBeInTheDocument();
    expect(screen.queryByText("Fear & Greed")).toBeNull();
  });

  it("renders a skeleton while loading", () => {
    setFn("MSENT", "loading");
    const { container } = render(<MSENTPane code="MSENT" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });
});

describe("MSENT pane — sections", () => {
  it("shows the Fear & Greed score, rating and change vs the previous close", () => {
    setFn("MSENT", "ok", okMsent());
    const { container } = render(<MSENTPane code="MSENT" />);
    const card = container.querySelector("#msent-fg")?.closest("section");
    expect(card?.textContent).toContain("22");
    expect(card?.textContent).toContain("Extreme Fear");
    expect(card?.textContent).toContain("−2.2 vs previous close");
    expect(
      screen.getByRole("img", { name: /Fear and Greed gauge at 22, extreme fear/ }),
    ).toBeInTheDocument();
  });

  it("a null CNN block renders its empty state and no gauge value", () => {
    setFn("MSENT", "ok", okMsent({ cnn: null }));
    const { container } = render(<MSENTPane code="MSENT" />);
    const card = container.querySelector("#msent-fg")?.closest("section");
    expect(card?.textContent).toMatch(/No data yet/);
    expect(card?.querySelector("svg")).toBeNull();
    expect(screen.queryByRole("img", { name: /Fear and Greed gauge/ })).toBeNull();
  });

  it("shows the contango badge, the ratio, and the near-term warning when VIX9D > VIX", () => {
    setFn("MSENT", "ok", okMsent());
    render(<MSENTPane code="MSENT" />);
    expect(screen.getByText("Contango")).toBeInTheDocument();
    expect(screen.getByText(/VIX \/ VIX3M 0\.939/)).toBeInTheDocument();
    expect(screen.getByRole("note").textContent).toMatch(/9-day above spot/);
  });

  it("renders the social buzz rows with a signed 24h change", () => {
    setFn("MSENT", "ok", okMsent());
    render(<MSENTPane code="MSENT" />);
    expect(screen.getByRole("button", { name: "NVDA" })).toBeInTheDocument();
    expect(screen.getByText("+12.5%")).toBeInTheDocument();
    expect(screen.getByText("▲2")).toBeInTheDocument();
  });
});

describe("MSENT pane — news sentiment card", () => {
  it("asks SOSC for the first watchlist ticker with the 7-day window", async () => {
    watchSymbols = ["nvda", "msft"];
    setFn("MSENT", "ok", okMsent());
    render(<MSENTPane code="MSENT" />);
    await waitFor(() =>
      expect(calls.filter((c) => c.code === "SOSC").at(-1)?.symbol).toBe("NVDA"),
    );
    expect(calls.filter((c) => c.code === "SOSC").at(-1)?.params).toEqual({ window: "7d" });
  });

  it("with no watchlist there is no ticker and no news request is made", () => {
    setFn("MSENT", "ok", okMsent());
    render(<MSENTPane code="MSENT" />);
    expect(screen.getByText(/Add a watchlist symbol/)).toBeInTheDocument();
  });

  it("empty series shows the no-scored-news line and no bars", async () => {
    watchSymbols = ["NVDA"];
    setFn("MSENT", "ok", okMsent());
    setFn("SOSC", "ok", { status: "empty", news: { count: 0, series: [] } });
    const { container } = render(<MSENTPane code="MSENT" />);
    expect(
      await screen.findByText("No scored news for NVDA in the last 7 days."),
    ).toBeInTheDocument();
    expect(container.querySelector(".aw-bars")).toBeNull();
  });

  it("selecting another ticker switches the news request", async () => {
    watchSymbols = ["NVDA", "MSFT"];
    setFn("MSENT", "ok", okMsent());
    render(<MSENTPane code="MSENT" />);
    fireEvent.click(await screen.findByRole("button", { name: "MSFT" }));
    expect(calls.filter((c) => c.code === "SOSC").at(-1)?.symbol).toBe("MSFT");
  });
});
