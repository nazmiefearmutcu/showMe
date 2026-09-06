/**
 * `createFlowMap` — the embedded-library entry point (the frozen contract).
 *
 * Mirrors what upstream `App.tsx` did at mount, minus the DOM chrome (top bar,
 * ladder, tape, drawer — not vendored):
 *
 * - instantiates the per-instance store + `Renderer(canvas, store)`. The
 *   Renderer self-wires its ResizeObserver, the canvas gestures, the stream
 *   subscription and the rAF loop (constructor/dispose);
 * - applies the boot settings (upstream defaults): overlay visibility, bubble
 *   threshold, contrast/tolerance/colormap/norm percentile, follow ON and price
 *   FIT for the session;
 * - connects + subscribes via `connectAndSubscribe(market, symbol, 'live', band)`
 *   (band default `'wide'` per the contract);
 * - watches `sessionResetKey(subscription)` — on a target/band change it tears
 *   the GL session down (`Renderer.resetForSession()`) and re-arms the eager
 *   history prefetch (upstream keyed this off App's subscription effect);
 * - eagerly prefetches ~1h of history after the first column lands (the loader
 *   needs the epoch's dt, which only exists once a column arrived);
 * - wires the app-level Space key to toggle time-follow (upstream App did; `/`
 *   symbol-search focus has no embedded counterpart — a no-op handler);
 * - bridges the store's low-frequency state to `onStatus({ conn, feedState,
 *   capability, latencyMs, webgl })`. `webgl:false` when the Renderer could not
 *   create a WebGL2 context (VMs, remote desktops): the connection still runs so
 *   the pane can show an honest fallback instead of dying;
 * - `destroy()` is idempotent: stops the prefetch poll, unsubscribes the store
 *   listener + global keys, closes the socket and disposes GL.
 */

import { resolveEndpoint } from './endpoint';
import { floorForTolerance, gammaForContrast } from './gl/heatmap';
import { Renderer } from './gl/renderer';
import type {
  FlowMapHandle,
  FlowMapOptions,
  FlowMapStatus,
  FlowMapTarget,
} from './index';
import { attachGlobalKeys } from './input/keys';
import { DEFAULT_SETTINGS, historyDepthCols } from './settings';
import { createFlowMapStore, sessionResetKey } from './state/store';

/** How often to poll for the first column before firing the eager prefetch. */
const PREFETCH_POLL_MS = 250;

export function createFlowMap(
  canvas: HTMLCanvasElement,
  opts: FlowMapOptions,
): FlowMapHandle {
  const url = resolveEndpoint(opts.wsUrl);
  const store = createFlowMapStore({ url });

  let destroyed = false;
  let webgl = false;
  let renderer: Renderer | null = null;

  // --- renderer lifecycle (GL setup can legitimately fail — keep connecting) ---
  try {
    renderer = new Renderer(canvas, store);
    // Boot settings (upstream App.tsx mount effect). `setFollowTime` /
    // `setPriceFollow` are remembered by the renderer (`want*` fields) so the
    // lazy ring creation on the first column cannot discard them. BOOT uses
    // price 'fit' on purpose: there is no user zoom to preserve yet.
    renderer.setOverlayVisibility(DEFAULT_SETTINGS.overlays);
    renderer.setBubbleMinSize(DEFAULT_SETTINGS.bubbleMinSize);
    renderer.setContrast(gammaForContrast(DEFAULT_SETTINGS.contrast));
    renderer.setTolerance(floorForTolerance(DEFAULT_SETTINGS.tolerance));
    renderer.setColormap(DEFAULT_SETTINGS.colormap);
    renderer.setNormPercentile(DEFAULT_SETTINGS.normPercentile);
    renderer.setFollowTime(DEFAULT_SETTINGS.follow);
    renderer.setPriceFollow(DEFAULT_SETTINGS.followPrice ? 'fit' : 'off');
    webgl = true;
  } catch (err) {
    // WebGL2 unavailable in this environment: report honestly (webgl:false) and
    // degrade — the stream still connects so status/ladder-style consumers work.
    console.warn('[flowmap] WebGL2 renderer unavailable — webgl:false', err);
  }

  // --- status bridge (store low-frequency state → onStatus) ---------------------
  const emitStatus = (): void => {
    const s = store.getState();
    const status: FlowMapStatus = {
      conn: s.status,
      feedState: s.feedState ?? undefined,
      capability: s.capability ?? undefined,
      latencyMs: s.latencyMs,
      webgl,
    };
    opts.onStatus?.(status);
  };

  // --- eager history prefetch (first column of each session) --------------------
  let prefetchTimer: ReturnType<typeof setInterval> | null = null;
  let prefetchDone = false;
  const stopPrefetchTimer = (): void => {
    if (prefetchTimer !== null) {
      clearInterval(prefetchTimer);
      prefetchTimer = null;
    }
  };
  const armPrefetch = (): void => {
    prefetchDone = false;
    if (prefetchTimer !== null) return; // one poller serves every session
    prefetchTimer = setInterval(() => {
      if (prefetchDone || renderer === null || destroyed) return;
      const tl = renderer.timeline();
      if (tl === null || tl.timeBase === null) return; // wait for the first column
      prefetchDone = true;
      stopPrefetchTimer();
      renderer.prefetchHistory(historyDepthCols(DEFAULT_SETTINGS.historyDepth, tl.timeBase.dtNs));
    }, PREFETCH_POLL_MS);
  };

  // --- session reset on a grid-identity change (App.tsx equivalent) -------------
  let prevSubKey: string | null = null;
  const unsubStore = store.subscribe((state) => {
    const key = sessionResetKey(state.subscription);
    if (key !== null) {
      // Skip the FIRST subscription (the renderer already starts empty); a real
      // target/band change tears the GL session down — the next column of the
      // new session rebuilds it fit to the new price range.
      if (prevSubKey !== null && key !== prevSubKey) {
        renderer?.resetForSession();
        armPrefetch();
      }
      prevSubKey = key;
    }
    emitStatus();
  });

  const subscribe = (target: FlowMapTarget): void => {
    if (destroyed) return;
    store
      .getState()
      .connectAndSubscribe(
        target.market,
        target.symbol,
        'live',
        target.band ?? DEFAULT_SETTINGS.priceBand,
      );
  };

  // --- app-level Space key (upstream App global keys; `/` search has no pane) ---
  const keysDispose = attachGlobalKeys({
    onSpace: () => {
      renderer?.toggleFollow();
    },
    onFocusSearch: () => undefined,
  });

  // Initial subscription + status; the prefetch poller re-arms per session.
  subscribe(opts.target);
  armPrefetch();
  emitStatus();

  const destroy = (): void => {
    if (destroyed) return;
    destroyed = true;
    stopPrefetchTimer();
    unsubStore();
    keysDispose();
    // Close the socket (rejects in-flight history waiters) BEFORE disposing the
    // renderer so no in-flight frame races the GL teardown.
    store.getState().disconnect();
    renderer?.dispose();
    renderer = null;
    emitStatus(); // final honest status: conn 'closed'
  };

  return { subscribe, destroy };
}
