/**
 * KAOS Multibot shared badges (frozen contract §D, Lane D 2026-09-09).
 *
 * Small render helpers shared by the BOT / BOTS / PERF panes so the KAOS
 * identity + per-venue lanes read identically everywhere:
 *
 *   - KaosEngineBadge  — "KAOS" chip for records the engine identifies.
 *   - VenueBadges      — one chip per configured venue (crypto / nasdaq),
 *                        rendered ONLY from payload data; hidden when the
 *                        payload carries no venues (honesty contract: hide,
 *                        never fake).
 *   - KaosLaneBanner   — the backend's own lane_status text ("PAPER (no
 *                        Alpaca keys)") shown verbatim ONLY when the
 *                        venue_rows payload proves the NASDAQ lane is paper.
 *
 * Reuses the design-system Pill (single honesty-pill system) and CSS
 * variables — no new tokens, no raw palette values.
 */
import { Pill } from "@/design-system";
import {
  nasdaqLaneStatusText,
  venueLabel,
  venueTitle,
  type BotVenue,
  type KaosLaneRow,
} from "@/lib/kaos-venues";

/** "KAOS" engine chip — marks a record identified as the KAOS Multibot. */
export function KaosEngineBadge() {
  return (
    <span
      data-testid="kaos-engine-badge"
      title="KAOS Multibot — the default engine. One bot scanning crypto + NASDAQ venues."
      style={{ marginLeft: 6, display: "inline-block" }}
    >
      <Pill tone="accent" variant="soft" withDot={false}>
        KAOS
      </Pill>
    </span>
  );
}

/**
 * One chip per configured venue. Renders nothing when `venues` is
 * absent/empty — the supervisor list payload does not carry venues, and an
 * empty chips row must never imply a venue exists.
 */
export function VenueBadges({ venues }: { venues?: BotVenue[] | null }) {
  if (!venues || venues.length === 0) return null;
  return (
    <span
      data-testid="kaos-venue-badges"
      style={{ marginLeft: 6, display: "inline-flex", gap: 4, alignItems: "center" }}
    >
      {venues.map((v) => (
        <span key={v.id} title={venueTitle(v)} style={{ display: "inline-block" }}>
          <Pill tone="neutral" variant="soft" withDot={false}>
            {venueLabel(v)}
          </Pill>
        </span>
      ))}
    </span>
  );
}

/**
 * Honest NASDAQ lane banner. Renders the backend's own `lane_status` text
 * verbatim when the venue_rows payload proves the equities lane is paper
 * (e.g. "PAPER (no Alpaca keys)"). Absent/undecidable/keyed lanes render
 * NOTHING — never a fake all-clear and never a UI-invented label.
 */
export function KaosLaneBanner({ venueRows }: { venueRows?: KaosLaneRow[] | null }) {
  const text = nasdaqLaneStatusText(venueRows);
  if (text == null) return null;
  return (
    <div
      data-testid="kaos-nasdaq-paper-banner"
      role="note"
      aria-label={`NASDAQ lane status: ${text}`}
      style={{
        display: "flex",
        gap: 8,
        alignItems: "center",
        padding: "var(--space-2) var(--space-3)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-sm)",
        background: "var(--surface-2)",
        fontSize: "var(--font-size-sm, 12px)",
        color: "var(--text-secondary)",
      }}
    >
      <Pill tone="warn" variant="soft" withDot>
        {text}
      </Pill>
      <span>
        NASDAQ lane trades paper until a real Alpaca credential is connected;
        the crypto lane is unaffected.
      </span>
    </div>
  );
}
