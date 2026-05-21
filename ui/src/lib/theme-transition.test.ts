/**
 * Recovery S01 — theme-transition runtime guarantees.
 *
 * Captures the regressions that made the post-theme-update shell feel
 * untouchable. The producer (`runThemeTransition`) must:
 *   1. Always fire `THEME_TRANSITION_END` after a `START`, even if the
 *      callback throws or the rAF chain never reaches it.
 *   2. Fire END exactly once per call, regardless of which path
 *      (happy / finally / watchdog) wins the race.
 *   3. Expose a synchronous emergency clear (`forceEndThemeTransition`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  THEME_TRANSITION_END,
  THEME_TRANSITION_FORCE_END,
  THEME_TRANSITION_START,
  THEME_TRANSITION_WATCHDOG_MS,
  __setBypassThemeTransitionForTests,
  forceEndThemeTransition,
  runThemeTransition,
} from "./theme-transition";

function recordEvents(): {
  starts: number;
  ends: number;
  forceEnds: number;
  cleanup: () => void;
} {
  const counters = { starts: 0, ends: 0, forceEnds: 0 };
  const onStart = () => {
    counters.starts += 1;
  };
  const onEnd = () => {
    counters.ends += 1;
  };
  const onForceEnd = () => {
    counters.forceEnds += 1;
  };
  window.addEventListener(THEME_TRANSITION_START, onStart);
  window.addEventListener(THEME_TRANSITION_END, onEnd);
  window.addEventListener(THEME_TRANSITION_FORCE_END, onForceEnd);
  return {
    get starts() {
      return counters.starts;
    },
    get ends() {
      return counters.ends;
    },
    get forceEnds() {
      return counters.forceEnds;
    },
    cleanup: () => {
      window.removeEventListener(THEME_TRANSITION_START, onStart);
      window.removeEventListener(THEME_TRANSITION_END, onEnd);
      window.removeEventListener(THEME_TRANSITION_FORCE_END, onForceEnd);
    },
  };
}

beforeEach(() => {
  // The module defaults to bypass=true under Vitest. Turn it off so the
  // real rAF + setTimeout pipeline runs and we can observe START/END.
  __setBypassThemeTransitionForTests(false);
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "requestAnimationFrame"],
  });
});

afterEach(() => {
  vi.useRealTimers();
  __setBypassThemeTransitionForTests(true);
});

describe("runThemeTransition — happy path", () => {
  it("dispatches START synchronously and END after the planned delay", () => {
    const rec = recordEvents();
    let mutateRan = 0;
    runThemeTransition(() => {
      mutateRan += 1;
    });

    expect(rec.starts).toBe(1);
    expect(rec.ends).toBe(0);
    expect(mutateRan).toBe(0);

    // Two rAF ticks before mutate; jsdom + fake-timers exposes rAF as a
    // setTimeout, so advancing time also drains rAF.
    vi.advanceTimersByTime(50);
    expect(mutateRan).toBe(1);
    expect(rec.ends).toBe(0);

    vi.advanceTimersByTime(350);
    expect(rec.ends).toBe(1);

    // Watchdog timeout would fire at >=1200ms — make sure it's a no-op
    // (no second END) because the planned-end already cleared it.
    vi.advanceTimersByTime(THEME_TRANSITION_WATCHDOG_MS + 200);
    expect(rec.ends).toBe(1);
    rec.cleanup();
  });
});

describe("runThemeTransition — failure paths", () => {
  it("still fires END exactly once when mutate throws", () => {
    const rec = recordEvents();
    runThemeTransition(() => {
      throw new Error("simulated chart-palette fan-out crash");
    });
    expect(rec.starts).toBe(1);

    // Fake-timer rethrows synchronous exceptions from rAF/timeout
    // callbacks. The producer's `try/finally` still scheduled the
    // planned-end timer before the throw escaped — that's exactly the
    // invariant we're testing — so we swallow the expected throw and
    // continue draining.
    expect(() => vi.advanceTimersByTime(50)).toThrow(/simulated/);
    // Drain the planned-end timer that was queued inside `finally`.
    vi.advanceTimersByTime(500);
    expect(rec.ends).toBe(1);

    // Watchdog must NOT fire a second END — `finally`'s end already
    // cleared it.
    vi.advanceTimersByTime(THEME_TRANSITION_WATCHDOG_MS + 200);
    expect(rec.ends).toBe(1);
    rec.cleanup();
  });

  it("watchdog fires END if the rAF chain never reaches mutate", () => {
    // Simulate a backgrounded tab: rAF callbacks never resolve, only
    // setTimeout does. The `toFake` includes rAF so we can suppress it
    // manually by stubbing it out for this single call.
    const rec = recordEvents();
    const realRaf = window.requestAnimationFrame;
    window.requestAnimationFrame = (() => 0) as typeof window.requestAnimationFrame;

    let mutateRan = 0;
    runThemeTransition(() => {
      mutateRan += 1;
    });
    expect(rec.starts).toBe(1);

    // Even though rAF is dead, the watchdog setTimeout still runs.
    vi.advanceTimersByTime(THEME_TRANSITION_WATCHDOG_MS + 50);
    expect(mutateRan).toBe(0);
    expect(rec.ends).toBe(1);

    window.requestAnimationFrame = realRaf;
    rec.cleanup();
  });

  it("forceEndThemeTransition emits FORCE_END synchronously", () => {
    const rec = recordEvents();
    forceEndThemeTransition();
    expect(rec.forceEnds).toBe(1);
    rec.cleanup();
  });
});

describe("runThemeTransition — concurrency", () => {
  it("dispatches matched START/END counts for rapid back-to-back calls", () => {
    const rec = recordEvents();
    runThemeTransition(() => {});
    runThemeTransition(() => {});
    runThemeTransition(() => {});

    expect(rec.starts).toBe(3);
    vi.advanceTimersByTime(THEME_TRANSITION_WATCHDOG_MS + 500);
    expect(rec.ends).toBe(3);
    rec.cleanup();
  });
});
