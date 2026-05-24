/**
 * Canonical live market-data frontend contract.
 *
 * S02 — single source of truth for price-bearing UI. Replaces the ad hoc
 * `fetchQuote` + `subscribeQuote` weave that every pane open-coded.
 *
 * Public hooks:
 *   - useQuote(symbol)         — snapshot fetch (+ optional poll), last-good
 *                                preservation, distinct loading vs refreshing.
 *   - useLiveQuote(symbol)     — snapshot seed + WebSocket tick overlay; adds
 *                                connecting / reconnecting / stale / offline
 *                                / error transport states.
 *   - useLiveQuotes(symbols)   — batch variant for watchlists; one effect
 *                                manages N subscriptions + one shared poll so
 *                                callers don't need illegal dynamic hook loops.
 *   - useChartSeries(symbol,…) — historical seed + live tick channel shape for
 *                                S03 chart runtimes. Returns an explicit
 *                                `unavailable` / `snapshotOnly` state when the
 *                                backend cannot deliver candles — never invents
 *                                data.
 *
 * Design rules:
 *   - Background refresh NEVER clears last-good data.
 *   - Empty / invalid symbols short-circuit before touching the network.
 *   - Sockets and timers are torn down on unmount or symbol change.
 *   - `transportState` distinguishes `connecting | live | stale | reconnecting
 *     | offline | error` so panes can show "looks alive while actually static"
 *     instead of silently lying.
 *   - Pure data layer — no DOM, no React render dependencies beyond the hook.
 */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { fetchQuote, type QuoteSnapshot } from "./quotes";
import {
  subscribeQuote,
  type StreamHandle,
  type StreamStatus,
  type Tick,
} from "./stream";
import { runFunction } from "./functions";

// ---------- public types ----------

export type TransportState =
  | "idle"
  | "connecting"
  | "live"
  | "stale"
  | "reconnecting"
  | "offline"
  | "error";

export type QuoteSourceKind = "snapshot" | "tick" | "none";

export interface NormalizedTick {
  symbol: string;
  price: number;
  changePct: number | null;
  volume: number | null;
  bid: number | null;
  ask: number | null;
  ts: number; // unix ms
  source: string;
}

export interface QuoteView {
  symbol: string;
  snapshot: QuoteSnapshot | null;
  lastTick: NormalizedTick | null;
  price: number | null;
  changePct: number | null;
  source: string | null;
  sourceKind: QuoteSourceKind;
  /** ms epoch of the freshest data point we have for the symbol. */
  fetchedAt: number | null;
  /** Sampled at each freshness tick; null when we have nothing. */
  freshnessMs: number | null;
  /** True when freshnessMs > staleMs (default 60s). */
  stale: boolean;
  /** Initial load with no usable data yet. */
  loading: boolean;
  /** Background refresh in flight; previous data still visible. */
  refreshing: boolean;
  error: string | null;
  transportState: TransportState;
  lastTickAt: number | null;
  /** Trigger an immediate snapshot refresh. */
  refetch: () => void;
}

export interface UseQuoteOptions {
  enabled?: boolean;
  pollMs?: number | null;
  staleMs?: number;
  fetcher?: (symbol: string) => Promise<QuoteSnapshot>;
}

export interface UseLiveQuoteOptions extends UseQuoteOptions {
  autoSubscribe?: boolean;
  staleTickMs?: number;
  subscriber?: typeof subscribeQuote;
}

export interface UseLiveQuotesOptions {
  enabled?: boolean;
  pollMs?: number | null;
  staleMs?: number;
  staleTickMs?: number;
  fetcher?: (symbol: string) => Promise<QuoteSnapshot>;
  subscriber?: typeof subscribeQuote;
}

export type ChartSeriesState =
  | "idle"
  | "loading"
  | "ready"
  | "refreshing"
  | "snapshotOnly"
  | "unavailable"
  | "error";

export interface OhlcBar {
  time: number; // unix seconds (lightweight-charts compatible)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export interface ChartSeriesView {
  state: ChartSeriesState;
  bars: OhlcBar[];
  liveTick: NormalizedTick | null;
  transportState: TransportState;
  error: string | null;
  fetchedAt: number | null;
  refetch: () => void;
}

