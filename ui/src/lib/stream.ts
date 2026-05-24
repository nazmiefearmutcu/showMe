/**
 * Round 29 — Real-time WebSocket quote subscription helper.
 *
 * Connects to `ws://127.0.0.1:<port>/ws/quote/<symbol>` and forwards
 * normalized ticks to a callback. Auto-reconnects on transient errors
 * with exponential backoff (capped at 5 s) and emits status changes
 * so callers can render a "live / reconnecting / offline" pill.
 *
 * QA-2026-05-23: when ticks have flowed at least once (`everLive`) and the
 * socket subsequently disconnects, surface a single throttled toast so the
 * user knows live data is paused. Throttled at 30 s per process to avoid
 * spam during noisy reconnect storms.
 */
import { sidecarWsUrl } from "./sidecar";
import { toast } from "./toast";

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
const DISCONNECT_TOAST_THROTTLE_MS = 30_000;

let lastDisconnectToastAt = 0;

/** Test seam — clear the cross-process throttle so each test starts fresh. */
export function __resetStreamDisconnectToastForTests(): void {
  lastDisconnectToastAt = 0;
}

function maybeEmitDisconnectToast(): void {
  const now = Date.now();
  if (now - lastDisconnectToastAt < DISCONNECT_TOAST_THROTTLE_MS) return;
  lastDisconnectToastAt = now;
  toast.warn(
    "Live data disconnected — retrying",
    "The quote stream dropped. We're attempting to reconnect.",
  );
}

export function subscribeQuote(symbol: string, opts: StreamOpts): StreamHandle {
  const target = symbol.trim().toUpperCase();
  if (!target) {
    opts.onStatus?.("error", "empty symbol");
    return { close: () => undefined };
  }

  let closed = false;
  let attempt = 0;
  let socket: WebSocket | null = null;
  // PERF-03 P1: track the reconnect timer so close() can cancel it instead
  // of letting orphaned timers fire and pin React closures.
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let everLive = false; // QA-2026-05-23: only toast after a successful connect.

  const stop = () => {
    closed = true;
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    socket?.close();
  };

  const connect = () => {
    if (closed) return;
    opts.onStatus?.(attempt === 0 ? "connecting" : "connecting", `attempt ${attempt + 1}`);
    const url = `${sidecarWsUrl()}/ws/quote/${encodeURIComponent(target)}`;
    socket = new WebSocket(url);
    socket.onopen = () => {
      attempt = 0;
      everLive = true;
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
      // Only toast when we've actually had live data; failing-to-connect on
      // boot is reported as a different UI signal (the runtime pill).
      if (everLive) maybeEmitDisconnectToast();
      const wait = Math.min(MAX_BACKOFF_MS, 250 * 2 ** attempt);
      attempt += 1;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, wait);
    };
  };

  connect();
  // Bundle D / LEAK-01. Track the abort listener so the cleanup returned to
  // the caller can detach it. Without `removeEventListener` we held a strong
  // reference to `stop` (and its closure over `socket`, `reconnectTimer`,
  // `opts.onTick`/`opts.onStatus`) for the entire lifetime of the AbortSignal
  // — i.e. the whole page on persistent signals.
  const signal = opts.signal;
  signal?.addEventListener("abort", stop);

  const close = () => {
    stop();
    signal?.removeEventListener("abort", stop);
  };

  return { close };
}
