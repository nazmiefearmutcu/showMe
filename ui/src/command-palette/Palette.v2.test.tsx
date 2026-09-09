/**
 * Palette v2 (campaign 2026-09-08, Lane B / U1).
 *
 * The ⌘K surface now answers tickers and verbs, not just function codes:
 *   - symbol rows come from the known universe (recents, bound leaf
 *     symbols, curated quick list, S&P 500 catalog) and Enter rebinds the
 *     focused pane via /symbol/<SYM>/<focused code>;
 *   - action rows run real store verbs (theme presets, builtin layout
 *     presets, save-layout, sidebar toggle);
 *   - recents-first ranking now spans functions, tickers, and actions.
 * Function-catalog behaviour is regression-pinned by Palette.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, cleanup, waitFor } from "@testing-library/react";
import { CommandPalette } from "./Palette";
import { useAppStore } from "@/lib/store";
import { useWorkspace } from "@/lib/workspace";
import { __resetForTests as resetRecents } from "@/lib/palette-recents";
import { clearRecentSymbols, pushRecentSymbol } from "@/lib/symbols";

function setIndex() {
  useAppStore.setState({
    functionIndex: [
      { code: "DDM", name: "Dividend Discount Model", category: "equity", description: "" },
      { code: "DES", name: "Description", category: "equity", description: "" },
      { code: "GP", name: "Generic Price", category: "chart", description: "" },
    ],
  });
}

function focusLeaf(code: string, symbol?: string) {
  useWorkspace.setState({
    tree: { kind: "leaf", id: "L1", code, symbol },
    focusedId: "L1",
  } as never);
}

beforeEach(() => {
  window.location.hash = "#/";
  localStorage.clear();
  resetRecents();
  clearRecentSymbols();
  setIndex();
  focusLeaf("DES");
  useAppStore.setState({ paletteOpen: true });
});

afterEach(() => {
  cleanup();
  useAppStore.setState({ paletteOpen: false, shortcutsOpen: false });
  localStorage.clear();
  document.documentElement.removeAttribute("data-preset");
});

describe("CommandPalette v2 — symbols", () => {
  it("typing AAPL offers a symbol row bound to the focused pane's function", () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "AAPL" } });
    const option = screen.getByRole("option", { name: /Open AAPL in focused pane \(DES\)/ });
    expect(option).toBeTruthy();
  });

  it("Enter on a symbol row navigates to /symbol/AAPL/<focused code>", () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "AAPL" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toBe("#/symbol/AAPL/DES");
  });

  it("falls back to DES when the focused pane is HOME", () => {
    focusLeaf("HOME");
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "NVDA" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.hash).toBe("#/symbol/NVDA/DES");
  });

  it("empty query shows a Recent symbols block fed by the symbol recents stack", () => {
    pushRecentSymbol("TSLA");
    render(<CommandPalette />);
    expect(screen.getByText("Recent symbols")).toBeTruthy();
    expect(
      screen.getByRole("option", { name: /Open TSLA in focused pane \(DES\)/ }),
    ).toBeTruthy();
  });

  it("static catalog symbols are searchable (MSFT via the curated quick list)", () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "MSFT" } });
    expect(
      screen.getByRole("option", { name: /Open MSFT in focused pane \(DES\)/ }),
    ).toBeTruthy();
  });
});

describe("CommandPalette v2 — actions", () => {
  it("typing 'theme' surfaces theme actions and choosing one applies the preset", () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "theme" } });
    const matrix = screen.getByRole("option", { name: /Switch theme to Matrix/ });
    fireEvent.click(matrix);
    expect(document.documentElement.getAttribute("data-preset")).toBe("matrix");
    expect(useAppStore.getState().paletteOpen).toBe(false);
  });

  it("layout action loads a builtin preset into the workspace tree", async () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "layout" } });
    fireEvent.click(
      screen.getByRole("option", { name: /Load layout: Markets Overview/ }),
    );
    await waitFor(() => {
      expect(useWorkspace.getState().tree.kind).toBe("split");
    });
  });

  it("save-layout action persists a desk-* preset via the localStorage backend", async () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "save current layout" } });
    fireEvent.click(
      screen.getByRole("option", { name: /Save current layout as preset/ }),
    );
    await waitFor(() => {
      const raw = localStorage.getItem("showme.layout-presets");
      expect(raw).toBeTruthy();
      expect(raw as string).toContain("desk-");
    });
  });

  it("preference action toggles the functions sidebar store flag", () => {
    const before = useAppStore.getState().sidebarVisible;
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "sidebar" } });
    fireEvent.click(
      screen.getByRole("option", { name: /Toggle functions sidebar/ }),
    );
    expect(useAppStore.getState().sidebarVisible).toBe(!before);
  });

  it("a chosen action ranks first on the next empty open (Recent actions)", () => {
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "theme" } });
    fireEvent.click(screen.getByRole("option", { name: /Switch theme to Matrix/ }));

    cleanup();
    useAppStore.setState({ paletteOpen: true });
    render(<CommandPalette />);
    expect(screen.getByText("Recent actions")).toBeTruthy();
    expect(
      screen.getByRole("option", { name: /Switch theme to Matrix/ }),
    ).toBeTruthy();
  });

  it("the 'Shortcuts help' action opens the cheat sheet via the store and closes the palette", () => {
    expect(useAppStore.getState().shortcutsOpen).toBe(false);
    render(<CommandPalette />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "shortcuts" } });
    const option = screen.getByRole("option", { name: /Shortcuts help/ });
    expect(option).toBeTruthy();
    fireEvent.click(option);
    // The overlay reads `shortcutsOpen` from the store (same flag the `?`
    // key flips), and running any action closes the palette.
    expect(useAppStore.getState().shortcutsOpen).toBe(true);
    expect(useAppStore.getState().paletteOpen).toBe(false);
  });
});
