/**
 * showMe chart engine — pure indicator registry (milestone 1, 2026-09-15).
 *
 * Every indicator is a pure function over `Bar[]`: no DOM, no state, no
 * side effects. `IndicatorPlot.data` is always exactly as long as the input
 * and holds `null` (never `NaN`) during warmup or wherever the formula is
 * undefined. Params are read defensively — a missing, malformed or
 * out-of-range value falls back to the declared default.
 *
 * Formula conventions (standard definitions):
 *   - SMA / WMA — simple / linearly-weighted mean over `length`.
 *   - EMA / RSI / ATR / ADX — Wilder: SMA seed, then recursive smoothing.
 *   - MACD signal — EMA of the MACD line, seeded with its own SMA.
 *   - Bollinger — population standard deviation over the same window.
 *   - Ichimoku sense lines are forward-displaced by `base` bars (standard
 *     cloud placement), so the final `base` entries are null.
 *   - VWAP — typical-price volume weighting; rolling when `length > 0`.
 */
import type {
  Bar,
  IndicatorDef,
  IndicatorParamDef,
  IndicatorParams,
  IndicatorPlot,
  IndicatorResult,
} from "./types";

type Maybe = number | null;

/* ── numeric helpers ─────────────────────────────────────────────────── */

function paramNum(
  params: IndicatorParams,
  key: string,
  fallback: number,
  min = Number.NEGATIVE_INFINITY,
  max = Number.POSITIVE_INFINITY,
): number {
  const raw = params[key];
  const value =
    typeof raw === "number" ? raw : typeof raw === "string" ? Number(raw) : Number.NaN;
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

/** Integer period, at least `min` (default 1). */
function periodOf(params: IndicatorParams, key: string, fallback: number, min = 1): number {
  return Math.max(min, Math.round(paramNum(params, key, fallback, min)));
}

/** Replace any non-finite entry with null (the contract never allows NaN). */
function clean(data: (number | null)[]): Maybe[] {
  return data.map((v) => (v !== null && Number.isFinite(v) ? v : null));
}

function finish(
  plots: IndicatorPlot[],
  extra: { levels?: number[]; zeroLine?: boolean } = {},
): IndicatorResult {
  const result: IndicatorResult = {
    plots: plots.map((p) => ({ ...p, data: clean(p.data) })),
  };
  if (extra.levels !== undefined) result.levels = extra.levels.filter((v) => Number.isFinite(v));
  if (extra.zeroLine !== undefined) result.zeroLine = extra.zeroLine;
  return result;
}

/* ── rolling window primitives ───────────────────────────────────────── */

function sma(src: number[], period: number): Maybe[] {
  const n = src.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (period < 1 || n < period) return out;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += src[i];
    if (i >= period) sum -= src[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function ema(src: number[], period: number): Maybe[] {
  const n = src.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (period < 1 || n < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += src[i];
  let prev = sum / period;
  out[period - 1] = prev;
  const k = 2 / (period + 1);
  for (let i = period; i < n; i++) {
    prev += k * (src[i] - prev);
    out[i] = prev;
  }
  return out;
}

/** EMA over a series that itself has leading nulls (settles after the seed). */
function emaNullable(src: Maybe[], period: number): Maybe[] {
  const out: Maybe[] = new Array(src.length).fill(null);
  let start = -1;
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== null) {
      start = i;
      break;
    }
  }
  if (start < 0) return out;
  const defined: number[] = [];
  for (let i = start; i < src.length; i++) defined.push(src[i] as number);
  const smoothed = ema(defined, period);
  for (let j = 0; j < smoothed.length; j++) out[start + j] = smoothed[j];
  return out;
}

/** SMA over a series that itself has leading nulls. */
function smaNullable(src: Maybe[], period: number): Maybe[] {
  const out: Maybe[] = new Array(src.length).fill(null);
  let start = -1;
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== null) {
      start = i;
      break;
    }
  }
  if (start < 0) return out;
  const defined: number[] = [];
  for (let i = start; i < src.length; i++) defined.push(src[i] as number);
  const smoothed = sma(defined, period);
  for (let j = 0; j < smoothed.length; j++) out[start + j] = smoothed[j];
  return out;
}

/** Linearly weighted moving average (most recent bar carries weight `period`). */
function wma(src: number[], period: number): Maybe[] {
  const n = src.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (period < 1 || n < period) return out;
  const denom = (period * (period + 1)) / 2;
  for (let i = period - 1; i < n; i++) {
    let sum = 0;
    for (let k = 0; k < period; k++) sum += src[i - period + 1 + k] * (k + 1);
    out[i] = sum / denom;
  }
  return out;
}

