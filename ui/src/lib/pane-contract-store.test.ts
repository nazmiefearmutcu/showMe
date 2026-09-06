/**
 * Regression — UI-ROBUSTNESS F5.
 *
 * `byKey` grew without bound (every (code, symbol) pair ever fetched was
 * retained for the process lifetime) and `clear()` had zero production
 * callers. Now:
 *   - `record` caps the map drop-oldest at 200 entries by `receivedAt`;
 *   - the store subscribes to `onWorkspaceReset` so a workspace teardown
 *     wipes the contract cache.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  recordPaneContract,
  usePaneContractStore,
} from "./pane-contract-store";
import { useWorkspace } from "./workspace";

function snap(receivedAt: number) {
  return { dataMode: "live_exchange", receivedAt };
}

beforeEach(() => {
  usePaneContractStore.setState({ byKey: {} });
});

describe("pane-contract-store cap (UI-ROBUSTNESS F5)", () => {
  it("caps byKey at 200 entries, evicting the oldest by receivedAt", () => {
    for (let i = 0; i < 210; i += 1) {
      recordPaneContract("GP", `SYM${i}`, snap(Date.now() + i));
    }
    const byKey = usePaneContractStore.getState().byKey;
    expect(Object.keys(byKey)).toHaveLength(200);
    // Oldest 10 (SYM0..SYM9) were evicted; newest all present.
    expect(byKey["GP::SYM0"]).toBeUndefined();
    expect(byKey["GP::SYM9"]).toBeUndefined();
    expect(byKey["GP::SYM10"]).toBeDefined();
    expect(byKey["GP::SYM209"]).toBeDefined();
  });

  it("re-recording a key refreshes it instead of evicting the newest", () => {
    for (let i = 0; i < 200; i += 1) {
      recordPaneContract("GP", `SYM${i}`, snap(i));
    }
    // Touch the oldest entry — it must survive the next insert.
    recordPaneContract("GP", "SYM0", snap(1_000_000));
    recordPaneContract("GP", "NEW", snap(1_000_001));
    const byKey = usePaneContractStore.getState().byKey;
    expect(Object.keys(byKey)).toHaveLength(200);
    expect(byKey["GP::SYM0"]).toBeDefined();
    expect(byKey["GP::NEW"]).toBeDefined();
    // The new oldest is SYM1 (receivedAt=1).
    expect(byKey["GP::SYM1"]).toBeUndefined();
  });
});

describe("pane-contract-store workspace reset (UI-ROBUSTNESS F5)", () => {
  it("clear() with no code wipes the map", () => {
    recordPaneContract("GP", "AAPL", snap(1));
    usePaneContractStore.getState().clear();
    expect(usePaneContractStore.getState().byKey).toEqual({});
  });

  it("onWorkspaceReset wiring: resetting the workspace clears the store", () => {
    recordPaneContract("GP", "AAPL", snap(1));
    recordPaneContract("WATCH", "MSFT", snap(2));
    expect(Object.keys(usePaneContractStore.getState().byKey)).toHaveLength(2);

    // The store subscribed to onWorkspaceReset at module load; a real
    // workspace reset (preset switch / programmatic reset) must clear it.
    useWorkspace.getState().resetTo("HOME");

    expect(usePaneContractStore.getState().byKey).toEqual({});
  });
});
