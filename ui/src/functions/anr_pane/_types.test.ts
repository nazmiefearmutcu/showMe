/**
 * REL-04 P8 — BACKGROUND_VERYFINDER_REFRESHED_AT LRU eviction.
 *
 * Pin the contract that the previously-unbounded Map is now a real LRU
 * with a 256-entry cap. Without this, a long-running session that
 * cycles through hundreds of distinct (symbol, sample, source) keys
 * leaks one Map entry per key forever.
 */
import { describe, expect, it, beforeEach } from "vitest";
import {
  BACKGROUND_VERYFINDER_REFRESH_CAP,
  BACKGROUND_VERYFINDER_REFRESHED_AT,
} from "./_types";

describe("BACKGROUND_VERYFINDER_REFRESHED_AT LRU", () => {
  beforeEach(() => {
    BACKGROUND_VERYFINDER_REFRESHED_AT.clear();
  });

  it("respects the documented cap constant", () => {
    expect(BACKGROUND_VERYFINDER_REFRESH_CAP).toBeGreaterThanOrEqual(64);
    expect(BACKGROUND_VERYFINDER_REFRESH_CAP).toBeLessThanOrEqual(2048);
  });

  it("does not grow past the cap when inserting more keys", () => {
    for (let i = 0; i < BACKGROUND_VERYFINDER_REFRESH_CAP * 2; i++) {
      BACKGROUND_VERYFINDER_REFRESHED_AT.set(`SYM${i}:30:auto`, i);
    }
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.size).toBe(
      BACKGROUND_VERYFINDER_REFRESH_CAP,
    );
  });

  it("evicts the oldest key first when capacity is exceeded", () => {
    BACKGROUND_VERYFINDER_REFRESHED_AT.set("OLDEST", 1);
    for (let i = 0; i < BACKGROUND_VERYFINDER_REFRESH_CAP; i++) {
      BACKGROUND_VERYFINDER_REFRESHED_AT.set(`SYM${i}:30:auto`, i + 100);
    }
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.has("OLDEST")).toBe(false);
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.has("SYM0:30:auto")).toBe(true);
  });

  it("touching an existing key refreshes its insertion order", () => {
    BACKGROUND_VERYFINDER_REFRESHED_AT.set("KEEP_ME", 1);
    for (let i = 0; i < BACKGROUND_VERYFINDER_REFRESH_CAP - 1; i++) {
      BACKGROUND_VERYFINDER_REFRESHED_AT.set(`FILL${i}`, i);
    }
    // Touch KEEP_ME to mark it as most-recently-used.
    BACKGROUND_VERYFINDER_REFRESHED_AT.set("KEEP_ME", 999);
    // Now overflow by one — the LRU victim should be FILL0, not KEEP_ME.
    BACKGROUND_VERYFINDER_REFRESHED_AT.set("PUSH", 1000);
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.has("KEEP_ME")).toBe(true);
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.has("FILL0")).toBe(false);
  });

  it("supports delete + has + get like a real map", () => {
    BACKGROUND_VERYFINDER_REFRESHED_AT.set("AAPL:30:auto", 1234);
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.get("AAPL:30:auto")).toBe(1234);
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.has("AAPL:30:auto")).toBe(true);
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.delete("AAPL:30:auto")).toBe(true);
    expect(BACKGROUND_VERYFINDER_REFRESHED_AT.has("AAPL:30:auto")).toBe(false);
  });
});
