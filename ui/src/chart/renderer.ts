/**
 * showMe chart engine — canvas 2D renderer (milestone 1).
 *
 * Paints the whole chart from a RenderInput (see ./types): grid + axes,
 * candles/line/area/bars/Heikin-Ashi, overlay indicators on the price pane,
 * separate oscillator panes, crosshair + legend, watermark.
 *
 * Theme rule: every color comes from ThemePalette, which the shell resolves
 * from the LIVE CSS variables of the mounted element — all 7 themes work
 * without any per-theme branching here.
 */
import type {
  Bar,
  CrosshairState,
  IndicatorResult,
  PriceMode,
  RenderInput,
  ThemePalette,
  TimeScale,
  PriceScale,
  Viewport,
} from "./types";
import type { Drawing } from "./drawings";

/* ── palette ────────────────────────────────────────────────────────── */

function cssVar(el: HTMLElement, name: string, fallback: string): string {
  try {
    const v = getComputedStyle(el).getPropertyValue(name).trim();
    return v || fallback;
  } catch {
    return fallback;
  }
}

export function resolvePalette(el: HTMLElement): ThemePalette {
  return {
    background: cssVar(el, "--surface-1", "#fff"),
    grid: cssVar(el, "--border-subtle", "#e5e5e5"),
    axisText: cssVar(el, "--text-mute", "#888"),
    textPrimary: cssVar(el, "--text-primary", "#111"),
    textSecondary: cssVar(el, "--text-secondary", "#555"),
    positive: cssVar(el, "--positive", "#0a0"),
    negative: cssVar(el, "--negative", "#a00"),
    wick: cssVar(el, "--text-mute", "#888"),
    bodyUp: cssVar(el, "--positive", "#0a0"),
    bodyDown: cssVar(el, "--negative", "#a00"),
    line: cssVar(el, "--accent", "#36c"),
    areaTop: cssVar(el, "--accent", "#36c"),
    areaBottom: cssVar(el, "--accent", "#36c"),
    crosshair: cssVar(el, "--text-mute", "#888"),
    accent: cssVar(el, "--accent", "#36c"),
  };
}

/** Parse #rgb/#rrggbb/rgb()/rgba() to r,g,b; null when unparseable. */
function toRgb(color: string): { r: number; g: number; b: number } | null {
  const c = color.trim();
  if (c.startsWith("#")) {
    const hex = c.slice(1);
    if (hex.length === 3) {
      return {
        r: parseInt(hex[0] + hex[0], 16),
        g: parseInt(hex[1] + hex[1], 16),
        b: parseInt(hex[2] + hex[2], 16),
      };
    }
    if (hex.length === 6) {
      return {
        r: parseInt(hex.slice(0, 2), 16),
        g: parseInt(hex.slice(2, 4), 16),
        b: parseInt(hex.slice(4, 6), 16),
      };
    }
    return null;
  }
  const m = c.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i);
  if (m) return { r: +m[1], g: +m[2], b: +m[3] };
  return null;
}

function withAlpha(color: string, alpha: number): string {
  const rgb = toRgb(color);
  if (!rgb) return color;
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
}

/* ── price-scale modes ──────────────────────────────────────────────── */

/**
 * Percent change of `v` relative to `base`, in percent points. NaN for
 * degenerate input (non-finite operands or a zero base) so callers fall
 * back to plain price labels instead of printing a fake "+0.00%".
 */
export function percentFromBase(v: number, base: number): number {
  if (!Number.isFinite(v) || !Number.isFinite(base) || base === 0) return NaN;
  return ((v - base) / base) * 100;
}

/**
 * Mode-aware price <-> pixel mapper. The affine `PriceScale` itself stays
 * untouched; the mode transform lives only in this pipeline (plus its
 * consumers in Chart.tsx, so pointer coords match what was painted):
 *
 *   - "log": log10 mapping when the visible range is strictly positive;
 *     a non-positive range honestly falls back to linear (`mode` reports
 *     "linear", so the caller keeps price labels — never a broken axis).
 *   - "percent": linear mapping; the caller labels values as % change
 *     from the first visible bar's close via `percentFromBase`.
 */
