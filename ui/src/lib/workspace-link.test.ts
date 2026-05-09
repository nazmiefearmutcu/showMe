import { beforeEach, describe, expect, it } from "vitest";
import {
  broadcastSymbolToGroup,
  findLeaf,
  leaf,
  split,
  useWorkspace,
} from "./workspace";

beforeEach(() => useWorkspace.getState().resetTo("HOME"));

describe("link-group broadcast", () => {
  it("rebinds siblings sharing the same group", () => {
    const a = { ...leaf("DES", "AAPL"), linkGroup: "A" };
    const b = { ...leaf("FA", "AAPL"), linkGroup: "A" };
    const c = leaf("GP", "MSFT"); // no group → untouched
    const tree = split("h", [a, b, c]);
    const next = broadcastSymbolToGroup(tree, "A", "TSLA", a.id);
    if (next.kind !== "split") throw new Error("expected split");
    expect((next.children[0] as ReturnType<typeof leaf>).symbol).toBe("AAPL"); // origin unchanged
    expect((next.children[1] as ReturnType<typeof leaf>).symbol).toBe("TSLA"); // sibling
    expect((next.children[2] as ReturnType<typeof leaf>).symbol).toBe("MSFT"); // untouched
  });

  it("does nothing when no leaves share the group", () => {
    const a = leaf("DES", "AAPL");
    const b = leaf("FA", "AAPL");
    const tree = split("h", [a, b]);
    const next = broadcastSymbolToGroup(tree, "Z", "TSLA", a.id);
    if (next.kind !== "split") throw new Error("expected split");
    expect((next.children[0] as ReturnType<typeof leaf>).symbol).toBe("AAPL");
    expect((next.children[1] as ReturnType<typeof leaf>).symbol).toBe("AAPL");
  });

  it("setFocusedTarget propagates symbol when focused leaf is in a group", () => {
    const a = { ...leaf("DES", "AAPL"), linkGroup: "B" };
    const b = { ...leaf("FA", "AAPL"), linkGroup: "B" };
    const tree = split("h", [a, b]);
    useWorkspace.getState().setTree(tree, a.id);
    useWorkspace.getState().setFocusedTarget("DES", "MSFT");
    const after = useWorkspace.getState().tree;
    if (after.kind !== "split") throw new Error("expected split");
    const focused = findLeaf(after, useWorkspace.getState().focusedId);
    expect(focused?.symbol).toBe("MSFT");
    // sibling rebound too
    const sibling = (after.children[1] as ReturnType<typeof leaf>);
    expect(sibling.symbol).toBe("MSFT");
    expect(sibling.code).toBe("FA"); // sibling code preserved
  });

  it("setFocusedTarget without a group leaves siblings alone", () => {
    const a = leaf("DES", "AAPL");
    const b = leaf("FA", "AAPL");
    const tree = split("h", [a, b]);
    useWorkspace.getState().setTree(tree, a.id);
    useWorkspace.getState().setFocusedTarget("DES", "MSFT");
    const after = useWorkspace.getState().tree;
    if (after.kind !== "split") throw new Error("expected split");
    expect((after.children[1] as ReturnType<typeof leaf>).symbol).toBe("AAPL");
  });

  it("setLeafTarget updates the addressed leaf even when another pane is focused", () => {
    const a = leaf("DES", "AAPL");
    const b = leaf("NALRT", "BTCUSDT");
    const tree = split("h", [a, b]);
    useWorkspace.getState().setTree(tree, a.id);
    useWorkspace.getState().setLeafTarget(b.id, "NALRT", "ETHUSDT");
    const after = useWorkspace.getState().tree;
    if (after.kind !== "split") throw new Error("expected split");
    expect((after.children[0] as ReturnType<typeof leaf>).symbol).toBe("AAPL");
    expect((after.children[1] as ReturnType<typeof leaf>).symbol).toBe("ETHUSDT");
  });

  it("setLeafTarget propagates linked symbols from the addressed leaf", () => {
    const a = { ...leaf("DES", "AAPL"), linkGroup: "C" };
    const b = { ...leaf("NALRT", "BTCUSDT"), linkGroup: "C" };
    const tree = split("h", [a, b]);
    useWorkspace.getState().setTree(tree, a.id);
    useWorkspace.getState().setLeafTarget(b.id, "NALRT", "ETHUSDT");
    const after = useWorkspace.getState().tree;
    if (after.kind !== "split") throw new Error("expected split");
    expect((after.children[0] as ReturnType<typeof leaf>).symbol).toBe("ETHUSDT");
    expect((after.children[1] as ReturnType<typeof leaf>).symbol).toBe("ETHUSDT");
  });

  it("setLeafLinkGroup toggles on and off", () => {
    const a = leaf("DES", "AAPL");
    const tree = split("h", [a, leaf("FA", "AAPL")]);
    useWorkspace.getState().setTree(tree, a.id);
    useWorkspace.getState().setLeafLinkGroup(a.id, "X");
    expect(
      findLeaf(useWorkspace.getState().tree, a.id)?.linkGroup,
    ).toBe("X");
    useWorkspace.getState().setLeafLinkGroup(a.id, undefined);
    expect(
      findLeaf(useWorkspace.getState().tree, a.id)?.linkGroup,
    ).toBeUndefined();
  });
});
