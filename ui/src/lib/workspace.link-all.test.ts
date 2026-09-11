/**
 * L3 (campaign 2026-09-11) — desk-wide link-group assignment.
 *
 * Additive helper for the PaneChrome "Link all panes" / "Clear all links"
 * actions. Pins purity, full-tree coverage, and that symbols are untouched.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  findLeaf,
  leaf,
  setAllLinkGroupsInTree,
  split,
  useWorkspace,
  type WorkspaceNode,
} from "./workspace";

function treeWithTwoLinkedLeaves(): { tree: WorkspaceNode; a: string; b: string } {
  const a = { ...leaf("DES", "AAPL"), id: "L1", linkGroup: "A" };
  const b = { ...leaf("GP", "MSFT"), id: "L2", linkGroup: "B" };
  return { tree: split("h", [a, b], [0.5, 0.5]), a: "L1", b: "L2" };
}

beforeEach(() => {
  const { tree } = treeWithTwoLinkedLeaves();
  useWorkspace.setState({ tree, focusedId: "L1" });
});

describe("setAllLinkGroupsInTree", () => {
  it("assigns the same group to every leaf without touching symbols", () => {
    const { tree } = treeWithTwoLinkedLeaves();
    const out = setAllLinkGroupsInTree(tree, "C");
    expect(findLeaf(out, "L1")?.linkGroup).toBe("C");
    expect(findLeaf(out, "L2")?.linkGroup).toBe("C");
    expect(findLeaf(out, "L1")?.symbol).toBe("AAPL");
    expect(findLeaf(out, "L2")?.symbol).toBe("MSFT");
  });

  it("clears all groups when called with undefined", () => {
    const { tree } = treeWithTwoLinkedLeaves();
    const out = setAllLinkGroupsInTree(tree, undefined);
    expect(findLeaf(out, "L1")?.linkGroup).toBeUndefined();
    expect(findLeaf(out, "L2")?.linkGroup).toBeUndefined();
  });

  it("is pure — the input tree is not mutated", () => {
    const { tree } = treeWithTwoLinkedLeaves();
    setAllLinkGroupsInTree(tree, "D");
    expect(findLeaf(tree, "L1")?.linkGroup).toBe("A");
    expect(findLeaf(tree, "L2")?.linkGroup).toBe("B");
  });
});

describe("useWorkspace.setAllLinkGroups", () => {
  it("applies desk-wide via the store action", () => {
    useWorkspace.getState().setAllLinkGroups("D");
    expect(findLeaf(useWorkspace.getState().tree, "L1")?.linkGroup).toBe("D");
    expect(findLeaf(useWorkspace.getState().tree, "L2")?.linkGroup).toBe("D");
  });

  it("clears desk-wide via undefined", () => {
    useWorkspace.getState().setAllLinkGroups(undefined);
    expect(findLeaf(useWorkspace.getState().tree, "L1")?.linkGroup).toBeUndefined();
    expect(findLeaf(useWorkspace.getState().tree, "L2")?.linkGroup).toBeUndefined();
  });
});
