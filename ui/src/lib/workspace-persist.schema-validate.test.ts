/**
 * CRITICAL #4 (UI-Shell-Bundle UB) — strict schema validator on the
 * persisted workspace tree.
 *
 * Garbage in the persistence file must NOT throw inside React's render
 * cycle. `restoreWorkspace` should detect malformed state, drop it,
 * notify the user, and fall back to the in-memory default.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { useWorkspace, type SerializedWorkspace, type WorkspaceNode } from "./workspace";
import {
  isValidPersistedWorkspace,
  isValidWorkspaceNode,
  restoreWorkspace,
  sanitizePersistedWorkspace,
  sanitizeWorkspaceNode,
} from "./workspace-persist";

beforeEach(() => {
  localStorage.clear();
  useWorkspace.getState().resetTo("HOME");
});

describe("isValidWorkspaceNode", () => {
  it("accepts a minimal leaf", () => {
    expect(
      isValidWorkspaceNode({ id: "x", kind: "leaf", code: "HOME" }),
    ).toBe(true);
  });

  it("accepts a minimal split with two leaves", () => {
    expect(
      isValidWorkspaceNode({
        id: "s",
        kind: "split",
        direction: "h",
        children: [
          { id: "a", kind: "leaf", code: "DES" },
          { id: "b", kind: "leaf", code: "FA" },
        ],
        sizes: [0.5, 0.5],
      }),
    ).toBe(true);
  });

  it("rejects nodes without an id", () => {
    expect(isValidWorkspaceNode({ kind: "leaf", code: "HOME" })).toBe(false);
    expect(isValidWorkspaceNode({ id: "", kind: "leaf", code: "HOME" })).toBe(false);
  });

  it("rejects unknown kind values", () => {
    expect(
      isValidWorkspaceNode({ id: "x", kind: "table", code: "HOME" }),
    ).toBe(false);
  });

  it("rejects leaves with no code", () => {
    expect(isValidWorkspaceNode({ id: "x", kind: "leaf" })).toBe(false);
    expect(isValidWorkspaceNode({ id: "x", kind: "leaf", code: "" })).toBe(false);
  });

  it("rejects splits with bad direction", () => {
    expect(
      isValidWorkspaceNode({
        id: "s",
        kind: "split",
        direction: "diagonal",
        children: [{ id: "a", kind: "leaf", code: "DES" }],
        sizes: [1],
      }),
    ).toBe(false);
  });

  it("rejects splits whose sizes don't match children length", () => {
    expect(
      isValidWorkspaceNode({
        id: "s",
        kind: "split",
        direction: "h",
        children: [
          { id: "a", kind: "leaf", code: "DES" },
          { id: "b", kind: "leaf", code: "FA" },
        ],
        sizes: [1],
      }),
    ).toBe(false);
  });

  it("rejects sizes with negative or non-finite numbers", () => {
    expect(
      isValidWorkspaceNode({
        id: "s",
        kind: "split",
        direction: "h",
        children: [
          { id: "a", kind: "leaf", code: "DES" },
          { id: "b", kind: "leaf", code: "FA" },
        ],
        sizes: [-0.1, 1.1],
      }),
    ).toBe(false);
    expect(
      isValidWorkspaceNode({
        id: "s",
        kind: "split",
        direction: "h",
        children: [
          { id: "a", kind: "leaf", code: "DES" },
          { id: "b", kind: "leaf", code: "FA" },
        ],
        sizes: [Number.NaN, 1],
      }),
    ).toBe(false);
  });

  it("rejects splits with zero children", () => {
    expect(
      isValidWorkspaceNode({
        id: "s",
        kind: "split",
        direction: "h",
        children: [],
        sizes: [],
      }),
    ).toBe(false);
  });

  it("caps recursion at depth 32 (defends against pathological/cyclic trees)", () => {
    // Build a 35-deep nested split chain.
    let inner: unknown = { id: "leaf", kind: "leaf", code: "HOME" };
    for (let i = 0; i < 35; i += 1) {
      inner = {
        id: `s${i}`,
        kind: "split",
        direction: "h",
        children: [inner, { id: `l${i}`, kind: "leaf", code: "DES" }],
        sizes: [0.5, 0.5],
      };
    }
    expect(isValidWorkspaceNode(inner)).toBe(false);
  });
});

describe("isValidPersistedWorkspace", () => {
  it("accepts a fully-formed state envelope", () => {
    const state = {
      focusedId: "x",
      savedAt: new Date().toISOString(),
      tree: { id: "x", kind: "leaf", code: "HOME" },
    };
    expect(isValidPersistedWorkspace(state)).toBe(true);
  });

  it("rejects missing focusedId / savedAt / tree", () => {
    expect(isValidPersistedWorkspace({})).toBe(false);
    expect(isValidPersistedWorkspace({ focusedId: "x" })).toBe(false);
    expect(
      isValidPersistedWorkspace({ focusedId: "x", savedAt: "t" }),
    ).toBe(false);
  });

  it("rejects state whose tree fails node validation", () => {
    expect(
      isValidPersistedWorkspace({
        focusedId: "x",
        savedAt: "t",
        tree: { id: "x", kind: "leaf" /* code missing */ },
      }),
    ).toBe(false);
  });
});