/** Population standard deviation over the trailing window. */
function stdev(src: number[], period: number): Maybe[] {
  const n = src.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (period < 1 || n < period) return out;
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < n; i++) {
    sum += src[i];
    sumSq += src[i] * src[i];
    if (i >= period) {
      const old = src[i - period];
      sum -= old;
      sumSq -= old * old;
    }
    if (i >= period - 1) {
      const mean = sum / period;
      const variance = Math.max(0, sumSq / period - mean * mean);
      out[i] = Math.sqrt(variance);
    }
  }
  return out;
}

/** Wilder's smoothing (SMA seed, then `prev + (x - prev) / period`). */
function wilder(src: number[], period: number): Maybe[] {
  const n = src.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (period < 1 || n < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += src[i];
  let prev = sum / period;
  out[period - 1] = prev;
  for (let i = period; i < n; i++) {
    prev = (prev * (period - 1) + src[i]) / period;
    out[i] = prev;
  }
  return out;
}

function trueRange(bars: Bar[]): number[] {
  const n = bars.length;
  const tr: number[] = new Array(n).fill(0);
  if (n === 0) return tr;
  tr[0] = bars[0].h - bars[0].l;
  for (let i = 1; i < n; i++) {
    tr[i] = Math.max(
      bars[i].h - bars[i].l,
      Math.abs(bars[i].h - bars[i - 1].c),
      Math.abs(bars[i].l - bars[i - 1].c),
    );
  }
  return tr;
}

function rollingExtreme(src: number[], period: number, mode: "max" | "min"): Maybe[] {
  const n = src.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (period < 1 || n < period) return out;
  for (let i = period - 1; i < n; i++) {
    let value = src[i - period + 1];
    for (let k = i - period + 2; k <= i; k++) {
      value = mode === "max" ? Math.max(value, src[k]) : Math.min(value, src[k]);
    }
    out[i] = value;
  }
  return out;
}

function typicalPrices(bars: Bar[]): number[] {
  return bars.map((b) => (b.h + b.l + b.c) / 3);
}

function rsiFromAverages(avgGain: number, avgLoss: number): number {
  if (avgLoss === 0) return 100;
  if (avgGain === 0) return 0;
  return 100 - 100 / (1 + avgGain / avgLoss);
}

/** Wilder RSI, first value at index `period`. */
function rsiSeries(bars: Bar[], period: number): Maybe[] {
  const n = bars.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (period < 1 || n <= period) return out;
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const change = bars[i].c - bars[i - 1].c;
    if (change > 0) avgGain += change;
    else avgLoss -= change;
  }
  avgGain /= period;
  avgLoss /= period;
  out[period] = rsiFromAverages(avgGain, avgLoss);
  for (let i = period + 1; i < n; i++) {
    const change = bars[i].c - bars[i - 1].c;
    avgGain = (avgGain * (period - 1) + Math.max(change, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-change, 0)) / period;
    out[i] = rsiFromAverages(avgGain, avgLoss);
  }
  return out;
}

/* ── overlays ────────────────────────────────────────────────────────── */

function computeSma(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 20);
  const src = bars.map((b) => b.c);
  return finish([
    { key: "sma", label: "SMA", type: "line", color: "var(--accent)", data: sma(src, length) },
  ]);
}

function computeEma(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 20);
  const src = bars.map((b) => b.c);
  return finish([
    { key: "ema", label: "EMA", type: "line", color: "var(--warn)", data: ema(src, length) },
  ]);
}

function computeWma(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 20);
  const src = bars.map((b) => b.c);
  return finish([
    { key: "wma", label: "WMA", type: "line", color: "var(--positive)", data: wma(src, length) },
  ]);
}

function computeBollinger(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 20);
  const mult = paramNum(params, "mult", 2, 0.1, 20);
  const src = bars.map((b) => b.c);
  const mid = sma(src, length);
  const dev = stdev(src, length);
  const upper: Maybe[] = new Array(bars.length).fill(null);
  const lower: Maybe[] = new Array(bars.length).fill(null);
  for (let i = 0; i < bars.length; i++) {
    const m = mid[i];
    const d = dev[i];
    if (m === null || d === null) continue;
    upper[i] = m + mult * d;
    lower[i] = m - mult * d;
  }
  return finish([
    { key: "bbu", label: "BB Upper", type: "line", color: "var(--text-secondary)", data: upper },
    { key: "bbm", label: "BB Mid", type: "line", color: "var(--accent)", data: mid },
    { key: "bbl", label: "BB Lower", type: "line", color: "var(--text-secondary)", data: lower },
  ]);
}

