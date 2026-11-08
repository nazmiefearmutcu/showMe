export interface ImportanceMeterProps {
  importance: number | null | undefined;
}

/** Four bars, filled = ceil(importance / 25). Warn colour at >= 70. */
export function ImportanceMeter({ importance }: ImportanceMeterProps) {
  if (importance === null || importance === undefined || Number.isNaN(importance))
    return null;
  const value = Math.max(0, Math.min(100, Math.round(importance)));
  const filled = Math.ceil(value / 25);
  const hot = value >= 70;
  return (
    <span
      className={`aw-imp${hot ? " aw-imp--hot" : ""}`}
      title={`Importance ${value} of 100`}
      aria-label={`Importance ${value} of 100`}
    >
      <span className="aw-imp__bars" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className={`aw-imp__bar${i < filled ? " aw-imp__bar--on" : ""}`} />
        ))}
      </span>
      <span className="aw-imp__value">{value}</span>
    </span>
  );
}