describe("restoreWorkspace migrates malformed state to default", () => {
  it("drops a state whose tree is missing kind, in-memory stays single HOME", async () => {
    localStorage.setItem(
      "showme.workspace",
      JSON.stringify({
        focusedId: "x",
        savedAt: new Date().toISOString(),
        tree: { id: "x", code: "HOME" }, // missing kind
      } as Partial<SerializedWorkspace>),
    );
    const restored = await restoreWorkspace();
    expect(restored).toBe(false);
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
    if (tree.kind === "leaf") expect(tree.code).toBe("HOME");
  });

  it("drops outright JSON garbage", async () => {
    localStorage.setItem("showme.workspace", "{not actually json");
    const restored = await restoreWorkspace();
    expect(restored).toBe(false);
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
  });

  it("drops a state whose split.sizes length does not match children", async () => {
    localStorage.setItem(
      "showme.workspace",
      JSON.stringify({
        focusedId: "a",
        savedAt: new Date().toISOString(),
        tree: {
          id: "s",
          kind: "split",
          direction: "h",
          children: [
            { id: "a", kind: "leaf", code: "DES" },
            { id: "b", kind: "leaf", code: "FA" },
          ],
          sizes: [1], // wrong length
        },
      } as SerializedWorkspace),
    );
    const restored = await restoreWorkspace();
    expect(restored).toBe(false);
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
  });

  it("a valid persisted single HOME leaf still loads cleanly", async () => {
    const state: SerializedWorkspace = {
      focusedId: "x",
      savedAt: new Date().toISOString(),
      tree: { id: "x", kind: "leaf", code: "HOME" },
    };
    localStorage.setItem("showme.workspace", JSON.stringify(state));
    expect(await restoreWorkspace()).toBe(true);
  });
});

// ---------- M9 (campaign 2026-09-11, L3): leaf meta sanitization ----------

function envelope(tree: unknown): SerializedWorkspace {
  return {
    focusedId: "x",
    savedAt: new Date().toISOString(),
    tree: tree as WorkspaceNode,
  };
}

describe("sanitizeWorkspaceNode — linkGroup (M9)", () => {
  it("keeps canonical groups A–D", () => {
    for (const group of ["A", "B", "C", "D"]) {
      const out = sanitizeWorkspaceNode(
        { id: "x", kind: "leaf", code: "DES", linkGroup: group },
      );
      expect(out.kind === "leaf" && out.linkGroup).toBe(group);
    }
  });

  it("drops null, numbers, objects and arbitrary/legacy strings", () => {
    const bad: unknown[] = [null, 7, true, {}, [], "Z", "a", "A1", "link-a"];
    for (const value of bad) {
      const out = sanitizeWorkspaceNode({
        id: "x",
        kind: "leaf",
        code: "DES",
        linkGroup: value,
      } as unknown as WorkspaceNode);
      expect(out.kind === "leaf" && out.linkGroup).toBeUndefined();
    }
  });
});