function computeVwap(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = Math.round(paramNum(params, "length", 0, 0));
  const n = bars.length;
  const out: Maybe[] = new Array(n).fill(null);
  let sumPV = 0;
  let sumV = 0;
  for (let i = 0; i < n; i++) {
    const tp = (bars[i].h + bars[i].l + bars[i].c) / 3;
    sumPV += tp * bars[i].v;
    sumV += bars[i].v;
    if (length > 0 && i >= length) {
      const old = bars[i - length];
      sumPV -= ((old.h + old.l + old.c) / 3) * old.v;
      sumV -= old.v;
    }
    if (length === 0 || i >= length - 1) out[i] = sumV > 0 ? sumPV / sumV : null;
  }
  return finish([
    { key: "vwap", label: "VWAP", type: "line", color: "var(--warn)", data: out },
  ]);
}

function computeKeltner(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 20);
  const mult = paramNum(params, "mult", 2, 0.1, 20);
  const atrLength = periodOf(params, "atrLength", 10);
  const mid = ema(typicalPrices(bars), length);
  const range = wilder(trueRange(bars), atrLength);
  const upper: Maybe[] = new Array(bars.length).fill(null);
  const lower: Maybe[] = new Array(bars.length).fill(null);
  for (let i = 0; i < bars.length; i++) {
    const m = mid[i];
    const a = range[i];
    if (m === null || a === null) continue;
    upper[i] = m + mult * a;
    lower[i] = m - mult * a;
  }
  return finish([
    { key: "kcu", label: "Keltner Upper", type: "line", color: "var(--positive)", data: upper },
    { key: "kcm", label: "Keltner Mid", type: "line", color: "var(--text-secondary)", data: mid },
    { key: "kcl", label: "Keltner Lower", type: "line", color: "var(--negative)", data: lower },
  ]);
}

function computeDonchian(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 20);
  const upper = rollingExtreme(
    bars.map((b) => b.h),
    length,
    "max",
  );
  const lower = rollingExtreme(
    bars.map((b) => b.l),
    length,
    "min",
  );
  const mid: Maybe[] = new Array(bars.length).fill(null);
  for (let i = 0; i < bars.length; i++) {
    const u = upper[i];
    const l = lower[i];
    if (u !== null && l !== null) mid[i] = (u + l) / 2;
  }
  return finish([
    { key: "dcu", label: "Donchian Upper", type: "line", color: "var(--positive)", data: upper },
    { key: "dcm", label: "Donchian Mid", type: "line", color: "var(--text-secondary)", data: mid },
    { key: "dcl", label: "Donchian Lower", type: "line", color: "var(--negative)", data: lower },
  ]);
}

function computePsar(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const step = paramNum(params, "step", 0.02, 0.001, 1);
  const maxAf = paramNum(params, "max", 0.2, 0.001, 5);
  const n = bars.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (n >= 2) {
    let up = bars[1].c >= bars[0].c;
    let sar = up ? Math.min(bars[0].l, bars[1].l) : Math.max(bars[0].h, bars[1].h);
    let ep = up ? Math.max(bars[0].h, bars[1].h) : Math.min(bars[0].l, bars[1].l);
    let af = step;
    out[1] = sar;
    for (let i = 2; i < n; i++) {
      let next = sar + af * (ep - sar);
      if (up) {
        next = Math.min(next, bars[i - 1].l, bars[i - 2].l);
        if (bars[i].l < next) {
          up = false;
          next = ep;
          ep = bars[i].l;
          af = step;
        } else if (bars[i].h > ep) {
          ep = bars[i].h;
          af = Math.min(af + step, maxAf);
        }
      } else {
        next = Math.max(next, bars[i - 1].h, bars[i - 2].h);
        if (bars[i].h > next) {
          up = true;
          next = ep;
          ep = bars[i].h;
          af = step;
        } else if (bars[i].l < ep) {
          ep = bars[i].l;
          af = Math.min(af + step, maxAf);
        }
      }
      sar = next;
      out[i] = sar;
    }
  }
  return finish([
    { key: "psar", label: "Parabolic SAR", type: "dots", color: "var(--warn)", data: out },
  ]);
}

