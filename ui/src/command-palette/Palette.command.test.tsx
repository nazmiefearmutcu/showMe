/**
 * Lane L2 — Palette command grammar + history + match highlighting
 * (campaign 2026-09-11). Existing palette behaviour stays pinned by
 * Palette.test.tsx / Palette.v2.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CommandPalette } from "./Palette";
import { useAppStore } from "@/lib/store";
import { useWorkspace } from "@/lib/workspace";
import { __resetForTests as resetRecents } from "@/lib/palette-recents";
import {
  __resetForTests as resetHistory,
  pushCommandHistory,
} from "@/lib/command-history";
import { clearRecentSymbols } from "@/lib/symbols";

function setIndex() {
  useAppStore.setState({
    functionIndex: [
      { code: "DES", name: "Description", category: "equity", description: "" },
      { code: "GP", name: "Generic Price", category: "chart", description: "" },
      { code: "FA", name: "Financial Analysis", category: "equity", description: "" },
    ],
  });
}

function focusLeaf(code: string, symbol?: string) {
  useWorkspace.setState({
    tree: { kind: "leaf", id: "L1", code, symbol },
    focusedId: "L1",
  } as never);
}

function input(): HTMLInputElement {
  return screen.getByRole("combobox") as HTMLInputElement;
}

beforeEach(() => {
  window.location.hash = "#/";
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetRecents();
  resetHistory();
  clearRecentSymbols();
  setIndex();
  focusLeaf("DES");
  useAppStore.setState({ paletteOpen: true });
});

afterEach(() => {
  cleanup();
  useAppStore.setState({ paletteOpen: false, shortcutsOpen: false });
  document.documentElement.removeAttribute("data-preset");
});

describe("CommandPalette — command grammar (L2)", () => {
  it("MSFT GP pins an 'Open GP with MSFT' row that Enter executes", () => {
    render(<CommandPalette />);
    fireEvent.change(input(), { target: { value: "MSFT GP" } });
    expect(screen.getByRole("option", { name: /Open GP with MSFT/ })).toBeTruthy();
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(window.location.hash).toBe("#/symbol/MSFT/GP");
  });

  it("MSFT DES also resolves (symbol + function, either order)", () => {
    render(<CommandPalette />);
    fireEvent.change(input(), { target: { value: "MSFT DES" } });
    expect(screen.getByRole("option", { name: /Open DES with MSFT/ })).toBeTruthy();
  });

  it("highlights fuzzy matches using fuzzyRank indices (survey-2 M10)", () => {
    const { container } = render(<CommandPalette />);
    fireEvent.change(input(), { target: { value: "des" } });
    const mark = container.querySelector("mark.palette__match");
    expect(mark?.textContent?.toLowerCase()).toBe("des");
  });

  it("ArrowUp on an empty query recalls the last session command", () => {
    pushCommandHistory("zzz");
    render(<CommandPalette />);
    expect(input().value).toBe("");
    fireEvent.keyDown(input(), { key: "ArrowUp" });
    expect(input().value).toBe("zzz");
    // No suggestions for "zzz", so ArrowDown restores the empty draft.
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(input().value).toBe("");
  });
});