export interface PriceMapper {
  /** Effective mode: "log" downgrades to "linear" on a non-positive range. */
  mode: PriceMode;
  toY(price: number): number;
  toPrice(y: number): number;
}

export function priceMapperFor(price: PriceScale, mode: PriceMode = "linear"): PriceMapper {
  const linear: PriceMapper = {
    mode: mode === "percent" ? "percent" : "linear",
    toY: (v) => price.toY(v),
    toPrice: (y) => price.toPrice(y),
  };
  if (mode !== "log") return linear;
  const r = price.range();
  if (!(r.min > 0) || !Number.isFinite(r.min) || !Number.isFinite(r.max) || !(r.max > r.min)) {
    return linear;
  }
  const yBottom = price.toY(r.min);
  const yTop = price.toY(r.max);
  const lmin = Math.log10(r.min);
  const lmax = Math.log10(r.max);
  const lspan = lmax - lmin;
  if (!Number.isFinite(yBottom) || !Number.isFinite(yTop) || yBottom === yTop || !(lspan > 0)) {
    return linear;
  }
  return {
    mode: "log",
    toY(v: number): number {
      /* Log of a non-positive value does not exist — NaN tells the caller
         to skip the point instead of plotting a lie. */
      if (!Number.isFinite(v) || v <= 0) return NaN;
      return yBottom - ((Math.log10(v) - lmin) / lspan) * (yBottom - yTop);
    },
    toPrice(y: number): number {
      return Math.pow(10, lmin + ((yBottom - y) / (yBottom - yTop)) * lspan);
    },
  };
}

/* ── number helpers ─────────────────────────────────────────────────── */

function niceStep(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / pow;
  const mult = n >= 5 ? 10 : n >= 2 ? 5 : n >= 1 ? 2 : 1;
  return mult * pow;
}