function computeSupertrend(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const atrLength = periodOf(params, "atrLength", 10);
  const mult = paramNum(params, "mult", 3, 0.1, 50);
  const n = bars.length;
  const atr = wilder(trueRange(bars), atrLength);
  const st: Maybe[] = new Array(n).fill(null);
  const dir: Maybe[] = new Array(n).fill(null);
  let finalUpper = 0;
  let finalLower = 0;
  let trendUp = true;
  let started = false;
  for (let i = 0; i < n; i++) {
    const a = atr[i];
    if (a === null) continue;
    const hl2 = (bars[i].h + bars[i].l) / 2;
    const upper = hl2 + mult * a;
    const lower = hl2 - mult * a;
    if (!started) {
      finalUpper = upper;
      finalLower = lower;
      trendUp = bars[i].c >= lower;
      started = true;
    } else {
      finalUpper = upper < finalUpper || bars[i - 1].c > finalUpper ? upper : finalUpper;
      finalLower = lower > finalLower || bars[i - 1].c < finalLower ? lower : finalLower;
      if (trendUp && bars[i].c < finalLower) trendUp = false;
      else if (!trendUp && bars[i].c > finalUpper) trendUp = true;
    }
    st[i] = trendUp ? finalLower : finalUpper;
    dir[i] = trendUp ? 1 : -1;
  }
  return finish([
    { key: "st", label: "SuperTrend", type: "line", color: "var(--accent)", data: st },
    { key: "trend", label: "Direction", type: "line", color: "var(--text-secondary)", data: dir },
  ]);
}

function computeIchimoku(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const conv = periodOf(params, "conv", 9);
  const base = periodOf(params, "base", 26);
  const spanBLength = periodOf(params, "spanB", 52);
  const n = bars.length;
  const highs = bars.map((b) => b.h);
  const lows = bars.map((b) => b.l);
  const hiConv = rollingExtreme(highs, conv, "max");
  const loConv = rollingExtreme(lows, conv, "min");
  const hiBase = rollingExtreme(highs, base, "max");
  const loBase = rollingExtreme(lows, base, "min");
  const hiSpan = rollingExtreme(highs, spanBLength, "max");
  const loSpan = rollingExtreme(lows, spanBLength, "min");
  const tenkan: Maybe[] = new Array(n).fill(null);
  const kijun: Maybe[] = new Array(n).fill(null);
  const senkouA: Maybe[] = new Array(n).fill(null);
  const senkouB: Maybe[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    const hc = hiConv[i];
    const lc = loConv[i];
    if (hc !== null && lc !== null) tenkan[i] = (hc + lc) / 2;
    const hb = hiBase[i];
    const lb = loBase[i];
    if (hb !== null && lb !== null) kijun[i] = (hb + lb) / 2;
    const tk = tenkan[i];
    const kj = kijun[i];
    const target = i + base;
    if (tk !== null && kj !== null && target < n) senkouA[target] = (tk + kj) / 2;
    const hs = hiSpan[i];
    const ls = loSpan[i];
    if (hs !== null && ls !== null && target < n) senkouB[target] = (hs + ls) / 2;
  }
  return finish([
    { key: "tenkan", label: "Tenkan-sen", type: "line", color: "var(--accent)", data: tenkan },
    { key: "kijun", label: "Kijun-sen", type: "line", color: "var(--warn)", data: kijun },
    { key: "senkouA", label: "Senkou A", type: "line", color: "var(--positive)", data: senkouA },
    { key: "senkouB", label: "Senkou B", type: "line", color: "var(--negative)", data: senkouB },
  ]);
}

/** Classic floor-trader pivots from the most recent bar (levels only). */
function computePivot(bars: Bar[]): IndicatorResult {
  const levels: number[] = [];
  const last = bars.length > 0 ? bars[bars.length - 1] : null;
  if (last !== null) {
    const p = (last.h + last.l + last.c) / 3;
    const r1 = 2 * p - last.l;
    const s1 = 2 * p - last.h;
    const r2 = p + (last.h - last.l);
    const s2 = p - (last.h - last.l);
    const r3 = last.h + 2 * (p - last.l);
    const s3 = last.l - 2 * (last.h - p);
    levels.push(s3, s2, s1, p, r1, r2, r3);
  }
  return { plots: [], levels: levels.filter((v) => Number.isFinite(v)) };
}

/* ── oscillator panes ────────────────────────────────────────────────── */

function computeRsi(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 14);
  return finish(
    [
      {
        key: "rsi",
        label: "RSI",
        type: "line",
        color: "var(--accent)",
        data: rsiSeries(bars, length),
      },
    ],
    { levels: [30, 70] },
  );
}

function computeMacd(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const fast = periodOf(params, "fast", 12);
  const slow = periodOf(params, "slow", 26);
  const signalPeriod = periodOf(params, "signal", 9);
  const closes = bars.map((b) => b.c);
  const fastEma = ema(closes, fast);
  const slowEma = ema(closes, slow);
  const macd: Maybe[] = closes.map((_, i) => {
    const f = fastEma[i];
    const s = slowEma[i];
    return f !== null && s !== null ? f - s : null;
  });
  const signal = emaNullable(macd, signalPeriod);
  const hist: Maybe[] = macd.map((m, i) => {
    const s = signal[i];
    return m !== null && s !== null ? m - s : null;
  });
  return finish(
    [
      { key: "macd", label: "MACD", type: "line", color: "var(--accent)", data: macd },
      { key: "signal", label: "Signal", type: "line", color: "var(--warn)", data: signal },
      { key: "hist", label: "Histogram", type: "histogram", color: "var(--positive)", data: hist },
    ],
    { zeroLine: true },
  );
}

