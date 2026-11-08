import type { CSSProperties } from "react";

/**
 * Entity sentiment per time bucket: one bar per bucket, up (positive mean) in
 * `--positive`, down (negative mean) in `--negative`, height proportional to
 * |mean| against the largest bucket in view. An optional GDELT tone polyline
 * is drawn on its own scale. A bucket with a null mean is left blank, never
 * defaulted to zero.
 *
 * Bars and tone share one time axis: each bucket is centred on its timestamp
 * and each tone sample is placed by its own timestamp, so the two series line
 * up in time. Sample counts may differ; position never comes from the index.
 */
export interface SentimentBucket {
  ts: string;
  mean: number | null | undefined;
}

export interface ToneSample {
  ts: string;
  value: number | null | undefined;
}

export interface SentimentBarsProps {
  series: SentimentBucket[];
  tone?: ToneSample[];
  ariaLabel: string;
  height?: number;
  /** Legend text for the tone line; callers state the scale they use. */
  toneLabel?: string;
}

const W = 400;
const PAD = 6;
const HOUR_MS = 3_600_000;

function finite(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Smallest positive gap between consecutive sorted times, or undefined. */
function smallestGap(sorted: number[]): number | undefined {
  let gap: number | undefined;
  for (let i = 1; i < sorted.length; i += 1) {
    const d = sorted[i] - sorted[i - 1];
    if (d > 0 && (gap === undefined || d < gap)) gap = d;
  }
  return gap;
}

export function SentimentBars({
  series,
  tone,
  ariaLabel,
  height = 120,
  toneLabel = "GDELT tone (own scale)",
}: SentimentBarsProps) {
  const mid = height / 2;
  const half = mid - PAD;
  const maxAbs = series.reduce(
    (m, b) => (finite(b.mean) ? Math.max(m, Math.abs(b.mean)) : m),
    0,
  );

  const toneList = tone ?? [];
  const toneMax = toneList.reduce(
    (m, t) => (finite(t.value) ? Math.max(m, Math.abs(t.value)) : m),
    0,
  );

  // Shared time axis: spans every bucket and tone sample, padded by half a bucket
  // so the outer bars sit inside the plot.
  const bucketMs = series.map((b) => Date.parse(b.ts));
  const toneMs = toneList.map((t) => Date.parse(t.ts));
  const bucketTimes = bucketMs.filter((ms) => Number.isFinite(ms)).sort((a, b) => a - b);
  const allTimes = [...bucketTimes, ...toneMs.filter((ms) => Number.isFinite(ms))];
  const slotMs = smallestGap(bucketTimes) ?? HOUR_MS;
  const lo = allTimes.length > 0 ? Math.min(...allTimes) : 0;
  const hi = allTimes.length > 0 ? Math.max(...allTimes) : 0;
  const t0 = lo - slotMs / 2;
  const span = hi - lo + slotMs;
  const xOf = (ms: number) => ((ms - t0) / span) * W;
  const barW = Math.max(2, (slotMs / span) * W * 0.6);

  const tonePoints = toneList
    .map((t, i) => ({ ms: toneMs[i], value: t.value }))
    .filter(
      (p): p is { ms: number; value: number } => finite(p.value) && Number.isFinite(p.ms),
    )
    .sort((a, b) => a.ms - b.ms)
    .map((p) => {
      const x = xOf(p.ms);
      const y = toneMax > 0 ? mid - (p.value / toneMax) * half : mid;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="aw-bars">
      <svg
        className="aw-bars__svg"
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={ariaLabel}
        focusable="false"
        style={{ height }}
      >
        <line
          x1={0}
          x2={W}
          y1={mid}
          y2={mid}
          strokeWidth={1}
          style={{ stroke: "var(--border-strong)" } as CSSProperties}
        />
        {series.map((b, i) => {
          const ms = bucketMs[i];
          if (!finite(b.mean) || maxAbs === 0 || !Number.isFinite(ms)) return null;
          const h = (Math.abs(b.mean) / maxAbs) * half;
          const x = xOf(ms) - barW / 2;
          const up = b.mean > 0;
          const y = up ? mid - h : mid;
          const fill =
            b.mean === 0 ? "var(--text-mute)" : up ? "var(--positive)" : "var(--negative)";
          return (
            <rect
              key={`${b.ts}-${i}`}
              x={x.toFixed(1)}
              y={y.toFixed(1)}
              width={barW.toFixed(1)}
              height={Math.max(h, 0.5).toFixed(1)}
              data-direction={b.mean > 0 ? "up" : b.mean < 0 ? "down" : "flat"}
              style={{ fill } as CSSProperties}
            />
          );
        })}
        {tonePoints ? (
          <polyline
            points={tonePoints}
            fill="none"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
            data-testid="gdelt-tone-line"
            style={{ stroke: "var(--accent-2)" } as CSSProperties}
          />
        ) : null}
      </svg>
      {tonePoints ? (
        <div className="aw-bars__legend">
          <span aria-hidden="true">▲▼ news mean</span>
          <span aria-hidden="true">— {toneLabel}</span>
        </div>
      ) : null}
    </div>
  );
}
