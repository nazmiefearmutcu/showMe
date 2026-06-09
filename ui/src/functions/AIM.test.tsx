/**
 * AIM pane — honesty + a11y + display contract tests.
 *
 * AIM is a read-only cross-broker order ledger (live open orders + a persisted
 * order_history tail). These tests pin the HONESTY-FIRST upgrade:
 *
 *  - loading → Skeleton; error → an announced role=status live region;
 *  - the empty state per `data_mode` shows the right honest message
 *    (not_configured → "Configure a broker adapter…");
 *  - symbol scoping filters rows to the focused symbol;
 *  - the Open ↔ History tabs partition working vs terminal orders;
 *  - the RefreshButton reports aria-busy while the poll is in flight;
 *  - the KPI card reads the honest all-time "Filled" (NOT "Filled Today");
 *  - the cached_snapshot notice EXPLAINS the reason, not just a coloured pill;
 *  - the side cell renders as a design-system Pill with a buy/sell aria-label;
 *  - provider_errors surface in an announced (role=status/alert) region.
 *
 * `useFunction` is mocked via mutable shared state so each test drives the pane
 * into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { AIMPane } from "./AIM";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetch = vi.fn();

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
    refetch,
  }),
}));

// Visibility poll is irrelevant to render assertions — return a stable tick.
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const NOW = new Date("2026-06-09T12:00:00.000Z");
const AS_OF = "2026-06-09T11:55:00.000Z";

const orders = [
  {
    created_at: "2026-06-09T10:00:00.000Z",
    broker: "alpaca_broker",
    order_id: "o-aapl-1",
    symbol: "AAPL",
    side: "buy",
    quantity: 10,
    price: 195.5,
    type: "limit",
    tif: "gtc",
    status: "open",
  },
  {
    created_at: "2026-06-09T09:00:00.000Z",
    broker: "alpaca_broker",
    order_id: "o-aapl-2",
    symbol: "AAPL",
    side: "sell",
    quantity: 5,
    price: 200.0,
    type: "limit",
    tif: "day",
    status: "filled",
    filled_qty: 5,
    avg_fill_px: 200.1,
  },
  {
    created_at: "2026-06-09T08:00:00.000Z",
    broker: "binance_broker",
    order_id: "o-btc-1",
    symbol: "BTCUSDT",
    side: "buy",
    quantity: 0.5,
    price: 60000.0,
    type: "limit",
    tif: "gtc",
    status: "open",
  },
];

function okPayload(extra: Record<string, unknown> = {}) {
  return {
    data: {
      data: {
        status: "ok",
        orders,
        rows: orders,
        cards: {
          open_count: 2,
          filled_today: 1,
          brokers_online: 2,
          total_notional: 1_234_567,
          data_mode: "live_exchange",
          as_of: AS_OF,
        },
        brokers_checked: ["binance_broker", "alpaca_broker"],
        brokers_online: ["binance_broker", "alpaca_broker"],
        data_mode: "live_exchange",
        as_of: AS_OF,
        ...extra,
      },
      sources: ["order_history", "binance_broker", "alpaca_broker"],
      elapsed_ms: 12,
    },
  };
}

function emptyPayload(dataMode: string) {
  return {
    data: {
      data: {
        status: "empty",
        reason: "No open or recent orders were found.",
        orders: [],
        rows: [],
        cards: {
          open_count: 0,
          filled_today: 0,
          brokers_online: 0,
          total_notional: 0,
          data_mode: dataMode,
          as_of: AS_OF,
        },
        brokers_checked: ["binance_broker", "alpaca_broker"],
        data_mode: dataMode,
        as_of: AS_OF,
        next_actions: ["Use BBGT/EMSX to preview a ticket."],
      },
      sources: ["order_history"],
      elapsed_ms: 8,
    },
  };
}

function cachedPayload() {
  // Brokers all down → cached_snapshot from the history tail.
  return {
    data: {
      data: {
        status: "ok",
        orders: [orders[1]],
        rows: [orders[1]],
        cards: {
          open_count: 0,
          filled_today: 1,
          brokers_online: 0,
          total_notional: 1000,
          data_mode: "cached_snapshot",
          as_of: AS_OF,
        },
        brokers_checked: ["binance_broker", "alpaca_broker"],
        data_mode: "cached_snapshot",
        as_of: AS_OF,
      },
      sources: ["order_history"],
      elapsed_ms: 9,
      metadata: {
        provider_errors: ["binance_broker.get_open_orders: timeout"],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  localStorage.clear();
  refetch.mockClear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("AIM pane — load states", () => {
  it("renders the loading placeholder in an aria-busy live region (no grid)", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<AIMPane code="AIM" />);
    // The body live region flips aria-busy while the poll is in flight…
    const busy = container.querySelector('[role="status"][aria-busy="true"]');
    expect(busy).not.toBeNull();
    // …and the order blotter is not yet mounted.
    expect(container.querySelector('[aria-label="AIM order blotter"]')).toBeNull();
  });

  it("wraps the error state in a role=status live region", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("boom") });
    const { container } = render(<AIMPane code="AIM" />);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.textContent ?? "").toMatch(/boom/);
  });

  it("flags the RefreshButton aria-busy while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    render(<AIMPane code="AIM" />);
    const refresh = screen.getByRole("button", { name: /refresh/i });
    expect(refresh).toHaveAttribute("aria-busy", "true");
  });

  it("does NOT wrap the steady-state order grid in a polite live region", () => {
    // Regression: the live region must be scoped to loading/error transitions.
    // The grid re-renders on every 15s poll — if it sat inside an aria-live
    // region, screen readers would re-announce the whole blotter each refresh.
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<AIMPane code="AIM" />);
    const grid = container.querySelector('[aria-label="AIM order blotter"]');
    expect(grid).not.toBeNull();
    expect(grid?.closest('[role="status"]')).toBeNull();
  });
});

describe("AIM pane — honest empty states per data_mode", () => {
  it("not_configured → explains how to configure a broker", () => {
    setMockFn({ state: "ok", ...emptyPayload("not_configured") });
    render(<AIMPane code="AIM" />);
    expect(screen.getByText(/No open orders/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Configure a broker adapter in Settings/i),
    ).toBeInTheDocument();
  });

  it("not_configured → the notice EXPLAINS the mode (not just a coloured pill)", () => {
    setMockFn({ state: "ok", ...emptyPayload("not_configured") });
    render(<AIMPane code="AIM" />);
    const notice = screen.getByTestId("aim-mode-notice");
    expect(notice).toHaveAttribute("role", "status");
    expect(notice.textContent ?? "").toMatch(/Broker yapılandırılmamış/i);
  });
});

describe("AIM pane — symbol scoping + tabs", () => {
  it("scopes rows to the focused symbol (AAPL → no BTC row)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<AIMPane code="AIM" symbol="AAPL" />);
    // Open tab is default — the AAPL open order shows, BTCUSDT is filtered out.
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("BTCUSDT")).toBeNull();
  });

  it("partitions Open vs History across the tabs", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<AIMPane code="AIM" />);
    // Default Open tab: the two open orders, not the filled one.
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
    // Switch to History — the filled AAPL order surfaces; opens disappear.
    fireEvent.click(screen.getByRole("tab", { name: /History/i }));
    expect(screen.queryByText("BTCUSDT")).toBeNull();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByLabelText(/durum: filled/i)).toBeInTheDocument();
  });
});

describe("AIM pane — honesty fixes", () => {
  it("labels the fills KPI 'Filled' (NOT 'Filled Today')", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<AIMPane code="AIM" />);
    expect(screen.getByText("Filled")).toBeInTheDocument();
    expect(screen.queryByText(/Filled Today/i)).toBeNull();
  });

  it("cached_snapshot → notice explains 'son anlık görüntü' (degraded reason)", () => {
    setMockFn({ state: "ok", ...cachedPayload() });
    render(<AIMPane code="AIM" />);
    const notice = screen.getByTestId("aim-mode-notice");
    expect(notice).toHaveAttribute("role", "status");
    expect(notice.textContent ?? "").toMatch(/son anlık görüntü/i);
  });

  it("derives the header freshness from server as_of (not the client clock)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<AIMPane code="AIM" />);
    // as_of = 11:55 UTC; client clock frozen at 12:00 — must show 11:55.
    const veri = screen.getByText(/Veri:/i);
    expect(veri.textContent ?? "").toContain("11:55");
    expect(veri.textContent ?? "").not.toContain("12:00");
  });
});

describe("AIM pane — a11y + display", () => {
  it("renders the side cell as a Pill with a buy/sell accessible name", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<AIMPane code="AIM" />);
    // Two buy orders are open (AAPL + BTC) → both carry the buy aria-label.
    const buys = screen.getAllByLabelText(/yön: alış/i);
    expect(buys.length).toBeGreaterThan(0);
    // It is a design-system Pill, not the old hand-rolled span.
    expect(buys[0].classList.contains("ds-pill")).toBe(true);
    expect(container.querySelector(".ds-pill")).not.toBeNull();
  });

  it("surfaces provider_errors in an announced (role=alert) region", () => {
    setMockFn({ state: "ok", ...cachedPayload() });
    const { container } = render(<AIMPane code="AIM" />);
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(within(alert as HTMLElement).getByText(/Broker errors/i)).toBeInTheDocument();
    expect(alert?.textContent ?? "").toMatch(/timeout/);
  });

  it("gives the KPI ribbon an accessible label", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<AIMPane code="AIM" />);
    expect(container.querySelector('[aria-label="AIM KPI ribbon"]')).not.toBeNull();
  });

  it("labels the data_mode pill with a human-readable mode explanation", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<AIMPane code="AIM" />);
    expect(screen.getByLabelText(/Veri modu: Canlı/i)).toBeInTheDocument();
  });
});
