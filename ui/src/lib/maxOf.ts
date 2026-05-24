/**
 * UA-CRITICAL-01 / OVERFLOW-01 — stack-safe min/max/maxAbs helpers.
 *
 * `Math.max(...arr)` and `Math.min(...arr)` blow the call stack on arrays
 * beyond ~100k entries (engine-dependent: V8 sometimes optimizes, sometimes
 * throws `RangeError: Maximum call stack size exceeded`). Real chart series
 * routinely cross that threshold (1m intraday over a year is ~400k bars).
 *
 * These helpers are O(n) with constant stack use. Match Math.max/Math.min
 * contract for empty arrays (returns -Infinity / +Infinity respectively).
 */

export function maxOf(values: readonly number[]): number {
  let max = -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (v > max) max = v;
  }
  return max;
}

export function minOf(values: readonly number[]): number {
  let min = Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (v < min) min = v;
  }
  return min;
}

/**
 * Returns the maximum absolute value across `values`, never below `floor`.
 * Used by zero-centered chart series (PnL, returns, deltas) to keep at least
 * a minimum visible band.
 */
export function maxAbsOf(values: readonly number[], floor = 0): number {
  let max = floor;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    const abs = v < 0 ? -v : v;
    if (abs > max) max = abs;
  }
  return max;
}
