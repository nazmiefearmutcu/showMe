/**
 * `theme.ts` — the host-terminal theme bridge.
 *
 * The heatmap used to be a fixed near-black surface with factory neon ramps —
 * a foreign rectangle inside a themed terminal. This module derives the WHOLE
 * canvas palette from the host's design tokens instead ("the heatmap wears the
 * terminal's ink"):
 *
 *  - canvas background = the `--bg` token (no more black hole on light presets);
 *  - the real-depth ramp is generated per preset — accent-glow on dark presets,
 *    accent-into-ink ("ledger") on light ones — and rasterized into the LUT
 *    atlas row the active colormap family uses;
 *  - the reconstructed-history ramp keeps its own single-hue family (accent-2)
 *    so backfilled columns stay visibly distinct from live depth (§7 honesty);
 *  - overlay semantics map onto the host's semantic pair: buy/bid =
 *    `--positive-hex`, sell/ask = `--negative-hex`, price = the display-text
 *    color, VWAP = `--accent-2`, CVD/POC/events = `--accent`, axes/grid =
 *    the mute-text and `--grid-color` tokens.
 *
 * Pure helpers take plain colors so tests need no DOM; `resolveFlowMapTheme`
 * reads tokens through a `(name) => string` resolver.
 */
import type { Stop } from './gl/lut';
import {
  setOverlayPalette,
  resetOverlayPalette,
  type OverlayColor,
  type OverlayPalette,
} from './gl/overlays/palette';
import type { ThemeRampStops } from './gl/renderer';

/** Structural slice of the Renderer the bridge needs (keeps theme.ts GL-free). */
export interface ThemeTarget {
  setThemeRamp(stops: ThemeRampStops | null): void;
  setBackgroundColor(color: [number, number, number, number] | null): void;
}

/** Host tokens the bridge consumes (alpha is kept where the token carries one). */
export interface FlowMapTokens {
  bg: Rgba;
  accent: Rgba;
  accent2: Rgba;
  positive: Rgba;
  negative: Rgba;
  textDisplay: Rgba;
  textMute: Rgba;
  grid: Rgba;
}

export interface ResolvedFlowMapTheme {
  background: [number, number, number, number];
  ramps: ThemeRampStops;
  overlay: { [K in keyof OverlayPalette]?: OverlayPalette[K] };
}

// --- color parsing / mixing ----------------------------------------------------

/** Parse `#rgb #rgba #rrggbb #rrggbbaa`, `rgb()/rgba()` (comma or space), or
 *  `transparent`. Returns null for anything unparseable. */
export function parseCssColor(input: string): Rgba | null {
  const s = input.trim().toLowerCase();
  if (s === '' || s === 'transparent' || s === 'none' || s === 'currentcolor') return null;
  if (s.startsWith('#')) {
    const hex = s.slice(1);
    if (hex.length === 3 || hex.length === 4) {
      const [r, g, b, a] = hex.split('').map((c) => parseInt(c + c, 16));
      return [r, g, b, hex.length === 4 ? a / 255 : 1];
    }
    if (hex.length === 6 || hex.length === 8) {
      const r = parseInt(hex.slice(0, 2), 16);
      const g = parseInt(hex.slice(2, 4), 16);
      const b = parseInt(hex.slice(4, 6), 16);
      const a = hex.length === 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1;
      if ([r, g, b, a].some((v) => Number.isNaN(v))) return null;
      return [r, g, b, a];
    }
    return null;
  }
  const m = /^rgba?\(([^)]+)\)$/.exec(s);
  if (m === null) return null;
  const parts = m[1].split(/[\s,/]+/).filter((p) => p.length > 0);
  if (parts.length < 3) return null;
  const nums = parts.map((p) => Number.parseFloat(p));
  if (nums.slice(0, 3).some((v) => Number.isNaN(v))) return null;
  const a = nums.length > 3 && !Number.isNaN(nums[3]) ? nums[3] : 1;
  return [nums[0], nums[1], nums[2], a];
}

/** sRGB color as 0..255 bytes + alpha 0..1. */
export type Rgb = [number, number, number];
export type Rgba = [...Rgb, number];
/** Anything the color helpers read: alpha is ignored unless stated. */
export type RgbLike = Rgb | Rgba;

