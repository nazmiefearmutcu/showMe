/**
 * Overlay palette (§9 UI: trading-terminal buy-sell accent pair).
 *
 * One source of truth for the overlay colors, in both forms the two layers need:
 * `gl` = normalized RGBA [0..1] for the GL primitives, `css` = a string for the
 * 2D text layer / axis labels. The FACTORY palette is the teal/red terminal
 * pair; a host terminal can retheme every slot at runtime via
 * {@link setOverlayPalette} (see `theme.ts` — ShowMe maps buy/sell onto its
 * own positive/negative tokens so the surface reads as one system).
 */

import type { RGBA } from './primitives';

function rgba(r: number, g: number, b: number, a = 1): RGBA {
  return [r / 255, g / 255, b / 255, a] as const;
}
function css(r: number, g: number, b: number, a = 1): string {
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

export interface OverlayColor {
  /** Normalized RGBA [0..1] for the GL primitives. */
  gl: RGBA;
  /** CSS string for the 2D text layer / axis labels. */
  css: string;
}

/** Every theme-adjustable overlay slot (see {@link OVERLAY} for semantics). */
export type OverlayPalette = Record<
  | 'buy' | 'sell' | 'unknown' | 'bid' | 'ask'
  | 'price' | 'priceGlow' | 'priceFillTop' | 'priceFillBottom' | 'priceLevel'
  | 'pricePill' | 'pricePillText'
  | 'vwap' | 'cvd' | 'profile' | 'poc'
  | 'liquidation' | 'gap' | 'event' | 'axis' | 'grid',
  OverlayColor
> & { badgeBg: string };

const FACTORY_OVERLAY: OverlayPalette = {
  /** Aggressive buy (hits the ask). App accent teal. */
  buy: { gl: rgba(31, 182, 166, 0.95), css: css(31, 182, 166) },
  /** Aggressive sell (hits the bid). */
  sell: { gl: rgba(224, 84, 84, 0.95), css: css(224, 84, 84) },
  /** Unknown-aggressor trade (equity keyless / N/A side). Neutral grey. */
  unknown: { gl: rgba(150, 160, 176, 0.8), css: css(150, 160, 176) },
  /** Best-bid line + badge. */
  bid: { gl: rgba(31, 182, 166, 0.95), css: css(31, 182, 166) },
  /** Best-ask line + badge. */
  ask: { gl: rgba(224, 84, 84, 0.95), css: css(224, 84, 84) },
  /** Last-price line over the heatmap — bright near-white so it reads as THE
   *  price, clearly apart from the colored density, VWAP (violet) and BBO. */
  price: { gl: rgba(245, 248, 252, 0.98), css: css(245, 248, 252) },
  /** Soft glow drawn under the price line to fatten it without hard edges. */
  priceGlow: { gl: rgba(245, 248, 252, 0.22), css: css(245, 248, 252, 0.22) },
  /** Area wash under the price line (text-layer gradient, top → bottom). Kept
   *  very faint: the density field is the protagonist, the wash only seats the
   *  line visually. */
  priceFillTop: { gl: rgba(245, 248, 252, 0.07), css: css(210, 225, 245, 0.07) },
  priceFillBottom: { gl: rgba(245, 248, 252, 0.0), css: css(210, 225, 245, 0) },
  /** Dashed last-price level marker (quieter than the line itself). */
  priceLevel: { gl: rgba(245, 248, 252, 0.38), css: css(245, 248, 252, 0.38) },
  /** Price-axis pill: near-white plate, near-black text (the axis "last" tag). */
  pricePill: { gl: rgba(245, 248, 252, 0.95), css: css(245, 248, 252, 0.95) },
  pricePillText: { gl: rgba(10, 14, 20, 1), css: css(10, 14, 20) },
  /** Session VWAP polyline — distinct violet so it reads apart from buy/sell. */
  vwap: { gl: rgba(196, 142, 255, 0.95), css: css(196, 142, 255) },
  /** CVD (cumulative volume delta) line in the lower pane. Amber-gold. */
  cvd: { gl: rgba(232, 176, 74, 0.98), css: css(232, 176, 74) },
  /** Volume profile bars. */
  profile: { gl: rgba(120, 150, 200, 0.35), css: css(120, 150, 200) },
  /** Point-of-control (max) profile row. */
  poc: { gl: rgba(240, 196, 90, 0.8), css: css(240, 196, 90) },
  /** Liquidation marker glyph (a hot orange triangle). */
  liquidation: { gl: rgba(255, 138, 46, 0.95), css: css(255, 138, 46) },
  /** Gap / session-break vertical hatch. */
  gap: { gl: rgba(150, 160, 176, 0.6), css: css(150, 160, 176) },
  /** Iceberg / large-lot / halt / luld / info generic glyph. */
  event: { gl: rgba(214, 161, 58, 0.9), css: css(214, 161, 58) },
  /** Axis label + tick color. */
  axis: { gl: rgba(91, 102, 117, 1), css: css(163, 176, 194) },
  /** Faint gridline for axis ticks over the heatmap. */
  grid: { gl: rgba(120, 132, 150, 0.14), css: css(120, 132, 150, 0.14) },
  /** Text-badge background (near-black terminal chrome). */
  badgeBg: 'rgba(5, 8, 12, 0.82)',
};


/**
 * Live overlay palette — the overlay colors, themed by the host terminal when
 * `createFlowMap({ theme })` resolves the host's design tokens (see theme.ts).
 * Every consumer reads it at draw time, so {@link setOverlayPalette} takes
 * effect on the next frame without touching any caller.
 */
export const OVERLAY: OverlayPalette = { ...FACTORY_OVERLAY };

type PaletteKey = keyof OverlayPalette;

/** Merge theme overrides into the live palette (missing slots keep factory). */
export function setOverlayPalette(
  overrides: Partial<Record<PaletteKey, OverlayColor | string>>,
): void {
  for (const [key, value] of Object.entries(overrides) as [PaletteKey, OverlayColor | string][]) {
    if (key === 'badgeBg') {
      if (typeof value === 'string') OVERLAY.badgeBg = value;
      continue;
    }
    if (typeof value !== 'string') OVERLAY[key] = { ...value };
  }
}

/** Restore every slot to the factory terminal palette. */
export function resetOverlayPalette(): void {
  Object.assign(OVERLAY, FACTORY_OVERLAY);
}
