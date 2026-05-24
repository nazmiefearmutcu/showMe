/**
 * Contract tests for the canonical market-data layer.
 *
 * The targets are the exact failure modes that S01 left open in the
 * `fetchQuote` + `subscribeQuote` weave:
 *   - background refresh erasing last-good data,
 *   - WebSocket ticks clearing the snapshot,
 *   - silent "looks alive while actually static" UI when ticks dry up,
 *   - leaking sockets / timers across symbol changes,
 *   - empty / invalid symbols hitting the network.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __internal,
  __resetMultiplexForTests,
  normalizeSymbol,
  normalizeTick,
  subscribeQuoteMultiplexed,
  subscribeQuoteStream,
  useLiveQuote,
  useLiveQuotes,
  useQuote,
} from "./market-data";
import type { QuoteSnapshot } from "./quotes";
import type { StreamOpts, Tick } from "./stream";

function makeSnapshot(overrides: Partial<QuoteSnapshot> = {}): QuoteSnapshot {
  return {
    symbol: "AAPL",
    asset_class: "EQUITY",
    last: 200,
    price: 200,
    previous_close: 195,
    change_pct: 2.56,
    volume: 10_000_000,
    bid: null,
    ask: null,
    source: "yahoo_chart",
    provider_symbol: "AAPL",
    currency: "USD",
    fetched_at: "2026-05-20T12:00:00Z",
    ...overrides,
  };
}

type FakeStreamCtl = {
  emitTick: (tick: Partial<Tick>) => void;
  emitStatus: (status: Parameters<NonNullable<StreamOpts["onStatus"]>>[0], info?: string) => void;
  close: () => void;
  closed: boolean;
  symbol: string;
};

function makeFakeSubscriber() {
  const handles: FakeStreamCtl[] = [];
  const subscriber = vi.fn((symbol: string, opts: StreamOpts) => {
    const ctl: FakeStreamCtl = {
      symbol,
      closed: false,
      emitTick: (partial) => {
        if (ctl.closed) return;
        const tick: Tick = {
          symbol,
          price: 0,
          change_pct: null,
          volume: null,
          bid: null,
          ask: null,
          ts: Math.floor(Date.now() / 1000),
          source: "fake",
          ...partial,
        };
        opts.onTick(tick);
      },
      emitStatus: (status, info) => {
        if (ctl.closed) return;
        opts.onStatus?.(status, info);
      },
      close: () => {
        ctl.closed = true;
      },
    };
    handles.push(ctl);
    return { close: () => ctl.close() };
  });
  return { subscriber, handles };
}

afterEach(() => {
  vi.useRealTimers();
  __resetMultiplexForTests();
});

describe("normalizers", () => {
  it("normalizeSymbol trims, uppercases, and rejects garbage", () => {
    expect(normalizeSymbol("  aapl  ")).toBe("AAPL");
    expect(normalizeSymbol("btcusdt")).toBe("BTCUSDT");
    expect(normalizeSymbol("")).toBe("");
    expect(normalizeSymbol(null)).toBe("");
    expect(normalizeSymbol(undefined)).toBe("");
    expect(normalizeSymbol(42 as unknown as string)).toBe("");
  });

  it("normalizeTick promotes seconds-since-epoch into ms", () => {
    const t = normalizeTick({
      symbol: "BTCUSDT",
      price: 50_000,
      change_pct: 1.2,
      volume: 100,
      bid: 49_999,
      ask: 50_001,
      ts: 1_700_000_000, // seconds
      source: "binance",
    });
    expect(t.ts).toBe(1_700_000_000_000);
    expect(t.changePct).toBe(1.2);
    expect(t.bid).toBe(49_999);
  });

  it("normalizeTick leaves milliseconds untouched", () => {
    const t = normalizeTick({
      symbol: "BTCUSDT",
      price: 1,
      change_pct: null,
      ts: 1_700_000_000_000,
      source: "binance",
    });
    expect(t.ts).toBe(1_700_000_000_000);
  });
});

describe("subscribeQuoteStream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("emits reconnecting after the first successful connect", () => {
    const onTick = vi.fn();
    const onTransport = vi.fn();
    const { subscriber, handles } = makeFakeSubscriber();
    const h = subscribeQuoteStream("AAPL", {
      onTick,
      onTransportState: onTransport,
      subscriber,
    });
    const ctl = handles[0];
    ctl.emitStatus("connecting");
    ctl.emitStatus("live");
    ctl.emitStatus("offline");
    expect(onTransport.mock.calls.map((c) => c[0])).toEqual([
      "connecting",
      "live",
      "reconnecting",
    ]);
    h.close();
  });

  it("marks the channel stale when no tick arrives within staleTickMs", () => {
    const onTransport = vi.fn();
    const { subscriber, handles } = makeFakeSubscriber();
    subscribeQuoteStream("AAPL", {
      onTick: () => undefined,
      onTransportState: onTransport,
      staleTickMs: 1_000,
      subscriber,
    });
    handles[0].emitTick({ price: 100 });
    expect(onTransport).toHaveBeenLastCalledWith("live", undefined);
    vi.advanceTimersByTime(1_500);
    const transitions = onTransport.mock.calls.map((c) => c[0]);
    expect(transitions).toContain("stale");
  });

  it("error transport is forwarded as-is", () => {
    const onTransport = vi.fn();
    const { subscriber, handles } = makeFakeSubscriber();
    subscribeQuoteStream("AAPL", {
      onTick: () => undefined,
      onTransportState: onTransport,
      subscriber,
    });
    handles[0].emitStatus("error", "socket error");
    expect(onTransport).toHaveBeenCalledWith("error", "socket error");
  });

  it("rejects empty symbols without opening a socket", () => {
    const onTransport = vi.fn();
    const { subscriber } = makeFakeSubscriber();
    const h = subscribeQuoteStream("  ", {
      onTick: () => undefined,
      onTransportState: onTransport,
      subscriber,
    });
    expect(onTransport).toHaveBeenCalledWith("error", "empty symbol");
    expect(subscriber).not.toHaveBeenCalled();
    h.close();
  });

  it("close() drops the stale timer and stops emitting state", () => {
    const onTransport = vi.fn();
    const { subscriber, handles } = makeFakeSubscriber();
    const h = subscribeQuoteStream("AAPL", {
      onTick: () => undefined,
      onTransportState: onTransport,
      staleTickMs: 1_000,
      subscriber,
    });
    handles[0].emitTick({ price: 100 });
    onTransport.mockClear();
    h.close();
    vi.advanceTimersByTime(5_000);
    expect(onTransport).not.toHaveBeenCalled();
  });
});

describe("toView projection", () => {
  it("returns no-data view when state is undefined", () => {
    const view = __internal.toView("AAPL", undefined, Date.now(), 60_000);
    expect(view.price).toBeNull();
    expect(view.sourceKind).toBe("none");
    expect(view.loading).toBe(false);
  });

  it("snapshot price wins when no live tick has arrived", () => {
    const base = __internal.emptySymbolState("AAPL");
    const withSnap = __internal.withSnapshot(base, makeSnapshot({ last: 200 }));
    const now = Date.parse("2026-05-20T12:00:30Z");
    const view = __internal.toView("AAPL", withSnap, now, 60_000);
    expect(view.sourceKind).toBe("snapshot");
    expect(view.price).toBe(200);
    expect(view.freshnessMs).toBe(30_000);
    expect(view.stale).toBe(false);
  });

  it("tick overrides snapshot once newer", () => {
    let s = __internal.emptySymbolState("AAPL");
    s = __internal.withSnapshot(s, makeSnapshot({ last: 200 }));
    s = __internal.withTick(s, {
      symbol: "AAPL",
      price: 205,
      changePct: 3.0,
      volume: 1,
      bid: null,
      ask: null,
      ts: Date.parse("2026-05-20T12:00:45Z"),
      source: "tick",
    });
    const view = __internal.toView(
      "AAPL",
      s,
      Date.parse("2026-05-20T12:00:46Z"),
      60_000,
    );
    expect(view.sourceKind).toBe("tick");
    expect(view.price).toBe(205);
    expect(view.snapshot?.last).toBe(200); // snapshot still preserved
  });

  it("stale flips once freshnessMs exceeds staleMs", () => {
    const s = __internal.withSnapshot(
      __internal.emptySymbolState("AAPL"),
      makeSnapshot({ fetched_at: "2026-05-20T12:00:00Z" }),
    );
    const view = __internal.toView(
      "AAPL",
      s,
      Date.parse("2026-05-20T12:02:00Z"), // +120s
      60_000,
    );
    expect(view.stale).toBe(true);
    expect(view.freshnessMs).toBe(120_000);
  });
});

// ---------- hook contract tests ----------

describe("useQuote hook", () => {
  it("preserves the previous snapshot while a refresh is in flight", async () => {
    let resolveSecond: ((value: QuoteSnapshot) => void) | null = null;
    const calls: string[] = [];
    const fetcher = vi.fn((sym: string) => {
      calls.push(sym);
      if (calls.length === 1) {
        return Promise.resolve(makeSnapshot({ last: 200 }));
      }
      return new Promise<QuoteSnapshot>((resolve) => {
        resolveSecond = resolve;
      });
    });

    const { result } = renderHook(() =>
      useQuote("AAPL", { pollMs: null, fetcher }),
    );

    expect(result.current.loading).toBe(true);
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.snapshot?.last).toBe(200);

    await act(async () => {
      result.current.refetch();
      await Promise.resolve();
    });
    expect(result.current.refreshing).toBe(true);
    expect(result.current.snapshot?.last).toBe(200);

    await act(async () => {
      resolveSecond?.(makeSnapshot({ last: 210 }));
      await Promise.resolve();
    });
    expect(result.current.refreshing).toBe(false);
    expect(result.current.snapshot?.last).toBe(210);
  });

  it("keeps last-good data when the refresh fails", async () => {
    const calls: number[] = [];
    const fetcher = vi.fn(async (sym: string) => {
      calls.push(calls.length);
      if (calls.length === 1) return makeSnapshot({ last: 200, symbol: sym });
      throw new Error("network down");
    });
    const { result } = renderHook(() =>
      useQuote("AAPL", { pollMs: null, fetcher }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.snapshot?.last).toBe(200);
    await act(async () => {
      result.current.refetch();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.error).toBe("network down");
    expect(result.current.snapshot?.last).toBe(200);
    expect(result.current.refreshing).toBe(false);
  });

  it("does not hit the network for empty symbols", () => {
    const fetcher = vi.fn();
    const { result } = renderHook(() =>
      useQuote("  ", { pollMs: null, fetcher }),
    );
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current.transportState).toBe("idle");
  });
});

describe("useLiveQuote hook", () => {
  it("overlays WebSocket ticks without clearing the snapshot", async () => {
    const fetcher = vi.fn(async () => makeSnapshot({ last: 200 }));
    const { subscriber, handles } = makeFakeSubscriber();
    const { result } = renderHook(() =>
      useLiveQuote("AAPL", {
        pollMs: null,
        fetcher,
        subscriber,
      }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.snapshot?.last).toBe(200);
    expect(result.current.transportState).toBe("connecting");

    await act(async () => {
      handles[0].emitTick({ price: 205, change_pct: 3, ts: Date.now() / 1000 });
    });
    expect(result.current.price).toBe(205);
    expect(result.current.snapshot?.last).toBe(200);
    expect(result.current.transportState).toBe("live");
    expect(result.current.sourceKind).toBe("tick");
  });

  it("reconnect cycle exposes connecting → live → reconnecting transport states", async () => {
    const fetcher = vi.fn(async () => makeSnapshot());
    const { subscriber, handles } = makeFakeSubscriber();
    const { result } = renderHook(() =>
      useLiveQuote("AAPL", { pollMs: null, fetcher, subscriber }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.transportState).toBe("connecting");
    await act(async () => {
      handles[0].emitStatus("live");
    });
    expect(result.current.transportState).toBe("live");
    await act(async () => {
      handles[0].emitStatus("offline");
    });
    expect(result.current.transportState).toBe("reconnecting");
  });

  it("closes the stream when the symbol changes", async () => {
    const fetcher = vi.fn(async (sym: string) => makeSnapshot({ symbol: sym }));
    const { subscriber, handles } = makeFakeSubscriber();
    const { result, rerender } = renderHook(
      ({ sym }: { sym: string }) =>
        useLiveQuote(sym, { pollMs: null, fetcher, subscriber }),
      { initialProps: { sym: "AAPL" } },
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(handles).toHaveLength(1);
    expect(handles[0].closed).toBe(false);

    rerender({ sym: "MSFT" });
    await act(async () => {
      await Promise.resolve();
    });
    expect(handles[0].closed).toBe(true);
    expect(handles).toHaveLength(2);
    expect(handles[1].symbol).toBe("MSFT");
    expect(result.current.symbol).toBe("MSFT");
  });

  it("unmount tears down the socket", async () => {
    const fetcher = vi.fn(async () => makeSnapshot());
    const { subscriber, handles } = makeFakeSubscriber();
    const { unmount } = renderHook(() =>
      useLiveQuote("AAPL", { pollMs: null, fetcher, subscriber }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    unmount();
    expect(handles[0].closed).toBe(true);
  });

  it("autoSubscribe=false skips the WebSocket entirely", async () => {
    const fetcher = vi.fn(async () => makeSnapshot());
    const subscriber = vi.fn();
    renderHook(() =>
      useLiveQuote("AAPL", {
        pollMs: null,
        fetcher,
        subscriber,
        autoSubscribe: false,
      }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(subscriber).not.toHaveBeenCalled();
  });
});

describe("useLiveQuotes batch hook", () => {
  it("opens one subscription per symbol, keyed in the result map", async () => {
    const fetcher = vi.fn(async (sym: string) => makeSnapshot({ symbol: sym }));
    const { subscriber, handles } = makeFakeSubscriber();
    const { result } = renderHook(() =>
      useLiveQuotes(["aapl", "BTCUSDT", "AAPL", ""], {
        pollMs: null,
        fetcher,
        subscriber,
      }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(Object.keys(result.current).sort()).toEqual(["AAPL", "BTCUSDT"]);
    expect(handles.map((h) => h.symbol).sort()).toEqual(["AAPL", "BTCUSDT"]);
    expect(result.current.AAPL.snapshot?.symbol).toBe("AAPL");
    expect(result.current.BTCUSDT.snapshot?.symbol).toBe("BTCUSDT");
  });

  it("array identity churn does not re-subscribe when contents match", async () => {
    const fetcher = vi.fn(async (sym: string) => makeSnapshot({ symbol: sym }));
    const { subscriber } = makeFakeSubscriber();
    const { rerender } = renderHook(
      ({ symbols }: { symbols: string[] }) =>
        useLiveQuotes(symbols, { pollMs: null, fetcher, subscriber }),
      { initialProps: { symbols: ["AAPL", "MSFT"] } },
    );
    await act(async () => {
      await Promise.resolve();
    });
    const initialCalls = subscriber.mock.calls.length;
    rerender({ symbols: ["msft", "aapl"] });
    await act(async () => {
      await Promise.resolve();
    });
    // Same content (sorted+normalized) → no new sockets.
    expect(subscriber.mock.calls.length).toBe(initialCalls);
  });

  it("rotating in a new symbol closes the old subscription", async () => {
    const fetcher = vi.fn(async (sym: string) => makeSnapshot({ symbol: sym }));
    const { subscriber, handles } = makeFakeSubscriber();
    const { rerender, result } = renderHook(
      ({ symbols }: { symbols: string[] }) =>
        useLiveQuotes(symbols, { pollMs: null, fetcher, subscriber }),
      { initialProps: { symbols: ["AAPL"] } },
    );
    await act(async () => {
      await Promise.resolve();
    });
    const firstHandle = handles[0];
    rerender({ symbols: ["MSFT"] });
    await act(async () => {
      await Promise.resolve();
    });
    expect(firstHandle.closed).toBe(true);
    expect(Object.keys(result.current)).toEqual(["MSFT"]);
  });

  it("empty input short-circuits — no fetch, no socket", async () => {
    const fetcher = vi.fn();
    const subscriber = vi.fn();
    const { result } = renderHook(() =>
      useLiveQuotes([], { pollMs: null, fetcher, subscriber }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(fetcher).not.toHaveBeenCalled();
    expect(subscriber).not.toHaveBeenCalled();
    expect(Object.keys(result.current)).toEqual([]);
  });

  it("snapshot fetch error preserves last-good for siblings", async () => {
    const seen: string[] = [];
    const fetcher = vi.fn(async (sym: string) => {
      seen.push(sym);
      if (sym === "FAIL") throw new Error("nope");
      return makeSnapshot({ symbol: sym, last: 200 });
    });
    const { subscriber } = makeFakeSubscriber();
    const { result } = renderHook(() =>
      useLiveQuotes(["AAPL", "FAIL"], {
        pollMs: null,
        fetcher,
        subscriber,
      }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.AAPL.snapshot?.last).toBe(200);
    expect(result.current.FAIL.error).toBe("nope");
    expect(result.current.FAIL.snapshot).toBeNull();
    expect(result.current.AAPL.error).toBeNull();
  });

  it("background polling refreshes without clearing data", async () => {
    vi.useFakeTimers();
    let nth = 0;
    const fetcher = vi.fn(async (sym: string) => {
      nth += 1;
      return makeSnapshot({ symbol: sym, last: 200 + nth });
    });
    const { subscriber } = makeFakeSubscriber();
    const { result } = renderHook(() =>
      useLiveQuotes(["AAPL"], { pollMs: 500, fetcher, subscriber }),
    );
    // Flush the initial fetch.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const initialCalls = fetcher.mock.calls.length;
    const firstPrice = result.current.AAPL.snapshot?.last;
    expect(firstPrice).toBeDefined();
    // Advance one poll cycle — must trigger at least one more refresh, must
    // never null out the snapshot, must end in refreshing=false.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(fetcher.mock.calls.length).toBeGreaterThan(initialCalls);
    expect(result.current.AAPL.snapshot).not.toBeNull();
    expect((result.current.AAPL.snapshot?.last ?? 0)).toBeGreaterThan(firstPrice ?? 0);
    expect(result.current.AAPL.refreshing).toBe(false);
  });
});

// ---------- multiplex contract tests ----------

describe("subscribeQuoteMultiplexed", () => {
  it("opens exactly one upstream subscription for N hooks on the same symbol", () => {
    const { subscriber } = makeFakeSubscriber();
    const a = subscribeQuoteMultiplexed("BTCUSDT", {
      onTick: () => undefined,
      onTransportState: () => undefined,
      subscriber,
    });
    const b = subscribeQuoteMultiplexed("BTCUSDT", {
      onTick: () => undefined,
      onTransportState: () => undefined,
      subscriber,
    });
    const c = subscribeQuoteMultiplexed("BTCUSDT", {
      onTick: () => undefined,
      onTransportState: () => undefined,
      subscriber,
    });
    expect(subscriber).toHaveBeenCalledTimes(1);
    a.close();
    b.close();
    c.close();
  });

  it("fans out a tick to every listener", () => {
    const { subscriber, handles } = makeFakeSubscriber();
    const tickA = vi.fn();
    const tickB = vi.fn();
    subscribeQuoteMultiplexed("AAPL", {
      onTick: tickA,
      onTransportState: () => undefined,
      subscriber,
    });
    subscribeQuoteMultiplexed("AAPL", {
      onTick: tickB,
      onTransportState: () => undefined,
      subscriber,
    });
    handles[0].emitTick({ price: 200 });
    expect(tickA).toHaveBeenCalled();
    expect(tickB).toHaveBeenCalled();
    expect(tickA.mock.calls[0][0].price).toBe(200);
    expect(tickB.mock.calls[0][0].price).toBe(200);
  });

  it("late joiners receive the last transport state on attach", () => {
    const { subscriber, handles } = makeFakeSubscriber();
    subscribeQuoteMultiplexed("AAPL", {
      onTick: () => undefined,
      onTransportState: () => undefined,
      subscriber,
    });
    handles[0].emitStatus("live");
    const transport = vi.fn();
    subscribeQuoteMultiplexed("AAPL", {
      onTick: () => undefined,
      onTransportState: transport,
      subscriber,
    });
    expect(transport).toHaveBeenCalledWith("live");
  });

  it("closes the upstream socket only after the last listener unsubscribes", () => {
    const { subscriber, handles } = makeFakeSubscriber();
    const a = subscribeQuoteMultiplexed("AAPL", {
      onTick: () => undefined,
      onTransportState: () => undefined,
      subscriber,
    });
    const b = subscribeQuoteMultiplexed("AAPL", {
      onTick: () => undefined,
      onTransportState: () => undefined,
      subscriber,
    });
    a.close();
    expect(handles[0].closed).toBe(false);
    b.close();
    expect(handles[0].closed).toBe(true);
  });

  it("rejects empty symbols without opening a socket", () => {
    const { subscriber } = makeFakeSubscriber();
    const onTransport = vi.fn();
    const h = subscribeQuoteMultiplexed("  ", {
      onTick: () => undefined,
      onTransportState: onTransport,
      subscriber,
    });
    expect(subscriber).not.toHaveBeenCalled();
    expect(onTransport).toHaveBeenCalledWith("error", "empty symbol");
    h.close();
  });
});

describe("useLiveQuotes multiplex integration", () => {
  it("4 hooks subscribing to the same symbol open ONE upstream socket", async () => {
    const fetcher = vi.fn(async (sym: string) => ({
      symbol: sym,
      asset_class: "EQUITY",
      last: 200,
      price: 200,
      previous_close: 199,
      change_pct: 0.5,
      volume: 0,
      bid: null,
      ask: null,
      source: "fake",
      provider_symbol: sym,
      currency: "USD",
      fetched_at: new Date().toISOString(),
    }));
    const { subscriber } = makeFakeSubscriber();
    renderHook(() =>
      useLiveQuotes(["BTCUSDT"], { pollMs: null, fetcher, subscriber }),
    );
    renderHook(() =>
      useLiveQuotes(["BTCUSDT"], { pollMs: null, fetcher, subscriber }),
    );
    renderHook(() =>
      useLiveQuotes(["BTCUSDT"], { pollMs: null, fetcher, subscriber }),
    );
    renderHook(() =>
      useLiveQuotes(["BTCUSDT"], { pollMs: null, fetcher, subscriber }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    // Four hook instances all want BTCUSDT — only one underlying WebSocket
    // subscription should be opened.
    expect(subscriber).toHaveBeenCalledTimes(1);
  });
});
