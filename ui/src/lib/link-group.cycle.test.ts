/**
 * HIGH #10 (UI-Shell-Bundle UB) — broadcastSymbolToGroup is cycle-safe
 * and capped.
 *
 * The hardening adds:
 *   - a `visited: Set<string>` guard so a malformed tree that points
 *     two children at the same node id terminates instead of looping,
 *   - a per-call write cap so a balloon-sized tree cannot rewrite more
 *     than MAX_BROADCAST_LEAVES siblings on a single setFocusedTarget.
 */
import { describe, expect, it } from "vitest";
import {
  broadcastSymbolToGroup,
  leaf,
  split,
  type WorkspaceNode,
} from "./workspace";

describe("broadcastSymbolToGroup cycle/cap guards", () => {
  it("terminates even when two children share the same node id", () => {
    // Synthesise a cycle-y tree by referencing the same leaf twice.
    const shared = { ...leaf("DES", "AAPL"), linkGroup: "X" };
    const sibling = { ...leaf("FA", "AAPL"), linkGroup: "X" };
    const tree: WorkspaceNode = {
      id: "root",
      kind: "split",
      direction: "h",
      // Same id on the two children — the visited set must catch it.
      children: [shared, { ...shared }],
      sizes: [0.5, 0.5],
    };
    // Add a real sibling that should still get the update on the
    // first pass.
    const wrapped: WorkspaceNode = {
      id: "outer",
      kind: "split",
      direction: "v",
      children: [tree, sibling],
      sizes: [0.5, 0.5],
    };
    // Should return without hanging.
    const next = broadcastSymbolToGroup(wrapped, "X", "TSLA", shared.id);
    if (next.kind !== "split") throw new Error("expected split");
    // The non-cycle sibling got the update.
    const sib = next.children[1];
    expect(sib.kind).toBe("leaf");
    if (sib.kind === "leaf") expect(sib.symbol).toBe("TSLA");
  });

  it("respects the MAX_BROADCAST_LEAVES cap on a huge group", () => {
    // Build a flat 50-leaf split where every leaf is in group "X".
    const leaves: WorkspaceNode[] = [];
    for (let i = 0; i < 50; i += 1) {
      leaves.push({ ...leaf("DES", "AAPL"), id: `leaf-${i}`, linkGroup: "X" });
    }
    const sizes = leaves.map(() => 1 / leaves.length);
    const tree: WorkspaceNode = {
      id: "root",
      kind: "split",
      direction: "h",
      children: leaves,
      sizes,
    };
    const origin = (leaves[0] as ReturnType<typeof leaf>).id;
    const next = broadcastSymbolToGroup(tree, "X", "TSLA", origin);
    if (next.kind !== "split") throw new Error("expected split");
    // Count how many got rewritten (origin excluded).
    let rewritten = 0;
    for (const c of next.children) {
      if (c.kind === "leaf" && c.symbol === "TSLA" && c.id !== origin) {
        rewritten += 1;
      }
    }
    // Cap should kick in well before 49.
    expect(rewritten).toBeLessThanOrEqual(20);
    // And it must rewrite *some* of them — not zero.
    expect(rewritten).toBeGreaterThan(0);
  });

  it("regular two-pane broadcast unchanged (regression for the happy path)", () => {
    const a = { ...leaf("DES", "AAPL"), linkGroup: "A" };
    const b = { ...leaf("FA", "AAPL"), linkGroup: "A" };
    const c = leaf("GP", "MSFT");
    const tree = split("h", [a, b, c]);
    const next = broadcastSymbolToGroup(tree, "A", "TSLA", a.id);
    if (next.kind !== "split") throw new Error("expected split");
    expect((next.children[0] as ReturnType<typeof leaf>).symbol).toBe("AAPL");
    expect((next.children[1] as ReturnType<typeof leaf>).symbol).toBe("TSLA");
    expect((next.children[2] as ReturnType<typeof leaf>).symbol).toBe("MSFT");
  });
});
