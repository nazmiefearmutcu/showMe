/**
 * createFlowMap smoke test — NO WebGL (jsdom): the Renderer module is mocked and
 * the transport gets a stubbed global WebSocket, so only the wiring promised by
 * the frozen contract is exercised:
 *
 *   - construction: Renderer(canvas, store) + boot settings + initial subscribe
 *     + onStatus({ webgl: true });
 *   - webgl:false when the renderer cannot create a context (still connects);
 *   - subscribe(newTarget): re-subscribes and resets the GL session;
 *   - idempotent same-target subscribe does NOT reset;
 *   - destroy(): closes the socket, disposes the renderer, final status, and is
 *     safe to call twice.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { createFlowMap } from './createFlowMap';
import type { FlowMapStatus, FlowMapTarget } from './index';

// --- Renderer mock (jsdom has no WebGL2) ----------------------------------------
// A canvas marked data-gl="off" makes the constructor throw, simulating a
// WebGL2 context-creation failure (Renderer's real initGL path).

const h = vi.hoisted(() => {
  class FlowTestRenderer {
    static all: FlowTestRenderer[] = [];
    static reset(): void {
      FlowTestRenderer.all = [];
    }
    readonly followCalls: boolean[] = [];
    readonly priceFollowCalls: string[] = [];
    resetForSessionCount = 0;
    disposeCount = 0;
    canvas: unknown;
    store: unknown;

    constructor(canvas: unknown, store: unknown) {
      const el = canvas as HTMLCanvasElement | null;
      if (
        el !== null &&
        typeof el.getAttribute === 'function' &&
        el.getAttribute('data-gl') === 'off'
      ) {
        throw new Error('WebGL2 context creation failed');
      }
      this.canvas = canvas;
      this.store = store;
      FlowTestRenderer.all.push(this);
    }
    setOverlayVisibility(): void {}
    setBubbleMinSize(): void {}
    setContrast(): void {}
    setTolerance(): void {}
    setColormap(): void {}
    setNormPercentile(): void {}
    setThemeRamp(): void {}
    setBackgroundColor(): void {}
    setFollowTime(on: boolean): void {
      this.followCalls.push(on);
    }
    setPriceFollow(mode: string): void {
      this.priceFollowCalls.push(mode);
    }
    resetForSession(): void {
      this.resetForSessionCount += 1;
    }
    toggleFollow(): void {}
    prefetchHistory(): void {}
    timeline(): null {
      return null;
    }
    dispose(): void {
      this.disposeCount += 1;
    }
  }
  return { FlowTestRenderer };
});

vi.mock('./gl/renderer', () => ({ Renderer: h.FlowTestRenderer }));

// --- WebSocket stub (no real sockets) --------------------------------------------

class StubWebSocket {
  static all: StubWebSocket[] = [];
  static reset(): void {
    StubWebSocket.all = [];
  }
  binaryType = 'blob';
  onopen: ((ev?: unknown) => void) | null = null;
  onclose: ((ev?: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onerror: ((ev?: unknown) => void) | null = null;
  closed = false;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    StubWebSocket.all.push(this);
  }

  send(): void {}
  close(): void {
    this.closed = true;
  }
}

const TARGET: FlowMapTarget = { market: 'crypto', symbol: 'BTCUSDT' };
const WS_URL = 'ws://127.0.0.1:8765/ws/flowmap?token=x';

function stubSocket(): void {
  StubWebSocket.reset();
  h.FlowTestRenderer.reset();
  vi.stubGlobal('WebSocket', StubWebSocket);
}

function makePane(onStatus?: (s: FlowMapStatus) => void) {
  const canvas = document.createElement('canvas');
  return createFlowMap(canvas, { wsUrl: WS_URL, target: TARGET, onStatus });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('createFlowMap — construction', () => {
  it('builds the renderer on the host canvas, applies boot settings, connects', () => {
    stubSocket();
    const onStatus = vi.fn<(s: FlowMapStatus) => void>();
    const canvas = document.createElement('canvas');
    const pane = createFlowMap(canvas, { wsUrl: WS_URL, target: TARGET, onStatus });

    expect(h.FlowTestRenderer.all).toHaveLength(1);
    const r = h.FlowTestRenderer.all[0];
    expect(r.canvas).toBe(canvas);
    expect(typeof (r.store as { getState: unknown }).getState).toBe('function');
    // Boot settings: follow ON, price FIT for the session (upstream defaults).
    expect(r.followCalls).toEqual([true]);
    expect(r.priceFollowCalls).toEqual(['fit']);
    // The endpoint is handed to the transport verbatim (absolute).
    expect(StubWebSocket.all).toHaveLength(1);
    expect(StubWebSocket.all[0].url).toBe(WS_URL);
    // Status bridge is live: connecting (subscribe ran synchronously), GL OK.
    expect(onStatus).toHaveBeenCalled();
    const last = onStatus.mock.calls[onStatus.mock.calls.length - 1][0];
    expect(last.conn).toBe('connecting');
    expect(last.webgl).toBe(true);

    pane.destroy();
  });

  it('reports webgl:false and still connects when the renderer throws', () => {
    stubSocket();
    const statuses: FlowMapStatus[] = [];
    const canvas = document.createElement('canvas');
    canvas.setAttribute('data-gl', 'off'); // the mock's GL-failure trigger
    const pane = createFlowMap(canvas, {
      wsUrl: WS_URL,
      target: TARGET,
      onStatus: (s) => statuses.push(s),
    });

    expect(h.FlowTestRenderer.all).toHaveLength(0); // no renderer instance
    expect(statuses.length).toBeGreaterThan(0);
    expect(statuses.every((s) => s.webgl === false)).toBe(true);
    // The stream still connects so the pane can degrade honestly.
    expect(StubWebSocket.all).toHaveLength(1);

    pane.destroy();
  });

  it('refuses a relative wsUrl instead of silently connecting somewhere else', () => {
    stubSocket();
    expect(() =>
      createFlowMap(document.createElement('canvas'), {
        wsUrl: '/ws/flowmap',
        target: TARGET,
      }),
    ).toThrow(/absolute ws:\/\//);
  });
});

describe('createFlowMap — subscribe / session reset', () => {
  it('re-subscribes to a new target and resets the GL session once', () => {
    stubSocket();
    const pane = makePane();
    const r = h.FlowTestRenderer.all[0];
    expect(r.resetForSessionCount).toBe(0); // first subscription: starts empty

    pane.subscribe({ market: 'crypto', symbol: 'ETHUSDT' });
    expect(r.resetForSessionCount).toBe(1);

    // Idempotent same-target subscribe must NOT reset (no new server session).
    pane.subscribe({ market: 'crypto', symbol: 'ETHUSDT' });
    expect(r.resetForSessionCount).toBe(1);

    // A band change is part of the grid identity → resets too.
    pane.subscribe({ market: 'crypto', symbol: 'ETHUSDT', band: 'deep' });
    expect(r.resetForSessionCount).toBe(2);

    pane.destroy();
  });
});

describe('createFlowMap — destroy', () => {
  it('closes the socket, disposes the renderer, emits a final closed status', () => {
    stubSocket();
    const onStatus = vi.fn<(s: FlowMapStatus) => void>();
    const pane = makePane(onStatus);
    const socket = StubWebSocket.all[0];

    pane.destroy();
    expect(socket.closed).toBe(true);
    expect(h.FlowTestRenderer.all[0].disposeCount).toBe(1);
    const last = onStatus.mock.calls[onStatus.mock.calls.length - 1][0];
    expect(last.conn).toBe('closed');

    // Idempotent: a second destroy must not re-dispose or throw.
    expect(() => pane.destroy()).not.toThrow();
    expect(h.FlowTestRenderer.all[0].disposeCount).toBe(1);
    expect(StubWebSocket.all).toHaveLength(1); // no reconnect socket spawned
  });

  it('ignores subscribe after destroy', () => {
    stubSocket();
    const pane = makePane();
    pane.destroy();
    pane.subscribe({ market: 'crypto', symbol: 'SOLUSDT' });
    expect(StubWebSocket.all).toHaveLength(1);
    expect(h.FlowTestRenderer.all[0].resetForSessionCount).toBe(0);
  });
});