describe("sanitizeWorkspaceNode — symbol type (M9)", () => {
  it("normalizes valid strings through the standard symbol resolver", () => {
    const out = sanitizeWorkspaceNode(
      { id: "x", kind: "leaf", code: "DES", symbol: "aapl" },
    );
    expect(out.kind === "leaf" && out.symbol).toBe("AAPL");
    const alias = sanitizeWorkspaceNode(
      { id: "x", kind: "leaf", code: "DES", symbol: "btc" },
    );
    expect(alias.kind === "leaf" && alias.symbol).toBe("BTCUSDT");
  });

  it("drops non-strings and blank strings instead of stringifying them", () => {
    const bad: unknown[] = [42, {}, ["AAPL"], true, "   ", ""];
    for (const value of bad) {
      const out = sanitizeWorkspaceNode({
        id: "x",
        kind: "leaf",
        code: "DES",
        symbol: value,
      } as unknown as WorkspaceNode);
      expect(out.kind === "leaf" && out.symbol).toBeUndefined();
    }
  });

  it("sanitizes nested leaves without touching valid siblings", () => {
    const out = sanitizeWorkspaceNode({
      id: "s",
      kind: "split",
      direction: "h",
      children: [
        { id: "a", kind: "leaf", code: "DES", symbol: "btc", linkGroup: "B" },
        { id: "b", kind: "leaf", code: "GP", symbol: 99, linkGroup: "legacy" },
      ],
      sizes: [0.5, 0.5],
    } as unknown as WorkspaceNode);
    if (out.kind !== "split") throw new Error("expected split");
    const [a, b] = out.children;
    expect(a.kind === "leaf" && a.symbol).toBe("BTCUSDT");
    expect(a.kind === "leaf" && a.linkGroup).toBe("B");
    expect(b.kind === "leaf" && b.symbol).toBeUndefined();
    expect(b.kind === "leaf" && b.linkGroup).toBeUndefined();
  });
});

describe("sanitizePersistedWorkspace + restoreWorkspace (M9)", () => {
  it("sanitizes the tree inside the persisted envelope", () => {
    const out = sanitizePersistedWorkspace(
      envelope({ id: "x", kind: "leaf", code: "DES", symbol: 42, linkGroup: "Z" }),
    );
    expect(out.tree.kind).toBe("leaf");
    if (out.tree.kind === "leaf") {
      expect(out.tree.symbol).toBeUndefined();
      expect(out.tree.linkGroup).toBeUndefined();
    }
  });

  it("restore keeps the workspace but drops malformed meta", async () => {
    localStorage.setItem(
      "showme.workspace",
      JSON.stringify(
        envelope({ id: "x", kind: "leaf", code: "DES", symbol: 42, linkGroup: "Z" }),
      ),
    );
    expect(await restoreWorkspace()).toBe(true);
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
    if (tree.kind === "leaf") {
      expect(tree.code).toBe("DES");
      expect(tree.symbol).toBeUndefined();
      expect(tree.linkGroup).toBeUndefined();
    }
  });

  it("restore keeps a valid linkGroup", async () => {
    localStorage.setItem(
      "showme.workspace",
      JSON.stringify(
        envelope({ id: "x", kind: "leaf", code: "DES", symbol: "AAPL", linkGroup: "C" }),
      ),
    );
    expect(await restoreWorkspace()).toBe(true);
    const tree = useWorkspace.getState().tree;
    if (tree.kind === "leaf") {
      expect(tree.symbol).toBe("AAPL");
      expect(tree.linkGroup).toBe("C");
    }
  });
});
