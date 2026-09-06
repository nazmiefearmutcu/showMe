/**
 * FlowMap session store (zustand) — PER-INSTANCE factory.
 *
 * Adapted from upstream `state/store.ts`, which held the Connection and the
 * stream listener set in MODULE scope behind a single `useFlowMapStore`
 * singleton. The embedded library must allow several independent FlowMap panes
 * (and tests) to coexist in one page, so everything the singleton owned lives in
 * the `createFlowMapStore` closure now, and the endpoint is INJECTED (`deps.url`
 * — see endpoint.ts) instead of derived from window.location.
 *
 * Holds ONLY low-frequency connection/session metadata — connection status,
 * capability, session id, epoch geometry, the current subscription. The
 * high-frequency stream (DepthColumn / BarColumn / Trade / BBO / Marker) is
 * deliberately kept OUT of React state: pushing every column through zustand
 * would fire a `set()` per frame and storm re-renders. Instead the store owns
 * the Connection and fans the stream to a plain listener Set; the renderer
 * subscribes via `onStream(handler)` and reads those messages directly (e.g.
 * into a WebGL buffer), never through React.
 *
 * The Connection instance and the listener Set live in the factory closure, not
 * in the store's state, so touching them never triggers a store update.
 */

import { create, type StoreApi, type UseBoundStore } from 'zustand';

import {
  Connection,
  type ConnStatus,
  type ConnectionOptions,
  type StreamMsg,
} from '../net/connection';
import type { EpochParams, FeedState, HistoryResponse, StreamMode } from '../proto/types';

export interface Subscription {
  market: string;
  symbol: string;
  mode: StreamMode;
  /** Server price-grid coverage preset ('native' | 'wide' | 'full' | 'deep'). */
  band: string;
}

/**
 * The identity of the GRID a subscription renders — the key the host watches to
 * decide when the GL ring must be torn down.
 *
 * Deliberately NOT the whole subscription. `mode` is excluded: a live⇄replay
 * toggle re-subscribes the same instrument on the same grid, and resetting there
 * would throw away the user's scrolled-back history for nothing.
 *
 * `band` IS included: it is part of the subscription identity in
 * `connectAndSubscribe` below and in net/connection.ts, so changing it genuinely
 * starts a new server session — one whose grid may be a different HEIGHT (`deep`
 * is 4096 rows against the default 2048).
 */
export function sessionResetKey(sub: Subscription | null): string | null {
  return sub === null ? null : `${sub.market}:${sub.symbol}:${sub.band}`;
}

export interface FlowMapState {
  // --- low-frequency session/connection metadata ---
  status: ConnStatus;
  feedState: FeedState | null;
  /** Next RTH open (UTC ns) from a `Status{feed_state='closed'}`; else null. */
  nextOpenTs: bigint | null;
  capability: Record<string, unknown> | null;
  sessionId: string | null;
  /**
   * Wire protocol version from Hello. Deliberately NOT cleared on a
   * re-subscribe: it describes the SERVER (identical across every session on the
   * same socket), not the session.
   */
  protocolVersion: number | null;
  gridEpoch: number | null;
  normSeed: number | null;
  latencyMs: number | null;
  clockSkewMs: number | null;
  epochs: Map<number, EpochParams>;
  subscription: Subscription | null;
  /**
   * The server refused a replay subscribe with the unsupported close (1003) —
   * there is NO recording for this symbol/session. The store already fell back
   * to live mode when this is set.
   */
  replayUnavailable: boolean;
  /** Replay transport (low-frequency state; ignored in live mode). */
  speed: number;
  paused: boolean;

  // --- actions ---
  connectAndSubscribe: (
    market: string,
    symbol: string,
    mode?: StreamMode,
    band?: string,
  ) => void;
  requestHistory: (before_t: bigint, n: number) => Promise<HistoryResponse>;
  /** Replay transport controls — send the matching control message + track UI state. */
  setSpeed: (x: number) => void;
  pause: () => void;
  resume: () => void;
  seek: (t: bigint) => void;
  disconnect: () => void;
  /** Subscribe to the raw high-frequency stream; returns an unsubscribe fn. */
  onStream: (handler: (msg: StreamMsg) => void) => () => void;
}

export interface FlowMapStoreDeps {
  /** Absolute WS endpoint for the Connection (validated in endpoint.ts). */
  url: string;
  /**
   * Transport overrides (WebSocket factory / timers / jitter) merged into the
   * Connection when it is created. Production leaves this empty; tests inject a
   * FakeWebSocket factory and a deterministic clock.
   */
  transport?: Partial<ConnectionOptions>;
}

export type FlowMapStoreApi = UseBoundStore<StoreApi<FlowMapState>>;

