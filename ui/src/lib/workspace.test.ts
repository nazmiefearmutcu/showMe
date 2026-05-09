import { beforeEach, describe, expect, it } from "vitest";
import {
  findLeaf,
  firstLeafId,
  leaf,
  loadWorkspace,
  normalize,
  removeLeaf,
  serializeWorkspace,
  split,
  useWorkspace,
} from "./workspace";

beforeEach(() => useWorkspace.getState().resetTo("HOME"));

describe("workspace tree helpers", () => {
  it("normalize sums to 1", () => {
    const n = normalize([2, 2, 4]);
    expect(n.reduce((s, v) => s + v, 0)).toBeCloseTo(1, 9);
    expect(n).toEqual([0.25, 0.25, 0.5]);
  });

  it("normalize handles all-zero gracefully", () => {
    expect(normalize([0, 0, 0])).toEqual([1 / 3, 1 / 3, 1 / 3]);
  });

  it("findLeaf walks the tree", () => {
    const tree = split("h", [leaf("DES", "AAPL"), leaf("FA", "AAPL")]);
    const target = tree.children[1];
    expect(findLeaf(tree, target.id)).toBe(target);
    expect(findLeaf(tree, "missing")).toBeNull();
  });

  it("removeLeaf collapses the parent when only one survivor remains", () => {
    const a = leaf("DES");
    const b = leaf("FA");
    const tree = split("h", [a, b]);
    const next = removeLeaf(tree, b.id);
    expect(next).toEqual(a);
  });

  it("removeLeaf re-distributes sizes when there are multiple survivors", () => {
    const a = leaf("DES");
    const b = leaf("FA");
    const c = leaf("GP");
    const tree = split("h", [a, b, c], [0.5, 0.25, 0.25]);
    const next = removeLeaf(tree, b.id) as ReturnType<typeof split>;
    expect(next.kind).toBe("split");
    expect(next.children).toHaveLength(2);
    expect(next.sizes.reduce((s, v) => s + v, 0)).toBeCloseTo(1, 9);
  });
});

describe("workspace store", () => {
  it("starts as a single HOME leaf", () => {
    const { tree, focusedId } = useWorkspace.getState();
    expect(tree.kind).toBe("leaf");
    expect((tree as ReturnType<typeof leaf>).code).toBe("HOME");
    expect(focusedId).toBe(tree.id);
  });

  it("setFocusedTarget mutates the focused leaf only", () => {
    const { setFocusedTarget } = useWorkspace.getState();
    setFocusedTarget("DES", "AAPL");
    const { tree } = useWorkspace.getState();
    expect(tree.kind).toBe("leaf");
    expect((tree as ReturnType<typeof leaf>).code).toBe("DES");
    expect((tree as ReturnType<typeof leaf>).symbol).toBe("AAPL");
  });

  it("splitFocused inserts a new leaf and focuses it", () => {
    const startId = useWorkspace.getState().focusedId;
    useWorkspace.getState().splitFocused("h", { code: "FA", symbol: "MSFT" });
    const { tree, focusedId } = useWorkspace.getState();
    expect(tree.kind).toBe("split");
    expect(focusedId).not.toBe(startId);
    const focused = findLeaf(tree, focusedId);
    expect(focused?.code).toBe("FA");
    expect(focused?.symbol).toBe("MSFT");
  });

  it("closeFocused collapses the parent when only one sibling remains", () => {
    useWorkspace.getState().splitFocused("h", { code: "FA", symbol: "AAPL" });
    expect(useWorkspace.getState().closeFocused()).toBe(true);
    const { tree } = useWorkspace.getState();
    expect(tree.kind).toBe("leaf");
    expect((tree as ReturnType<typeof leaf>).code).toBe("HOME");
  });

  it("closeFocused returns false when only one leaf remains", () => {
    expect(useWorkspace.getState().closeFocused()).toBe(false);
  });

  it("setSplitSizes normalizes and replaces", () => {
    useWorkspace.getState().splitFocused("h", { code: "FA" });
    const { tree, setSplitSizes } = useWorkspace.getState();
    if (tree.kind !== "split") throw new Error("expected split");
    setSplitSizes(tree.id, [3, 1]);
    const next = useWorkspace.getState().tree;
    if (next.kind !== "split") throw new Error("still split");
    expect(next.sizes[0]).toBeCloseTo(0.75, 6);
    expect(next.sizes[1]).toBeCloseTo(0.25, 6);
  });

  it("serialize → load round-trips and remaps ids", () => {
    useWorkspace.getState().splitFocused("v", { code: "GP", symbol: "MSFT" });
    const original = useWorkspace.getState().tree;
    const serialized = serializeWorkspace();
    useWorkspace.getState().resetTo("HOME");
    loadWorkspace(serialized);
    const restored = useWorkspace.getState().tree;
    expect(restored.kind).toBe("split");
    expect(restored.id).not.toBe(original.id); // ids remapped
    if (restored.kind === "split") {
      expect(restored.children.map((c) => (c as ReturnType<typeof leaf>).code))
        .toEqual([(original as ReturnType<typeof split>).children[0].kind === "leaf"
          ? ((original as ReturnType<typeof split>).children[0] as ReturnType<typeof leaf>).code
          : "?",
          ((original as ReturnType<typeof split>).children[1] as ReturnType<typeof leaf>).code]);
    }
  });

  it("firstLeafId always returns a leaf id even after a split", () => {
    useWorkspace.getState().splitFocused("h", { code: "FA" });
    const { tree } = useWorkspace.getState();
    const id = firstLeafId(tree);
    expect(findLeaf(tree, id)).not.toBeNull();
  });
});