function computeStochastic(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const kLength = periodOf(params, "kLength", 14);
  const kSmooth = periodOf(params, "kSmooth", 3);
  const dSmooth = periodOf(params, "dSmooth", 3);
  const hh = rollingExtreme(
    bars.map((b) => b.h),
    kLength,
    "max",
  );
  const ll = rollingExtreme(
    bars.map((b) => b.l),
    kLength,
    "min",
  );
  const raw: Maybe[] = bars.map((b, i) => {
    const hi = hh[i];
    const lo = ll[i];
    if (hi === null || lo === null) return null;
    const range = hi - lo;
    return range > 0 ? ((b.c - lo) / range) * 100 : 50;
  });
  const k = smaNullable(raw, kSmooth);
  const d = smaNullable(k, dSmooth);
  return finish(
    [
      { key: "k", label: "%K", type: "line", color: "var(--accent)", data: k },
      { key: "d", label: "%D", type: "line", color: "var(--warn)", data: d },
    ],
    { levels: [20, 80] },
  );
}

function computeAtr(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 14);
  return finish([
    {
      key: "atr",
      label: "ATR",
      type: "line",
      color: "var(--warn)",
      data: wilder(trueRange(bars), length),
    },
  ]);
}

function computeAdx(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 14);
  const n = bars.length;
  const adx: Maybe[] = new Array(n).fill(null);
  const plusDI: Maybe[] = new Array(n).fill(null);
  const minusDI: Maybe[] = new Array(n).fill(null);
  const tr = trueRange(bars);
  if (n > length) {
    const plusDM: number[] = new Array(n).fill(0);
    const minusDM: number[] = new Array(n).fill(0);
    for (let i = 1; i < n; i++) {
      const up = bars[i].h - bars[i - 1].h;
      const down = bars[i - 1].l - bars[i].l;
      plusDM[i] = up > down && up > 0 ? up : 0;
      minusDM[i] = down > up && down > 0 ? down : 0;
    }
    let sTR = 0;
    let sPlus = 0;
    let sMinus = 0;
    for (let i = 1; i <= length; i++) {
      sTR += tr[i];
      sPlus += plusDM[i];
      sMinus += minusDM[i];
    }
    const dx: Maybe[] = new Array(n).fill(null);
    for (let i = length; i < n; i++) {
      if (i > length) {
        sTR = sTR - sTR / length + tr[i];
        sPlus = sPlus - sPlus / length + plusDM[i];
        sMinus = sMinus - sMinus / length + minusDM[i];
      }
      const p = sTR > 0 ? (100 * sPlus) / sTR : 0;
      const m = sTR > 0 ? (100 * sMinus) / sTR : 0;
      plusDI[i] = p;
      minusDI[i] = m;
      const total = p + m;
      dx[i] = total > 0 ? (100 * Math.abs(p - m)) / total : 0;
    }
    if (n >= 2 * length) {
      let seed = 0;
      for (let i = length; i < 2 * length; i++) seed += dx[i] as number;
      let prev = seed / length;
      adx[2 * length - 1] = prev;
      for (let i = 2 * length; i < n; i++) {
        prev = (prev * (length - 1) + (dx[i] as number)) / length;
        adx[i] = prev;
      }
    }
  }
  return finish(
    [
      { key: "adx", label: "ADX", type: "line", color: "var(--accent)", data: adx },
      { key: "plusDI", label: "+DI", type: "line", color: "var(--positive)", data: plusDI },
      { key: "minusDI", label: "-DI", type: "line", color: "var(--negative)", data: minusDI },
    ],
    { levels: [25] },
  );
}

function computeCci(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 20);
  const n = bars.length;
  const tp = typicalPrices(bars);
  const ma = sma(tp, length);
  const out: Maybe[] = new Array(n).fill(null);
  for (let i = length - 1; i < n; i++) {
    const m = ma[i];
    if (m === null) continue;
    let deviation = 0;
    for (let k = i - length + 1; k <= i; k++) deviation += Math.abs(tp[k] - m);
    deviation /= length;
    out[i] = deviation > 0 ? (tp[i] - m) / (0.015 * deviation) : 0;
  }
  return finish(
    [{ key: "cci", label: "CCI", type: "line", color: "var(--accent)", data: out }],
    { levels: [-100, 100], zeroLine: true },
  );
}

