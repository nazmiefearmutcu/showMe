import { beforeEach, describe, expect, it } from "vitest";
import { useWorkspace, type SerializedWorkspace } from "./workspace";
import {
  applyWorkspaceMigrations,
  flushWorkspaceAutosave,
  isPersistedStatePreS11Cutoff,
  isPoisonedMarketsOverviewLayout,
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

/* ────────────────────── S11 poisoned-layout migration ────────────────────── */

const PRE_CUTOFF_SAVEDAT = "2026-05-20T19:34:42.115Z";
const POST_CUTOFF_SAVEDAT = "2026-05-21T08:00:00.000Z";

function poisonedMarketsOverviewState(
  topLeft: "DES" | "HOME",
  savedAt: string = PRE_CUTOFF_SAVEDAT,
): SerializedWorkspace {
  const top = {
    children: [
      topLeft === "DES"
        ? { code: "DES", id: "n-tl", kind: "leaf" as const, symbol: "AAPL" }
        : { code: "HOME", id: "n-tl", kind: "leaf" as const },
      { code: "GP", id: "n-tr", kind: "leaf" as const, symbol: "AAPL" },
    ],
    direction: "h" as const,
    id: "n-top",
    kind: "split" as const,
    sizes: [0.5, 0.5],
  };
  const bottom = {
    children: [
      { code: "WEI", id: "n-bl", kind: "leaf" as const },
      { code: "TOP", id: "n-br", kind: "leaf" as const },
    ],
    direction: "h" as const,
    id: "n-bot",
    kind: "split" as const,
    sizes: [0.5, 0.5],
  };
  return {
    focusedId: "n-tl",
    savedAt,
    tree: {
      children: [top, bottom],
      direction: "v",
      id: "n-root",
      kind: "split",
      sizes: [0.55, 0.45],
    },
  };
}

describe("S11 poisoned-layout self-heal migration", () => {
  it("detects the exact DES+GP+WEI+TOP S09 markets-overview default", () => {
    const state = poisonedMarketsOverviewState("DES");
    expect(isPoisonedMarketsOverviewLayout(state.tree)).toBe(true);
    expect(isPersistedStatePreS11Cutoff(state)).toBe(true);
    expect(applyWorkspaceMigrations(state)).toBe("skip-flush");
  });

  it("detects the HOME+GP+WEI+TOP welcome-route mutation variant", () => {
    const state = poisonedMarketsOverviewState("HOME");
    expect(isPoisonedMarketsOverviewLayout(state.tree)).toBe(true);
    expect(applyWorkspaceMigrations(state)).toBe("skip-flush");
  });

  it("preserves real custom multi-pane layouts (different codes/order)", () => {
    // Same skeleton shape but the bottom row uses PORT+WATCH instead of
    // WEI+TOP — that's a real user choice, must NOT be reset.
    const custom: SerializedWorkspace = {
      focusedId: "n-tl",
      savedAt: PRE_CUTOFF_SAVEDAT,
      tree: {
        children: [
          {
            children: [
              { code: "GP", id: "n-tl", kind: "leaf", symbol: "MSFT" },
              { code: "DES", id: "n-tr", kind: "leaf", symbol: "MSFT" },
            ],
            direction: "h",
            id: "n-top",
            kind: "split",
            sizes: [0.5, 0.5],
          },
          {
            children: [
              { code: "PORT", id: "n-bl", kind: "leaf" },
              { code: "WATCH", id: "n-br", kind: "leaf" },
            ],
            direction: "h",
            id: "n-bot",
            kind: "split",
            sizes: [0.5, 0.5],
          },
        ],
        direction: "v",
        id: "n-root",
        kind: "split",
        sizes: [0.55, 0.45],
      },
    };
    expect(isPoisonedMarketsOverviewLayout(custom.tree)).toBe(false);
    expect(applyWorkspaceMigrations(custom)).toBe("restore");
  });

  it("preserves the same skeleton with non-default GP symbol (user customization)", () => {
    // The poisoned layout always ships GP@AAPL — if the user changed
    // the symbol on the GP leaf, that's a real customization.
    const state = poisonedMarketsOverviewState("DES");
    const top = state.tree.kind === "split" ? state.tree.children[0] : null;
    if (top?.kind === "split" && top.children[1].kind === "leaf") {
      top.children[1].symbol = "TSLA";
    }
    expect(isPoisonedMarketsOverviewLayout(state.tree)).toBe(false);
    expect(applyWorkspaceMigrations(state)).toBe("restore");
  });

  it("preserves single-HOME persisted state (legacy default, native dashboard)", () => {
    const legacy: SerializedWorkspace = {
      focusedId: "n2-gx71",
      savedAt: PRE_CUTOFF_SAVEDAT,
      tree: { code: "HOME", id: "n2-gx71", kind: "leaf" },
    };
    expect(isPoisonedMarketsOverviewLayout(legacy.tree)).toBe(false);
    expect(applyWorkspaceMigrations(legacy)).toBe("restore");
  });

  it("trusts a post-cutoff save that happens to match the poisoned shape (user explicitly loaded Markets Overview)", () => {
    // Post-S11 the only way to land on this layout is an explicit
    // `loadBuiltinPreset("markets-overview")` action. Trust the user.
    const explicit = poisonedMarketsOverviewState("DES", POST_CUTOFF_SAVEDAT);
    expect(isPoisonedMarketsOverviewLayout(explicit.tree)).toBe(true);
    expect(isPersistedStatePreS11Cutoff(explicit)).toBe(false);
    expect(applyWorkspaceMigrations(explicit)).toBe("restore");
  });

  it("treats malformed/missing savedAt as pre-cutoff (defensive)", () => {
    const noTimestamp = poisonedMarketsOverviewState("DES");
    delete (noTimestamp as Partial<SerializedWorkspace>).savedAt;
    expect(isPersistedStatePreS11Cutoff(noTimestamp as SerializedWorkspace)).toBe(true);
    const garbage = poisonedMarketsOverviewState("DES", "not-an-iso-string");
    expect(isPersistedStatePreS11Cutoff(garbage)).toBe(true);
  });

  it("restoreWorkspace heals poisoned state on disk: in-memory stays default, file rewrites to clean single HOME", async () => {
    // Seed localStorage with a poisoned tree from the S09 era.
    const poisoned = poisonedMarketsOverviewState("DES");
    localStorage.setItem("showme.workspace", JSON.stringify(poisoned));
    // Cold-boot path: restore reads it, detects the poison, refuses
    // to load it, and persists the clean default back out.
    expect(await restoreWorkspace()).toBe(false);
    // In-memory store stayed on the clean default (single HOME leaf).
    const liveTree = useWorkspace.getState().tree;
    expect(liveTree.kind).toBe("leaf");
    if (liveTree.kind === "leaf") expect(liveTree.code).toBe("HOME");
    // Disk got rewritten with the clean default — next launch is
    // idempotent, no migration needed.
    const rewritten = localStorage.getItem("showme.workspace");
    expect(rewritten).not.toBeNull();
    const parsed = JSON.parse(rewritten!) as SerializedWorkspace;
    expect(parsed.tree.kind).toBe("leaf");
    if (parsed.tree.kind === "leaf") expect(parsed.tree.code).toBe("HOME");
  });
});
