/**
 * Lane L2 — session command history (campaign 2026-09-11).
 *
 * Pins: newest-first storage, consecutive-dupe collapse, the 50 cap,
 * draft-preserving step semantics, and first-use seeding from the palette
 * recents stack.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  __resetForTests,
  getCommandHistory,
  pushCommandHistory,
  stepCommandHistory,
} from "./command-history";
import {
  __resetForTests as resetRecents,
  recordRecentCode,
} from "./palette-recents";

beforeEach(() => {
  __resetForTests();
  resetRecents();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("pushCommandHistory", () => {
  it("stores newest-first", () => {
    pushCommandHistory("GP");
    pushCommandHistory("MSFT DES");
    expect(getCommandHistory()).toEqual(["MSFT DES", "GP"]);
  });

  it("trims input and ignores empty commands", () => {
    pushCommandHistory("   ");
    pushCommandHistory("  GP  ");
    expect(getCommandHistory()).toEqual(["GP"]);
  });

  it("collapses CONSECUTIVE duplicates only", () => {
    pushCommandHistory("GP");
    pushCommandHistory("GP");
    expect(getCommandHistory()).toEqual(["GP"]);
    pushCommandHistory("DES");
    pushCommandHistory("GP");
    // A, B, A — the two GP runs are not adjacent, both stay.
    expect(getCommandHistory()).toEqual(["GP", "DES", "GP"]);
  });

  it("caps the stack at 50 entries", () => {
    for (let i = 0; i < 60; i += 1) pushCommandHistory(`CMD${i}`);
    const history = getCommandHistory();
    expect(history).toHaveLength(50);
    expect(history[0]).toBe("CMD59");
    expect(history[49]).toBe("CMD10");
  });
});

describe("stepCommandHistory", () => {
  it("returns null with an empty history (both directions)", () => {
    expect(stepCommandHistory(null, -1)).toBeNull();
    expect(stepCommandHistory(null, 1)).toBeNull();
    expect(stepCommandHistory("GP", -1)).toBeNull();
  });

  it("walks older on -1 and newer on +1", () => {
    pushCommandHistory("A");
    pushCommandHistory("B");
    pushCommandHistory("C");
    // history newest-first: [C, B, A]
    expect(stepCommandHistory(null, -1)).toBe("C");
    expect(stepCommandHistory("C", -1)).toBe("B");
    expect(stepCommandHistory("B", -1)).toBe("A");
    expect(stepCommandHistory("A", -1)).toBe("A"); // clamped at oldest
    expect(stepCommandHistory("A", 1)).toBe("B");
    expect(stepCommandHistory("B", 1)).toBe("C");
    expect(stepCommandHistory("C", 1)).toBeNull(); // past newest → draft
  });

  it("treats a non-history draft as the newest slot", () => {
    pushCommandHistory("GP");
    // Typing something new, then ArrowUp: go to newest…
    expect(stepCommandHistory("my draft", -1)).toBe("GP");
    // …ArrowDown from the newest returns null so the caller restores it.
    expect(stepCommandHistory("GP", 1)).toBeNull();
  });
});

describe("first-use seeding from palette recents", () => {
  it("seeds history from recent function codes when the session key is absent", () => {
    recordRecentCode("DES");
    recordRecentCode("GP");
    // Session history was cleared in beforeEach — first read seeds it.
    expect(getCommandHistory()).toEqual(["GP", "DES"]);
    // A pushed command then stacks on top of the seed.
    pushCommandHistory("MSFT");
    expect(getCommandHistory()).toEqual(["MSFT", "GP", "DES"]);
  });

  it("does not re-seed once the session key exists (even when empty)", () => {
    window.sessionStorage.setItem("showme.cmd.history.v1", "[]");
    recordRecentCode("DES");
    expect(getCommandHistory()).toEqual([]);
  });
});