function computeWilliamsR(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 14);
  const n = bars.length;
  const hh = rollingExtreme(
    bars.map((b) => b.h),
    length,
    "max",
  );
  const ll = rollingExtreme(
    bars.map((b) => b.l),
    length,
    "min",
  );
  const out: Maybe[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    const hi = hh[i];
    const lo = ll[i];
    if (hi === null || lo === null) continue;
    const range = hi - lo;
    out[i] = range > 0 ? (-100 * (hi - bars[i].c)) / range : -50;
  }
  return finish(
    [{ key: "wr", label: "Williams %R", type: "line", color: "var(--warn)", data: out }],
    { levels: [-20, -80] },
  );
}

function computeObv(bars: Bar[]): IndicatorResult {
  const n = bars.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (n > 0) {
    let value = 0;
    out[0] = 0;
    for (let i = 1; i < n; i++) {
      if (bars[i].c > bars[i - 1].c) value += bars[i].v;
      else if (bars[i].c < bars[i - 1].c) value -= bars[i].v;
      out[i] = value;
    }
  }
  return finish([{ key: "obv", label: "OBV", type: "line", color: "var(--accent)", data: out }]);
}

function mfiValue(positive: number, negative: number): number {
  if (negative === 0) return positive === 0 ? 50 : 100;
  if (positive === 0) return 0;
  return 100 - 100 / (1 + positive / negative);
}

function computeMfi(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 14);
  const n = bars.length;
  const out: Maybe[] = new Array(n).fill(null);
  if (n > length) {
    const positive: number[] = new Array(n).fill(0);
    const negative: number[] = new Array(n).fill(0);
    for (let i = 1; i < n; i++) {
      const tp = (bars[i].h + bars[i].l + bars[i].c) / 3;
      const prevTp = (bars[i - 1].h + bars[i - 1].l + bars[i - 1].c) / 3;
      const flow = tp * bars[i].v;
      if (tp > prevTp) positive[i] = flow;
      else if (tp < prevTp) negative[i] = flow;
    }
    let sumPos = 0;
    let sumNeg = 0;
    for (let i = 1; i <= length; i++) {
      sumPos += positive[i];
      sumNeg += negative[i];
    }
    out[length] = mfiValue(sumPos, sumNeg);
    for (let i = length + 1; i < n; i++) {
      sumPos += positive[i] - positive[i - length];
      sumNeg += negative[i] - negative[i - length];
      out[i] = mfiValue(sumPos, sumNeg);
    }
  }
  return finish(
    [{ key: "mfi", label: "MFI", type: "line", color: "var(--accent)", data: out }],
    { levels: [20, 80] },
  );
}

function computeRoc(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 12);
  const n = bars.length;
  const out: Maybe[] = new Array(n).fill(null);
  for (let i = length; i < n; i++) {
    const base = bars[i - length].c;
    if (base !== 0) out[i] = (100 * (bars[i].c - base)) / base;
  }
  return finish(
    [{ key: "roc", label: "ROC", type: "line", color: "var(--text-secondary)", data: out }],
    { zeroLine: true },
  );
}

function computeVolume(bars: Bar[]): IndicatorResult {
  return finish([
    {
      key: "volume",
      label: "Volume",
      type: "histogram",
      color: "var(--text-secondary)",
      data: bars.map((b) => b.v),
    },
  ]);
}

function computeStochRsi(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 14);
  const kPeriod = periodOf(params, "k", 3);
  const dPeriod = periodOf(params, "d", 3);
  const n = bars.length;
  const rsi = rsiSeries(bars, length);
  const raw: Maybe[] = new Array(n).fill(null);
  for (let i = length - 1; i < n; i++) {
    let lo = Number.POSITIVE_INFINITY;
    let hi = Number.NEGATIVE_INFINITY;
    let complete = true;
    for (let k = i - length + 1; k <= i; k++) {
      const v = rsi[k];
      if (v === null) {
        complete = false;
        break;
      }
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
    if (!complete) continue;
    const last = rsi[i];
    if (last === null) continue;
    raw[i] = hi > lo ? ((last - lo) / (hi - lo)) * 100 : 50;
  }
  const k = smaNullable(raw, kPeriod);
  const d = smaNullable(k, dPeriod);
  return finish(
    [
      { key: "k", label: "%K", type: "line", color: "var(--accent)", data: k },
      { key: "d", label: "%D", type: "line", color: "var(--warn)", data: d },
    ],
    { levels: [20, 80] },
  );
}

