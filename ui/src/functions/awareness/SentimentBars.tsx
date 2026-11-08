import type { CSSProperties } from "react";

/**
 * Entity sentiment per time bucket: one bar per bucket, up (positive mean) in
 * `--positive`, down (negative mean) in `--negative`, height proportional to
 * |mean| against the largest bucket in view. An optional GDELT tone polyline
 * is drawn on its own scale. A bucket with a null mean is left blank, never
 * defaulted to zero.
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

function finite(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function SentimentBars({
  series,
  tone,
  ariaLabel,
  height = 120,
  toneLabel = "GDELT tone (own scale)",
}: SentimentBarsProps) {
  const n = series.length;
  const mid = height / 2;
  const half = mid - PAD;
  const maxAbs = series.reduce(
    (m, b) => (finite(b.mean) ? Math.max(m, Math.abs(b.mean)) : m),
    0,
  );
  const slot = n > 0 ? W / n : W;
  const barW = Math.max(2, slot * 0.6);

  const toneList = tone ?? [];
  const toneMax = toneList.reduce(
    (m, t) => (finite(t.value) ? Math.max(m, Math.abs(t.value)) : m),
    0,
  );
  const toneStep = W / Math.max(toneList.length, 1);
  const tonePoints = toneList
    .map((t, i) => {
      if (!finite(t.value)) return null;
      const x = (i + 0.5) * toneStep;
      const y = toneMax > 0 ? mid - (t.value / toneMax) * half : mid;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter((p): p is string => p !== null)
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
          if (!finite(b.mean) || maxAbs === 0) return null;
          const h = (Math.abs(b.mean) / maxAbs) * half;
          const x = i * slot + (slot - barW) / 2;
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
      {tone ? (
        <div className="aw-bars__legend">
          <span aria-hidden="true">▲▼ news mean</span>
          <span aria-hidden="true">— {toneLabel}</span>
        </div>
      ) : null}
    </div>
  );
}
