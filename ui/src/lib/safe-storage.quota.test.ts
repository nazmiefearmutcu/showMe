/**
 * Regression — audit S14.
 *
 * `safeWriteLocal` is the central QuotaExceeded guard for every
 * preference-style localStorage write. Pinning the toast emission +
 * result shape here means callers (watchlist, alerts, symbols, pins)
 * can rely on a stable contract.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  safeWriteLocal,
  __resetSafeStorageThrottleForTests,
} from "./safe-storage";
import { useToastStore } from "./toast";

// jsdom's localStorage is an instance object with its own setItem; spying on
// Storage.prototype doesn't propagate. We monkey-patch the instance method
// directly and restore in afterEach.
let originalSetItem: ((key: string, value: string) => void) | null = null;

beforeEach(() => {
  __resetSafeStorageThrottleForTests();
  useToastStore.setState({ toasts: [] });
  localStorage.clear();
});

afterEach(() => {
  if (originalSetItem) {
    localStorage.setItem = originalSetItem;
    originalSetItem = null;
  }
});

function throwOnSetItem(err: Error): void {
  if (!originalSetItem) {
    originalSetItem = localStorage.setItem.bind(localStorage);
  }
  localStorage.setItem = () => {
    throw err;
  };
}

describe("safeWriteLocal (audit S14)", () => {
  it("returns ok=true and persists value on success", () => {
    const res = safeWriteLocal("test.k", { a: 1 });
    expect(res.ok).toBe(true);
    expect(JSON.parse(localStorage.getItem("test.k") ?? "")).toEqual({ a: 1 });
  });

  it("accepts a pre-serialized string without re-stringifying", () => {
    const res = safeWriteLocal("test.k", "raw");
    expect(res.ok).toBe(true);
    expect(localStorage.getItem("test.k")).toBe("raw");
  });

  it("returns ok=false reason='quota' AND emits a toast on QuotaExceededError", () => {
    const err = new Error("QuotaExceededError");
    err.name = "QuotaExceededError";
    throwOnSetItem(err);
    const res = safeWriteLocal("showme.watchlist", { rows: [] }, {
      label: "Watchlist",
    });
    expect(res.ok).toBe(false);
    expect(res.reason).toBe("quota");
    expect(useToastStore.getState().toasts.length).toBeGreaterThanOrEqual(1);
    const t = useToastStore.getState().toasts[0];
    expect(t.tone).toBe("error");
    expect(t.title).toBe("Storage full");
    expect(t.body).toContain("Watchlist");
  });

  it("detects Firefox-style NS_ERROR_DOM_QUOTA_REACHED as quota", () => {
    const err = new Error("ns boom");
    err.name = "NS_ERROR_DOM_QUOTA_REACHED";
    throwOnSetItem(err);
    const res = safeWriteLocal("test.k", { a: 1 });
    expect(res.reason).toBe("quota");
  });

  it("detects DOMException code 22 as quota", () => {
    const err = new Error("dom22");
    // @ts-expect-error — manual augmentation
    err.code = 22;
    throwOnSetItem(err);
    const res = safeWriteLocal("test.k", { a: 1 });
    expect(res.reason).toBe("quota");
  });

  it("throttles consecutive quota toasts per-key", () => {
    const err = new Error("QE");
    err.name = "QuotaExceededError";
    throwOnSetItem(err);
    safeWriteLocal("key.a", "1");
    safeWriteLocal("key.a", "2");
    safeWriteLocal("key.a", "3");
    // Same key → 1 toast despite 3 writes within the throttle window.
    expect(useToastStore.getState().toasts.length).toBe(1);
    // Different key → another toast.
    safeWriteLocal("key.b", "1");
    expect(useToastStore.getState().toasts.length).toBe(2);
  });

  it("returns reason='serialize' when JSON.stringify throws (cycles)", () => {
    const cyc: Record<string, unknown> = {};
    cyc.self = cyc;
    const res = safeWriteLocal("test.k", cyc);
    expect(res.ok).toBe(false);
    expect(res.reason).toBe("serialize");
  });

  it("returns reason='unknown' on non-quota error and does NOT toast", () => {
    throwOnSetItem(new Error("disk on fire"));
    const res = safeWriteLocal("test.k", { a: 1 });
    expect(res.ok).toBe(false);
    expect(res.reason).toBe("unknown");
    // No toast for unknown errors — caller can decide.
    expect(useToastStore.getState().toasts.length).toBe(0);
  });

  it("silent option suppresses toast even on quota error", () => {
    const err = new Error("QE");
    err.name = "QuotaExceededError";
    throwOnSetItem(err);
    const res = safeWriteLocal("test.k", "x", { silent: true });
    expect(res.reason).toBe("quota");
    expect(useToastStore.getState().toasts.length).toBe(0);
  });
});