export interface UseChartSeriesOptions {
  interval: string;
  /** Number of historical bars to request from the backend. */
  depth?: number;
  /** Bloomberg-style range token (`1M`, `3M`, ...) — when known. */
  range?: string;
  enabled?: boolean;
  autoSubscribe?: boolean;
  fnCode?: string;
  fetcher?: (symbol: string, params: Record<string, unknown>) => Promise<unknown>;
  subscriber?: typeof subscribeQuote;
}

// ---------- defaults ----------

const DEFAULT_POLL_MS = 30_000;
const DEFAULT_STALE_QUOTE_MS = 60_000;
const DEFAULT_STALE_TICK_MS = 15_000;
/** How often the freshness clock ticks (drives `freshnessMs` recompute). */
const FRESHNESS_TICK_MS = 1_000;

// ---------- normalizers ----------

export function normalizeSymbol(input: string | null | undefined): string {
  if (typeof input !== "string") return "";
  return input.trim().toUpperCase();
}

export function normalizeTick(tick: Tick): NormalizedTick {
  const rawTs = typeof tick.ts === "number" ? tick.ts : Date.now();
  // Backends sometimes deliver seconds, sometimes milliseconds. Normalize.
  const tsMs = rawTs > 1e12 ? rawTs : rawTs * 1000;
  return {
    symbol: tick.symbol,
    price: tick.price,
    changePct: tick.change_pct ?? null,
    volume: tick.volume ?? null,
    bid: tick.bid ?? null,
    ask: tick.ask ?? null,
    ts: tsMs,
    source: tick.source,
  };
}

function snapshotFetchedAtMs(snap: QuoteSnapshot): number {
  const parsed = Date.parse(snap.fetched_at);
  return Number.isFinite(parsed) ? parsed : Date.now();
}

// ---------- stream wrapper (adds reconnecting/stale) ----------

interface StreamWrapperOpts {
  onTick: (tick: NormalizedTick) => void;
  onTransportState: (state: TransportState, info?: string) => void;
  staleTickMs?: number;
  subscriber?: typeof subscribeQuote;
}

/**
 * Wraps `subscribeQuote` (low-level WS helper) so consumers see a richer
 * transport-state machine. The low-level helper only knows `connecting / live
 * / offline / error`. Here we add:
 *   - `reconnecting` after the first successful connect or any close/retry;
 *   - `stale` after `staleTickMs` of socket-up-but-no-tick.
 * The wrapper takes ownership of cleanup: closing the handle also tears down
 * the stale timer.
 */
export function subscribeQuoteStream(
  symbol: string,
  opts: StreamWrapperOpts,
): StreamHandle {
  const target = normalizeSymbol(symbol);
  if (!target) {
    opts.onTransportState("error", "empty symbol");
    return { close: () => undefined };
  }
  let everConnected = false;
  let staleTimer: ReturnType<typeof setTimeout> | null = null;
  let currentState: TransportState = "idle";
  let closed = false;

  const setState = (next: TransportState, info?: string) => {
    if (closed) return;
    if (next === currentState) return;
    currentState = next;
    opts.onTransportState(next, info);
  };

  const clearStaleTimer = () => {
    if (staleTimer != null) {
      clearTimeout(staleTimer);
      staleTimer = null;
    }
  };

  const armStaleTimer = () => {
    clearStaleTimer();
    const wait = opts.staleTickMs ?? DEFAULT_STALE_TICK_MS;
    if (wait <= 0) return;
    staleTimer = setTimeout(() => {
      staleTimer = null;
      if (closed) return;
      if (currentState === "live") setState("stale", "no tick");
    }, wait);
  };

  const subscriberFn = opts.subscriber ?? subscribeQuote;
  const handle = subscriberFn(target, {
    onTick: (tick) => {
      if (closed) return;
      everConnected = true;
      setState("live");
      armStaleTimer();
      opts.onTick(normalizeTick(tick));
    },
    onStatus: (status: StreamStatus, info?: string) => {
      if (closed) return;
      switch (status) {
        case "connecting":
          setState(everConnected ? "reconnecting" : "connecting", info);
          break;
        case "live":
          everConnected = true;
          setState("live", info);
          armStaleTimer();
          break;
        case "offline":
          // The low-level helper schedules a reconnect itself; reflect that
          // back to the UI as "reconnecting" so panes don't briefly flash
          // an idle/offline state on every transient blip.
          setState(everConnected ? "reconnecting" : "offline", info);
          break;
        case "error":
          setState("error", info);
          break;
      }
    },
  });

  return {
    close: () => {
      if (closed) return;
      closed = true;
      clearStaleTimer();
      handle.close();
    },
  };
}

