/**
 * QA-2026-05-23 — Agent E scope.
 *
 * Covers the palette behaviours called out in the QA report:
 *   • cmd+k no longer self-toggles from inside the palette (collision
 *     with the App-level handler removed).
 *   • Typing "DES" + Enter opens the DES route, NOT DDM.
 *   • Multi-word queries ("general price") resolve to GP, not HP/TP.
 *   • Recent group inside the palette is empty on first boot.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { act } from "react";
import { CommandPalette } from "./Palette";
import { useAppStore } from "@/lib/store";
import { __resetForTests as resetRecents } from "@/lib/palette-recents";

function setIndex() {
  useAppStore.setState({
    functionIndex: [
      { code: "DDM", name: "Dividend Discount Model", category: "equity", description: "" },
      { code: "DEBT", name: "Debt Summary", category: "equity", description: "" },
      { code: "DES", name: "Description", category: "equity", description: "" },
      { code: "FA", name: "Financial Analysis", category: "equity", description: "" },
      { code: "GP", name: "Generic Price", category: "chart", description: "" },
      { code: "HP", name: "Historical Price", category: "chart", description: "" },
      { code: "TP", name: "Trade Price Box", category: "chart", description: "" },
    ],
  });
}

beforeEach(() => {
  window.location.hash = "#/";
  resetRecents();
  setIndex();
  useAppStore.setState({ paletteOpen: true });
});

afterEach(() => {
  cleanup();
  useAppStore.setState({ paletteOpen: false });
});

describe("CommandPalette — QA-2026-05-23", () => {
  it("typing 'DES' + Enter navigates to /fn/DES (NOT DDM)", () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "DES" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toBe("#/fn/DES");
  });

  it("multi-word query 'generic price' opens GP, not HP", () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "generic price" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toBe("#/fn/GP");
  });

  it("first-boot Recent shows nothing (no fake seed)", () => {
    render(<CommandPalette />);
    // The placeholder-empty palette state should NOT label any visible
    // group as Recent. Once the user opens at least one function the
    // recents bucket will fill — but on first paint it is empty.
    expect(screen.queryByText("Recent")).toBeNull();
  });

  it("cmd+k INSIDE the palette no longer re-toggles (was a collision)", () => {
    render(<CommandPalette />);
    expect(useAppStore.getState().paletteOpen).toBe(true);
    act(() => {
      // Fire cmd+k at the window. With the duplicate handler removed,
      // Palette.tsx must NOT respond — only Escape closes from inside.
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "k", metaKey: true }),
      );
    });
    expect(useAppStore.getState().paletteOpen).toBe(true);
  });

  it("Escape closes the palette", () => {
    render(<CommandPalette />);
    expect(useAppStore.getState().paletteOpen).toBe(true);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(useAppStore.getState().paletteOpen).toBe(false);
  });
});
