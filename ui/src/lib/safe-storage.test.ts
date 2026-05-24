/**
 * Contract tests for the safe-storage corruption recovery helper.
 *
 * Verifies:
 *   - Missing key returns the fallback without side-effects.
 *   - Valid JSON is returned as-is and the toast is silent.
 *   - Corrupt JSON triggers cleanup + a warn toast.
 *   - The toast is throttled per-key so a hot loop cannot spam the user.
 *   - A schema validator failure is treated the same as corrupt JSON.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  __resetSafeStorageThrottleForTests,
  safeReadLocal,
} from "./safe-storage";
import { useToastStore } from "./toast";

beforeEach(() => {
  localStorage.clear();
  useToastStore.getState().clear();
  __resetSafeStorageThrottleForTests();
});

afterEach(() => {
  localStorage.clear();
  useToastStore.getState().clear();
  __resetSafeStorageThrottleForTests();
});

describe("safeReadLocal", () => {
  it("returns the fallback when the key is missing", () => {
    const result = safeReadLocal("missing.key", []);
    expect(result).toEqual([]);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("returns the parsed value when JSON is valid", () => {
    localStorage.setItem("good.key", JSON.stringify({ rows: [1, 2, 3] }));
    const result = safeReadLocal<{ rows: number[] }>("good.key", { rows: [] });
    expect(result.rows).toEqual([1, 2, 3]);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("clears the bad blob and toasts when JSON is corrupt", () => {
    localStorage.setItem("bad.key", "{ not valid json ");
    const result = safeReadLocal("bad.key", { rows: [] });
    expect(result).toEqual({ rows: [] });
    expect(localStorage.getItem("bad.key")).toBeNull();
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].tone).toBe("warn");
    expect(toasts[0].title).toMatch(/reset due to corrupted data/i);
  });

  it("throttles repeated toasts for the same key", () => {
    localStorage.setItem("bad.key", "{");
    safeReadLocal("bad.key", []);
    // The remove already cleared the key, so re-seed it once.
    localStorage.setItem("bad.key", "{");
    safeReadLocal("bad.key", []);
    expect(useToastStore.getState().toasts).toHaveLength(1);
  });

  it("fires a separate toast for a separate key", () => {
    localStorage.setItem("bad.a", "{");
    localStorage.setItem("bad.b", "{");
    safeReadLocal("bad.a", []);
    safeReadLocal("bad.b", []);
    expect(useToastStore.getState().toasts).toHaveLength(2);
  });

  it("treats a validator rejection as corruption", () => {
    localStorage.setItem("schema.key", JSON.stringify({ wrong: true }));
    const result = safeReadLocal<{ rows: number[] }>(
      "schema.key",
      { rows: [] },
      {
        validate: (v): v is { rows: number[] } =>
          Boolean(v && typeof v === "object" && Array.isArray((v as { rows?: unknown }).rows)),
      },
    );
    expect(result.rows).toEqual([]);
    expect(localStorage.getItem("schema.key")).toBeNull();
    expect(useToastStore.getState().toasts).toHaveLength(1);
  });

  it("custom label is reflected in the toast title", () => {
    localStorage.setItem("bad.key", "{");
    safeReadLocal("bad.key", [], { label: "Pins" });
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].title.startsWith("Pins")).toBe(true);
  });

  it("silent option suppresses both cleanup and toast", () => {
    localStorage.setItem("bad.key", "{");
    safeReadLocal("bad.key", [], { silent: true });
    expect(localStorage.getItem("bad.key")).toBe("{");
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});