function computeUltimate(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const p1 = periodOf(params, "p1", 7);
  const p2 = periodOf(params, "p2", 14);
  const p3 = periodOf(params, "p3", 28);
  const n = bars.length;
  const buyingPressure: number[] = new Array(n).fill(0);
  const trueRangeU: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    buyingPressure[i] = bars[i].c - Math.min(bars[i].l, bars[i - 1].c);
    trueRangeU[i] =
      Math.max(bars[i].h, bars[i - 1].c) - Math.min(bars[i].l, bars[i - 1].c);
  }
  const out: Maybe[] = new Array(n).fill(null);
  for (let i = p3; i < n; i++) {
    let bp1 = 0;
    let tr1 = 0;
    let bp2 = 0;
    let tr2 = 0;
    let bp3 = 0;
    let tr3 = 0;
    for (let k = i - p1 + 1; k <= i; k++) {
      bp1 += buyingPressure[k];
      tr1 += trueRangeU[k];
    }
    for (let k = i - p2 + 1; k <= i; k++) {
      bp2 += buyingPressure[k];
      tr2 += trueRangeU[k];
    }
    for (let k = i - p3 + 1; k <= i; k++) {
      bp3 += buyingPressure[k];
      tr3 += trueRangeU[k];
    }
    if (tr1 === 0 || tr2 === 0 || tr3 === 0) continue;
    out[i] = (100 * (4 * (bp1 / tr1) + 2 * (bp2 / tr2) + bp3 / tr3)) / 7;
  }
  return finish(
    [{ key: "uo", label: "Ultimate Oscillator", type: "line", color: "var(--accent)", data: out }],
    { levels: [30, 70] },
  );
}

function computeCmf(bars: Bar[], params: IndicatorParams): IndicatorResult {
  const length = periodOf(params, "length", 20);
  const n = bars.length;
  const out: Maybe[] = new Array(n).fill(null);
  let sumFlow = 0;
  let sumVolume = 0;
  for (let i = 0; i < n; i++) {
    const range = bars[i].h - bars[i].l;
    const mfm = range > 0 ? (bars[i].c - bars[i].l - (bars[i].h - bars[i].c)) / range : 0;
    sumFlow += mfm * bars[i].v;
    sumVolume += bars[i].v;
    if (i >= length) {
      const old = bars[i - length];
      const oldRange = old.h - old.l;
      const oldMfm = oldRange > 0 ? (old.c - old.l - (old.h - old.c)) / oldRange : 0;
      sumFlow -= oldMfm * old.v;
      sumVolume -= old.v;
    }
    if (i >= length - 1) out[i] = sumVolume > 0 ? sumFlow / sumVolume : 0;
  }
  return finish(
    [{ key: "cmf", label: "Chaikin MF", type: "line", color: "var(--warn)", data: out }],
    { zeroLine: true },
  );
}

/* ── param schemas ───────────────────────────────────────────────────── */

function numeric(
  key: string,
  label: string,
  def: number,
  min = 0,
  max = 1000,
  step = 1,
): IndicatorParamDef {
  return { key, label, kind: "number", default: def, min, max, step };
}

const lengthParam = (def = 20, label = "Length"): IndicatorParamDef =>
  numeric("length", label, def, 1, 500, 1);

/* ── registry ────────────────────────────────────────────────────────── */

