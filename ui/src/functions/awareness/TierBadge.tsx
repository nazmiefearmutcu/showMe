import { TIER_TITLES } from "./format";

/** Publisher tier chip (T1..T5). Text colour steps down with the tier. */
export function TierBadge({ tier }: { tier: number }) {
  const t = Math.min(5, Math.max(1, Math.round(tier) || 5));
  return (
    <span
      className={`aw-tier aw-tier--t${t}`}
      title={TIER_TITLES[t]}
      aria-label={`Tier ${t}`}
    >
      T{t}
    </span>
  );
}
