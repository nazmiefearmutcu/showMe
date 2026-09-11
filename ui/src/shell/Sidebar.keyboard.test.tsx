/**
 * Lane L2 — Sidebar search keyboard traversal (campaign 2026-09-11).
 *
 * ArrowUp/Down highlight filtered function rows, Enter opens the
 * highlighted row, Escape clears then blurs. Existing recents/not-found
 * behaviour is pinned by Sidebar.recents.test.tsx / Sidebar.notfound-route.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Sidebar } from "./Sidebar";
import { useAppStore } from "@/lib/store";
import { __resetForTests as resetRecents } from "@/lib/palette-recents";
import { resetPinnedItemsForTests } from "@/lib/pins";

function seedIndex() {
  useAppStore.setState({
    functionIndex: [
      { code: "DES", name: "Description", category: "equity", description: "" },
      { code: "GP", name: "Generic Price", category: "chart", description: "" },
      { code: "FA", name: "Financial Analysis", category: "equity", description: "" },
    ],
  });
  useAppStore.getState().toggleSidebar(true);
}

function searchInput(): HTMLInputElement {
  return screen.getByPlaceholderText("code, name, category") as HTMLInputElement;
}

function highlighted(): Element | null {
  return document.querySelector(".sidebar-function-link--kbd-active");
}

beforeEach(() => {
  window.location.hash = "#/";
  window.localStorage.clear();
  resetRecents();
  resetPinnedItemsForTests();
  seedIndex();
});

afterEach(() => {
  cleanup();
});

describe("Sidebar search keyboard traversal", () => {
  it("ArrowDown walks the grouped results in render order, Enter opens", () => {
    render(<Sidebar />);
    const input = searchInput();
    // equity group first: DES, FA — then chart: GP.
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(highlighted()?.textContent).toContain("DES");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(highlighted()?.textContent).toContain("FA");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(highlighted()?.textContent).toContain("DES");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toBe("#/fn/DES");
  });

  it("typing narrows the list and Enter opens the highlighted hit", () => {
    render(<Sidebar />);
    const input = searchInput();
    fireEvent.change(input, { target: { value: "generic" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(highlighted()?.textContent).toContain("GP");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toBe("#/fn/GP");
  });

  it("Escape clears the query first, then blurs on a second press", () => {
    render(<Sidebar />);
    const input = searchInput();
    input.focus();
    fireEvent.change(input, { target: { value: "gen" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("");
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(document.activeElement).not.toBe(input);
  });
});
