import type { CSSProperties } from "react";

/**
 * Semicircle Fear & Greed gauge (0-100). Pure SVG; the caller renders the
 * number, rating and delta next to it. Draws nothing for a missing score:
 * callers must pass a finite number and show their own empty state otherwise.
 *
 * Zones (design spec §6): 0-25 extreme fear (negative), 25-45 fear (warn),
 * 45-55 neutral (secondary), 55-75 greed (positive, 55% opacity), 75-100
 * extreme greed (positive).
 */

export type FearGreedZoneKey =
  "extreme-fear" | "fear" | "neutral" | "greed" | "extreme-greed";

export interface FearGreedZone {
  key: FearGreedZoneKey;
  label: string;
  color: string;
  opacity: number;
}

const ZONES: ReadonlyArray<{ upTo: number; zone: FearGreedZone }> = [
  {
    upTo: 25,
    zone: {
      key: "extreme-fear",
      label: "Extreme fear",
      color: "var(--negative)",
      opacity: 1,
    },
  },
  { upTo: 45, zone: { key: "fear", label: "Fear", color: "var(--warn)", opacity: 1 } },
  {
    upTo: 55,
    zone: { key: "neutral", label: "Neutral", color: "var(--text-secondary)", opacity: 1 },
  },
  {
    upTo: 75,
    zone: { key: "greed", label: "Greed", color: "var(--positive)", opacity: 0.55 },
  },
  {
    upTo: 100,
    zone: {
      key: "extreme-greed",
      label: "Extreme greed",
      color: "var(--positive)",
      opacity: 1,
    },
  },
];

function clampScore(score: number): number {
  return Math.max(0, Math.min(100, score));
}

/** Zone for a score. Out-of-range values clamp to the end zones. */
export function fearGreedZone(score: number): FearGreedZone {
  const s = clampScore(score);
  for (const { upTo, zone } of ZONES) {
    if (s < upTo) return zone;
  }
  return ZONES[ZONES.length - 1].zone;
}

/** Needle angle θ = π(1 − score/100), in radians (0 = left end, π/2 = top). */
export function needleAngle(score: number): number {
  return Math.PI * (1 - clampScore(score) / 100);
}

/**
 * Display casing for a provider rating: awareness sends lowercase ("extreme fear"), the zone
 * labels are sentence case. Null for a missing or blank rating.
 */
export function ratingLabel(raw: string | null | undefined): string | null {
  const text = typeof raw === "string" ? raw.trim().toLowerCase() : "";
  if (!text) return null;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "6 Nov 23:59 UTC" from an ISO timestamp; "" when unparseable. */
export function formatUtcStamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${months[d.getUTCMonth()]} ${hh}:${mm} UTC`;
}

/** Signed one-decimal delta with a real minus sign (U+2212). */
export function formatSignedDelta(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "0.0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(1)}`;
}

const VB_W = 200;
const VB_H = 118;
const CX = 100;
const CY = 100;
const R = 84;
const STROKE = 14;
const NEEDLE_LEN = R - 10;
/** Half-width of the visual gap between adjacent zones, in score units. */
const GAP = 0.6;

function pointAt(score: number, radius: number): [number, number] {
  const theta = needleAngle(score);
  return [CX + radius * Math.cos(theta), CY - radius * Math.sin(theta)];
}

function arcPath(from: number, to: number): string {
  const [x0, y0] = pointAt(from, R);
  const [x1, y1] = pointAt(to, R);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${R} ${R} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

export interface FearGreedGaugeProps {
  score: number;
  /** "hero" = 240 x 132 with tick labels; "compact" = 140 x 78 (Welcome); "crypto" = 160 x 88 (MSENT). */
  size?: "hero" | "compact" | "crypto";
  testId?: string;
}

export function FearGreedGauge({ score, size = "compact", testId }: FearGreedGaugeProps) {
  const s = clampScore(score);
  const zone = fearGreedZone(s);
  const [nx, ny] = pointAt(s, NEEDLE_LEN);
  const hero = size === "hero";
  const dims =
    size === "hero"
      ? { w: 240, h: 132 }
      : size === "crypto"
        ? { w: 160, h: 88 }
        : { w: 140, h: 78 };
  const width = dims.w;
  const height = dims.h;
  const ariaLabel = `Fear and Greed gauge at ${Math.round(s)}, ${zone.label.toLowerCase()}`;

  const bounds = [0, ...ZONES.map((z) => z.upTo)];
  return (
    <svg
      data-testid={testId}
      className="aw-gauge"
      width={width}
      height={height}
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      role="img"
      aria-label={ariaLabel}
      focusable="false"
    >
      {ZONES.map(({ zone: z }, i) => {
        const from = bounds[i] + (i === 0 ? 0 : GAP);
        const to = bounds[i + 1] - (i === ZONES.length - 1 ? 0 : GAP);
        return (
          <path
            key={z.key}
            d={arcPath(from, to)}
            fill="none"
            strokeWidth={STROKE}
            strokeLinecap="butt"
            data-zone={z.key}
            style={{ stroke: z.color, strokeOpacity: z.opacity } as CSSProperties}
          />
        );
      })}
      <line
        x1={CX}
        y1={CY}
        x2={nx.toFixed(2)}
        y2={ny.toFixed(2)}
        strokeWidth={2}
        strokeLinecap="round"
        data-testid="fear-greed-needle"
        style={{ stroke: "var(--text-display)" } as CSSProperties}
      />
      <circle
        cx={CX}
        cy={CY}
        r={4}
        style={{ fill: "var(--text-display)" } as CSSProperties}
      />
      {hero ? (
        <g
          aria-hidden="true"
          style={
            {
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              fill: "var(--text-mute)",
            } as CSSProperties
          }
        >
          <text x={CX - R} y={VB_H - 2} textAnchor="middle">
            0
          </text>
          <text x={CX} y={CY - R - STROKE / 2 - 2} textAnchor="middle">
            50
          </text>
          <text x={CX + R} y={VB_H - 2} textAnchor="middle">
            100
          </text>
        </g>
      ) : null}
    </svg>
  );
}
