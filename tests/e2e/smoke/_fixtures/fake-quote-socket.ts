/**
 * Fake `/ws/quote/<symbol>` WebSocket server for smoke gates.
 *
 * The UI's `subscribeQuote` (lib/stream.ts) connects to
 * `ws://127.0.0.1:<port>/ws/quote/<SYM>` and forwards each JSON message to
 * the consumer hook (`subscribeQuoteStream` in lib/market-data.ts). For the
 * smoke we don't want a real backend, so we intercept the WebSocket with
 * Playwright's `page.routeWebSocket` and emit a tiny scripted tick stream.
 *
 * Why this matters for the gates:
 *   * GP's `gp-transport-pill[data-state="live"]` only appears AFTER a tick
 *     lifts the transport state from `connecting` → `live`.
 *   * WATCH's `LIVE · N` count is computed from how many symbols are in
 *     `transportState === "live"`. Without ticks, the pill stays on
 *     `OFFLINE` forever and the gate assertion drifts to false-positive.
 *
 * The helper is symbol-aware: each connection inspects its path, finds the
 * matching tick script, and sends one tick immediately so the consumer
 * sees `live` on the first message. Additional ticks fire on a small
 * interval to keep `lastTickAt` advancing for assertions that check
 * freshness or sparkline updates.
 */
import type { Page, WebSocketRoute } from "@playwright/test";

export interface FakeTick {
  price: number;
  changePct?: number;
  volume?: number;
  source?: string;
}

export interface FakeQuoteSocketOptions {
  /** Map of upper-case symbol → ordered tick script. */
  ticks: Record<string, FakeTick[]>;
  /** ms between scripted ticks (default 120). */
  intervalMs?: number;
}

export interface FakeQuoteSocketHandle {
  /** Total connection count seen so far. Use for sanity checks. */
  connections(): number;
  /** Stop all interval timers. Called automatically on page close. */
  stop(): void;
}

interface ActiveConnection {
  symbol: string;
  ws: WebSocketRoute;
  timer: ReturnType<typeof setInterval> | null;
  idx: number;
}

export async function installFakeQuoteSocket(
  page: Page,
  options: FakeQuoteSocketOptions,
): Promise<FakeQuoteSocketHandle> {
  const intervalMs = options.intervalMs ?? 120;
  const active = new Set<ActiveConnection>();
  let connectionCount = 0;

  await page.routeWebSocket(/\/ws\/quote\/[^/?]+/, (ws: WebSocketRoute) => {
    connectionCount += 1;
    const url = new URL(ws.url());
    const segments = url.pathname.split("/").filter(Boolean);
    const symbol = decodeURIComponent(
      segments[segments.length - 1] ?? "",
    ).toUpperCase();
    const script = options.ticks[symbol] ?? [];
    const conn: ActiveConnection = { symbol, ws, timer: null, idx: 0 };
    active.add(conn);

    const sendNext = () => {
      if (script.length === 0) return;
      const tick = script[conn.idx % script.length];
      conn.idx += 1;
      const payload = {
        symbol,
        price: tick.price,
        change_pct: tick.changePct ?? null,
        volume: tick.volume ?? null,
        bid: null,
        ask: null,
        // Real backend sends seconds; normalizer in lib/market-data.ts
        // accepts both, but we feed seconds so we exercise the same path.
        ts: Math.floor(Date.now() / 1000),
        source: tick.source ?? "fake-ws",
      };
      try {
        ws.send(JSON.stringify(payload));
      } catch {
        /* socket closed mid-send — drop the tick. */
      }
    };

    // First tick fires immediately so the consumer hook flips to `live`
    // on the very first frame after the WS handshake. Subsequent ticks
    // come every `intervalMs` so the test can wait for either the pill
    // or a freshness update without flakiness.
    sendNext();
    if (script.length > 1) {
      conn.timer = setInterval(sendNext, intervalMs);
    }

    ws.onClose(() => {
      if (conn.timer != null) clearInterval(conn.timer);
      active.delete(conn);
    });
  });

  const stop = () => {
    for (const conn of active) {
      if (conn.timer != null) {
        clearInterval(conn.timer);
        conn.timer = null;
      }
    }
    active.clear();
  };

  page.on("close", stop);

  return {
    connections: () => connectionCount,
    stop,
  };
}
