/**
 * Workspace splitter a11y — Agent F close-out.
 *
 * Before this round, the resize handle had `role="separator"` but no
 * tabindex, no aria-value*, and no keyboard handler — so screen-reader /
 * keyboard-only users could not resize panes at all. The fix:
 *
 *   - tabIndex=0
 *   - aria-valuenow/min/max (the percentage of the first child)
 *   - ArrowKey (5% step) + Home/End (collapse to min/max)
 *
 * Test boots a minimal Split tree and asserts every guarantee.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import { Workspace } from "./Workspace";
import { useWorkspace } from "@/lib/workspace";

beforeEach(() => {
  // Force a 2-leaf horizontal split before each test so the handle exists.
  useWorkspace.setState({
    tree: {
      kind: "split",
      id: "root",
      direction: "h",
      sizes: [0.5, 0.5],
      children: [
        { kind: "leaf", id: "L1", code: "HOME" },
        { kind: "leaf", id: "L2", code: "HOME" },
      ],
    },
    focusedId: "L1",
  });
  cleanup();
});

describe("Workspace splitter (a11y)", () => {
  it("renders the handle with role=separator + tabIndex=0 + aria-value*", () => {
    const { container } = render(<Workspace />);
    const handle = container.querySelector('[role="separator"]') as HTMLElement;
    expect(handle).not.toBeNull();
    expect(handle.getAttribute("tabindex")).toBe("0");
    expect(handle.getAttribute("aria-valuemin")).toBe("8");
    expect(handle.getAttribute("aria-valuemax")).toBe("92");
    expect(handle.getAttribute("aria-valuenow")).toBe("50");
    expect(handle.getAttribute("aria-orientation")).toBe("vertical");
  });

  it("ArrowRight increases the first child's share by 5%", () => {
    const { container } = render(<Workspace />);
    const handle = container.querySelector('[role="separator"]') as HTMLElement;
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    // Sizes are clamped/rounded by setSplitSizes; check the store directly.
    const tree = useWorkspace.getState().tree;
    if (tree.kind !== "split") throw new Error("split lost");
    expect(tree.sizes[0]).toBeCloseTo(0.55, 2);
    expect(tree.sizes[1]).toBeCloseTo(0.45, 2);
  });

  it("ArrowLeft decreases the first child's share by 5%", () => {
    const { container } = render(<Workspace />);
    const handle = container.querySelector('[role="separator"]') as HTMLElement;
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    const tree = useWorkspace.getState().tree;
    if (tree.kind !== "split") throw new Error("split lost");
    expect(tree.sizes[0]).toBeCloseTo(0.45, 2);
  });

  it("Home collapses the first child to the 8% floor", () => {
    const { container } = render(<Workspace />);
    const handle = container.querySelector('[role="separator"]') as HTMLElement;
    fireEvent.keyDown(handle, { key: "Home" });
    const tree = useWorkspace.getState().tree;
    if (tree.kind !== "split") throw new Error("split lost");
    expect(tree.sizes[0]).toBeCloseTo(0.08, 2);
  });

  it("End expands the first child to the 92% ceiling", () => {
    const { container } = render(<Workspace />);
    const handle = container.querySelector('[role="separator"]') as HTMLElement;
    fireEvent.keyDown(handle, { key: "End" });
    const tree = useWorkspace.getState().tree;
    if (tree.kind !== "split") throw new Error("split lost");
    expect(tree.sizes[0]).toBeCloseTo(0.92, 2);
  });

  it("ArrowUp/ArrowDown are ignored on horizontal-direction splits", () => {
    const { container } = render(<Workspace />);
    const handle = container.querySelector('[role="separator"]') as HTMLElement;
    fireEvent.keyDown(handle, { key: "ArrowUp" });
    fireEvent.keyDown(handle, { key: "ArrowDown" });
    const tree = useWorkspace.getState().tree;
    if (tree.kind !== "split") throw new Error("split lost");
    expect(tree.sizes[0]).toBe(0.5);
  });
});
