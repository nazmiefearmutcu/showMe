import { beforeEach, describe, expect, it } from "vitest";
import { toast, useToastStore } from "./toast";

beforeEach(() => useToastStore.getState().clear());

describe("toast", () => {
  it("queues entries with unique ids", () => {
    const a = toast.info("hi");
    const b = toast.success("done");
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(2);
    expect(toasts.map((t) => t.id)).toContain(a);
    expect(toasts.map((t) => t.id)).toContain(b);
  });

  it("dismisses by id", () => {
    const a = toast.info("hi");
    useToastStore.getState().dismiss(a);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("error toasts default to longer ttl", () => {
    toast.error("boom");
    const t = useToastStore.getState().toasts[0];
    expect(t.tone).toBe("error");
  });
});