function fmtPrice(v: number): string {
  const abs = Math.abs(v);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function fmtTime(tMs: number, spanMs: number, stepMs: number): string {
  const d = new Date(tMs);
  const p2 = (n: number) => String(n).padStart(2, "0");
  const time = `${p2(d.getHours())}:${p2(d.getMinutes())}`;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const dateLabel = `${d.getDate()} ${months[d.getMonth()]}`;
  if (spanMs <= 5 * 60_000) return `${time}:${p2(d.getSeconds())}`;
  /* Label granularity follows the TICK STEP (not the whole span), so
     intraday ticks on a multi-day window show distinct times instead of the
     same date repeated. */
  if (stepMs <= 60_000) {
    return spanMs <= 3 * 86_400_000 ? time : `${dateLabel} ${time}`;
  }
  if (stepMs < 86_400_000) {
    return spanMs <= 3 * 86_400_000 ? time : `${dateLabel}`;
  }
  if (spanMs <= 400 * 86_400_000) return dateLabel;
  return `${months[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
}

/* ── Heikin-Ashi ────────────────────────────────────────────────────── */

function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const prev = out[i - 1];
    const c = (b.o + b.h + b.l + b.c) / 4;
    const o = prev ? (prev.o + prev.c) / 2 : (b.o + b.c) / 2;
    out.push({ t: b.t, o, h: Math.max(b.h, o, c), l: Math.min(b.l, o, c), c, v: b.v });
  }
  return out;
}

/* ── pane layout ────────────────────────────────────────────────────── */

interface PaneLayout {
  /** Plot pixel top/bottom per pane: [main, ...separate]. */
  panes: { top: number; bottom: number }[];
  plotW: number;
  priceTop: number;
  priceBottom: number;
  timeTop: number;
}

function layout(vp: Viewport, separateCount: number): PaneLayout {
  const plotW = Math.max(10, vp.width - vp.priceAxisWidth);
  const plotH = Math.max(10, vp.height - vp.timeAxisHeight);
  const paneH =
    separateCount === 0
      ? 0
      : Math.max(52, Math.min(120, (plotH * 0.42) / separateCount));
  const mainBottom = plotH - paneH * separateCount;
  const panes: { top: number; bottom: number }[] = [{ top: 0, bottom: mainBottom }];
  for (let i = 0; i < separateCount; i++) {
    panes.push({ top: mainBottom + i * paneH, bottom: mainBottom + (i + 1) * paneH });
  }
  return { panes, plotW, priceTop: 0, priceBottom: mainBottom, timeTop: plotH };
}

/** Pane-local numeric range across every finite plot value. */
function resultRange(result: IndicatorResult): { min: number; max: number } | null {
  let min = Infinity;
  let max = -Infinity;
  for (const plot of result.plots) {
    for (const v of plot.data) {
      if (v == null || !Number.isFinite(v)) continue;
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  for (const level of result.levels ?? []) {
    if (!Number.isFinite(level)) continue;
    if (level < min) min = level;
    if (level > max) max = level;
  }
  if (min > max) return null;
  if (min === max) {
    const pad = Math.abs(min) * 0.01 || 1;
    return { min: min - pad, max: max + pad };
  }
  const pad = (max - min) * 0.08;
  return { min: min - pad, max: max + pad };
}

function paneY(value: number, range: { min: number; max: number }, top: number, bottom: number): number {
  const span = range.max - range.min || 1;
  return bottom - ((value - range.min) / span) * (bottom - top);
}

/* ── volume strip ───────────────────────────────────────────────────── */

/** Volume histogram in the bottom ~18% of the main pane; skipped silently
 *  when every visible volume is 0/null (no fake baseline). */
function drawVolumeStrip(
  ctx: CanvasRenderingContext2D,
  displayBars: Bar[],
  i0: number,
  i1: number,
  time: TimeScale,
  barW: number,
  pane: { top: number; bottom: number },
  plotW: number,
  palette: ThemePalette,
): void {
  let max = 0;
  for (let i = i0; i <= i1; i++) {
    const v = displayBars[i]?.v;
    if (typeof v === "number" && Number.isFinite(v) && v > max) max = v;
  }
  if (!(max > 0)) return;
  const stripH = Math.max(1, (pane.bottom - pane.top) * 0.18);
  const stripTop = pane.bottom - stripH;
  const w = Math.max(1, Math.min(28, barW * 0.72));
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, stripTop, plotW, stripH);
  ctx.clip();
  for (let i = i0; i <= i1; i++) {
    const b = displayBars[i];
    if (!b) continue;
    const v = b.v;
    if (typeof v !== "number" || !Number.isFinite(v) || v <= 0) continue;
    const x = time.toX(i);
    if (x < -8 || x > plotW + 8) continue;
    const h = Math.max(1, (v / max) * (stripH - 1));
    ctx.fillStyle = withAlpha(b.c >= b.o ? palette.bodyUp : palette.bodyDown, 0.35);
    ctx.fillRect(x - w / 2, pane.bottom - h, w, h);
  }
  ctx.restore();
}

/* ── user drawings ──────────────────────────────────────────────────── */

interface DrawingPaintCtx {
  time: TimeScale;
  pm: PriceMapper;
  pane: { top: number; bottom: number };
  plotW: number;
  axisWidth: number;
  palette: ThemePalette;
  axisLabel: (v: number) => string;
}

/** Hlines: dashed across the plot + an axis tag; trendlines: 2 px line with
 *  round handles. Lines are clipped to the main pane; tags live in the
 *  gutter. Unmappable values (e.g. non-positive price in log mode) skip. */
function drawDrawings(
  ctx: CanvasRenderingContext2D,
  drawings: Drawing[] | undefined,
  d: DrawingPaintCtx,
): void {
  if (!drawings || drawings.length === 0) return;
  const tags: { y: number; label: string }[] = [];
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, d.pane.top, d.plotW, d.pane.bottom - d.pane.top);
  ctx.clip();
  for (const drawing of drawings) {
    if (drawing.kind === "hline") {
      if (typeof drawing.price !== "number") continue;
      const y = d.pm.toY(drawing.price);
      if (!Number.isFinite(y) || y < d.pane.top || y > d.pane.bottom) continue;
      const yy = Math.round(y) + 0.5;
      ctx.save();
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = withAlpha(d.palette.accent, 0.85);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, yy);
      ctx.lineTo(d.plotW, yy);
      ctx.stroke();
      ctx.restore();
      tags.push({ y: yy, label: d.axisLabel(drawing.price) });
      continue;
    }
    if (drawing.kind === "trend") {
      const { p1, p2 } = drawing;
      if (!p1 || !p2) continue;
      const x1 = d.time.toX(p1.index);
      const y1 = d.pm.toY(p1.price);
      const x2 = d.time.toX(p2.index);
      const y2 = d.pm.toY(p2.price);
      if (![x1, y1, x2, y2].every(Number.isFinite)) continue;
      ctx.setLineDash([]);
      ctx.strokeStyle = d.palette.accent;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      for (const [hx, hy] of [
        [x1, y1],
        [x2, y2],
      ] as const) {
        ctx.beginPath();
        ctx.arc(hx, hy, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = d.palette.background;
        ctx.fill();
        ctx.strokeStyle = d.palette.accent;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
  }
  ctx.restore();

  for (const tag of tags) {
    ctx.fillStyle = d.palette.accent;
    ctx.fillRect(d.plotW + 1, tag.y - 8, Math.max(0, d.axisWidth - 2), 16);
    ctx.fillStyle = d.palette.background;
    ctx.textAlign = "left";
    ctx.fillText(tag.label, d.plotW + 6, tag.y);
  }
}

/** Grid tick values; log mode generates decades evenly spaced in log space. */
function priceTicks(range: { min: number; max: number }, plotH: number, mode: PriceMode): number[] {
  const count = Math.max(2, plotH / 64);
  const out: number[] = [];
  if (mode === "log") {
    const lmin = Math.log10(range.min);
    const lmax = Math.log10(range.max);
    const step = niceStep((lmax - lmin) / count);
    const lastK = Math.floor(lmax / step + 1e-9);
    for (let k = Math.ceil(lmin / step); k <= lastK && out.length < 64; k++) {
      const v = Math.pow(10, k * step);
      if (Number.isFinite(v) && v > 0) out.push(v);
    }
    return out;
  }
  const step = niceStep((range.max - range.min) / count);
  const first = Math.ceil(range.min / step) * step;
  for (let k = 0; out.length < 64; k++) {
    const v = first + k * step;
    if (v > range.max + 1e-9) break;
    out.push(v);
  }
  return out;
}

/* ── main draw ──────────────────────────────────────────────────────── */

export function drawChart(input: RenderInput): void {
  const { ctx, dpr, viewport: vp, palette: p, bars, chartType, time, price, indicators, crosshair, symbol } = input;
  const overlays = indicators.filter((i) => i.instance.visible && i.instance.pane === "overlay");
  const separates = indicators.filter((i) => i.instance.visible && i.instance.pane === "separate");
  const L = layout(vp, separates.length);

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, vp.width, vp.height);
  ctx.fillStyle = p.background;
  ctx.fillRect(0, 0, vp.width, vp.height);

  const rng = time.range();
  const i0 = Math.max(0, Math.floor(rng.from));
  const i1 = Math.min(bars.length - 1, Math.ceil(rng.to));
  const mainRange = price.range();

  /* Mode-aware price pipeline: grid, series, overlays, crosshair and
     drawings all map through the SAME mapper, so labels always line up. */
  const pm = priceMapperFor(price, input.priceMode ?? "linear");
  /* Percent labels anchor to the first visible bar's close; no finite
     non-zero close -> honest fallback to price labels. */
  let percentBase: number | null = null;
  if (pm.mode === "percent") {
    for (let i = i0; i <= i1; i++) {
      const c = bars[i]?.c;
      if (typeof c === "number" && Number.isFinite(c) && c !== 0) {
        percentBase = c;
        break;
      }
    }
  }
  const axisLabel = (v: number): string => {
    if (percentBase != null) {
      const pct = percentFromBase(v, percentBase);
      if (Number.isFinite(pct)) return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
    }
    return fmtPrice(v);
  };

  const xClamp = (x: number) => Math.max(0, Math.min(L.plotW, x));
  const visibleSpanMs =
    i0 <= i1 && bars[i0] && bars[i1] ? Math.max(1, bars[i1].t - bars[i0].t) : 86_400_000;

  ctx.font = "10px 'JetBrains Mono', monospace";
  ctx.textBaseline = "middle";

  /* grid — price */
  ctx.strokeStyle = p.grid;
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  for (const v of priceTicks(mainRange, L.priceBottom, pm.mode)) {
    const y = Math.round(pm.toY(v)) + 0.5;
    if (!Number.isFinite(y) || y < L.panes[0].top || y > L.panes[0].bottom) continue;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(L.plotW, y);
    ctx.stroke();
    ctx.fillStyle = p.axisText;
    ctx.textAlign = "left";
    ctx.fillText(axisLabel(v), L.plotW + 6, y);
  }

  /* grid — time */
  const targetPx = 96;
  const bw = time.barWidth();
  let idxStep = Math.max(1, Math.round(targetPx / Math.max(bw, 0.01)));
  /* snap to a nice count so labels stay regular */
  if (idxStep > 4) {
    const pow = Math.pow(10, Math.floor(Math.log10(idxStep)));
    const n = idxStep / pow;
    idxStep = Math.round((n >= 5 ? 5 : n >= 2 ? 2 : 1) * pow);
  }
  const barSpacingMs =
    bars.length > 1 ? Math.max(1, bars[1].t - bars[0].t) : 60_000;
  const stepMs = idxStep * barSpacingMs;
  const first = Math.ceil(i0 / idxStep) * idxStep;
  for (let i = first; i <= i1; i += idxStep) {
    const bar = bars[i];
    if (!bar) continue;
    const x = Math.round(time.toX(i)) + 0.5;
    if (x < 0 || x > L.plotW) continue;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, L.timeTop);
    ctx.stroke();
    ctx.fillStyle = p.axisText;
    ctx.textAlign = "center";
    ctx.fillText(
      fmtTime(bar.t, visibleSpanMs, stepMs),
      x,
      L.timeTop + Math.round(vp.timeAxisHeight / 2),
    );
  }

  /* axes borders */
  ctx.strokeStyle = p.grid;
  ctx.beginPath();
  ctx.moveTo(L.plotW + 0.5, 0);
  ctx.lineTo(L.plotW + 0.5, vp.height);
  ctx.moveTo(0, L.timeTop + 0.5);
  ctx.lineTo(vp.width, L.timeTop + 0.5);
  ctx.stroke();

  /* series */
  const drawBars = chartType === "heikin" ? heikinAshi(bars) : bars;
  if (chartType === "candles" || chartType === "heikin") {
    for (let i = i0; i <= i1; i++) {
      const b = drawBars[i];
      if (!b) continue;
      const x = time.toX(i);
      if (x < -8 || x > L.plotW + 8) continue;
      const up = b.c >= b.o;
      const color = up ? p.bodyUp : p.bodyDown;
      const bodyW = Math.max(1, Math.min(28, bw * 0.72));
      ctx.fillStyle = color;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      if (bw < 2.2) {
        /* sub-pixel bars: a single high-low line, honest at any zoom */
        ctx.beginPath();
        ctx.moveTo(x, pm.toY(b.h));
        ctx.lineTo(x, pm.toY(b.l));
        ctx.stroke();
        continue;
      }
      ctx.beginPath();
      ctx.moveTo(x, pm.toY(b.h));
      ctx.lineTo(x, pm.toY(b.l));
      ctx.stroke();
      const yO = pm.toY(b.o);
      const yC = pm.toY(b.c);
      const top = Math.min(yO, yC);
      const h = Math.max(1, Math.abs(yC - yO));
      ctx.fillRect(x - bodyW / 2, top, bodyW, h);
    }
  } else if (chartType === "bars") {
    for (let i = i0; i <= i1; i++) {
      const b = drawBars[i];
      if (!b) continue;
      const x = time.toX(i);
      if (x < -8 || x > L.plotW + 8) continue;
      const color = b.c >= b.o ? p.bodyUp : p.bodyDown;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      const tick = Math.max(1.5, Math.min(5, bw * 0.3));
      ctx.beginPath();
      ctx.moveTo(x, pm.toY(b.h));
      ctx.lineTo(x, pm.toY(b.l));
      ctx.moveTo(x - tick, pm.toY(b.o));
      ctx.lineTo(x, pm.toY(b.o));
      ctx.moveTo(x, pm.toY(b.c));
      ctx.lineTo(x + tick, pm.toY(b.c));
      ctx.stroke();
    }
  } else {
    /* line + area */
    const plot = (fill: boolean) => {
      ctx.beginPath();
      let started = false;
      for (let i = i0; i <= i1; i++) {
        const b = drawBars[i];
        if (!b) continue;
        const x = time.toX(i);
        const y = pm.toY(b.c);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      if (fill && started) {
        const grad = ctx.createLinearGradient(0, 0, 0, L.priceBottom);
        grad.addColorStop(0, withAlpha(p.areaTop, 0.28));
        grad.addColorStop(1, withAlpha(p.areaBottom, 0.02));
        ctx.save();
        ctx.lineTo(time.toX(i1), L.priceBottom);
        ctx.lineTo(time.toX(i0), L.priceBottom);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.restore();
        ctx.beginPath();
        started = false;
        for (let i = i0; i <= i1; i++) {
          const b = drawBars[i];
          if (!b) continue;
          const x = time.toX(i);
          const y = pm.toY(b.c);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
        }
      }
      ctx.strokeStyle = p.line;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    };
    plot(chartType === "area");
  }

  /* volume strip (bottom of the main pane, above separate panes) */
  if (input.showVolume) {
    drawVolumeStrip(ctx, drawBars, i0, i1, time, bw, L.panes[0], L.plotW, p);
  }

  /* overlay indicators on the main pane */
  for (const { def, result } of overlays) {
    drawResult(ctx, result, {
      toX: (i) => time.toX(i),
      toY: (v) => pm.toY(v),
      i0,
      i1,
      palette: p,
      dotsOnly: def.id === "psar",
    });
  }

  /* user drawings (clipped to the main pane; tags in the gutter) */
  drawDrawings(ctx, input.drawings, {
    time,
    pm,
    pane: L.panes[0],
    plotW: L.plotW,
    axisWidth: vp.priceAxisWidth,
    palette: p,
    axisLabel,
  });

  /* separate panes */
  separates.forEach((entry, paneIdx) => {
    const pane = L.panes[paneIdx + 1];
    if (!pane) return;
    const range = resultRange(entry.result);
    ctx.strokeStyle = p.grid;
    ctx.beginPath();
    ctx.moveTo(0, Math.round(pane.top) + 0.5);
    ctx.lineTo(L.plotW, Math.round(pane.top) + 0.5);
    ctx.stroke();
    if (!range) {
      ctx.fillStyle = p.axisText;
      ctx.textAlign = "left";
      ctx.fillText(`${entry.def.name} — no data`, 6, pane.top + 12);
      return;
    }
    /* pane price labels */
    const step = niceStep((range.max - range.min) / Math.max(1, (pane.bottom - pane.top) / 40));
    const start = Math.ceil(range.min / step) * step;
    for (let v = start; v <= range.max; v += step) {
      const y = Math.round(paneY(v, range, pane.top, pane.bottom)) + 0.5;
      if (y < pane.top - 2 || y > pane.bottom + 2) continue;
      ctx.strokeStyle = p.grid;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(L.plotW, y);
      ctx.stroke();
      ctx.fillStyle = p.axisText;
      ctx.textAlign = "left";
      ctx.fillText(fmtPrice(v), L.plotW + 6, y);
    }
    /* levels */
    for (const level of entry.result.levels ?? []) {
      const y = paneY(level, range, pane.top, pane.bottom);
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = withAlpha(p.textSecondary, 0.5);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(L.plotW, y);
      ctx.stroke();
      ctx.restore();
    }
    if (entry.result.zeroLine) {
      const y = paneY(0, range, pane.top, pane.bottom);
      ctx.save();
      ctx.setLineDash([2, 3]);
      ctx.strokeStyle = withAlpha(p.textSecondary, 0.55);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(L.plotW, y);
      ctx.stroke();
      ctx.restore();
    }
    drawResult(ctx, entry.result, {
      toX: (i) => time.toX(i),
      toY: (v) => paneY(v, range, pane.top, pane.bottom),
      i0,
      i1,
      palette: p,
      dotsOnly: false,
    });
    /* pane label */
    ctx.fillStyle = p.textSecondary;
    ctx.textAlign = "left";
    ctx.fillText(entry.def.name, 6, pane.top + 10);
  });

  /* watermark */
  ctx.save();
  ctx.globalAlpha = 0.06;
  ctx.fillStyle = p.textPrimary;
  ctx.font = "600 42px 'JetBrains Mono', monospace";
  ctx.textAlign = "center";
  ctx.fillText(symbol.toUpperCase(), L.plotW / 2, L.priceBottom / 2);
  ctx.restore();
  ctx.font = "10px 'JetBrains Mono', monospace";

  /* crosshair */
  if (crosshair) {
    const cx = xClamp(crosshair.x);
    if (cx > 0 && cx < L.plotW) {
      ctx.save();
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = withAlpha(p.crosshair, 0.7);
      ctx.beginPath();
      ctx.moveTo(Math.round(cx) + 0.5, 0);
      ctx.lineTo(Math.round(cx) + 0.5, L.timeTop);
      ctx.stroke();
      if (crosshair.y > 0 && crosshair.y < L.priceBottom) {
        const cy = Math.round(crosshair.y) + 0.5;
        ctx.beginPath();
        ctx.moveTo(0, cy);
        ctx.lineTo(L.plotW, cy);
        ctx.stroke();
        /* price tag */
        const priceVal = pm.toPrice(crosshair.y);
        const label = axisLabel(priceVal);
        ctx.setLineDash([]);
        ctx.fillStyle = p.textPrimary;
        ctx.fillRect(L.plotW + 1, crosshair.y - 8, vp.priceAxisWidth - 2, 16);
        ctx.fillStyle = p.background;
        ctx.textAlign = "left";
        ctx.fillText(label, L.plotW + 6, crosshair.y);
      }
      ctx.restore();
    }
  }

  /* legend / OHLC readout */
  drawLegend(ctx, input, crosshair, overlays, { i0, i1 });
}

interface XY {
  toX: (i: number) => number;
  toY: (v: number) => number;
  i0: number;
  i1: number;
  palette: ThemePalette;
  dotsOnly: boolean;
}

function drawResult(ctx: CanvasRenderingContext2D, result: IndicatorResult, xy: XY): void {
  for (const plot of result.plots) {
    ctx.strokeStyle = plot.color;
    ctx.fillStyle = plot.color;
    ctx.lineWidth = plot.width ?? 1.25;
    if (plot.type === "dots") {
      for (let i = xy.i0; i <= xy.i1; i++) {
        const v = plot.data[i];
        if (v == null || !Number.isFinite(v)) continue;
        ctx.beginPath();
        ctx.arc(xy.toX(i), xy.toY(v), 1.4, 0, Math.PI * 2);
        ctx.fill();
      }
      continue;
    }
    if (plot.type === "histogram") {
      const w = Math.max(1, Math.abs(xy.toX(1) - xy.toX(0)) * 0.7);
      const base = xy.toY(0);
      for (let i = xy.i0; i <= xy.i1; i++) {
        const v = plot.data[i];
        if (v == null || !Number.isFinite(v)) continue;
        const y = xy.toY(v);
        ctx.fillRect(xy.toX(i) - w / 2, Math.min(base, y), w, Math.max(1, Math.abs(y - base)));
      }
      continue;
    }
    ctx.beginPath();
    let started = false;
    for (let i = xy.i0; i <= xy.i1; i++) {
      const v = plot.data[i];
      if (v == null || !Number.isFinite(v)) {
        started = false;
        continue;
      }
      const x = xy.toX(i);
      const y = xy.toY(v);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
  }
}

function drawLegend(
  ctx: CanvasRenderingContext2D,
  input: RenderInput,
  crosshair: CrosshairState | null,
  overlays: RenderInput["indicators"],
  range: { i0: number; i1: number },
): void {
  const { bars, palette: p, chartType } = input;
  const idx =
    crosshair && crosshair.index != null && bars[crosshair.index]
      ? crosshair.index
      : range.i1;
  const bar = bars[idx];
  if (!bar) return;
  const prev = bars[idx - 1];
  const chg = prev ? bar.c - prev.c : 0;
  const chgPct = prev && prev.c ? (chg / prev.c) * 100 : 0;
  const up = chg >= 0;
  let x = 6;
  const y = 12;
  ctx.textAlign = "left";
  ctx.fillStyle = p.textPrimary;
  const symText = `${input.symbol.toUpperCase()} · ${chartType.toUpperCase()}`;
  ctx.fillText(symText, x, y);
  x += ctx.measureText(symText).width + 14;
  ctx.fillStyle = up ? p.positive : p.negative;
  const chgText = `${chg >= 0 ? "+" : ""}${fmtPrice(chg)} (${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%)`;
  ctx.fillText(chgText, x, y);
  x += ctx.measureText(chgText).width + 14;
  ctx.fillStyle = p.textSecondary;
  ctx.fillText(
    `O ${fmtPrice(bar.o)}  H ${fmtPrice(bar.h)}  L ${fmtPrice(bar.l)}  C ${fmtPrice(bar.c)}`,
    x,
    y,
  );
  if (input.legend) {
    ctx.fillStyle = p.axisText;
    ctx.textAlign = "right";
    ctx.fillText(input.legend, input.viewport.width - input.viewport.priceAxisWidth - 6, y);
    ctx.textAlign = "left";
  }
  /* indicator value rows */
  let rowY = y + 13;
  for (const { def, result } of overlays) {
    const parts: string[] = [];
    for (const plot of result.plots) {
      const v = plot.data[idx];
      parts.push(`${plot.label} ${v == null || !Number.isFinite(v) ? "—" : fmtPrice(v)}`);
    }
    if (!parts.length) continue;
    ctx.fillStyle = p.textSecondary;
    ctx.fillText(`${def.name} · ${parts.join("  ")}`, 6, rowY);
    rowY += 12;
  }
}

/** Autofit helper the shell calls when data/viewport changes. */
export function fitPriceToVisible(
  price: PriceScale,
  bars: Bar[],
  time: TimeScale,
  padFrac = 0.08,
): void {
  const rng = time.range();
  const i0 = Math.max(0, Math.floor(rng.from));
  const i1 = Math.min(bars.length - 1, Math.ceil(rng.to));
  let min = Infinity;
  let max = -Infinity;
  for (let i = i0; i <= i1; i++) {
    const b = bars[i];
    if (!b) continue;
    if (b.l < min) min = b.l;
    if (b.h > max) max = b.h;
  }
  if (min > max) return;
  price.fit(min, max, padFrac);
}
