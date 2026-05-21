/**
 * Recovery S01 — ThemeTransitionOverlay invariants.
 *
 * These tests would have caught the post-theme-update "shell feels
 * untouchable" regression. They cover:
 *   1. Overlay self-clears via the lifetime watchdog if no END arrives.
 *   2. `THEME_TRANSITION_FORCE_END` immediately tears the overlay down.
 *   3. CSS guarantees the brief overlay never blocks input — even mid-
 *      transition the workspace is reachable.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { ThemeTransitionOverlay, MAX_OVERLAY_LIFETIME_MS } from "@/shell/ThemeTransitionOverlay";
import {
  THEME_TRANSITION_END,
  THEME_TRANSITION_FORCE_END,
  THEME_TRANSITION_START,
} from "@/lib/theme-transition";

const __dirname = dirname(fileURLToPath(import.meta.url));
const indexCssRaw = readFileSync(
  resolve(__dirname, "..", "styles", "index.css"),
  "utf-8",
);

function dispatch(name: string): void {
  window.dispatchEvent(new CustomEvent(name));
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ThemeTransitionOverlay — render gating", () => {
  it("renders nothing by default", () => {
    const { queryByTestId } = render(<ThemeTransitionOverlay />);
    expect(queryByTestId("theme-transition-overlay")).toBeNull();
  });

  it("mounts on START and unmounts after the leave keyframe", () => {
    const { queryByTestId } = render(<ThemeTransitionOverlay />);
    act(() => {
      dispatch(THEME_TRANSITION_START);
    });
    expect(queryByTestId("theme-transition-overlay")).toBeTruthy();
    expect(queryByTestId("theme-transition-overlay")?.getAttribute("data-phase")).toBe(
      "expanding",
    );

    act(() => {
      dispatch(THEME_TRANSITION_END);
    });
    // Leaving phase visible immediately.
    expect(queryByTestId("theme-transition-overlay")?.getAttribute("data-phase")).toBe(
      "leaving",
    );

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(queryByTestId("theme-transition-overlay")).toBeNull();
  });
});

describe("ThemeTransitionOverlay — recovery hardening", () => {
  it("self-clears via the lifetime watchdog when END never arrives", () => {
    const { queryByTestId } = render(<ThemeTransitionOverlay />);
    act(() => {
      dispatch(THEME_TRANSITION_START);
    });
    expect(queryByTestId("theme-transition-overlay")).toBeTruthy();

    // Simulate a stranded transition — no END is ever dispatched.
    act(() => {
      vi.advanceTimersByTime(MAX_OVERLAY_LIFETIME_MS + 50);
    });
    expect(queryByTestId("theme-transition-overlay")).toBeNull();
  });

  it("THEME_TRANSITION_FORCE_END synchronously hides the overlay", () => {
    const { queryByTestId } = render(<ThemeTransitionOverlay />);
    act(() => {
      dispatch(THEME_TRANSITION_START);
      dispatch(THEME_TRANSITION_START);
    });
    expect(queryByTestId("theme-transition-overlay")).toBeTruthy();

    act(() => {
      dispatch(THEME_TRANSITION_FORCE_END);
    });
    // No timers needed — force-end is synchronous.
    expect(queryByTestId("theme-transition-overlay")).toBeNull();
  });

  it("re-arms the watchdog on every START so rapid presses still recover", () => {
    const { queryByTestId } = render(<ThemeTransitionOverlay />);
    act(() => {
      dispatch(THEME_TRANSITION_START);
    });
    act(() => {
      vi.advanceTimersByTime(MAX_OVERLAY_LIFETIME_MS - 100);
    });
    // Second START re-arms the watchdog — overlay should still be active.
    act(() => {
      dispatch(THEME_TRANSITION_START);
    });
    act(() => {
      vi.advanceTimersByTime(MAX_OVERLAY_LIFETIME_MS - 100);
    });
    expect(queryByTestId("theme-transition-overlay")).toBeTruthy();

    // After enough cumulative idle time the second watchdog fires.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(queryByTestId("theme-transition-overlay")).toBeNull();
  });

  it("balances depth so the first END during overlapping starts keeps it visible", () => {
    const { queryByTestId } = render(<ThemeTransitionOverlay />);
    act(() => {
      dispatch(THEME_TRANSITION_START);
      dispatch(THEME_TRANSITION_START);
    });
    act(() => {
      dispatch(THEME_TRANSITION_END);
    });
    // depth is still 1 — overlay must NOT enter the leaving phase yet.
    expect(queryByTestId("theme-transition-overlay")?.getAttribute("data-phase")).toBe(
      "expanding",
    );

    act(() => {
      dispatch(THEME_TRANSITION_END);
      vi.advanceTimersByTime(200);
    });
    expect(queryByTestId("theme-transition-overlay")).toBeNull();
  });
});

describe("ThemeTransitionOverlay — CSS contract", () => {
  it("brief overlay declares pointer-events: none so it never eats clicks", () => {
    // Pull the `.showme-intro--brief` block and assert it carries the
    // `pointer-events: none` declaration. If a future refactor drops
    // it, the shell becomes input-blocking again — this test guards
    // exactly that regression.
    const briefBlock = extractBlock(indexCssRaw, ".showme-intro--brief");
    expect(briefBlock).toBeTruthy();
    expect(briefBlock).toMatch(/pointer-events\s*:\s*none/);
  });
});

function extractBlock(css: string, selector: string): string | null {
  // Find the FIRST occurrence of `selector` that is immediately followed
  // by ` {` (not `.foo--brief.bar {`). We want the standalone declaration.
  const re = new RegExp(`(^|\\s)${escapeRegex(selector)}\\s*\\{`, "m");
  const m = css.match(re);
  if (!m || m.index == null) return null;
  const start = css.indexOf("{", m.index);
  if (start < 0) return null;
  const end = css.indexOf("}", start);
  if (end < 0) return null;
  return css.slice(start, end + 1);
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
