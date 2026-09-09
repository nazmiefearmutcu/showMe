/**
 * Titlebar mini-tape (UI-finish wave F, 2026-09-09).
 *
 * Same honest-aggregation contract as the Statusbar pill, pinned against
 * the REAL tape registry with the fake-registry pattern from
 * Statusbar.tape-health.test.tsx:
 *   - zero subscriptions → nothing rendered (no tape, no claim);
 *   - live tape          → `LIVE · N` (+ tick age) with data-tape-state;
 *   - reconnecting/down  → state word only, never a fake count or age;
 *   - labels come from the shared TAPE_LABEL vocabulary.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { Titlebar } from "./Titlebar";
import { useAppStore } from "@/lib/store";
import { useWorkspace, leaf } from "@/lib/workspace";
import {
  __resetTapeHealthForTests,
  __tapeRecordTick,
  __tapeRecordTransport,
} from "@/lib/tape-health";

// Tauri invoke is a no-op in jsdom (same as Titlebar.nav.test.tsx).
vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => undefined),
  listen: vi.fn(async () => () => undefined),
}));

beforeEach(() => {
  __resetTapeHealthForTests();
  window.location.hash = "#/";
  useAppStore.setState({
    paletteOpen: false,
    shortcutsOpen: false,
    sidebarVisible: false,
    functionIndex: [],
    sidecarStatus: "healthy",
  });
  useWorkspace.setState({
    tree: leaf("HOME"),
    focusedId: "HOME",
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  __resetTapeHealthForTests();
});

describe("Titlebar — mini tape readout", () => {
  it("renders nothing when the desk has zero quote subscriptions", () => {
    render(<Titlebar />);
    expect(screen.queryByTestId("titlebar-tape")).toBeNull();
  });

  it("live tape reads LIVE · 2 with a fresh tick age and data-tape-state=live", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-09T15:00:00Z"));
    const now = Date.now();
    __tapeRecordTransport("BTCUSDT", "live");
    __tapeRecordTransport("ETHUSDT", "live");
    __tapeRecordTick("BTCUSDT", now - 2_000);
    __tapeRecordTick("ETHUSDT", now - 9_000);
    render(<Titlebar />);
    const tape = screen.getByTestId("titlebar-tape");
    expect(tape.getAttribute("data-tape-state")).toBe("live");
    // Freshest tick wins (BTCUSDT at 2s, not ETHUSDT at 9s). Spans are
    // gap-separated visually, so assert the parts, not one joined string.
    expect(tape.textContent).toContain("LIVE");
    expect(tape.textContent).toContain("· 2");
    expect(tape.textContent).toContain("· 2s");
  });

  it("reconnecting tape shows the state word only — no count, no age", () => {
    __tapeRecordTransport("BTCUSDT", "reconnecting");
    __tapeRecordTransport("ETHUSDT", "offline");
    __tapeRecordTick("BTCUSDT", Date.now() - 60_000);
    render(<Titlebar />);
    const tape = screen.getByTestId("titlebar-tape");
    expect(tape.getAttribute("data-tape-state")).toBe("reconnecting");
    // Word only — no symbol count, no stale age.
    expect(tape.textContent).toBe("RECONNECTING");
  });

  it("stale-only tape is DOWN, never LIVE (shared honest vocabulary)", () => {
    __tapeRecordTransport("BTCUSDT", "stale");
    render(<Titlebar />);
    const tape = screen.getByTestId("titlebar-tape");
    expect(tape.getAttribute("data-tape-state")).toBe("down");
    expect(tape.textContent).toContain("DOWN");
    expect(tape.textContent).not.toContain("LIVE");
  });

  it("semantic state wording is the shared TAPE_LABEL vocabulary, not a private copy", async () => {
    const { TAPE_LABEL } = await import("@/lib/tape-health");
    expect(TAPE_LABEL.live).toBe("LIVE");
    expect(TAPE_LABEL.reconnecting).toBe("RECONNECTING");
    expect(TAPE_LABEL.down).toBe("DOWN");
  });
});
