/**
 * Regression — UI-ROBUSTNESS F2 + F3.
 *
 * F2: `subscribeQuote` blind-cast every parsed WS frame to `Tick`. A
 * primitive frame (`5`, `"x"`, `null`) made `"error" in tick` throw a
 * TypeError that was swallowed as a generic transport error. Now the parse
 * and the shape check are separate: non-object frames become a deliberate
 * protocol-error status, and well-formed frames still reach `onTick`.
 *
 * F3: `StreamHandle.reconnect` force-closes the live socket without ending
 * the subscription — the normal onclose → scheduleReconnect machinery then
 * opens a fresh socket. This is the primitive the stale-transport escalation
 * in market-data.ts uses for half-open TCP connections.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { subscribeQuote, type Tick } from "./stream";

interface MockSocket {
  url: string;
  readyState: number;
  onopen?: () => void;
  onmessage?: (ev: { data: string }) => void;
  onerror?: () => void;
  onclose?: () => void;
  close: () => void;
}

let sockets: MockSocket[] = [];
let originalWebSocket: typeof WebSocket | undefined;

function installMockWebSocket(): void {
  originalWebSocket = globalThis.WebSocket;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).WebSocket = function MockWS(url: string): MockSocket {
    const sock: MockSocket = {
      url,
      readyState: 0,
      close: () => {
        sock.readyState = 3;
        sock.onclose?.();
      },
    };
    sockets.push(sock);
    return sock;
  } as unknown as typeof WebSocket;
}

function restoreWebSocket(): void {
  if (originalWebSocket) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).WebSocket = originalWebSocket;
  }
}

beforeEach(() => {
  sockets = [];
  installMockWebSocket();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  restoreWebSocket();
});

function validTick(): Tick {
  return {
    symbol: "AAPL",
    price: 200,
    change_pct: 1,
    volume: null,
    bid: null,
    ask: null,
    ts: Math.floor(Date.now() / 1000),
    source: "test",
  };
}

describe("subscribeQuote protocol-frame validation (F2)", () => {
  it("primitive number frame → protocol error status, not onTick", () => {
    const onTick = vi.fn();
    const onStatus = vi.fn();
    const h = subscribeQuote("AAPL", { onTick, onStatus });
    sockets[0].onopen?.();
    sockets[0].onmessage?.({ data: "5" });
    expect(onTick).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith(
      "error",
      expect.stringContaining("protocol error"),
    );
    h.close();
  });

  it("primitive string frame and null frame → protocol error status", () => {
    const onTick = vi.fn();
    const onStatus = vi.fn();
    const h = subscribeQuote("AAPL", { onTick, onStatus });
    sockets[0].onopen?.();
    sockets[0].onmessage?.({ data: JSON.stringify("x") });
    sockets[0].onmessage?.({ data: "null" });
    expect(onTick).not.toHaveBeenCalled();
    const errorStatuses = onStatus.mock.calls.filter((c) => c[0] === "error");
    expect(errorStatuses).toHaveLength(2);
    expect(errorStatuses.every((c) => String(c[1]).includes("protocol error"))).toBe(
      true,
    );
    h.close();
  });

  it("array frame → protocol error status", () => {
    const onTick = vi.fn();
    const onStatus = vi.fn();
    const h = subscribeQuote("AAPL", { onTick, onStatus });
    sockets[0].onopen?.();
    sockets[0].onmessage?.({ data: "[1,2]" });
    expect(onTick).not.toHaveBeenCalled();
    const errorStatuses = onStatus.mock.calls.filter((c) => c[0] === "error");
    expect(errorStatuses).toHaveLength(1);
    expect(String(errorStatuses[0][1])).toContain("protocol error");
    h.close();
  });

  it("unparsable JSON → protocol error status", () => {
    const onTick = vi.fn();
    const onStatus = vi.fn();
    const h = subscribeQuote("AAPL", { onTick, onStatus });
    sockets[0].onopen?.();
    sockets[0].onmessage?.({ data: "{not json" });
    expect(onTick).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith(
      "error",
      expect.stringContaining("protocol error"),
    );
    h.close();
  });

  it("error-object frame still surfaces the backend error string", () => {
    const onTick = vi.fn();
    const onStatus = vi.fn();
    const h = subscribeQuote("AAPL", { onTick, onStatus });
    sockets[0].onopen?.();
    sockets[0].onmessage?.({ data: JSON.stringify({ error: "no such symbol" }) });
    expect(onTick).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith("error", "no such symbol");
    h.close();
  });

  it("a well-formed frame still reaches onTick", () => {
    const onTick = vi.fn();
    const h = subscribeQuote("AAPL", { onTick, onStatus: () => undefined });
    sockets[0].onopen?.();
    sockets[0].onmessage?.({ data: JSON.stringify(validTick()) });
    expect(onTick).toHaveBeenCalledTimes(1);
    h.close();
  });
});

describe("StreamHandle.reconnect (F3 primitive)", () => {
  it("drops the live socket and the normal machinery opens a new one", async () => {
    const h = subscribeQuote("AAPL", { onTick: () => undefined });
    const first = sockets[0];
    first.onopen?.();
    expect(sockets).toHaveLength(1);

    h.reconnect?.();
    // Mock close fires onclose synchronously; scheduleReconnect waits 250ms.
    await vi.advanceTimersByTimeAsync(300);

    expect(sockets.length).toBeGreaterThanOrEqual(2);
    // The handle is still live — the replacement socket can deliver ticks.
    sockets[sockets.length - 1].onopen?.();
    expect(first.readyState).toBe(3);
    h.close();
  });

  it("reconnect is a no-op after close() (subscription is terminal)", () => {
    const h = subscribeQuote("AAPL", { onTick: () => undefined });
    sockets[0].onopen?.();
    h.close();
    const count = sockets.length;
    h.reconnect?.();
    expect(sockets.length).toBe(count);
  });
});
