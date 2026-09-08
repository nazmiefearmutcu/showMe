/**
 * Tape-health pill (campaign 2026-09-08, Lane B / U3).
 *
 * Pins the honest aggregation contract:
 *   - no subscriptions  → no pill at all (no tape, no claim).
 *   - any live socket   → "LIVE · N sym · <age>" using the live count.
 *   - nothing live but
 *     a socket creating → "RECONNECTING · N sym".
 *   - stale/error/offline-only → "DOWN" (a socket-up-no-ticks tape is down,
 *     not live — the age figure tells the rest of the truth).
 *   - instrumentation through the REAL market-data multiplexer: transport
 *     states + ticks feed the registry, full unsubscribe releases it.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Statusbar } from "./Statusbar";
import {
  __resetTapeHealthForTests,
  __tapeRecordTick,
  __tapeRecordTransport,
  getTapeHealth,
} from "@/lib/tape-health";
import { subscribeQuoteMultiplexed } from "@/lib/market-data";
import type { StreamOpts, StreamHandle } from "@/lib/stream";

beforeEach(() => {
  __resetTapeHealthForTests();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Statusbar — tape health pill", () => {
  it("renders nothing when the desk has zero quote subscriptions", () => {
    render(<Statusbar />);
    expect(screen.queryByTestId("tape-health")).toBeNull();
  });

  it("live sockets + a 2s-old tick → LIVE · 2 sym · 2s", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-08T15:00:00Z"));
    const now = Date.now();
    __tapeRecordTransport("BTCUSDT", "live");
    __tapeRecordTransport("ETHUSDT", "live");
    __tapeRecordTick("BTCUSDT", now - 2_000);
    __tapeRecordTick("ETHUSDT", now - 9_000);
    render(<Statusbar />);
    const pill = screen.getByTestId("tape-health");
    expect(pill.getAttribute("data-tape-state")).toBe("live");
    // Freshest tick wins (BTCUSDT at 2s, not ETHUSDT at 9s).
    expect(pill.textContent).toContain("LIVE · 2 sym · 2s");
  });

  it("nothing live but a socket (re)connecting → RECONNECTING with total count", () => {
    __tapeRecordTransport("BTCUSDT", "reconnecting");
    __tapeRecordTransport("ETHUSDT", "offline");
    render(<Statusbar />);
    const pill = screen.getByTestId("tape-health");
    expect(pill.getAttribute("data-tape-state")).toBe("reconnecting");
    expect(pill.textContent).toContain("RECONNECTING · 2 sym");
  });

  it("stale-only tape is DOWN, never LIVE (honest vocabulary)", () => {
    __tapeRecordTransport("BTCUSDT", "stale");
    render(<Statusbar />);
    const pill = screen.getByTestId("tape-health");
    expect(pill.getAttribute("data-tape-state")).toBe("down");
    expect(pill.textContent).toContain("DOWN · 1 sym");
  });

  it("never ticked yet shows an em-dash age instead of a fake number", () => {
    __tapeRecordTransport("BTCUSDT", "connecting");
    render(<Statusbar />);
    const pill = screen.getByTestId("tape-health");
    expect(pill.textContent).toContain("· —");
  });
});

describe("Tape health — market-data multiplexer instrumentation", () => {
  /** Minimal StreamHandle double standing in for lib/stream's WebSocket. */
  function fakeSubscriber(): {
    subscriber: (symbol: string, opts: StreamOpts) => StreamHandle;
    clients: StreamOpts[];
  } {
    const clients: StreamOpts[] = [];
    const subscriber = vi.fn((_symbol: string, opts: StreamOpts): StreamHandle => {
      clients.push(opts);
      return { close: () => undefined };
    });
    return { subscriber: subscriber as (s: string, o: StreamOpts) => StreamHandle, clients };
  }

  it("transport transitions and ticks reach the registry; close releases", () => {
    const { subscriber, clients } = fakeSubscriber();
    const handle = subscribeQuoteMultiplexed("BTCUSDT", {
      subscriber,
      onTick: () => undefined,
      onTransportState: () => undefined,
    });

    clients[0].onStatus?.("connecting");
    expect(getTapeHealth().state).toBe("reconnecting");
    expect(getTapeHealth().totalSymbols).toBe(1);

    clients[0].onStatus?.("live");
    expect(getTapeHealth().state).toBe("live");

    clients[0].onTick?.({
      symbol: "BTCUSDT",
      price: 101.5,
      change_pct: 0.4,
      ts: Date.now(),
      source: "test",
    });
    expect(getTapeHealth().lastTickAt).not.toBeNull();

    handle.close();
    expect(getTapeHealth().totalSymbols).toBe(0);
    expect(getTapeHealth().state).toBe("idle");
  });

  it("a symbol stays registered until its LAST listener unsubscribes", () => {
    const { subscriber, clients } = fakeSubscriber();
    const mk = () =>
      subscribeQuoteMultiplexed("ETHUSDT", {
        subscriber,
        onTick: () => undefined,
        onTransportState: () => undefined,
      });
    const first = mk();
    const second = mk();
    expect(getTapeHealth().totalSymbols).toBe(1);

    first.close();
    expect(getTapeHealth().totalSymbols).toBe(1);

    second.close();
    expect(getTapeHealth().totalSymbols).toBe(0);
    // The shared upstream double was closed exactly once per open — sanity.
    expect(clients.length).toBe(1);
  });
});
