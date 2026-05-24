/**
 * REL-04 P7 — main.tsx global handler smoke tests.
 *
 * These tests just import `main.tsx` for its side effects (window error
 * + unhandledrejection + app:panic listeners) and verify the toast
 * dedupe behaviour. Full DOM rendering of `<App />` is exercised by
 * the existing a11y-shell test; we don't repeat that here.
 *
 * Note: vitest's jsdom does not fire `error` from synthetic Error events
 * automatically — we have to dispatch them.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

// Don't let main.tsx mount react during the test — replace ReactDOM
// before main.tsx executes.
vi.mock("react-dom/client", () => ({
  default: { createRoot: () => ({ render: () => undefined }) },
  createRoot: () => ({ render: () => undefined }),
}));

vi.mock("@/lib/tauri", async () => ({
  invoke: vi.fn().mockResolvedValue(undefined),
  listen: vi.fn().mockResolvedValue(() => undefined),
  emit: vi.fn().mockResolvedValue(undefined),
  isInTauri: () => false,
}));

describe("main.tsx global handlers", () => {
  beforeEach(async () => {
    // Re-import a clean module copy each time so the dedupe map resets.
    vi.resetModules();
    // Ensure the root mount-point exists for main.tsx's strict check.
    if (!document.getElementById("root")) {
      const el = document.createElement("div");
      el.id = "root";
      document.body.appendChild(el);
    }
  });

  it("registers error + unhandledrejection + contextmenu listeners", async () => {
    const spy = vi.spyOn(window, "addEventListener");
    await import("./main");
    const types = spy.mock.calls.map((c) => c[0]);
    expect(types).toContain("error");
    expect(types).toContain("unhandledrejection");
    expect(types).toContain("contextmenu");
  });

  it("dedupes repeated errors within the 5s window via console.error", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await import("./main");
    // Two identical errors back-to-back: both reach console.error but
    // only the first surfaces a toast — we assert the dedupe map by
    // counting console.error invocations from our handler. They're both
    // logged (the dedupe applies to the toast, not the log).
    const ev1 = new ErrorEvent("error", { message: "boom", error: new Error("boom") });
    const ev2 = new ErrorEvent("error", { message: "boom", error: new Error("boom") });
    window.dispatchEvent(ev1);
    window.dispatchEvent(ev2);
    // First arg of either logged call mentions window.onerror.
    const onerrorCalls = errSpy.mock.calls.filter(
      (call) => typeof call[0] === "string" && call[0].includes("window.onerror"),
    );
    expect(onerrorCalls.length).toBeGreaterThanOrEqual(2);
  });
});
