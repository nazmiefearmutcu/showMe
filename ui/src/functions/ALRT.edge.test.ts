/**
 * ALRT edge state and fire cooldown (P2a-g05, ALRT#5).
 *
 * Pure helpers, no network. Covers two review findings: a stale observation
 * (a REST snapshot fetched before a newer live tick) must not move the edge
 * state backwards, and an alert fired by one evaluation must stay in cooldown
 * for an overlapping evaluation even before the rows state has caught up.
 */
import { describe, expect, it } from "vitest";
import { isInFireCooldown, observeAlertEdge } from "./ALRT";

describe("observeAlertEdge", () => {
  it("fires once on a genuine above-edge and records the observation", () => {
    const seen = new Map();
    expect(observeAlertEdge(seen, "a", "above", 200, 195, 1000).newTrigger).toBe(false);
    const hit = observeAlertEdge(seen, "a", "above", 200, 201, 2000);
    expect(hit.newTrigger).toBe(true);
    expect(hit.stale).toBe(false);
    expect(seen.get("a")).toEqual({ value: 201, at: 2000 });
  });

  it("ignores a reading older than the newest recorded observation", () => {
    const seen = new Map();
    observeAlertEdge(seen, "a", "above", 200, 195, 1000);
    observeAlertEdge(seen, "a", "above", 200, 205, 3000); // live tick, edge
    // A REST snapshot fetched before that tick reports the old, lower price.
    const late = observeAlertEdge(seen, "a", "above", 200, 195, 2000);
    expect(late).toEqual({ newTrigger: false, stale: true });
    expect(seen.get("a")).toEqual({ value: 205, at: 3000 });
    // The next genuine tick must not re-fire as if the price had just crossed.
    const next = observeAlertEdge(seen, "a", "above", 200, 206, 4000);
    expect(next.newTrigger).toBe(false);
  });

  it("keeps the last value when an observation carries no number", () => {
    const seen = new Map();
    observeAlertEdge(seen, "a", "cross_up", 200, 190, 1000);
    observeAlertEdge(seen, "a", "cross_up", 200, null, 2000);
    expect(seen.get("a")).toEqual({ value: 190, at: 1000 });
    expect(observeAlertEdge(seen, "a", "cross_up", 200, 205, 3000).newTrigger).toBe(true);
  });
});

describe("isInFireCooldown", () => {
  const now = Date.parse("2026-11-08T12:00:00Z");

  it("honours the persisted last_fired_at", () => {
    expect(isInFireCooldown(new Date(now - 60_000).toISOString(), undefined, now)).toBe(true);
    expect(isInFireCooldown(new Date(now - 10 * 60_000).toISOString(), undefined, now)).toBe(false);
  });

  it("honours a fire that is still in flight although rows have not refreshed", () => {
    // rows still say the alert never fired; this pane fired it 100 ms ago.
    expect(isInFireCooldown(null, now - 100, now)).toBe(true);
  });

  it("is not in cooldown when neither source has a fire", () => {
    expect(isInFireCooldown(null, undefined, now)).toBe(false);
  });
});
