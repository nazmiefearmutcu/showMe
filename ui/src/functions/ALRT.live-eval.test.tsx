/**
 * ALRT — live-tick evaluation (P2a-g05, ALRT#5).
 *
 * The REST poll samples every 45 s, so a crossing that starts and returns
 * between two polls was never observed. These specs pin the live path: each
 * quote tick from the pane's live feed is evaluated against the active alerts
 * for that symbol, and the REST poll stays as the refresh/fallback path.
 *
 * The live feed is a controllable in-test stand-in for `useLiveQuote`; no
 * network or WebSocket is opened.
 */
import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const live = vi.hoisted(() => ({
  price: null as number | null,
  /** "tick": a live feed tick. "snapshot": the hook's REST fallback price. */
  kind: "tick" as "tick" | "snapshot",
  at: 0,
  listeners: new Set<() => void>(),
}));

vi.mock("@/lib/quotes", () => ({
  fetchQuote: vi.fn(),
}));
vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => undefined),
  isInTauri: vi.fn(() => false),
}));
vi.mock("@/lib/toast", () => ({
  toast: { info: vi.fn(), success: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/confirm", () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  const React = await import("react");
  return {
    ...actual,
    useLiveQuote: (symbol: string) => {
      const [, force] = React.useReducer((n: number) => n + 1, 0);
      React.useEffect(() => {
        live.listeners.add(force);
        return () => {
          live.listeners.delete(force);
        };
      }, []);
      const price = live.price;
      const isTick = live.kind === "tick" && price != null;
      return {
        symbol,
        snapshot: price != null && !isTick ? { last: price, volume: null } : null,
        lastTick: isTick ? { symbol, price, changePct: null, volume: null, bid: null, ask: null, ts: live.at, source: "live-test" } : null,
        price,
        changePct: null,
        source: price == null ? null : "live-test",
        sourceKind: isTick ? "tick" : price == null ? "none" : "snapshot",
        fetchedAt: price == null ? null : Date.now(),
        freshnessMs: null,
        stale: false,
        loading: false,
        refreshing: false,
        error: null,
        transportState: "idle",
        lastTickAt: isTick ? live.at : null,
        refetch: () => undefined,
      } as unknown as import("@/lib/market-data").QuoteView;
    },
  };
});

import { ALRTPane } from "./ALRT";
import { fetchQuote } from "@/lib/quotes";
import { toast } from "@/lib/toast";
import { clearAlerts, addAlert } from "@/lib/alerts";

function quote(symbol: string, price: number) {
  return {
    symbol,
    asset_class: "EQUITY",
    last: price,
    price,
    previous_close: null,
    change_pct: 0,
    volume: 1,
    bid: null,
    ask: null,
    source: "test",
    provider_symbol: symbol,
    currency: "USD",
    fetched_at: new Date().toISOString(),
  };
}

async function flush() {
  await act(async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  });
}

/** Push one live tick through the stand-in feed and let the evaluation settle. */
async function tick(price: number) {
  live.price = price;
  live.kind = "tick";
  live.at = Math.max(Date.now(), live.at + 1);
  await act(async () => {
    for (const fn of Array.from(live.listeners)) fn();
  });
  await flush();
}

/** The hook falls back to a REST snapshot price (no live tick). */
async function snapshotOnly(price: number) {
  live.price = price;
  live.kind = "snapshot";
  await act(async () => {
    for (const fn of Array.from(live.listeners)) fn();
  });
  await flush();
}

async function mountPane() {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<ALRTPane code="ALRT" />);
  });
  await flush();
  return utils;
}

beforeEach(async () => {
  await clearAlerts();
  live.price = null;
  live.kind = "tick";
  live.at = 0;
  live.listeners.clear();
  (fetchQuote as ReturnType<typeof vi.fn>).mockReset();
  (fetchQuote as ReturnType<typeof vi.fn>).mockResolvedValue(quote("AAPL", 190));
  (toast.info as ReturnType<typeof vi.fn>).mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ALRT live-tick evaluation", () => {
  it("a cross_up that starts and returns between REST polls still fires from live ticks", async () => {
    await addAlert({ symbol: "AAPL", field: "price", direction: "cross_up", threshold: 200 });
    await mountPane();
    expect(toast.info).not.toHaveBeenCalled();

    await tick(190); // armed below, first observation, no fire
    await tick(205); // real crossing between REST samples: fires once
    expect(toast.info).toHaveBeenCalledTimes(1);

    await tick(190); // falls back through the level: no fire for a cross_up
    expect(toast.info).toHaveBeenCalledTimes(1);
  });

  it("does not refire from live ticks while the price stays past the level", async () => {
    await addAlert({ symbol: "AAPL", field: "price", direction: "cross_up", threshold: 200 });
    await mountPane();

    await tick(190);
    await tick(205); // fire
    await tick(210);
    await tick(215);
    expect(toast.info).toHaveBeenCalledTimes(1);
  });

  it("a level already passed when first observed does not fire on that first tick", async () => {
    await addAlert({ symbol: "TSLA", field: "price", direction: "above", threshold: 200 });
    await mountPane();

    await tick(250); // first observation already above: recorded, no edge, no fire
    await tick(250);
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("an above alert fires once on the live edge, not on every tick", async () => {
    await addAlert({ symbol: "AAPL", field: "price", direction: "above", threshold: 200 });
    await mountPane();

    await tick(195);
    await tick(201); // edge
    await tick(202);
    expect(toast.info).toHaveBeenCalledTimes(1);
  });

  it("a REST snapshot price the live hook falls back to is not evaluated as a live tick", async () => {
    await addAlert({ symbol: "AAPL", field: "price", direction: "above", threshold: 200 });
    await mountPane();
    await tick(190); // genuine live observation, below the level

    await snapshotOnly(205); // hook falls back to a REST snapshot price: not a tick
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("the footer discloses live tick evaluation and the first-observation rule", async () => {
    await mountPane();
    expect(screen.getByText(/live quote ticks/)).toBeInTheDocument();
    expect(screen.getByText(/already past its level/)).toBeInTheDocument();
  });
});
