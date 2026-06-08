/**
 * Shared numeric formatters — single source of truth for the dashboard.
 *
 * All panes should import from here instead of rolling their own
 * `fmtNum` / `fmtCompact` / `fmt$`. Centralisation guarantees that:
 *   - negative currency renders sign-first ("-$1.50B" not "$-1.50B")
 *   - missing values share one sentinel ("—") across every cell
 *   - the percent contract is explicit (fraction vs already-percent)
 *   - sub-cent prices keep their precision instead of collapsing to "$0.00"
 *
 * Background: FUNC-05 quality audit found 13+ ad-hoc formatters across
 * panes with subtly different behaviour. This module replaces them.
 */

/** Em-dash sentinel for missing / not-applicable values. */
export const formatMissing = "—";

const isFiniteNumber = (n: unknown): n is number =>
  typeof n === "number" && Number.isFinite(n);

export interface FormatCurrencyOptions {
  /** Use compact notation ("1.2M", "1.2B") instead of full digits. */
  compact?: boolean;
  /** Override max fractional digits. Defaults to 2 when compact, else 0. */
  fractionDigits?: number;
  /** ISO currency code, defaults to "USD". */
  currency?: string;
}

/**
 * Format a value as currency with the sign before the symbol.
 *
 * Negative values render as `-$1.50B` (NOT `$-1.50B`). NaN / Infinity /
 * null / undefined render as the {@link formatMissing} em-dash.
 */
export function formatCurrency(
  n: number | null | undefined,
  opts: FormatCurrencyOptions = {},
): string {
  if (!isFiniteNumber(n)) return formatMissing;
  const { compact = false, fractionDigits, currency = "USD" } = opts;
  const digits = fractionDigits ?? (compact ? 2 : 0);
  const fmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
  // Intl emits "$-1.50B" by default; we want "-$1.50B".
  if (n < 0) return `-${fmt.format(Math.abs(n))}`;
  return fmt.format(n);
}

export interface FormatCompactOptions {
  /**
   * Force a fixed number of fractional digits (both min and max). Use this
   * for grid columns that must not jitter as magnitudes change — e.g. a
   * volume column rendering "3.50M" / "1.20B" with stable width. When
   * omitted, trailing zeros are trimmed ("3.5M").
   */
  fixedDigits?: number;
}

/**
 * Format a number using compact notation with up to 2 decimals.
 * Used for volumes, counts, and other non-currency magnitudes.
 */
export function formatCompactNumber(
  n: number | null | undefined,
  opts: FormatCompactOptions = {},
): string {
  if (!isFiniteNumber(n)) return formatMissing;
  const { fixedDigits } = opts;
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: fixedDigits ?? 2,
    ...(fixedDigits != null ? { minimumFractionDigits: fixedDigits } : {}),
  }).format(n);
}

export type FormatSignedCurrencyOptions = FormatCurrencyOptions;

/**
 * Currency with an explicit leading "+" / "-" sign. Wraps
 * {@link formatCurrency} so leader/laggard and 1D-notional cells share one
 * rounding + sentinel contract. Zero renders without a sign.
 */
export function formatSignedCurrency(
  n: number | null | undefined,
  opts: FormatSignedCurrencyOptions = {},
): string {
  if (!isFiniteNumber(n)) return formatMissing;
  if (n === 0) return formatCurrency(0, opts);
  const sign = n > 0 ? "+" : "-";
  return `${sign}${formatCurrency(Math.abs(n), opts)}`;
}

export interface FormatPercentOptions {
  /** Multiply input by 100 first (e.g. for raw 0.42 → "42.00%"). */
  fromFraction?: boolean;
  /** Force a leading "+" / "-" sign (no leading "+" by default). */
  signed?: boolean;
  /** Decimal digits, defaults to 2. */
  digits?: number;
}

/** Format a percentage with explicit fraction-vs-percent contract. */
export function formatPercent(
  n: number | null | undefined,
  opts: FormatPercentOptions = {},
): string {
  if (!isFiniteNumber(n)) return formatMissing;
  const { fromFraction = false, signed = false, digits = 2 } = opts;
  const value = fromFraction ? n * 100 : n;
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

/**
 * Render a number with an explicit `+` / `-` sign and fixed precision.
 * Zero renders as `"0.00"` (no sign). Used by leader/laggard cards
 * where the sign carries meaning.
 */
export function formatSignedDelta(
  n: number | null | undefined,
  digits = 2,
): string {
  if (!isFiniteNumber(n)) return formatMissing;
  if (n === 0) return (0).toFixed(digits);
  const sign = n > 0 ? "+" : "-";
  return `${sign}${Math.abs(n).toFixed(digits)}`;
}

/**
 * Adaptive price formatter — keeps precision on sub-dollar assets
 * (penny stocks, sat-denominated crypto, FX micro-pairs) without
 * collapsing them to "0.00".
 */
export function formatPrice(n: number | null | undefined): string {
  if (!isFiniteNumber(n)) return formatMissing;
  const a = Math.abs(n);
  if (a === 0) return (0).toFixed(2);
  if (a >= 1) return n.toFixed(2);
  if (a >= 0.01) return n.toFixed(4);
  if (a >= 0.0001) return n.toFixed(6);
  // Ultra-small: scientific notation keeps the magnitude readable.
  return n.toExponential(2);
}

/** Format a number with locale-en-US thousands separators, no currency. */
export function formatNumber(
  n: number | null | undefined,
  fractionDigits = 0,
): string {
  if (!isFiniteNumber(n)) return formatMissing;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: fractionDigits,
    minimumFractionDigits: 0,
  }).format(n);
}