// ---------- module-level WebSocket multiplex ----------

interface MultiplexListener {
  onTick: (tick: NormalizedTick) => void;
  onTransportState: (state: TransportState, info?: string) => void;
}

interface MultiplexEntry {
  symbol: string;
  upstream: StreamHandle;
  listeners: Set<MultiplexListener>;
  lastTransportState: TransportState;
  lastTick: NormalizedTick | null;
}

/**
 * Subscriber identity → symbol → shared entry. Production code uses the
 * default `subscribeQuote` reference so a single underlying WebSocket per
 * symbol is shared across every pane in the workspace. Tests that inject a
 * custom subscriber get their own bucket — keeping unit isolation intact.
 */
const multiplexBuckets = new WeakMap<
  typeof subscribeQuote,
  Map<string, MultiplexEntry>
>();

/**
 * Reset every multiplex entry. Tests should call this between cases to avoid
 * leaking upstream handles into the next test.
 */
export function __resetMultiplexForTests(): void {
  // WeakMap cannot be iterated; just drop the reference so GC reclaims it.
  // Existing live entries will close on their last unsubscribe.
  for (const subscriber of __knownSubscribers) {
    const bucket = multiplexBuckets.get(subscriber);
    if (!bucket) continue;
    for (const entry of bucket.values()) {
      entry.upstream.close();
      entry.listeners.clear();
    }
    bucket.clear();
  }
  __knownSubscribers.clear();
}

const __knownSubscribers = new Set<typeof subscribeQuote>();

function bucketFor(subscriber: typeof subscribeQuote): Map<string, MultiplexEntry> {
  let bucket = multiplexBuckets.get(subscriber);
  if (!bucket) {
    bucket = new Map<string, MultiplexEntry>();
    multiplexBuckets.set(subscriber, bucket);
    __knownSubscribers.add(subscriber);
  }
  return bucket;
}

interface MultiplexedSubscribeOpts {
  onTick: (tick: NormalizedTick) => void;
  onTransportState: (state: TransportState, info?: string) => void;
  staleTickMs?: number;
  subscriber?: typeof subscribeQuote;
}

/**
 * Share a single underlying WebSocket per (subscriber, symbol). Each caller
 * gets its own handle; the upstream stays open until the last listener
 * unsubscribes. The shared entry replays the most-recent transport state and
 * tick to late joiners so a freshly-mounted pane doesn't sit on "idle".
 *
 * Pre-QA each (hookInstance, symbol) pair opened its own WebSocket; 4 WATCH
 * panes × 7 symbols meant 28 sockets fighting over the same data. After this
 * change every hook funnels through the multiplexer and the upstream socket
 * count collapses to one per symbol.
 */
export function subscribeQuoteMultiplexed(
  symbol: string,
  opts: MultiplexedSubscribeOpts,
): StreamHandle {
  const target = normalizeSymbol(symbol);
  if (!target) {
    opts.onTransportState("error", "empty symbol");
    return { close: () => undefined };
  }
  const subscriber = opts.subscriber ?? subscribeQuote;
  const bucket = bucketFor(subscriber);
  let entry = bucket.get(target);
  if (!entry) {
    const newEntry: MultiplexEntry = {
      symbol: target,
      upstream: { close: () => undefined },
      listeners: new Set(),
      lastTransportState: "idle",
      lastTick: null,
    };
    bucket.set(target, newEntry);
    // Open the shared upstream subscription. This is the only place where
    // `subscribeQuoteStream` (and thereby the underlying WebSocket) is
    // exercised — all other callers attach to the existing entry.
    newEntry.upstream = subscribeQuoteStream(target, {
      staleTickMs: opts.staleTickMs,
      subscriber,
      onTick: (tick) => {
        newEntry.lastTick = tick;
        for (const listener of newEntry.listeners) {
          try {
            listener.onTick(tick);
          } catch (err) {
            // A listener throwing should never kill the multiplex fan-out.
            console.warn("[market-data] multiplex listener tick threw", err);
          }
        }
      },
      onTransportState: (state, info) => {
        newEntry.lastTransportState = state;
        for (const listener of newEntry.listeners) {
          try {
            listener.onTransportState(state, info);
          } catch (err) {
            console.warn(
              "[market-data] multiplex listener transport threw",
              err,
            );
          }
        }
      },
    });
    entry = newEntry;
  }

  const listener: MultiplexListener = {
    onTick: opts.onTick,
    onTransportState: opts.onTransportState,
  };
  entry.listeners.add(listener);

  // Replay the most recent state so the joiner can paint immediately. The
  // upstream pushes future events as they arrive.
  if (entry.lastTransportState !== "idle") {
    try {
      listener.onTransportState(entry.lastTransportState);
    } catch {
      /* listener throwing on replay is non-fatal */
    }
  }
  if (entry.lastTick) {
    try {
      listener.onTick(entry.lastTick);
    } catch {
      /* listener throwing on replay is non-fatal */
    }
  }

  let closed = false;
  return {
    close: () => {
      if (closed) return;
      closed = true;
      const live = bucket.get(target);
      if (!live) return;
      live.listeners.delete(listener);
      if (live.listeners.size === 0) {
        live.upstream.close();
        bucket.delete(target);
      }
    },
  };
}

