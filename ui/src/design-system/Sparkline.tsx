/**
 * Sparkline — tiny inline chart for KPI cards and inventory rows.
 *
 * Pure SVG, no deps. Tone defaults to neutral; pass `positive`/`negative`
 * to color it semantically. The path is rendered as an area fill plus a
 * thin stroke; both colors track tokens.
 *
 * ROUND-2B (PERF-09): single-pass min/max instead of `Math.min(...values)`
 * (which blows the stack at ~100k arguments). React.memo so unchanged
 * series do not re-render when the parent does.
 */

import { memo, useMemo } from "react";

type Tone = "neutral" | "positive" | "negative" | "accent";

const STROKE: Record<Tone, string> = {
  neutral: "var(--text-secondary)",
  positive: "var(--positive)",
  negative: "var(--negative)",
  accent: "var(--accent)",
};

const FILL: Record<Tone, string> = {
  neutral: "color-mix(in srgb, var(--text-secondary) 14%, transparent)",
  positive: "var(--positive-soft)",
  negative: "var(--negative-soft)",
  accent: "var(--accent-soft)",
};

function SparklineImpl({
  values,
  width = 80,
  height = 24,
  tone = "neutral",
  ariaLabel,
}: {
  values: number[];
  width?: number;
  height?: number;
  tone?: Tone;
  ariaLabel?: string;
}) {
  const { line, area, summary } = useMemo(() => {
    if (!values.length) return { line: "", area: "", summary: "" };
    // Single pass — avoids stack overflow on large arrays (PERF-09 P1).
    let min = values[0];
    let max = values[0];
    for (let i = 1; i < values.length; i += 1) {
      const v = values[i];
      if (v < min) min = v;
      if (v > max) max = v;
    }
    const span = max - min || 1;
    const step = values.length > 1 ? width / (values.length - 1) : 0;
    const points: Array<readonly [number, number]> = [];
    for (let i = 0; i < values.length; i += 1) {
      const x = i * step;
      const y = height - ((values[i] - min) / span) * (height - 2) - 1;
      points.push([x, y] as const);
    }
    const linePath = points
      .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
      .join(" ");
    const last = points[points.length - 1];
    const first = points[0];
    const areaPath =
      `${linePath} L${last ? last[0].toFixed(1) : 0},${height} ` +
      `L${first ? first[0].toFixed(1) : 0},${height} Z`;
    const lastValue = values[values.length - 1];
    const firstValue = values[0];
    const summaryStr = `${values.length} points, first ${firstValue.toFixed(2)}, last ${lastValue.toFixed(2)}`;
    return { line: linePath, area: areaPath, summary: summaryStr };
  }, [values, width, height]);

  if (!values.length) {
    return <div style={{ width, height }} aria-hidden />;
  }

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel ?? `trend (${summary})`}
      className="u-block"
    >
      <path d={area} fill={FILL[tone]} />
      <path
        d={line}
        fill="none"
        stroke={STROKE[tone]}
        strokeWidth={1.25}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export const Sparkline = memo(SparklineImpl);
