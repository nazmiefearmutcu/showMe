/**
 * REL-04 P9 — chart-palette MutationObserver lifecycle.
 *
 * Pin the contract:
 *  - The observer is created lazily on the first subscribe.
 *  - The observer is disconnected when the last subscriber unsubscribes
 *    (was a real leak — observer persisted for the entire page lifetime
 *    even with zero listeners).
 *  - A second subscribe after teardown re-creates the observer cleanly.
 */
import { describe, expect, it, afterEach } from "vitest";
import {
  subscribeChartPalette,
  __isChartPaletteObserverActive,
} from "./chart-palette";

describe("chart-palette MutationObserver lifecycle", () => {
  afterEach(() => {
    // Tests assert observer state directly; nothing to clean.
  });

  it("attaches observer on first subscribe and detaches on last unsubscribe", () => {
    expect(__isChartPaletteObserverActive()).toBe(false);
    const off = subscribeChartPalette(() => {});
    expect(__isChartPaletteObserverActive()).toBe(true);
    off();
    expect(__isChartPaletteObserverActive()).toBe(false);
  });

  it("keeps observer attached while any subscriber remains", () => {
    const offA = subscribeChartPalette(() => {});
    const offB = subscribeChartPalette(() => {});
    expect(__isChartPaletteObserverActive()).toBe(true);
    offA();
    expect(__isChartPaletteObserverActive()).toBe(true);
    offB();
    expect(__isChartPaletteObserverActive()).toBe(false);
  });

  it("re-creates observer cleanly after full teardown", () => {
    const off1 = subscribeChartPalette(() => {});
    off1();
    expect(__isChartPaletteObserverActive()).toBe(false);
    const off2 = subscribeChartPalette(() => {});
    expect(__isChartPaletteObserverActive()).toBe(true);
    off2();
    expect(__isChartPaletteObserverActive()).toBe(false);
  });
});