// ---------- internal per-symbol state ----------

interface SymbolState {
  symbol: string;
  snapshot: QuoteSnapshot | null;
  snapshotAt: number | null;
  lastTick: NormalizedTick | null;
  lastTickAt: number | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  transportState: TransportState;
}

function emptySymbolState(symbol: string, transportState: TransportState = "idle"): SymbolState {
  return {
    symbol,
    snapshot: null,
    snapshotAt: null,
    lastTick: null,
    lastTickAt: null,
    loading: true,
    refreshing: false,
    error: null,
    transportState,
  };
}

function withSnapshot(state: SymbolState, snap: QuoteSnapshot): SymbolState {
  return {
    ...state,
    snapshot: snap,
    snapshotAt: snapshotFetchedAtMs(snap),
    loading: false,
    refreshing: false,
    error: null,
  };
}

function withSnapshotError(state: SymbolState, err: unknown): SymbolState {
  const message = err instanceof Error ? err.message : String(err ?? "snapshot error");
  // CRITICAL FIX (audit S2): `state.snapshot ? false : false` was a copy-paste
  // bug — both branches set `loading=false`, masking the very-first-fetch error
  // because the row never flipped out of the "loading…" placeholder. Loading
  // is true ONLY when we have NEITHER a previous snapshot NOR a live tick AND
  // the error itself is what surfaces (so retry CTAs can render).
  return {
    ...state,
    loading: state.snapshot == null && state.lastTick == null,
    refreshing: false,
    // Keep prior snapshot intact — that's the whole point of last-good.
    error: message,
  };
}

function withTick(state: SymbolState, tick: NormalizedTick): SymbolState {
  return {
    ...state,
    lastTick: tick,
    lastTickAt: tick.ts,
    // A live tick clears the prior snapshot error visually; the snapshot
    // itself stays as last-good in case ticks dry up.
    error: null,
  };
}

function withTransportState(state: SymbolState, transportState: TransportState): SymbolState {
  if (state.transportState === transportState) return state;
  return { ...state, transportState };
}

function toView(
  symbol: string,
  state: SymbolState | undefined,
  now: number,
  staleMs: number,
): QuoteView {
  if (!state) {
    return {
      symbol,
      snapshot: null,
      lastTick: null,
      price: null,
      changePct: null,
      source: null,
      sourceKind: "none",
      fetchedAt: null,
      freshnessMs: null,
      stale: false,
      loading: false,
      refreshing: false,
      error: null,
      transportState: "idle",
      lastTickAt: null,
      refetch: () => undefined,
    };
  }
  const tickAt = state.lastTickAt;
  const snapAt = state.snapshotAt;
  const tickFresher = tickAt != null && (snapAt == null || tickAt >= snapAt);
  const sourceKind: QuoteSourceKind = tickFresher
    ? "tick"
    : state.snapshot
      ? "snapshot"
      : "none";
  const price = tickFresher
    ? (state.lastTick?.price ?? state.snapshot?.last ?? null)
    : (state.snapshot?.last ?? state.lastTick?.price ?? null);
  const changePct = tickFresher
    ? (state.lastTick?.changePct ?? state.snapshot?.change_pct ?? null)
    : (state.snapshot?.change_pct ?? state.lastTick?.changePct ?? null);
  const source = tickFresher
    ? (state.lastTick?.source ?? state.snapshot?.source ?? null)
    : (state.snapshot?.source ?? state.lastTick?.source ?? null);
  const fetchedAt = tickFresher
    ? tickAt
    : (snapAt ?? tickAt ?? null);
  const freshnessMs = fetchedAt != null ? Math.max(0, now - fetchedAt) : null;
  return {
    symbol,
    snapshot: state.snapshot,
    lastTick: state.lastTick,
    price,
    changePct,
    source,
    sourceKind,
    fetchedAt,
    freshnessMs,
    stale: freshnessMs != null && freshnessMs > staleMs,
    loading: state.loading && state.snapshot == null && state.lastTick == null,
    refreshing: state.refreshing,
    error: state.error,
    transportState: state.transportState,
    lastTickAt: tickAt,
    refetch: () => undefined,
  };
}

