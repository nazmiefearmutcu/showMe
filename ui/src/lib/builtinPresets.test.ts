import { describe, expect, it } from "vitest";
import { BUILTIN_PRESETS, loadBuiltinPreset } from "./builtinPresets";
import { useWorkspace } from "./workspace";

function leafCodes(node: ReturnType<typeof useWorkspace.getState>["tree"]): string[] {
  if (node.kind === "leaf") return [node.code];
  return node.children.flatMap(leafCodes);
}

describe("builtin presets", () => {
  it("ships at least Markets Overview, Trading Desk and Macro Watch", () => {
    const ids = BUILTIN_PRESETS.map((p) => p.id);
    expect(ids).toEqual(
      expect.arrayContaining(["markets-overview", "trading-desk", "macro"]),
    );
  });

  it("Markets Overview puts DES, GP, WEI, TOP into the workspace", () => {
    expect(loadBuiltinPreset("markets-overview")).toBe(true);
    const tree = useWorkspace.getState().tree;
    expect(leafCodes(tree)).toEqual(
      expect.arrayContaining(["DES", "GP", "WEI", "TOP"]),
    );
  });

  it("Trading Desk hosts DES + PORT + GP + WATCH on first load", () => {
    loadBuiltinPreset("trading-desk", "MSFT");
    const tree = useWorkspace.getState().tree;
    expect(leafCodes(tree)).toEqual(
      expect.arrayContaining(["DES", "PORT", "GP", "WATCH"]),
    );
  });

  it("Macro Watch covers WEI + WCRS + GLCO + ECO", () => {
    loadBuiltinPreset("macro");
    const tree = useWorkspace.getState().tree;
    expect(leafCodes(tree)).toEqual(
      expect.arrayContaining(["WEI", "WCRS", "GLCO", "ECO"]),
    );
  });

  it("returns false for an unknown preset id", () => {
    expect(loadBuiltinPreset("does-not-exist")).toBe(false);
  });
});