export const INDICATORS: IndicatorDef[] = [
  {
    id: "sma",
    name: "SMA",
    category: "Moving averages",
    overlayDefault: true,
    params: [lengthParam(20)],
    compute: computeSma,
  },
  {
    id: "ema",
    name: "EMA",
    category: "Moving averages",
    overlayDefault: true,
    params: [lengthParam(20)],
    compute: computeEma,
  },
  {
    id: "wma",
    name: "WMA",
    category: "Moving averages",
    overlayDefault: true,
    params: [lengthParam(20)],
    compute: computeWma,
  },
  {
    id: "bb",
    name: "Bollinger Bands",
    category: "Bands",
    overlayDefault: true,
    params: [lengthParam(20), numeric("mult", "Std dev", 2, 0.1, 10, 0.1)],
    compute: computeBollinger,
  },
  {
    id: "vwap",
    name: "VWAP",
    category: "Moving averages",
    overlayDefault: true,
    params: [
      { ...lengthParam(0), min: 0, label: "Window (0 = session)" },
    ],
    compute: computeVwap,
  },
  {
    id: "keltner",
    name: "Keltner Channels",
    category: "Bands",
    overlayDefault: true,
    params: [
      lengthParam(20),
      numeric("mult", "ATR mult", 2, 0.1, 10, 0.1),
      numeric("atrLength", "ATR length", 10, 1, 200, 1),
    ],
    compute: computeKeltner,
  },
  {
    id: "donchian",
    name: "Donchian Channels",
    category: "Bands",
    overlayDefault: true,
    params: [lengthParam(20)],
    compute: computeDonchian,
  },
  {
    id: "psar",
    name: "Parabolic SAR",
    category: "Trend",
    overlayDefault: true,
    params: [
      numeric("step", "Step", 0.02, 0.001, 1, 0.001),
      numeric("max", "Max", 0.2, 0.01, 5, 0.01),
    ],
    compute: computePsar,
  },
  {
    id: "supertrend",
    name: "SuperTrend",
    category: "Trend",
    overlayDefault: true,
    params: [
      numeric("atrLength", "ATR length", 10, 1, 200, 1),
      numeric("mult", "Multiplier", 3, 0.1, 50, 0.1),
    ],
    compute: computeSupertrend,
  },
  {
    id: "ichimoku",
    name: "Ichimoku Cloud",
    category: "Trend",
    overlayDefault: true,
    params: [
      numeric("conv", "Conversion", 9, 1, 200, 1),
      numeric("base", "Base", 26, 1, 200, 1),
      numeric("spanB", "Span B", 52, 1, 500, 1),
    ],
    compute: computeIchimoku,
  },
  {
    id: "pivot",
    name: "Pivot Points",
    category: "Levels",
    overlayDefault: true,
    params: [],
    compute: computePivot,
  },
  {
    id: "rsi",
    name: "RSI",
    category: "Oscillators",
    overlayDefault: false,
    params: [lengthParam(14)],
    compute: computeRsi,
  },
  {
    id: "macd",
    name: "MACD",
    category: "Oscillators",
    overlayDefault: false,
    params: [
      numeric("fast", "Fast", 12, 1, 200, 1),
      numeric("slow", "Slow", 26, 2, 400, 1),
      numeric("signal", "Signal", 9, 1, 200, 1),
    ],
    compute: computeMacd,
  },
  {
    id: "stoch",
    name: "Stochastic",
    category: "Oscillators",
    overlayDefault: false,
    params: [
      numeric("kLength", "%K length", 14, 1, 200, 1),
      numeric("kSmooth", "%K smooth", 3, 1, 100, 1),
      numeric("dSmooth", "%D smooth", 3, 1, 100, 1),
    ],
    compute: computeStochastic,
  },
  {
    id: "atr",
    name: "ATR",
    category: "Volatility",
    overlayDefault: false,
    params: [lengthParam(14)],
    compute: computeAtr,
  },
  {
    id: "adx",
    name: "ADX",
    category: "Trend",
    overlayDefault: false,
    params: [lengthParam(14)],
    compute: computeAdx,
  },
  {
    id: "cci",
    name: "CCI",
    category: "Oscillators",
    overlayDefault: false,
    params: [lengthParam(20)],
    compute: computeCci,
  },
  {
    id: "williams-r",
    name: "Williams %R",
    category: "Oscillators",
    overlayDefault: false,
    params: [lengthParam(14)],
    compute: computeWilliamsR,
  },
  {
    id: "obv",
    name: "OBV",
    category: "Volume",
    overlayDefault: false,
    params: [],
    compute: computeObv,
  },
  {
    id: "mfi",
    name: "MFI",
    category: "Oscillators",
    overlayDefault: false,
    params: [lengthParam(14)],
    compute: computeMfi,
  },
  {
    id: "roc",
    name: "ROC",
    category: "Oscillators",
    overlayDefault: false,
    params: [lengthParam(12, "Length")],
    compute: computeRoc,
  },
  {
    id: "volume",
    name: "Volume",
    category: "Volume",
    overlayDefault: false,
    params: [],
    compute: computeVolume,
  },
  {
    id: "stoch-rsi",
    name: "Stochastic RSI",
    category: "Oscillators",
    overlayDefault: false,
    params: [
      numeric("length", "RSI length", 14, 1, 200, 1),
      numeric("k", "%K smooth", 3, 1, 100, 1),
      numeric("d", "%D smooth", 3, 1, 100, 1),
    ],
    compute: computeStochRsi,
  },
  {
    id: "uo",
    name: "Ultimate Oscillator",
    category: "Oscillators",
    overlayDefault: false,
    params: [
      numeric("p1", "Short", 7, 1, 200, 1),
      numeric("p2", "Medium", 14, 1, 200, 1),
      numeric("p3", "Long", 28, 1, 400, 1),
    ],
    compute: computeUltimate,
  },
  {
    id: "cmf",
    name: "Chaikin Money Flow",
    category: "Oscillators",
    overlayDefault: false,
    params: [lengthParam(20)],
    compute: computeCmf,
  },
];

/** Registry lookup; undefined for an unknown id (caller decides the UX). */
export function indicatorById(id: string): IndicatorDef | undefined {
  return INDICATORS.find((def) => def.id === id);
}

/** Unique category names in registry order (picker groups). */
export function indicatorCategories(): string[] {
  const seen: string[] = [];
  for (const def of INDICATORS) {
    if (!seen.includes(def.category)) seen.push(def.category);
  }
  return seen;
}