// ---------- freshness clock ----------

const freshnessListeners = new Set<() => void>();
let freshnessTimer: ReturnType<typeof setInterval> | null = null;
let freshnessNow = Date.now();

function startFreshnessTimer() {
  if (freshnessTimer != null) return;
  freshnessTimer = setInterval(() => {
    freshnessNow = Date.now();
    for (const fn of freshnessListeners) fn();
  }, FRESHNESS_TICK_MS);
}

function stopFreshnessTimer() {
  if (freshnessListeners.size > 0) return;
  if (freshnessTimer != null) {
    clearInterval(freshnessTimer);
    freshnessTimer = null;
  }
}

/**
 * Shared 1Hz clock so every market-data view recomputes `freshnessMs` and
 * `stale` on the same heartbeat without spawning a setInterval per consumer.
 */
function useFreshnessNow(): number {
  return useSyncExternalStore(
    (notify) => {
      freshnessListeners.add(notify);
      startFreshnessTimer();
      return () => {
        freshnessListeners.delete(notify);
        stopFreshnessTimer();
      };
    },
    () => freshnessNow,
    () => freshnessNow,
  );
}

// ---------- canonical batch implementation ----------

interface UseLiveQuotesInternalOptions extends UseLiveQuotesOptions {
  autoSubscribe?: boolean;
}

