import type { CSSProperties } from "react";

/**
 * VIX term structure: VIX9D, VIX and VIX3M joined by a line, labelled with
 * their values. A VIX9D point above spot is drawn in the warn colour: near-term
 * event risk. Missing points are omitted, never filled in.
 */
export interface TermStructureChartProps {
  vix9d: number | null | undefined;
  vix: number | null | undefined;
  vix3m: number | null | undefined;
}

interface Point {
  label: "VIX9D" | "VIX" | "VIX3M";
  value: number;
  slot: number;
}

const W = 280;
const H = 120;
const TOP = 22;
const BOTTOM = 96;
const SLOTS = [40, 140, 240];

function finite(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function nearTermAboveSpot(
  vix9d: number | null | undefined,
  vix: number | null | undefined,
): boolean {
  return finite(vix9d) && finite(vix) && vix9d > vix;
}

export function TermStructureChart({ vix9d, vix, vix3m }: TermStructureChartProps) {
  const raw: Array<{
    label: Point["label"];
    value: number | null | undefined;
    slot: number;
  }> = [
    { label: "VIX9D", value: vix9d, slot: 0 },
    { label: "VIX", value: vix, slot: 1 },
    { label: "VIX3M", value: vix3m, slot: 2 },
  ];
  const points: Point[] = raw
    .filter((r): r is { label: Point["label"]; value: number; slot: number } =>
      finite(r.value),
    )
    .map((r) => ({ label: r.label, value: r.value, slot: r.slot }));

  if (points.length < 2) {
    return (
      <p className="aw-ts__empty" role="note">
        Not enough VIX points to draw the term structure.
      </p>
    );
  }

  const values = points.map((p) => p.value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const yOf = (v: number) => TOP + ((hi - v) / span) * (BOTTOM - TOP);
  const xOf = (p: Point) => SLOTS[p.slot];
  const warn = nearTermAboveSpot(vix9d, vix);

  const line = points.map((p) => `${xOf(p)},${yOf(p.value).toFixed(1)}`).join(" ");
  const ariaLabel = `VIX term structure: ${points
    .map((p) => `${p.label} ${p.value.toFixed(2)}`)
    .join(", ")}`;

  return (
    <svg
      className="aw-ts"
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={ariaLabel}
      focusable="false"
    >
      <polyline
        points={line}
        fill="none"
        strokeWidth={1.5}
        style={{ stroke: "var(--text-primary)" } as CSSProperties}
      />
      {points.map((p) => {
        const isWarn = p.label === "VIX9D" && warn;
        const cy = yOf(p.value);
        return (
          <g key={p.label}>
            <circle
              cx={xOf(p)}
              cy={cy}
              r={3.5}
              data-warn={isWarn ? "true" : undefined}
              style={
                { fill: isWarn ? "var(--warn)" : "var(--text-primary)" } as CSSProperties
              }
            />
            <text
              x={xOf(p)}
              y={cy - 8}
              textAnchor="middle"
              style={
                {
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  fill: "var(--text-primary)",
                } as CSSProperties
              }
            >
              {p.value.toFixed(2)}
            </text>
            <text
              x={xOf(p)}
              y={H - 4}
              textAnchor="middle"
              style={
                {
                  fontFamily: "var(--font-mono)",
                  fontSize: 9,
                  fill: "var(--text-mute)",
                } as CSSProperties
              }
            >
              {p.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