function rgb3(c: RgbLike): Rgb {
  return [c[0], c[1], c[2]];
}

/** Rec.601 luma 0..1 — the same weighting the factory ramps document. */
export function relLuminance(c: RgbLike): number {
  return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;
}

/** A preset is "light" when its background carries the ink, not the light. */
export function isLightBg(bg: RgbLike): boolean {
  return relLuminance(bg) > 0.5;
}

export function mixRgb(a: RgbLike, b: RgbLike, t: number): Rgb {
  const [ar, ag, ab] = rgb3(a);
  const [br, bg2, bb] = rgb3(b);
  return [
    Math.round(ar + (br - ar) * t),
    Math.round(ag + (bg2 - ag) * t),
    Math.round(ab + (bb - ab) * t),
  ];
}

const WHITE: Rgb = [255, 255, 255];
const BLACK: Rgb = [0, 0, 0];

function css(c: RgbLike, a = 1): string {
  return `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${a})`;
}
function gl(c: RgbLike, a = 1): OverlayColor['gl'] {
  return [c[0] / 255, c[1] / 255, c[2] / 255, a];
}
function color(c: RgbLike, a = 1): OverlayColor {
  return { gl: gl(c, a), css: css(c, a) };
}

// --- ramp generation -------------------------------------------------------------

/**
 * Real-depth ramp for a preset. Dark presets glow from the background into the
 * accent and cap ~35% short of white so a max-density wall never blends into
 * the white price line (the same discipline as the factory ramps, whose tops
 * are saturated gold). Light presets run paper → accent → ink: density reads
 * as ink settling into the page.
 */
export function buildMainStops(bg: RgbLike, accent: RgbLike, ink: RgbLike, light: boolean): Stop[] {
  const base = rgb3(bg);
  if (light) {
    return [
      { t: 0.0, rgb: base },
      { t: 0.3, rgb: mixRgb(bg, accent, 0.35) },
      { t: 0.62, rgb: mixRgb(accent, ink, 0.45) },
      { t: 1.0, rgb: mixRgb(ink, BLACK, 0.25) },
    ];
  }
  return [
    { t: 0.0, rgb: base },
    { t: 0.35, rgb: mixRgb(bg, accent, 0.55) },
    { t: 0.72, rgb: rgb3(accent) },
    { t: 1.0, rgb: mixRgb(accent, WHITE, 0.35) },
  ];
}

/**
 * Reconstructed-history ramp — a SINGLE-HUE family distinct from the main ramp
 * (built on accent-2, falling back to accent) so `HISTORY: reconstructed`
 * columns are separable from live depth at a glance, mirroring the factory
 * SYNTH-vs-real ramp separation.
 */
export function buildSynthStops(bg: RgbLike, hue: RgbLike, ink: RgbLike, light: boolean): Stop[] {
  const base = rgb3(bg);
  if (light) {
    return [
      { t: 0.0, rgb: base },
      { t: 0.4, rgb: mixRgb(bg, hue, 0.3) },
      { t: 0.75, rgb: mixRgb(hue, ink, 0.35) },
      { t: 1.0, rgb: mixRgb(hue, ink, 0.7) },
    ];
  }
  return [
    { t: 0.0, rgb: base },
    { t: 0.4, rgb: mixRgb(bg, hue, 0.5) },
    { t: 0.78, rgb: rgb3(hue) },
    { t: 1.0, rgb: mixRgb(hue, WHITE, 0.45) },
  ];
}

// --- overlay mapping --------------------------------------------------------------

/**
 * Map host semantic tokens onto the overlay slots. Missing tokens simply stay
 * absent from the returned partial, keeping factory colors for those slots.
 */
