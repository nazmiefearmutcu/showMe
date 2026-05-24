/**
 * Regression — audit S2 dead-code ternary.
 *
 * `withSnapshotError` previously did:
 *     loading: state.snapshot ? false : false
 *
 * Both branches of the ternary returned `false`, so the very-first-fetch
 * error never flipped `loading` to a meaningful value — and because
 * `toView`'s loading rule is `state.loading && state.snapshot == null
 * && state.lastTick == null`, the row stayed visually loading even when
 * the snapshot fetch had already errored.
 *
 * Fix sets `loading` to true only when we have NEITHER a previous snapshot
 * NOR a live tick — i.e. there is genuinely nothing to show yet. That way
 * the view exposes the error AND can offer a retry CTA.
 */
import { describe, expect, it } from "vitest";
import { __internal } from "./market-data";
import type { QuoteSnapshot } from "./quotes";

const { withSnapshotError } = __internal;

function baseState(over: Partial<Parameters<typeof withSnapshotError>[0]> = {}) {
  return {
    symbol: "AAPL",
    snapshot: null,
    snapshotAt: null,
    lastTick: null,
    lastTickAt: null,
    loading: true,
    refreshing: false,
    error: null,
    transportState: "idle" as const,
    ...over,
  };
}

const SNAP: QuoteSnapshot = {
  symbol: "AAPL",
  asset_class: "EQUITY",
  last: 100,
  price: 100,
  previous_close: null,
  change_pct: null,
  volume: null,
  bid: null,
  ask: null,
  source: "yahoo_chart",
  provider_symbol: "AAPL",
  fetched_at: new Date().toISOString(),
} as unknown as QuoteSnapshot;

describe("market-data withSnapshotError loading state (audit S2)", () => {
  it("keeps loading=true when no snapshot AND no tick (first-fetch failure)", () => {
    const next = withSnapshotError(baseState(), new Error("boom"));
    // Before the fix this was incorrectly false in BOTH branches; the
    // expectation is that with nothing to show we tell the view to render
    // its loading skeleton OR error state — never the false-positive
    // "we have data" state.
    expect(next.loading).toBe(true);
    expect(next.error).toBe("boom");
    expect(next.snapshot).toBeNull();
    expect(next.lastTick).toBeNull();
    expect(next.refreshing).toBe(false);
  });

  it("flips loading=false when a prior snapshot is on screen", () => {
    const next = withSnapshotError(
      baseState({ snapshot: SNAP, snapshotAt: 1 }),
      new Error("boom"),
    );
    expect(next.loading).toBe(false);
    expect(next.snapshot).toBe(SNAP); // last-good preserved
    expect(next.error).toBe("boom");
  });

  it("flips loading=false when a prior tick is on screen", () => {
    const next = withSnapshotError(
      baseState({ lastTick: { price: 100 } as never, lastTickAt: 1 }),
      new Error("boom"),
    );
    expect(next.loading).toBe(false);
    expect(next.lastTick).not.toBeNull();
    expect(next.error).toBe("boom");
  });

  it("string errors are stringified, Error.message is taken verbatim, null falls back", () => {
    const fromErr = withSnapshotError(baseState(), new Error("a"));
    const fromStr = withSnapshotError(baseState(), "b");
    const fromNull = withSnapshotError(baseState(), null);
    expect(fromErr.error).toBe("a");
    expect(fromStr.error).toBe("b");
    // null / undefined values fall back to the canonical "snapshot error".
    expect(fromNull.error).toBe("snapshot error");
  });
});
