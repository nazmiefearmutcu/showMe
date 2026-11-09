/**
 * Three-dot importance meter for economic events (1 = low, 2 = medium, 3 = high).
 *
 * Colour is never the only cue: the level is carried by the accessible name
 * ("High importance") and the number of filled dots.
 */
export type ImportanceLevel = 1 | 2 | 3;

export interface ImportanceDotsProps {
  importance: number | string | null | undefined;
}

export function importanceLevel(
  value: ImportanceDotsProps["importance"],
): ImportanceLevel | null {
  if (typeof value === "string" && value.trim() === "") return null;
  const n = typeof value === "string" ? Number(value.trim()) : value;
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  const rounded = Math.round(n);
  if (rounded <= 1) return 1;
  if (rounded >= 3) return 3;
  return 2;
}

const LABELS: Record<ImportanceLevel, string> = {
  3: "High importance",
  2: "Medium importance",
  1: "Low importance",
};

export function ImportanceDots({ importance }: ImportanceDotsProps) {
  const level = importanceLevel(importance);
  const label = level == null ? "Importance not reported" : LABELS[level];
  const onClass =
    level === 3 ? "aw-imp__dot aw-imp__dot--high" : "aw-imp__dot aw-imp__dot--on";
  return (
    <span className="aw-imp" role="img" aria-label={label} title={label}>
      {[1, 2, 3].map((slot) => (
        <span
          key={slot}
          aria-hidden="true"
          className={
            level != null && slot <= level ? onClass : "aw-imp__dot aw-imp__dot--off"
          }
        />
      ))}
    </span>
  );
}