export function createFlowMapStore(deps: FlowMapStoreDeps): FlowMapStoreApi {
  // --- closure-scoped transport (never in store state) ---------------------------
  let conn: Connection | null = null;
  const streamListeners = new Set<(msg: StreamMsg) => void>();

  const fanoutStream = (msg: StreamMsg): void => {
    for (const listener of streamListeners) {
      listener(msg);
    }
  };

  return create<FlowMapState>()((set, get) => ({
    status: 'idle',
    feedState: null,
    nextOpenTs: null,
    capability: null,
    sessionId: null,
    protocolVersion: null,
    gridEpoch: null,
    normSeed: null,
    latencyMs: null,
    clockSkewMs: null,
    epochs: new Map(),
    subscription: null,
    replayUnavailable: false,
    speed: 1,
    paused: false,

    connectAndSubscribe(market, symbol, mode = 'live', band = 'native') {
      if (conn === null) {
        conn = new Connection({
          ...deps.transport,
          url: deps.url,
          // High-frequency stream: straight to the listener Set, never `set()`.
          onStream: fanoutStream,
          onHello: (hello) => {
            const epochs = new Map(get().epochs);
            epochs.set(hello.epoch_params.epoch, hello.epoch_params);
            set({
              sessionId: hello.session_id,
              protocolVersion: hello.protocol_version,
              capability: hello.capability,
              normSeed: hello.norm_seed,
              gridEpoch: hello.grid_epoch,
              epochs,
              // NOTE `replayUnavailable` is deliberately NOT cleared here (see
              // the upstream rationale — it retires on a NEW replay attempt or a
              // different stream instead).
            });
          },
          onEpochStart: (ev) => {
            // Advance the grid epoch to the newest re-anchored frame. Only ever
            // advance: history responses batch EpochStarts for OLDER epochs and
            // must not regress the live price frame.
            const cur = get().gridEpoch;
            const gridEpoch = cur === null ? ev.epoch : Math.max(cur, ev.epoch);
            // No-op guard: reconnect snapshots re-send EpochStarts we already hold.
            if (get().epochs.has(ev.epoch) && gridEpoch === cur) return;
            const epochs = new Map(get().epochs);
            epochs.set(ev.epoch, ev.epoch_params);
            set({ epochs, gridEpoch });
          },
          onStatus: (status) => {
            set({
              feedState: status.feed_state,
              nextOpenTs: status.next_open_ts ?? null,
              capability: status.capability,
              latencyMs: status.latency_ms,
              clockSkewMs: status.clock_skew_ms,
            });
          },
          onConnStatus: (status) => set({ status }),
          // The server honestly refused the replay subscribe (1003 — no
          // recording). Fall back to LIVE right away and flag it.
          onReplayRefused: () => {
            set({ replayUnavailable: true });
            const sub = get().subscription;
            if (sub && sub.mode === 'replay') {
              get().connectAndSubscribe(sub.market, sub.symbol, 'live', sub.band);
            }
          },
        });
      }
      // A DIFFERENT stream is a different server session, so nothing the previous
      // one asserted may survive into it (see the long-form rationale upstream:
      // Status-derived fields, epoch geometry, transport state all reset here).
      const prev = get().subscription;
      if (
        prev === null ||
        prev.market !== market ||
        prev.symbol !== symbol ||
        prev.mode !== mode ||
        prev.band !== band
      ) {
        set({
          subscription: { market, symbol, mode, band },
          speed: 1,
          paused: false,
          feedState: null,
          nextOpenTs: null,
          latencyMs: null,
          clockSkewMs: null,
          // Re-asserted by the new session's Hello on attach.
          sessionId: null,
          capability: null,
          epochs: new Map(),
          gridEpoch: null,
          // gl/renderer.ts latches norm_seed ONCE behind a one-shot flag, so a
          // survivor would normalise the new session against the OLD symbol's
          // density scale.
          normSeed: null,
        });
        if (mode === 'replay') set({ replayUnavailable: false });
        else if (prev !== null && (prev.market !== market || prev.symbol !== symbol)) {
          set({ replayUnavailable: false });
        }
      }
      conn.subscribe(market, symbol, mode, band);
    },

    requestHistory(before_t, n) {
      if (conn === null) {
        return Promise.reject(new Error('flowmap: not connected'));
      }
      return conn.requestHistory(before_t, n);
    },

    setSpeed(x) {
      conn?.setSpeed(x);
      set({ speed: x });
    },

    pause() {
      conn?.pause();
      set({ paused: true });
    },

    resume() {
      conn?.resume();
      set({ paused: false });
    },

    seek(t) {
      conn?.seek(t);
    },

    disconnect() {
      conn?.close();
      conn = null;
      set({ status: 'closed', subscription: null });
    },

    onStream(handler) {
      streamListeners.add(handler);
      return () => {
        streamListeners.delete(handler);
      };
    },
  }));
}
