import { beforeEach, describe, expect, it } from "vitest";
import { useWorkspace } from "./workspace";
import {
  flushWorkspaceAutosave,
  restoreWorkspace,
  startWorkspaceAutosave,
} from "./workspace-persist";

beforeEach(() => {
  localStorage.clear();
  useWorkspace.getState().resetTo("HOME");
});

describe("workspace-persist (browser fallback)", () => {
  it("restoreWorkspace returns false when nothing is stored", async () => {
    expect(await restoreWorkspace()).toBe(false);
  });

  it("autosave persists tree mutations", async () => {
    const dispose = startWorkspaceAutosave();
    useWorkspace.getState().splitFocused("h", { code: "FA", symbol: "AAPL" });
    await flushWorkspaceAutosave();
    dispose();
    const text = localStorage.getItem("showme.workspace");
    expect(text).not.toBeNull();
    const parsed = JSON.parse(text!);
    expect(parsed.tree.kind).toBe("split");
  });

  it("restoreWorkspace replays a previously saved tree", async () => {
    const dispose = startWorkspaceAutosave();
    useWorkspace
      .getState()
      .splitFocused("v", { code: "GP", symbol: "MSFT" });
    await flushWorkspaceAutosave();
    dispose();
    useWorkspace.getState().resetTo("HOME");
    expect(useWorkspace.getState().tree.kind).toBe("leaf");
    expect(await restoreWorkspace()).toBe(true);
    expect(useWorkspace.getState().tree.kind).toBe("split");
  });
});
