/**
 * QA-2026-05-23 — Agent E scope.
 *
 * Sidebar Recent group should be empty on first boot (no fake seed of
 * GEX/BTMM/WEI/OMON/EQS). Once the user navigates to a function its
 * code is pushed onto `palette-recents.v2` and the group reflects it.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { act } from "react";
import { Sidebar } from "./Sidebar";
import { useAppStore } from "@/lib/store";
import {
  __resetForTests as resetRecents,
  recordRecentCode,
} from "@/lib/palette-recents";

function seedIndex() {
  useAppStore.setState({
    functionIndex: [
      {
        code: "DES",
        name: "Description",
        category: "equity",
        description: "",
      },
      {
        code: "GP",
        name: "Generic Price",
        category: "chart",
        description: "",
      },
      {
        code: "FA",
        name: "Financial Analysis",
        category: "equity",
        description: "",
      },
    ],
  });
  useAppStore.getState().toggleSidebar(true);
}

beforeEach(() => {
  window.location.hash = "#/";
  resetRecents();
  seedIndex();
});

afterEach(() => {
  cleanup();
});

describe("Sidebar Recent group — QA-2026-05-23", () => {
  it("renders the Recent section with zero items on first boot", () => {
    render(<Sidebar />);
    const recent = screen.getByTestId("sidebar-group-recent");
    // No anchor-tagged shortcut row should be present.
    const shortcuts = recent.querySelectorAll(".sidebar-shortcut");
    expect(shortcuts.length).toBe(0);
    // Empty hint should be visible to set expectation.
    expect(recent.textContent ?? "").toContain("No recent functions");
  });

  it("removes the OMON / EQS / GEX / BTMM / WEI hard-coded seed entirely", () => {
    render(<Sidebar />);
    const recent = screen.getByTestId("sidebar-group-recent");
    // None of the legacy seed codes should appear as shortcuts.
    const text = recent.textContent ?? "";
    expect(text).not.toMatch(/\bOMON\b/);
    expect(text).not.toMatch(/\bEQS\b/);
    // GEX/BTMM/WEI may legitimately appear elsewhere in the sidebar
    // (Workspaces / Quick), but never inside Recent.
    const inRecent = (code: string) =>
      Array.from(recent.querySelectorAll(".sidebar-shortcut strong")).some(
        (el) => el.textContent?.trim() === code,
      );
    for (const code of ["GEX", "BTMM", "WEI", "OMON", "EQS"]) {
      expect(inRecent(code)).toBe(false);
    }
  });

  it("populates after recordRecentCode is called", async () => {
    // Pretend the user opened DES → GP → FA.
    recordRecentCode("DES");
    recordRecentCode("GP");
    recordRecentCode("FA");
    // Mount AFTER recording so initial state already reflects.
    render(<Sidebar />);
    const recent = screen.getByTestId("sidebar-group-recent");
    const labels = Array.from(
      recent.querySelectorAll(".sidebar-shortcut strong"),
    ).map((el) => el.textContent?.trim());
    // Most-recent first.
    expect(labels[0]).toBe("Financial Analysis");
    expect(labels[1]).toBe("Generic Price");
    expect(labels[2]).toBe("Description");
  });

  it("does not render TLDR in Tools (stub code was removed)", () => {
    render(<Sidebar />);
    // Tools section should not contain a TLDR shortcut anymore.
    const tools = screen.queryByText("Daily TL;DR");
    expect(tools).toBeNull();
  });

  it("does not render OMON in Quick Functions (stub code was removed)", () => {
    render(<Sidebar />);
    // Look for an Option Monitor label within sidebar-shortcut anchors —
    // there should be none under "Quick Functions" anymore.
    const all = Array.from(document.querySelectorAll(".sidebar-shortcut strong"));
    const labels = all.map((el) => el.textContent?.trim());
    expect(labels).not.toContain("Option Monitor");
  });
});

describe("Sidebar route change → recent push", () => {
  it("re-reads palette-recents when the route updates", () => {
    render(<Sidebar />);
    const recent = screen.getByTestId("sidebar-group-recent");
    expect(recent.querySelectorAll(".sidebar-shortcut").length).toBe(0);
    act(() => {
      recordRecentCode("DES");
      // Simulate hashchange so Sidebar's `useRoute` notifies.
      window.location.hash = "#/fn/DES";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    const after = screen.getByTestId("sidebar-group-recent");
    expect(after.querySelectorAll(".sidebar-shortcut").length).toBe(1);
  });
});
