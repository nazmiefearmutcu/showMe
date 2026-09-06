/**
 * Theme bridge unit tests — pure color/ramp logic (no DOM, no GL).
 *
 * The design contract: the canvas inherits the host terminal's tokens, the
 * real-depth and reconstructed ramps stay visibly DISTINCT (the §7 honesty
 * signal), ramps are monotone in ink amount, and unparseable/missing tokens
 * fall back to the factory look instead of inventing colors.
 */
import { describe, expect, it } from "vitest";
import {
  buildMainStops,
  buildOverlayOverrides,
  buildSynthStops,
  isLightBg,
  mixRgb,
  parseCssColor,
  relLuminance,
  themeFromTokens,
} from "./theme";

const MIDNIGHT_BG: [number, number, number] = [0x0b, 0x09, 0x07];
const PAPYRUS_BG: [number, number, number] = [0xec, 0xe6, 0xd6];
const ACCENT: [number, number, number] = [0xc9, 0x64, 0x42];
const ACCENT2: [number, number, number] = [0xb1, 0x81, 0x3a];
const INK: [number, number, number] = [0x1c, 0x16, 0x10];
const POS: [number, number, number] = [0x2f, 0xd4, 0x80];
const NEG: [number, number, number] = [0xff, 0x58, 0x74];

describe("parseCssColor", () => {
  it("parses the token formats the design system emits", () => {
    expect(parseCssColor("#c96442")).toEqual([201, 100, 66, 1]);
    expect(parseCssColor("#C96442")).toEqual([201, 100, 66, 1]);
    expect(parseCssColor("#fa05")).toEqual([255, 170, 0, 0x55 / 255]);
    expect(parseCssColor("rgba(122, 78, 26, 0.20)")).toEqual([122, 78, 26, 0.2]);
    expect(parseCssColor("rgb(80 60 30 / 0.09)")).toEqual([80, 60, 30, 0.09]);
  });

  it("rejects junk and transparency honestly", () => {
    expect(parseCssColor("transparent")).toBeNull();
    expect(parseCssColor("")).toBeNull();
    expect(parseCssColor("not-a-color")).toBeNull();
    expect(parseCssColor("#12345")).toBeNull();
  });
});

describe("luminance / preset detection", () => {
  it("separates the dark and light presets", () => {
    expect(isLightBg(MIDNIGHT_BG)).toBe(false);
    expect(isLightBg(PAPYRUS_BG)).toBe(true);
    expect(relLuminance([255, 255, 255])).toBeCloseTo(1, 5);
    expect(relLuminance([0, 0, 0])).toBe(0);
  });

  it("mixes toward the second color", () => {
    expect(mixRgb([0, 0, 0], [255, 255, 255], 0.5)).toEqual([128, 128, 128]);
    expect(mixRgb([10, 20, 30], [10, 20, 30], 0.9)).toEqual([10, 20, 30]);
  });
});

describe("ramp generation", () => {
  it("starts at the background in both preset families", () => {
    for (const bg of [MIDNIGHT_BG, PAPYRUS_BG]) {
      const light = isLightBg(bg);
      expect(buildMainStops(bg, ACCENT, INK, light)[0].rgb).toEqual(bg);
      expect(buildSynthStops(bg, ACCENT2, INK, light)[0].rgb).toEqual(bg);
    }
  });

  it("keeps density monotone along each ramp (heavy tail must read)", () => {
    const luma = (c: [number, number, number]) => relLuminance(c);
    for (const bg of [MIDNIGHT_BG, PAPYRUS_BG]) {
      const light = isLightBg(bg);
      for (const stops of [
        buildMainStops(bg, ACCENT, INK, light),
        buildSynthStops(bg, ACCENT2, INK, light),
      ]) {
        // Dark presets: density = brightness; light presets: density = ink.
        const density = stops.map((s) => (light ? 1 - luma(s.rgb) : luma(s.rgb)));
        for (let i = 1; i < density.length; i += 1) {
          expect(density[i]).toBeGreaterThan(density[i - 1]);
        }
      }
    }
  });

  it("caps dark ramps short of white so walls never blend into the price line", () => {
    const top = buildMainStops(MIDNIGHT_BG, ACCENT, INK, false).at(-1)!.rgb;
    expect(top.every((v, i) => v < 250 || i < 2)).toBe(true);
  });

  it("keeps the reconstructed ramp a different family than live depth", () => {
    for (const bg of [MIDNIGHT_BG, PAPYRUS_BG]) {
      const light = isLightBg(bg);
      const main = buildMainStops(bg, ACCENT, INK, light);
      const synth = buildSynthStops(bg, ACCENT2, INK, light);
      const mid = (arr: typeof main) => arr[1].rgb;
      expect(mid(synth)).not.toEqual(mid(main));
    }
  });
});

describe("overlay mapping + token theme", () => {
  const get = (name: string): string | null => {
    const tokens: Record<string, string> = {
      "--bg": "#ece6d6",
      "--accent": "#8a5a1f",
      "--accent-2": "#b1813a",
      "--positive-hex": "#117a44",
      "--negative-hex": "#c43250",
      "--text-display-hex": "#1c1610",
      "--text-mute-hex": "#6a5e47",
      "--grid-color": "rgba(80, 60, 30, 0.09)",
    };
    return tokens[name] ?? null;
  };

  it("maps bid/ask onto the host semantic pair, price onto the display ink", () => {
    const theme = themeFromTokens(get);
    const overlay = buildOverlayOverrides({
      bg: [...PAPYRUS_BG, 1],
      accent: [...ACCENT, 1],
      accent2: [...ACCENT2, 1],
      positive: [...POS, 1],
      negative: [...NEG, 1],
      textDisplay: [...INK, 1],
      textMute: [0x6a, 0x5e, 0x47, 1],
      grid: [80, 60, 30, 0.09],
    });
    expect(overlay.bid?.gl[1]).toBeGreaterThan(overlay.bid?.gl[0] ?? 0); // green
    expect(overlay.ask?.gl[0]).toBeGreaterThan(overlay.ask?.gl[1] ?? 0); // red
    expect(overlay.price?.css).toContain("28, 22, 16"); // #1c1610
    expect(overlay.badgeBg).toContain("0.85");
    expect(theme.background[3]).toBe(1);
  });

  it("falls back to the renderer background when tokens are missing", () => {
    const theme = themeFromTokens(() => null);
    expect(theme.background).toEqual([8 / 255, 16 / 255, 27 / 255, 1]);
  });
});
