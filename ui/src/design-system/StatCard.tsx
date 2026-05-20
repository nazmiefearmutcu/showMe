/**
 * StatCard — KPI hero with delta + sparkline + caption.
 *
 * Used by Welcome ribbon, by per-pane KPI strips (PORT/HP/GP), and by
 * any surface that wants the "big number, tiny trend" pattern. Keeps
 * spacing under control via tokens; padding is generous (16-20px).
 *
 * Round-4A: lifted from inline `style` to the `.stat-card*` token classes
 * in `src/styles/index.css`.
 */

import { memo, type ReactNode } from "react";
import { DeltaChip } from "./DeltaChip";
import { Sparkline } from "./Sparkline";

type Tone = "neutral" | "positive" | "negative";

function StatCardImpl({
  label,
  value,
  caption,
  delta,
  deltaFormat = "percent",
  trend,
  tone = "neutral",
  rightSlot,
}: {
  label: string;
  value: ReactNode;
  caption?: ReactNode;
  delta?: number;
  deltaFormat?: "percent" | "currency" | "raw";
  trend?: number[];
  tone?: Tone;
  rightSlot?: ReactNode;
}) {
  const sparkTone =
    tone === "positive" ? "positive" : tone === "negative" ? "negative" : "neutral";

  return (
    <div className={`stat-card stat-card--${tone}`}>
      <div className="stat-card__head">
        <span className="stat-card__label">{label}</span>
        {rightSlot}
      </div>
      <div className="stat-card__value-row">
        <span className="stat-card__value">{value}</span>
        {trend && trend.length > 1 && (
          <span className="stat-card__spark">
            <Sparkline values={trend} width={64} height={22} tone={sparkTone} />
          </span>
        )}
      </div>
      <div className="stat-card__meta">
        {typeof delta === "number" && (
          <DeltaChip value={delta} format={deltaFormat} />
        )}
        {caption && <span className="stat-card__caption">{caption}</span>}
      </div>
    </div>
  );
}

export const StatCard = memo(StatCardImpl);