export function buildOverlayOverrides(t: FlowMapTokens): ResolvedFlowMapTheme['overlay'] {
  const light = isLightBg(t.bg);
  const ink = t.textDisplay;
  const hot = light ? mixRgb(t.negative, BLACK, 0.15) : t.negative;
  return {
    buy: color(t.positive, 0.95),
    bid: color(t.positive, 0.95),
    sell: color(t.negative, 0.95),
    ask: color(t.negative, 0.95),
    unknown: color(t.textMute, 0.8),
    price: color(ink, 0.98),
    priceGlow: color(ink, 0.22),
    priceFillTop: color(ink, 0.07),
    priceFillBottom: color(ink, 0.0),
    priceLevel: color(ink, 0.38),
    pricePill: color(ink, 0.95),
    pricePillText: color(t.bg, 1),
    vwap: color(t.accent2, 0.95),
    cvd: color(t.accent, 0.98),
    poc: color(t.accent, 0.8),
    event: color(t.accent, 0.9),
    profile: color(t.textMute, 0.35),
    liquidation: color(hot, 0.95),
    gap: color(t.textMute, 0.6),
    axis: color(t.textMute, 1),
    grid: color(t.grid.slice(0, 3) as Rgb, t.grid[3] * 0.9),
    badgeBg: css(t.bg, 0.85),
  };
}

// --- resolution -------------------------------------------------------------------

function token(color: string | null): Rgba {
  const parsed = color === null ? null : parseCssColor(color);
  return parsed ?? [8, 16, 27, 1]; // renderer BG — the honest last resort
}

/** Build a full theme from a token resolver (pure — tests pass a fake map). */
export function themeFromTokens(get: (name: string) => string | null): ResolvedFlowMapTheme {
  const bg = token(get('--bg'));
  const accent = token(get('--accent'));
  const accent2 = token(get('--accent-2'));
  const positive = token(get('--positive-hex'));
  const negative = token(get('--negative-hex'));
  const textDisplay = token(get('--text-display-hex'));
  const textMute = token(get('--text-mute-hex'));
  const grid = token(get('--grid-color'));
  const tokens: FlowMapTokens = {
    bg, accent, accent2, positive, negative, textDisplay, textMute, grid,
  };
  const light = isLightBg(bg);
  return {
    background: [bg[0] / 255, bg[1] / 255, bg[2] / 255, 1],
    ramps: {
      main: buildMainStops(bg, accent, textDisplay, light),
      synth: buildSynthStops(bg, accent2, textDisplay, light),
    },
    overlay: buildOverlayOverrides(tokens),
  };
}

/**
 * Resolve the theme from the DOM: tokens live on `:root`/`[data-preset]`, so
 * `documentElement` carries them (a host element is read as a fallback for
 * locally-overridden variables). Returns null when the host defines no `--bg`
 * (non-ShowMe embedding) — callers keep the factory palette then.
 */
export function resolveFlowMapTheme(doc: Document, host?: Element | null): ResolvedFlowMapTheme | null {
  const rootStyle = doc.defaultView?.getComputedStyle(doc.documentElement);
  if (!rootStyle) return null;
  const hostStyle = host && host !== doc.documentElement
    ? doc.defaultView?.getComputedStyle(host)
    : undefined;
  const get = (name: string): string | null => {
    const local = hostStyle?.getPropertyValue(name).trim();
    if (local !== undefined && local !== '') return local;
    return rootStyle.getPropertyValue(name).trim() || null;
  };
  if (parseCssColor(get('--bg') ?? '') === null) return null;
  return themeFromTokens(get);
}

/**
 * Apply the CURRENT host theme to a renderer and keep it in sync with preset
 * switches (`data-preset` / `data-theme` / `class` on `<html>`). Returns a
 * cleanup that stops observing and restores the renderer's factory ramps +
 * background. Global overlay palette restore is the caller's refcount duty.
 */
export function attachTheme(
  doc: Document,
  target: ThemeTarget,
  host?: Element | null,
): () => void {
  const apply = (): void => {
    const theme = resolveFlowMapTheme(doc, host);
    if (theme === null) {
      target.setThemeRamp(null);
      target.setBackgroundColor(null);
      resetOverlayPalette();
      return;
    }
    target.setThemeRamp(theme.ramps);
    target.setBackgroundColor(theme.background);
    setOverlayPalette(theme.overlay);
  };
  apply();
  const observer = new MutationObserver(apply);
  observer.observe(doc.documentElement, {
    attributes: true,
    attributeFilter: ['data-preset', 'data-theme', 'class', 'style'],
  });
  return () => {
    observer.disconnect();
    target.setThemeRamp(null);
    target.setBackgroundColor(null);
  };
}
