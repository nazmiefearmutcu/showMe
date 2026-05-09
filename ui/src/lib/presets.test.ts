import { beforeEach, describe, expect, it } from "vitest";
import {
  clearPresets,
  deletePreset,
  listPresets,
  loadPreset,
  savePreset,
} from "./presets";
import { useWorkspace } from "./workspace";

beforeEach(() => {
  clearPresets();
  useWorkspace.getState().resetTo("HOME");
});

describe("layout presets (browser-mode)", () => {
  it("starts empty", async () => {
    expect(await listPresets()).toEqual([]);
  });

  it("savePreset stores current workspace and listPresets returns it", async () => {
    useWorkspace.getState().splitFocused("h", { code: "FA", symbol: "AAPL" });
    await savePreset("dual");
    const list = await listPresets();
    expect(list).toHaveLength(1);
    expect(list[0].name).toBe("dual");
  });

  it("savePreset upserts when the same name is reused", async () => {
    await savePreset("foo");
    useWorkspace.getState().splitFocused("h", { code: "FA" });
    await savePreset("foo");
    expect(await listPresets()).toHaveLength(1);
  });

  it("loadPreset restores the saved tree", async () => {
    useWorkspace.getState().splitFocused("v", { code: "GP", symbol: "MSFT" });
    await savePreset("vertical");
    useWorkspace.getState().resetTo("HOME");
    expect(useWorkspace.getState().tree.kind).toBe("leaf");
    expect(await loadPreset("vertical")).toBe(true);
    expect(useWorkspace.getState().tree.kind).toBe("split");
  });

  it("loadPreset returns false for missing names", async () => {
    expect(await loadPreset("nope")).toBe(false);
  });

  it("deletePreset removes by name", async () => {
    await savePreset("a");
    await savePreset("b");
    expect(await deletePreset("a")).toBe(true);
    const remaining = await listPresets();
    expect(remaining.map((p) => p.name)).toEqual(["b"]);
  });

  it("savePreset rejects empty names", async () => {
    await expect(savePreset("   ")).rejects.toThrow();
  });
});
