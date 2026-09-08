/**
 * Lane D — U5 ShortcutsHelp truth pass.
 *
 * The overlay must list every REAL global shortcut (verified in source:
 * App.tsx, Palette.tsx, Workspace.tsx, ShortcutsHelp.tsx) and must NOT
 * advertise shortcuts that don't exist. Pins the 2026-09-08 additions:
 * ⌘J, ⌘1–9, F6/⇧F6, ⌘⇧]/⌘⇧[ pane cycling, splitter resize keys — and the
 * absence of unimplemented proposals (⌘G, sidebar `/`).
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { ShortcutsHelp } from "./ShortcutsHelp";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => cleanup());

function openHelp() {
  const utils = render(<ShortcutsHelp />);
  expect(utils.queryByRole("dialog")).toBeNull();
  fireEvent.keyDown(window, { key: "?" });
  expect(utils.getByRole("dialog")).toBeTruthy();
  return utils;
}

describe("ShortcutsHelp truth pass", () => {
  it("opens with ? and closes with Escape", () => {
    const { queryByRole, getByRole } = render(<ShortcutsHelp />);
    fireEvent.keyDown(window, { key: "?" });
    expect(getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(queryByRole("dialog")).toBeNull();
  });

  it("lists ⌘J and the palette ⌘1–9 jump (previously omitted)", () => {
    const { getByRole } = openHelp();
    const text = getByRole("dialog").textContent ?? "";
    expect(text).toContain("⌘J");
    expect(text).toContain("⌘1–9");
  });

  it("lists the new pane-focus cycling keys", () => {
    const { getByRole } = openHelp();
    const text = getByRole("dialog").textContent ?? "";
    expect(text).toContain("F6 / ⇧F6");
    expect(text).toContain("⌘⇧] / ⌘⇧[");
  });

  it("documents the real splitter keyboard resize + Esc cancel", () => {
    const { getByRole } = openHelp();
    const text = getByRole("dialog").textContent ?? "";
    expect(text).toContain("Home / End");
    expect(text).toContain("Resize focused splitter by 5%");
    expect(text).toContain("Cancel split drag");
  });

  it("documents the palette navigation keys", () => {
    const { getByRole } = openHelp();
    const text = getByRole("dialog").textContent ?? "";
    expect(text).toContain("Move selection");
    expect(text).toContain("Open selection");
    expect(text).toContain("Close palette");
  });

  it("keeps the previously documented workspace shortcuts", () => {
    const { getByRole } = openHelp();
    const text = getByRole("dialog").textContent ?? "";
    expect(text).toContain("⌘K");
    expect(text).toContain("⌘B");
    expect(text).toContain("⌘\\");
    expect(text).toContain("⌘⇧\\");
    expect(text).toContain("⌘W");
    expect(text).toContain("?");
  });

  it("does NOT advertise shortcuts that have no handler (⌘G, sidebar /)", () => {
    const { getByRole } = openHelp();
    const text = getByRole("dialog").textContent ?? "";
    expect(text).not.toContain("⌘G");
    expect(text).not.toContain("Sidebar search");
  });
});
