/**
 * Round 29 — Real-time WebSocket quote subscription helper.
 *
 * Connects to `ws://127.0.0.1:<port>/ws/quote/<symbol>` and forwards
 * normalized ticks to a callback. Auto-reconnects on transient errors
 * with exponential backoff (capped at 5 s) and emits status changes
 * so callers can render a "live / reconnecting / offline" pill.
 */
import { sidecarWsUrl } from "./sidecar";

export interface Tick {
  symbol: string;
  price: number;
  change_pct: number | null;
  volume?: number | null;
  bid?: number | null;
  ask?: number | null;
  ts: number;
  source: string;
}

export type StreamStatus = "connecting" | "live" | "offline" | "error";

export interface StreamHandle {
  close: () => void;
}

export interface StreamOpts {
  onTick: (tick: Tick) => void;
  onStatus?: (status: StreamStatus, info?: string) => void;
  signal?: AbortSignal;
}

const MAX_BACKOFF_MS = 5_000;

export function subscribeQuote(symbol: string, opts: StreamOpts): StreamHandle {
  const target = symbol.trim().toUpperCase();
  if (!target) {
    opts.onStatus?.("error", "empty symbol");
    return { close: () => undefined };
  }

  let closed = false;
  let attempt = 0;
  let socket: WebSocket | null = null;

  const connect = () => {
    if (closed) return;
    opts.onStatus?.(attempt === 0 ? "connecting" : "connecting", `attempt ${attempt + 1}`);
    const url = `${sidecarWsUrl()}/ws/quote/${encodeURIComponent(target)}`;
    socket = new WebSocket(url);
    socket.onopen = () => {
      attempt = 0;
      opts.onStatus?.("live");
    };
    socket.onmessage = (ev) => {
      try {
        const tick = JSON.parse(ev.data) as Tick;
        if ("error" in (tick as unknown as Record<string, unknown>)) {
          opts.onStatus?.(
            "error",
            (tick as unknown as Record<string, unknown>).error as string,
          );
          return;
        }
        opts.onTick(tick);
      } catch (err) {
        opts.onStatus?.("error", String(err));
      }
    };
    socket.onerror = () => {
      opts.onStatus?.("error", "socket error");
    };
    socket.onclose = () => {
      socket = null;
      if (closed) return;
      opts.onStatus?.("offline");
      const wait = Math.min(MAX_BACKOFF_MS, 250 * 2 ** attempt);
      attempt += 1;
      setTimeout(connect, wait);
    };
  };

  connect();
  opts.signal?.addEventListener("abort", () => {
    closed = true;
    socket?.close();
  });

  return {
    close: () => {
      closed = true;
      socket?.close();
    },
  };
}