function useLiveQuotesInternal(
  symbols: string[],
  options: UseLiveQuotesInternalOptions = {},
): Record<string, QuoteView> {
  const enabled = options.enabled !== false;
  const pollMs = options.pollMs === undefined ? DEFAULT_POLL_MS : options.pollMs;
  const staleMs = options.staleMs ?? DEFAULT_STALE_QUOTE_MS;
  const staleTickMs = options.staleTickMs ?? DEFAULT_STALE_TICK_MS;
  const autoSubscribe = options.autoSubscribe !== false;
  const fetcherRef = useRef(options.fetcher ?? fetchQuote);
  const subscriberRef = useRef(options.subscriber ?? subscribeQuote);
  useEffect(() => {
    fetcherRef.current = options.fetcher ?? fetchQuote;
    subscriberRef.current = options.subscriber ?? subscribeQuote;
  }, [options.fetcher, options.subscriber]);

  const normalized = useMemo(() => {
    const set = new Set<string>();
    for (const sym of symbols) {
      const n = normalizeSymbol(sym);
      if (n) set.add(n);
    }
    return Array.from(set).sort();
  }, [symbols]);
  const normalizedKey = normalized.join("|");

  const [state, setState] = useState<Record<string, SymbolState>>({});
  const refetchRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!enabled || normalized.length === 0) {
      // Drop subscriptions when disabled or empty — and don't fabricate state.
      return undefined;
    }

    let cancelled = false;
    let polling = false;

    setState((prev) => {
      const next: Record<string, SymbolState> = { ...prev };
      let changed = false;
      for (const sym of normalized) {
        if (!next[sym]) {
          next[sym] = emptySymbolState(sym, autoSubscribe ? "connecting" : "idle");
          changed = true;
        } else if (!next[sym].snapshot && !next[sym].lastTick) {
          // Re-entered loading after a previous disable.
          next[sym] = { ...next[sym], loading: true };
          changed = true;
        }
      }
      // Prune symbols that just rotated out.
      for (const sym of Object.keys(next)) {
        if (!normalized.includes(sym)) {
          delete next[sym];
          changed = true;
        }
      }
      return changed ? next : prev;
    });

    const refresh = async (kind: "initial" | "background") => {
      if (cancelled || polling) return;
      polling = true;
      try {
        if (kind === "background") {
          setState((prev) => {
            const next: Record<string, SymbolState> = { ...prev };
            let changed = false;
            for (const sym of normalized) {
              const existing = next[sym] ?? emptySymbolState(sym);
              if (!existing.refreshing) {
                next[sym] = { ...existing, refreshing: true };
                changed = true;
              }
            }
            return changed ? next : prev;
          });
        }
        const results = await Promise.all(
          normalized.map(async (sym) => {
            try {
              const snap = await fetcherRef.current(sym);
              return [sym, { snapshot: snap, error: null }] as const;
            } catch (err) {
              return [sym, { snapshot: null, error: err }] as const;
            }
          }),
        );
        if (cancelled) return;
        setState((prev) => {
          const next: Record<string, SymbolState> = { ...prev };
          for (const [sym, result] of results) {
            const base = next[sym] ?? emptySymbolState(sym);
            if (result.snapshot) {
              next[sym] = withSnapshot(base, result.snapshot);
            } else {
              next[sym] = withSnapshotError(base, result.error);
            }
          }
          return next;
        });
      } finally {
        polling = false;
      }
    };

    refetchRef.current = () => {
      void refresh("background");
    };

    void refresh("initial");

    const pollId =
      pollMs != null && pollMs > 0
        ? setInterval(() => {
            void refresh("background");
          }, pollMs)
        : null;

    const handles: StreamHandle[] = [];
    if (autoSubscribe) {
      for (const sym of normalized) {
        // Multiplex through the module-level entry so N panes subscribing to
        // the same symbol share one underlying WebSocket. Per-hook closures
        // still receive every tick / transport-state event.
        const h = subscribeQuoteMultiplexed(
          sym,
          {
            staleTickMs,
            subscriber: subscriberRef.current,
            onTick: (tick) => {
              if (cancelled) return;
              setState((prev) => {
                const base = prev[sym] ?? emptySymbolState(sym);
                return { ...prev, [sym]: withTick(base, tick) };
              });
            },
            onTransportState: (transport) => {
              if (cancelled) return;
              setState((prev) => {
                const base = prev[sym] ?? emptySymbolState(sym);
                return { ...prev, [sym]: withTransportState(base, transport) };
              });
            },
          },
        );
        handles.push(h);
      }
    }

    return () => {
      cancelled = true;
      if (pollId != null) clearInterval(pollId);
      for (const h of handles) h.close();
      refetchRef.current = () => undefined;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [normalizedKey, enabled, pollMs, autoSubscribe, staleTickMs]);

  const now = useFreshnessNow();

  return useMemo(() => {
    const out: Record<string, QuoteView> = {};
    const refetch = () => refetchRef.current();
    for (const sym of normalized) {
      const view = toView(sym, state[sym], now, staleMs);
      view.refetch = refetch;
      out[sym] = view;
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [normalizedKey, state, now, staleMs]);
}

// ---------- public hooks ----------

/**
 * Snapshot-only quote hook. Polls on a fixed cadence (`pollMs`, default 30s).
 * Last-good snapshot is preserved across refreshes and errors.
 */
export function useQuote(symbol: string | null | undefined, options: UseQuoteOptions = {}): QuoteView {
  const sym = normalizeSymbol(symbol);
  const symbols = useMemo(() => (sym ? [sym] : []), [sym]);
  const map = useLiveQuotesInternal(symbols, {
    enabled: options.enabled,
    pollMs: options.pollMs,
    staleMs: options.staleMs,
    fetcher: options.fetcher,
    autoSubscribe: false,
  });
  return sym
    ? (map[sym] ?? toEmptyView(sym))
    : toEmptyView("");
}

/**
 * Snapshot seed + WebSocket tick overlay. The snapshot acts as last-good when
 * the live channel drops; ticks update `price` / `changePct` / `lastTickAt`
 * without ever erasing the snapshot.
 */
export function useLiveQuote(
  symbol: string | null | undefined,
  options: UseLiveQuoteOptions = {},
): QuoteView {
  const sym = normalizeSymbol(symbol);
  const symbols = useMemo(() => (sym ? [sym] : []), [sym]);
  const map = useLiveQuotesInternal(symbols, {
    enabled: options.enabled,
    pollMs: options.pollMs,
    staleMs: options.staleMs,
    staleTickMs: options.staleTickMs,
    fetcher: options.fetcher,
    subscriber: options.subscriber,
    autoSubscribe: options.autoSubscribe !== false,
  });
  return sym ? (map[sym] ?? toEmptyView(sym)) : toEmptyView("");
}

/**
 * Batch live-quote hook for watchlists. The returned map is keyed by the
 * upper-cased trimmed symbol; symbols absent from the input do not appear.
 *
 * Caller stability rules:
 *   - Passing a new array reference with the same contents is fine — the hook
 *     stabilises on a sorted, deduped key internally.
 *   - Empty arrays short-circuit (no fetches, no sockets).
 */
export function useLiveQuotes(
  symbols: string[],
  options: UseLiveQuotesOptions = {},
): Record<string, QuoteView> {
  return useLiveQuotesInternal(symbols, {
    enabled: options.enabled,
    pollMs: options.pollMs,
    staleMs: options.staleMs,
    staleTickMs: options.staleTickMs,
    fetcher: options.fetcher,
    subscriber: options.subscriber,
    autoSubscribe: true,
  });
}

function toEmptyView(symbol: string): QuoteView {
  return {
    symbol,
    snapshot: null,
    lastTick: null,
    price: null,
    changePct: null,
    source: null,
    sourceKind: "none",
    fetchedAt: null,
    freshnessMs: null,
    stale: false,
    loading: false,
    refreshing: false,
    error: null,
    transportState: "idle",
    lastTickAt: null,
    refetch: () => undefined,
  };
}

// ---------- chart series (S03 contract only) ----------

interface ChartSeriesInternalState {
  state: ChartSeriesState;
  bars: OhlcBar[];
  error: string | null;
  fetchedAt: number | null;
  transportState: TransportState;
  liveTick: NormalizedTick | null;
}

const CHART_DEFAULT_DEPTH = 1_000;

function parseOhlcRows(input: unknown): OhlcBar[] {
  if (!input) return [];
  let rows: unknown[];
  if (Array.isArray(input)) {
    rows = input;
  } else if (typeof input === "object") {
    rows = Object.entries(input as Record<string, unknown>).map(([ts, row]) => ({
      ts,
      ...(row as Record<string, unknown>),
    }));
  } else {
    return [];
  }
  const bars: OhlcBar[] = [];
  for (const raw of rows) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const open = Number(row.open ?? row.o);
    const high = Number(row.high ?? row.h);
    const low = Number(row.low ?? row.l);
    const close = Number(row.close ?? row.c ?? row.value ?? row.price);
    if (
      !Number.isFinite(open) ||
      !Number.isFinite(high) ||
      !Number.isFinite(low) ||
      !Number.isFinite(close)
    ) {
      continue;
    }
    const timeRaw = row.time ?? row.ts ?? row.date;
    const time = toUnixSeconds(timeRaw);
    if (time == null) continue;
    const volumeRaw = row.volume ?? row.v;
    const volume =
      volumeRaw == null
        ? null
        : Number.isFinite(Number(volumeRaw))
          ? Number(volumeRaw)
          : null;
    bars.push({ time, open, high, low, close, volume });
  }
  bars.sort((a, b) => a.time - b.time);
  return bars;
}

