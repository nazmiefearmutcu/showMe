/**
 * FLW — FlowMap depth-heatmap library (vendored from the FlowMap project).
 *
 * PUBLIC CONTRACT (stable — the FLW pane codes against exactly this surface):
 * the implementation modules in this directory may be reorganized freely, but
 * the exports below must keep these names and shapes. `createFlowMap` is
 * implemented in ./createFlowMap (store + Connection + Renderer wiring).
 */

export type FlowMapConnState =
  | "idle"
  | "connecting"
  | "live"
  | "reconnecting"
  | "error"
  | "closed";

export interface FlowMapStatus {
  conn: FlowMapConnState;
  feedState?: "live" | "degraded" | "closed" | "reconnecting";
  /** Capability map announced by the server Hello frame (depth mode, history badge, ...). */
  capability?: Record<string, unknown>;
  latencyMs?: number | null;
  /** false = WebGL2 unavailable in this environment (pane must show an honest fallback). */
  webgl: boolean;
}

export interface FlowMapTarget {
  market: string;
  symbol: string;
  /** FlowMap price-band preset: "native" | "wide" | "full" | "deep". Default "wide". */
  band?: string;
}

export interface FlowMapOptions {
  /** Absolute sidecar WS endpoint, e.g. `ws://127.0.0.1:8765/ws/flowmap?token=...`. */
  wsUrl: string;
  target: FlowMapTarget;
  onStatus?: (status: FlowMapStatus) => void;
}

export interface FlowMapHandle {
  /** (Re)subscribe to a new target; tears down and resets the GL session state. */
  subscribe(target: FlowMapTarget): void;
  /** Stop the stream, release the GL context, remove listeners. Idempotent. */
  destroy(): void;
}

export { createFlowMap } from './createFlowMap';
