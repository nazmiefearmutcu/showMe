/**
 * PresetMenu — "Reset to default desk" (UI-finish wave F, 2026-09-09).
 *
 * Pins the destructive-reset contract:
 *   - the menu exposes a Reset item;
 *   - it confirms first via the shared ConfirmDialog (destructive styling,
 *     Cancel is the focused default);
 *   - Cancel leaves the live tree untouched;
 *   - Confirm loads the canonical `home` builtin preset through
 *     loadBuiltinPreset → the workspace collapses to a single HOME leaf.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PresetMenu } from "./PresetMenu";
import { useWorkspace, leaf, split } from "@/lib/workspace";

// Tauri invoke is a no-op in jsdom; listPresets falls back to localStorage.
vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => undefined),
  listen: vi.fn(async () => () => undefined),
}));

function seedSplitDesk() {
  const tree = split("v", [leaf("DES"), leaf("GP")]);
  useWorkspace.setState({ tree, focusedId: tree.kind === "split" ? tree.children[0].id : "" });
}

function leafCodes(node: ReturnType<typeof useWorkspace.getState>["tree"]): string[] {
  if (node.kind === "leaf") return [node.code];
  return node.children.flatMap(leafCodes);
}

beforeEach(() => {
  localStorage.clear();
  seedSplitDesk();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("PresetMenu — reset to default desk", () => {
  it("offers the reset item and confirms before touching the desk", () => {
    render(<PresetMenu />);
    fireEvent.click(screen.getByRole("button", { name: "⌘ Layout" }));
    const reset = screen.getByTestId("preset-menu-reset");
    fireEvent.click(reset);
    // Destructive confirm is up; the desk is still the seeded split.
    expect(screen.getByTestId("confirm-dialog-body")).toBeTruthy();
    expect(leafCodes(useWorkspace.getState().tree)).toEqual(["DES", "GP"]);
  });

  it("cancel keeps the current layout", () => {
    render(<PresetMenu />);
    fireEvent.click(screen.getByRole("button", { name: "⌘ Layout" }));
    fireEvent.click(screen.getByTestId("preset-menu-reset"));
    fireEvent.click(screen.getByTestId("confirm-dialog-cancel"));
    expect(screen.queryByTestId("confirm-dialog-body")).toBeNull();
    expect(leafCodes(useWorkspace.getState().tree)).toEqual(["DES", "GP"]);
  });

  it("confirm collapses the workspace to the canonical single HOME leaf", () => {
    render(<PresetMenu />);
    fireEvent.click(screen.getByRole("button", { name: "⌘ Layout" }));
    fireEvent.click(screen.getByTestId("preset-menu-reset"));
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    const tree = useWorkspace.getState().tree;
    expect(tree.kind).toBe("leaf");
    expect(leafCodes(tree)).toEqual(["HOME"]);
    expect(screen.queryByTestId("confirm-dialog-body")).toBeNull();
  });
});