function toUnixSeconds(value: unknown): number | null {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return value > 1e12 ? Math.floor(value / 1000) : Math.floor(value);
  }
  if (typeof value === "string") {
    if (!value) return null;
    if (value.includes("T")) {
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
    }
    const parsedDate = Date.parse(value.length === 10 ? `${value}T00:00:00Z` : value);
    if (Number.isFinite(parsedDate)) return Math.floor(parsedDate / 1000);
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return numeric > 1e12 ? Math.floor(numeric / 1000) : Math.floor(numeric);
    }
  }
  return null;
}

const emptyChartState = (): ChartSeriesInternalState => ({
  state: "idle",
  bars: [],
  error: null,
  fetchedAt: null,
  transportState: "idle",
  liveTick: null,
});

/**
 * Historical seed + live tick channel for chart panes (S03 will consume this).
 *
 * Returns `unavailable` when the backend cannot deliver bars (e.g., asset class
 * without history) and `snapshotOnly` when the backend reports `empty` /
 * `provider_unavailable` but the symbol has live ticks — that lets the chart
 * pane render a flat-line tick view instead of inventing OHLC candles.
 */
export function useChartSeries(
  symbol: string | null | undefined,
  options: UseChartSeriesOptions,
): ChartSeriesView {
  const sym = normalizeSymbol(symbol);
  const enabled = options.enabled !== false && Boolean(sym);
  const autoSubscribe = options.autoSubscribe !== false;
  const fnCode = options.fnCode ?? "GP";
  const interval = options.interval;
  const depth = options.depth ?? CHART_DEFAULT_DEPTH;
  const range = options.range;
  const fetcherRef = useRef(
    options.fetcher ??
      ((s: string, params: Record<string, unknown>) =>
        runFunction<Record<string, unknown>>(fnCode, { symbol: s, params })),
  );
  const subscriberRef = useRef(options.subscriber ?? subscribeQuote);
  useEffect(() => {
    fetcherRef.current =
      options.fetcher ??
      ((s: string, params: Record<string, unknown>) =>
        runFunction<Record<string, unknown>>(fnCode, { symbol: s, params }));
    subscriberRef.current = options.subscriber ?? subscribeQuote;
  }, [options.fetcher, options.subscriber, fnCode]);

  const [internal, setInternal] = useState<ChartSeriesInternalState>(emptyChartState);
  const refetchRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!enabled) {
      setInternal(emptyChartState());
      refetchRef.current = () => undefined;
      return undefined;
    }

    let cancelled = false;

    const params: Record<string, unknown> = { interval, bars: depth };
    if (range) params.range = range;

    const load = async (kind: "initial" | "background") => {
      if (cancelled) return;
      setInternal((prev) => ({
        ...prev,
        state: kind === "initial" && prev.bars.length === 0 ? "loading" : "refreshing",
        error: kind === "initial" ? null : prev.error,
      }));
      try {
        const raw = await fetcherRef.current(sym, params);
        if (cancelled) return;
        const payload = (raw ?? {}) as {
          status?: string;
          data?: { ohlcv?: unknown; bars?: unknown; rows?: unknown };
        };
        const ohlcvSource =
          payload.data?.ohlcv ?? payload.data?.bars ?? payload.data?.rows ?? null;
        const bars = parseOhlcRows(ohlcvSource);
        const status = payload.status;
        setInternal((prev) => {
          if (bars.length > 0) {
            return {
              ...prev,
              state: "ready",
              bars,
              error: null,
              fetchedAt: Date.now(),
            };
          }
          if (status === "provider_unavailable" || status === "input_error") {
            return {
              ...prev,
              state: "unavailable",
              error: null,
              fetchedAt: Date.now(),
            };
          }
          if (status === "empty") {
            return {
              ...prev,
              state: prev.bars.length > 0 ? "ready" : "snapshotOnly",
              error: null,
              fetchedAt: Date.now(),
            };
          }
          return {
            ...prev,
            // Backend returned 0 rows without an explicit status — surface this
            // as snapshotOnly rather than ready-with-no-data so charts can
            // render a "snapshot only" badge instead of an empty canvas.
            state: prev.bars.length > 0 ? "ready" : "snapshotOnly",
            error: null,
            fetchedAt: Date.now(),
          };
        });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err ?? "chart error");
        setInternal((prev) => ({
          ...prev,
          state: prev.bars.length > 0 ? "ready" : "error",
          error: message,
        }));
      }
    };

    refetchRef.current = () => {
      void load("background");
    };

    void load("initial");

    let handle: StreamHandle | null = null;
    if (autoSubscribe) {
      // Charts share the same per-symbol upstream as the WATCH grid via the
      // multiplexer — no second WebSocket for a chart pane already showing a
      // live quote in a sibling panel.
      handle = subscribeQuoteMultiplexed(sym, {
        subscriber: subscriberRef.current,
        onTick: (tick) => {
          if (cancelled) return;
          setInternal((prev) => ({ ...prev, liveTick: tick }));
        },
        onTransportState: (transport) => {
          if (cancelled) return;
          setInternal((prev) => ({ ...prev, transportState: transport }));
        },
      });
    }

    return () => {
      cancelled = true;
      handle?.close();
      refetchRef.current = () => undefined;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sym, interval, depth, range, autoSubscribe]);

  return {
    state: internal.state,
    bars: internal.bars,
    liveTick: internal.liveTick,
    transportState: internal.transportState,
    error: internal.error,
    fetchedAt: internal.fetchedAt,
    refetch: () => refetchRef.current(),
  };
}

// ---------- test surface ----------

/**
 * Internal helpers exported only so tests can drive the freshness clock and
 * the view projection in isolation. Production code should use the hooks.
 */
export const __internal = {
  toView,
  emptySymbolState,
  withSnapshot,
  withSnapshotError,
  withTick,
  withTransportState,
};
