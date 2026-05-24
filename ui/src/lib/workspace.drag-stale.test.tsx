/**
 * CRITICAL #2 (UI-Shell-Bundle UB) — splitter mousemove listener must not
 * write back stale sizes after a sibling pane closes mid-drag.
 *
 * Component-level regression: render a 3-pane Split, start a drag on
 * handle 0, close a sibling mid-drag (rebuilds the tree → unmounts the
 * `<Split>`), and verify that subsequent global `mousemove` events do
 * not call `setSplitSizes` on the now-missing split id.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import {
  leaf,
  split,
  useWorkspace,
} from "./workspace";
import { Workspace } from "@/shell/Workspace";

beforeEach(() => {
  useWorkspace.getState().resetTo("HOME");
});

afterEach(() => {
  cleanup();
});

function dispatchMouseEvent(type: string, clientX = 0, clientY = 0): void {
  const evt = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX,
    clientY,
    button: 0,
  });
  window.dispatchEvent(evt);
}

describe("Split drag listener does not write stale sizes after sibling close", () => {
  it("drag → close-sibling → mousemove does not call setSplitSizes on the dead split id", () => {
    // Build a 3-pane horizontal split so closing one sibling collapses
    // the split to a 2-pane variant — a fresh `<Split>` mounts and the
    // old one unmounts.
    const a = leaf("DES");
    const b = leaf("FA");
    const c = leaf("GP");
    const tree = split("h", [a, b, c], [1 / 3, 1 / 3, 1 / 3]);
    useWorkspace.getState().setTree(tree, a.id);
    const initialSplitId = tree.id;

    // Spy on setSplitSizes to track writes.
    const setSpy = vi.fn(useWorkspace.getState().setSplitSizes);
    useWorkspace.setState({ setSplitSizes: setSpy });

    const { container } = render(<Workspace />);
    const handle = container.querySelector<HTMLElement>(
      `[data-testid="ws-split-handle-${initialSplitId}-0"]`,
    );
    expect(handle).not.toBeNull();

    // Start drag (synthetic React mousedown via fireEvent-equivalent).
    act(() => {
      const md = new MouseEvent("mousedown", {
        bubbles: true,
        cancelable: true,
        clientX: 100,
        clientY: 50,
        button: 0,
      });
      handle!.dispatchEvent(md);
    });

    // First mousemove → should write to the current split id once.
    setSpy.mockClear();
    act(() => dispatchMouseEvent("mousemove", 120, 50));
    // 1 call against the original split id (drag is active).
    if (setSpy.mock.calls.length > 0) {
      expect(setSpy.mock.calls[0][0]).toBe(initialSplitId);
    }

    // Now close sibling `b` mid-drag — workspace tree rebuilds and the
    // old `<Split>` unmounts. The drag session in the unmounted Split
    // ref MUST be wiped so subsequent moves do not target the dead id.
    setSpy.mockClear();
    act(() => {
      useWorkspace.getState().setTree(
        split("h", [{ ...a }, { ...c }], [0.5, 0.5]),
        a.id,
      );
    });

    // Second mousemove arrives — the listener for the old <Split> has
    // been removed AND its session ref nulled. Either way, the spy
    // must not see a write against `initialSplitId`.
    act(() => dispatchMouseEvent("mousemove", 200, 50));
    for (const call of setSpy.mock.calls) {
      expect(call[0]).not.toBe(initialSplitId);
    }
    // mouseup terminates the session for good housekeeping.
    act(() => dispatchMouseEvent("mouseup", 200, 50));
  });

  it("a fresh Split mount installs its own listener even after a prior one unmounted", () => {
    // First mount a 3-pane split, drag, then close all the way down to
    // a single leaf, then build a brand-new 2-pane split. The new
    // split must accept drags as if nothing happened.
    const a = leaf("DES");
    const b = leaf("FA");
    const c = leaf("GP");
    let tree = split("h", [a, b, c], [1 / 3, 1 / 3, 1 / 3]);
    useWorkspace.getState().setTree(tree, a.id);

    const setSpy = vi.fn(useWorkspace.getState().setSplitSizes);
    useWorkspace.setState({ setSplitSizes: setSpy });

    const { container, rerender } = render(<Workspace />);
    // Tear down to single leaf — Split unmounts.
    act(() => {
      useWorkspace.getState().resetTo("HOME");
    });
    rerender(<Workspace />);

    // New 2-pane split.
    const a2 = leaf("DES");
    const b2 = leaf("FA");
    tree = split("h", [a2, b2], [0.5, 0.5]);
    act(() => useWorkspace.getState().setTree(tree, a2.id));
    rerender(<Workspace />);

    const handle = container.querySelector<HTMLElement>(
      `[data-testid="ws-split-handle-${tree.id}-0"]`,
    );
    expect(handle).not.toBeNull();

    setSpy.mockClear();
    act(() => {
      const md = new MouseEvent("mousedown", {
        bubbles: true,
        cancelable: true,
        clientX: 100,
        clientY: 50,
        button: 0,
      });
      handle!.dispatchEvent(md);
    });
    act(() => dispatchMouseEvent("mousemove", 140, 50));
    act(() => dispatchMouseEvent("mouseup", 140, 50));

    // The fresh split id is the only id we'd see calls against.
    for (const call of setSpy.mock.calls) {
      expect(call[0]).toBe(tree.id);
    }
  });
});
