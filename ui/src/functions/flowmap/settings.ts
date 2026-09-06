/**
 * Embedded-renderer settings defaults (trimmed from upstream `ui/settings.ts`).
 *
 * The vendored library has no settings drawer and no persistence: the host pane
 * (FLW) embeds a single canvas, so only the DEFAULTS the upstream App applied at
 * boot are needed here, plus `historyDepthCols` for the eager first-column
 * history prefetch. Values and semantics mirror upstream exactly, with ONE
 * deliberate deviation: `priceBand` defaults to `'wide'` (the frozen FLW
 * contract: "native | wide | full | deep (default wide)") instead of upstream's
 * `'deep'`.
 */

import { DEFAULT_CONTRAST, DEFAULT_TOLERANCE } from './gl/heatmap';
import { DEFAULT_COLORMAP, type Colormap } from './gl/lut';
import { DEFAULT_PERCENTILE } from './gl/normalize';
import {
  DEFAULT_OVERLAY_VISIBILITY,
  type OverlayVisibility,
} from './gl/overlays/frame';

export type { Colormap };

/** Server price-grid coverage around the reference price (§8.1). */
export type PriceBand = 'native' | 'wide' | 'full' | 'deep';

export const PRICE_BANDS: readonly PriceBand[] = ['native', 'wide', 'full', 'deep'] as const;

/** First-launch history depth — how much past data to eagerly pull on connect. */
export type HistoryDepth = 'off' | '1h' | '4h' | '1d' | 'max';

const HISTORY_DEPTH_NS: Record<Exclude<HistoryDepth, 'off' | 'max'>, number> = {
  '1h': 3_600e9,
  '4h': 14_400e9,
  '1d': 86_400e9,
};

/**
 * Target column count for a history depth given the epoch's `dtNs` (ns per
 * column). `off` → 0 (no prefetch); `max` → a large cap the prefetch clamps to
 * available history + the ring budget; durations → wall-clock / dtNs.
 */
export function historyDepthCols(depth: HistoryDepth, dtNs: number): number {
  if (depth === 'off') return 0;
  if (depth === 'max') return 1_000_000;
  const dt = dtNs > 0 ? dtNs : 250e6;
  return Math.max(1, Math.round(HISTORY_DEPTH_NS[depth] / dt));
}

export interface FlowMapSettings {
  /** Heatmap display contrast 0–100 (drives the perceptual gamma, §8.3). */
  contrast: number;
  /** Heatmap black point 0–100 — how much density a cell needs to paint at all. */
  tolerance: number;
  /** Heatmap colormap family. */
  colormap: Colormap;
  /** Viewport-normalization percentile (§8.3; higher = dimmer, more headroom). */
  normPercentile: number;
  /** Minimum trade size drawn as a tape bubble overlay. */
  bubbleMinSize: number;
  /** Auto-follow the live right edge — the TIME axis. */
  follow: boolean;
  /** Auto-track price on the PRICE axis (keeps your zoom, recentres on drift). */
  followPrice: boolean;
  /** Server price-grid coverage preset (FLW contract default: `wide`). */
  priceBand: PriceBand;
  /** How much history to eagerly load into the chart on connect. */
  historyDepth: HistoryDepth;
  /** Which heatmap overlays are on. */
  overlays: OverlayVisibility;
}

/**
 * The defaults the upstream App applied at boot (`ui/settings.ts` +
 * App.tsx mount effect): follow ON, price FIT on session, 1h eager history.
 */
export const DEFAULT_SETTINGS: FlowMapSettings = {
  contrast: DEFAULT_CONTRAST,
  tolerance: DEFAULT_TOLERANCE,
  colormap: DEFAULT_COLORMAP,
  normPercentile: DEFAULT_PERCENTILE,
  bubbleMinSize: 0,
  follow: true,
  followPrice: true,
  // FLW contract: `band` defaults to `wide` (upstream's drawer default was
  // `deep`; the frozen contract for the embedded pane pins `wide`).
  priceBand: 'wide',
  historyDepth: '1h',
  overlays: { ...DEFAULT_OVERLAY_VISIBILITY },
};
