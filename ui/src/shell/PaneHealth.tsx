/**
 * PaneHealth — inline data-health chip for the pane chrome
 * (campaign 2026-09-11, Lane L4).
 *
 * Per-pane provenance used to live only inside a `title` tooltip on the
 * contract strip. This chip puts the three facts a desk can act on —
 * tier (dot), as-of age, latency — on screen, and keeps the exact
 * timestamp, source list, and warnings one hover/click away.
 *
 * Honesty contract:
 *   - no contract snapshot → render NOTHING (no placeholder dot, no "—");
 *   - the tier is derived by the frozen store selectors, never guessed here;
 *   - age is recomputed every second (visibility-aware tick) so a stalled
 *     feed visibly ages instead of freezing at its last label.
 *
 * Can be mounted with an explicit `contract` (INT passes the snapshot
 * PaneChrome already holds) or with `leafId`, in which case the bound
 * (code, symbol) is resolved from the workspace tree and the contract is
 * read from the store.
 */
import "@/styles/pane-health.css";
import { useId, useState } from "react";
import {
  formatLatencyMs,
  paneAgeMs,
  paneHealthTier,
  paneStampedAt,
  usePaneContract,
  type PaneContract,
  type PaneHealthTier,
} from "@/lib/pane-contract-store";
import { formatTickAge } from "@/lib/tape-health";
import { findLeaf, useWorkspace } from "@/lib/workspace";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { formatDate, formatTime, useTimezone } from "@/lib/timezone";

export interface PaneHealthProps {
  /** Workspace leaf to resolve (code, symbol) from when no contract passed. */
  leafId?: string;
  /** Direct contract snapshot — wins over leaf lookup when provided. */
  contract?: PaneContract;
}

const TIER_LABEL: Record<PaneHealthTier, string> = {
  live: "LIVE",
  degraded: "DEGRADED",
  stale: "STALE",
};

export function PaneHealth({ leafId, contract }: PaneHealthProps) {
  const tree = useWorkspace((s) => s.tree);
  const leaf = leafId ? findLeaf(tree, leafId) : null;
  const storeContract = usePaneContract(leaf?.code ?? "", leaf?.symbol);
  const snap = contract ?? storeContract;
  const [open, setOpen] = useState(false);
  const tz = useTimezone();
  const popoverId = useId();
  // Re-render every second (pauses while the tab is hidden) so the as-of
  // age is always the CURRENT age of the shown contract.
  useVisibilityTick(1000);

  if (!snap) return null;

  const now = Date.now();
  const tier = paneHealthTier(snap, now);
  const age = formatTickAge(paneAgeMs(snap, now));
  const latency =
    typeof snap.latencyMs === "number" && Number.isFinite(snap.latencyMs)
      ? formatLatencyMs(snap.latencyMs)
      : null;
  const stampedMs = paneStampedAt(snap);
  const exactStamp = `${formatDate(stampedMs, { tz })} ${formatTime(stampedMs, { tz, seconds: true })}`;
  const mode = typeof snap.dataMode === "string" && snap.dataMode ? snap.dataMode : "—";
  const sources = snap.sources ?? [];
  const warnings = snap.warnings ?? [];

  const summary = `Data ${TIER_LABEL[tier]} · as of ${age} ago${latency ? ` · ${latency}` : ""}`;

  return (
    <span className="pane-health" data-testid="pane-health">
      <button
        type="button"
        className={`pane-health__chip pane-health__chip--${tier}`}
        data-tier={tier}
        aria-expanded={open}
        aria-describedby={open ? popoverId : undefined}
        aria-label={summary}
        title={summary}
        onClick={() => setOpen(true)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        <span aria-hidden className={`pane-health__dot pane-health__dot--${tier}`} />
        <span className="pane-health__age">{age}</span>
        {latency && <span className="pane-health__latency">{latency}</span>}
      </button>
      {open && (
        <span
          className="pane-health__popover"
          id={popoverId}
          role="tooltip"
          data-testid="pane-health-popover"
        >
          <span className="pane-health__row">
            <span className="pane-health__key">data</span>
            <span className={`pane-health__tier pane-health__tier--${tier}`}>
              {TIER_LABEL[tier]}
            </span>
          </span>
          <span className="pane-health__row" data-testid="pane-health-asof">
            <span className="pane-health__key">as of</span>
            <span className="pane-health__value">{exactStamp}</span>
          </span>
          <span className="pane-health__row">
            <span className="pane-health__key">mode</span>
            <span className="pane-health__value">{mode}</span>
          </span>
          {latency && (
            <span className="pane-health__row">
              <span className="pane-health__key">latency</span>
              <span className="pane-health__value">{latency}</span>
            </span>
          )}
          {sources.length > 0 && (
            <span className="pane-health__row" data-testid="pane-health-sources">
              <span className="pane-health__key">source{sources.length > 1 ? "s" : ""}</span>
              <span className="pane-health__value">{sources.join(", ")}</span>
            </span>
          )}
          {warnings.length > 0 && (
            <span className="pane-health__row pane-health__row--warn" data-testid="pane-health-warnings">
              <span className="pane-health__key">warnings</span>
              <span className="pane-health__value">{warnings.join(" · ")}</span>
            </span>
          )}
        </span>
      )}
    </span>
  );
}
