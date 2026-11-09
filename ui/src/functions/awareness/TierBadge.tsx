import { TIER_TITLES } from "./format";

/**
 * Publisher tier chip (T1..T5). Text colour steps down with the tier. A tier that is
 * missing or outside 1..5 is shown as "T?": it is unknown, not a tier 5 classification.
 */
export function TierBadge({ tier }: { tier: number | null | undefined }) {
  const known =
    typeof tier === "number" && Number.isFinite(tier) && tier >= 1 && tier <= 5
      ? Math.round(tier)
      : null;
  if (known === null) {
    return (
      <span className="aw-tier aw-tier--unknown" aria-label="Tier unknown">
        T?
      </span>
    );
  }
  return (
    <span
      className={`aw-tier aw-tier--t${known}`}
      title={TIER_TITLES[known]}
      aria-label={`Tier ${known}`}
    >
      T{known}
    </span>
  );
}
