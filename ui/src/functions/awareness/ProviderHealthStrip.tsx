import type { AwarenessProvider, FeedHealth } from "./types";

/**
 * 24px strip under a pane toolbar that tells the trader how fresh the data is.
 *
 * - Normal variant: green/amber/red dots with feed counts (when `feedHealth` is
 *   given) and the newest successful provider update.
 * - Warn variant (any provider degraded/down): keeps the data visible and says
 *   which provider is failing and when the last good update happened.
 */
export interface ProviderHealthStripProps {
  providers?: AwarenessProvider[];
  feedHealth?: FeedHealth;
  generatedAt?: string | null;
  nowMs?: number;
}

function minutesAgo(iso: string, nowMs: number): number | null {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((nowMs - t) / 60000));
}

function hhmmUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

export function ProviderHealthStrip({
  providers = [],
  feedHealth,
  generatedAt,
  nowMs = Date.now(),
}: ProviderHealthStripProps) {
  const failing = providers.filter((p) => p.status === "degraded" || p.status === "down");
  const lastOk = providers
    .map((p) => p.last_ok_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1);

  if (failing.length > 0) {
    const first = failing[0];
    const ago = lastOk ? minutesAgo(lastOk, nowMs) : null;
    return (
      <div className="aw-health aw-health--warn" role="status">
        <span aria-hidden="true">⏱</span>
        <span>
          {lastOk ? `Last good update ${hhmmUtc(lastOk)} UTC${ago !== null ? `, ${ago} min ago` : ""}. ` : ""}
          {first.provider} {first.status === "down" ? "failing" : "degraded"}
          {first.last_error ? `: ${first.last_error}` : ""}
          {failing.length > 1 ? ` (+${failing.length - 1} more)` : ""}
        </span>
      </div>
    );
  }

  return (
    <div className="aw-health" role="status">
      {feedHealth ? (
        <span className="aw-health__feeds">
          <span className="aw-dot aw-dot--ok" aria-hidden="true" /> {feedHealth.ok ?? 0} feeds fresh
          {(feedHealth.degraded ?? 0) + (feedHealth.down ?? 0) > 0 ? (
            <>
              {" · "}
              <span className="aw-dot aw-dot--warn" aria-hidden="true" />{" "}
              {(feedHealth.degraded ?? 0) + (feedHealth.down ?? 0)} stale
            </>
          ) : null}
        </span>
      ) : null}
      {lastOk ? (
        <span className="aw-health__updated">Updated {hhmmUtc(lastOk)} UTC</span>
      ) : generatedAt ? (
        <span className="aw-health__updated">Generated {hhmmUtc(generatedAt)} UTC</span>
      ) : null}
    </div>
  );
}
