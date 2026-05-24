/**
 * Stream helper contract tests — focuses on the QA-2026-05-23 fix that emits
 * a single throttled "Live data disconnected" toast on socket drops AFTER a
 * successful connect. The drop-before-first-connect path stays silent so a
 * cold boot doesn't bother the user with a redundant toast.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetStreamDisconnectToastForTests, subscribeQuote } from "./stream";
import { useToastStore } from "./toast";

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
  useToastStore.getState().clear();
  __resetStreamDisconnectToastForTests();
});

afterEach(() => {
  restoreWebSocket();
  useToastStore.getState().clear();
  vi.useRealTimers();
});

describe("subscribeQuote disconnect toast", () => {
  it("does NOT toast when the socket fails BEFORE a successful connect", () => {
    const h = subscribeQuote("AAPL", { onTick: () => undefined });
    const sock = sockets[0];
    // Close without firing onopen → simulate the cold-boot connect failure.
    sock.onclose?.();
    expect(useToastStore.getState().toasts).toHaveLength(0);
    h.close();
  });

  it("emits a single toast when a connected socket drops", () => {
    const h = subscribeQuote("AAPL", { onTick: () => undefined });
    const sock = sockets[0];
    sock.onopen?.();
    sock.onclose?.();
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].title).toMatch(/Live data disconnected/i);
    expect(toasts[0].tone).toBe("warn");
    h.close();
  });

  it("throttles repeat disconnects within the 30s window", () => {
    const h = subscribeQuote("AAPL", { onTick: () => undefined });
    const sock1 = sockets[0];
    sock1.onopen?.();
    sock1.onclose?.();
    // Pretend a new socket opens + drops shortly after — the toast should not
    // re-fire because the throttle hasn't elapsed.
    const sock2 = sockets[0]; // mock reuses array; just simulate same close path
    sock2.onopen?.();
    sock2.onclose?.();
    expect(useToastStore.getState().toasts).toHaveLength(1);
    h.close();
  });

  it("rejects empty symbols without opening a socket", () => {
    subscribeQuote("  ", { onTick: () => undefined });
    expect(sockets).toHaveLength(0);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});
