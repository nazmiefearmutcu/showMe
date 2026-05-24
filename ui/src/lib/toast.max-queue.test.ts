/**
 * HIGH #17 (UI-Shell-Bundle UB) — toast queue has a hard cap.
 *
 * A burst of 100 toasts must not render 100 cards. Older entries are
 * evicted FIFO; the freshest entries always stay visible.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { toast, useToastStore, TOAST_MAX_QUEUE } from "./toast";

beforeEach(() => useToastStore.getState().clear());

describe("toast max queue", () => {
  it("exposes the queue cap as a constant", () => {
    expect(TOAST_MAX_QUEUE).toBeGreaterThanOrEqual(5);
    expect(TOAST_MAX_QUEUE).toBeLessThanOrEqual(20);
  });

  it("never grows beyond TOAST_MAX_QUEUE", () => {
    for (let i = 0; i < TOAST_MAX_QUEUE * 5; i += 1) {
      toast.info(`toast ${i}`);
    }
    expect(useToastStore.getState().toasts.length).toBe(TOAST_MAX_QUEUE);
  });

  it("evicts oldest entries FIFO so freshest titles are always visible", () => {
    const N = TOAST_MAX_QUEUE * 3;
    for (let i = 0; i < N; i += 1) {
      toast.info(`toast ${i}`);
    }
    const titles = useToastStore.getState().toasts.map((t) => t.title);
    expect(titles).toHaveLength(TOAST_MAX_QUEUE);
    // The last entry should always be the most recent push.
    expect(titles[titles.length - 1]).toBe(`toast ${N - 1}`);
    // The first kept entry should be at index N - TOAST_MAX_QUEUE.
    expect(titles[0]).toBe(`toast ${N - TOAST_MAX_QUEUE}`);
  });

  it("a small batch under the cap is unaffected", () => {
    toast.info("a");
    toast.info("b");
    toast.info("c");
    const titles = useToastStore.getState().toasts.map((t) => t.title);
    expect(titles).toEqual(["a", "b", "c"]);
  });

  it("dedupe (re-push with same id) does not consume cap headroom", () => {
    for (let i = 0; i < TOAST_MAX_QUEUE - 1; i += 1) {
      toast.info(`k-${i}`);
    }
    // Force an explicit id by pushing through the store directly.
    useToastStore.getState().push({
      id: "fixed",
      tone: "info",
      title: "fixed-1",
    });
    expect(useToastStore.getState().toasts).toHaveLength(TOAST_MAX_QUEUE);
    // Re-push same id — should replace, not grow.
    useToastStore.getState().push({
      id: "fixed",
      tone: "info",
      title: "fixed-2",
    });
    expect(useToastStore.getState().toasts).toHaveLength(TOAST_MAX_QUEUE);
    // The replacement should also have updated the body.
    const fixed = useToastStore.getState().toasts.find((t) => t.id === "fixed");
    expect(fixed?.title).toBe("fixed-2");
  });
});
