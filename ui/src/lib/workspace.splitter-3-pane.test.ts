/**
 * CRITICAL #1 (UI-Shell-Bundle UB) — splitter math must handle 3+ panes.
 *
 * The legacy resize helper paired `start[idx]` with `start[idx+1]` and
 * silently corrupted sibling sizes whenever a horizontal/vertical split
 * had more than two children. These regression tests pin the contract
 * for the new `applySplitDragDelta` helper used by both mouse-drag and
 * keyboard-resize code paths.
 */
import { describe, expect, it } from "vitest";
import { applySplitDragDelta } from "@/shell/Workspace";

describe("applySplitDragDelta (3+ pane splitter math)", () => {
  it("two-pane delta still balances against the neighbour", () => {
    const start = [0.6, 0.4];
    const next = applySplitDragDelta(start, 0, 0.1);
    expect(next[0]).toBeCloseTo(0.7, 6);
    expect(next[1]).toBeCloseTo(0.3, 6);
    expect(next.reduce((s, v) => s + v, 0)).toBeCloseTo(1, 6);
  });

  it("three-pane delta preserves the third sibling proportionally", () => {
    const start = [0.4, 0.3, 0.3];
    // Drag handle 0 right by 0.1. Pane[0] grows to 0.5. Pane[1]+Pane[2]
    // shared the remaining 0.5 — they each held 0.3, so each owned 0.5
    // of the downstream mass, and the new total downstream is 0.5.
    const next = applySplitDragDelta(start, 0, 0.1);
    expect(next).toHaveLength(3);
    expect(next[0]).toBeCloseTo(0.5, 6);
    // Both downstream panes were equal so both halve the leftover.
    expect(next[1]).toBeCloseTo(0.25, 6);
    expect(next[2]).toBeCloseTo(0.25, 6);
    expect(next.reduce((s, v) => s + v, 0)).toBeCloseTo(1, 6);
  });

  it("three-pane delta keeps relative weights of unequal downstream", () => {
    // Downstream panes are 2:1 — after redistribution they must still
    // be 2:1.
    const start = [0.4, 0.4, 0.2]; // downstream 0.4 : 0.2 = 2:1
    const next = applySplitDragDelta(start, 0, 0.1);
    expect(next[0]).toBeCloseTo(0.5, 6);
    expect(next[1]).toBeCloseTo(0.5 * (0.4 / 0.6), 6);
    expect(next[2]).toBeCloseTo(0.5 * (0.2 / 0.6), 6);
    expect(next[1] / next[2]).toBeCloseTo(2, 6);
    expect(next.reduce((s, v) => s + v, 0)).toBeCloseTo(1, 6);
  });

  it("clamps to MIN floor when delta would crush the dragged pane", () => {
    const start = [0.4, 0.3, 0.3];
    // Drag wildly left — would push pane 0 to 0.04, below 0.08 floor.
    const next = applySplitDragDelta(start, 0, -0.5);
    expect(next[0]).toBeCloseTo(0.08, 6);
    // Downstream panes share the remaining 0.92, preserving their
    // 1:1 ratio.
    expect(next[1]).toBeCloseTo(0.46, 6);
    expect(next[2]).toBeCloseTo(0.46, 6);
  });

  it("clamps so downstream panes always keep their MIN floor", () => {
    const start = [0.5, 0.3, 0.2];
    // Drag pane 0 hard right. The clamp pins pane 0 at:
    //   max = totalSize(1) - downstreamFloor(min*2=0.16) = 0.84
    // Panes 1+2 share the remaining 0.16, each pinned at their floor.
    const next = applySplitDragDelta(start, 0, 1);
    expect(next[0]).toBeCloseTo(0.84, 6);
    expect(next[1]).toBeGreaterThanOrEqual(0.08 - 1e-9);
    expect(next[2]).toBeGreaterThanOrEqual(0.08 - 1e-9);
    expect(next.reduce((s, v) => s + v, 0)).toBeCloseTo(1, 6);
  });

  it("four-pane delta preserves every sibling after idx+1", () => {
    const start = [0.25, 0.25, 0.25, 0.25];
    const next = applySplitDragDelta(start, 0, 0.1);
    expect(next).toHaveLength(4);
    expect(next[0]).toBeCloseTo(0.35, 6);
    // Three equal downstream panes split the remaining 0.65 evenly.
    expect(next[1]).toBeCloseTo(0.65 / 3, 6);
    expect(next[2]).toBeCloseTo(0.65 / 3, 6);
    expect(next[3]).toBeCloseTo(0.65 / 3, 6);
  });

  it("does not mutate the input array", () => {
    const start = [0.4, 0.3, 0.3];
    const snapshot = [...start];
    applySplitDragDelta(start, 0, 0.1);
    expect(start).toEqual(snapshot);
  });

  it("returns a defensive copy when idx is invalid (out-of-range)", () => {
    const start = [0.5, 0.5];
    expect(applySplitDragDelta(start, -1, 0.1)).toEqual(start);
    expect(applySplitDragDelta(start, 99, 0.1)).toEqual(start);
    // idx === last pane has no neighbour to push into.
    expect(applySplitDragDelta(start, 1, 0.1)).toEqual(start);
  });

  it("zero downstream mass falls back to equal split (degenerate but safe)", () => {
    // Pathological tree where downstream sizes are all zero. Should
    // never happen in practice (normalize() prevents it) but the
    // helper must not divide-by-zero. totalSize=0.5 here so:
    //   max = 0.5 - min*2 = 0.34
    // requested a = 0.4, but the max-clamp pulls it down to 0.34.
    // Remaining 0.16 splits equally between panes 1 and 2 (each = 0.08,
    // the floor).
    const start = [0.5, 0, 0];
    const next = applySplitDragDelta(start, 0, -0.1);
    expect(next[0]).toBeLessThanOrEqual(0.4 + 1e-9);
    expect(next[0]).toBeGreaterThanOrEqual(0.08 - 1e-9);
    // Downstream split equally (zero-mass fallback path).
    expect(next[1]).toBeCloseTo(next[2], 6);
    expect(next.reduce((s, v) => s + v, 0)).toBeCloseTo(0.5, 6);
  });
});
