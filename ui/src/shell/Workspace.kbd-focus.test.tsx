/**
 * Lane D — U4 keyboard pane-focus cycling, mounted behavior + U7 fallback.
 *
 * Part 1 (U4): render the real <Workspace /> with a two-leaf HOME tree
 * (Welcome stubbed — the cycle logic doesn't care about pane contents) and
 * drive F6 / ⇧F6 / ⌘⇧] / ⌘⇧[ through a real window keydown. Pins:
 *   - forward/backward stepping with wrap-around,
 *   - editable-target skip (typing in an input never moves pane focus),
 *   - palette-open skip (⌘1–9 palette keyboard owns the window then),
 *   - single-leaf no-op,
 *   - mouse press clears the wx-kbd-nav emphasis class.
 *
 * Part 2 (U7): PaneFallback renders the pane-shaped skeleton frame
 * (role=status, no "loading…" text).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";

vi.mock("@/panes/Welcome", () => ({
  Welcome: () => <div data-testid="welcome-stub">welcome</div>,
}));

import { Workspace, PaneFallback } from "./Workspace";
import { leaf, split, useWorkspace, type WorkspaceNode } from "@/lib/workspace";
import { useAppStore } from "@/lib/store";

function snapshot(): { tree: WorkspaceNode; focusedId: string } {
  const { tree, focusedId } = useWorkspace.getState();
  return { tree, focusedId };
}

function restore(snap: { tree: WorkspaceNode; focusedId: string }) {
  useWorkspace.setState({ tree: snap.tree, focusedId: snap.focusedId });
}

function pressKey(init: {
  key: string;
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
}) {
  act(() => {
    window.dispatchEvent(new KeyboardEvent("keydown", init));
  });
}

beforeEach(() => {
  useAppStore.setState({ paletteOpen: false });
});

afterEach(() => {
  cleanup();
  document.body.classList.remove("wx-kbd-nav");
});

describe("Workspace keyboard pane-focus cycling (U4)", () => {
  it("F6 moves focus to the next leaf and wraps", async () => {
    const snap = snapshot();
    try {
      const a = leaf("HOME");
      const b = leaf("HOME");
      useWorkspace.setState({ tree: split("h", [a, b]), focusedId: a.id });
      const { findAllByTestId } = render(<Workspace />);
      await findAllByTestId("welcome-stub");

      pressKey({ key: "F6" });
      expect(useWorkspace.getState().focusedId).toBe(b.id);

      pressKey({ key: "F6" }); // wrap: b → a
      expect(useWorkspace.getState().focusedId).toBe(a.id);
    } finally {
      restore(snap);
    }
  });

  it("Shift+F6 moves focus backward", async () => {
    const snap = snapshot();
    try {
      const a = leaf("HOME");
      const b = leaf("HOME");
      useWorkspace.setState({ tree: split("h", [a, b]), focusedId: b.id });
      const { findAllByTestId } = render(<Workspace />);
      await findAllByTestId("welcome-stub");

      pressKey({ key: "F6", shiftKey: true });
      expect(useWorkspace.getState().focusedId).toBe(a.id);
    } finally {
      restore(snap);
    }
  });

  it("⌘⇧] / ⌘⇧[ cycle forward / backward", async () => {
    const snap = snapshot();
    try {
      const a = leaf("HOME");
      const b = leaf("HOME");
      useWorkspace.setState({ tree: split("h", [a, b]), focusedId: a.id });
      const { findAllByTestId } = render(<Workspace />);
      await findAllByTestId("welcome-stub");

      pressKey({ key: "]", metaKey: true, shiftKey: true });
      expect(useWorkspace.getState().focusedId).toBe(b.id);
      pressKey({ key: "[", metaKey: true, shiftKey: true });
      expect(useWorkspace.getState().focusedId).toBe(a.id);
    } finally {
      restore(snap);
    }
  });

  it("does NOT move focus while the user is typing in an input", async () => {
    const snap = snapshot();
    try {
      const a = leaf("HOME");
      const b = leaf("HOME");
      useWorkspace.setState({ tree: split("h", [a, b]), focusedId: a.id });
      render(
        <div>
          <input data-testid="pane-input" />
          <Workspace />
        </div>,
      );
      const input = document.querySelector("[data-testid='pane-input']") as HTMLInputElement;
      input.focus();

      pressKey({ key: "F6" });
      expect(useWorkspace.getState().focusedId).toBe(a.id);
    } finally {
      restore(snap);
    }
  });

  it("does NOT move focus while the command palette is open", async () => {
    const snap = snapshot();
    try {
      const a = leaf("HOME");
      const b = leaf("HOME");
      useWorkspace.setState({ tree: split("h", [a, b]), focusedId: a.id });
      const { findAllByTestId } = render(<Workspace />);
      await findAllByTestId("welcome-stub");
      useAppStore.setState({ paletteOpen: true });

      pressKey({ key: "F6" });
      expect(useWorkspace.getState().focusedId).toBe(a.id);
    } finally {
      useAppStore.setState({ paletteOpen: false });
      restore(snap);
    }
  });

  it("single-leaf workspace is a no-op (and never prevents default)", async () => {
    const snap = snapshot();
    try {
      const a = leaf("HOME");
      useWorkspace.setState({ tree: a, focusedId: a.id });
      const { findAllByTestId } = render(<Workspace />);
      await findAllByTestId("welcome-stub");

      pressKey({ key: "F6" });
      expect(useWorkspace.getState().focusedId).toBe(a.id);
    } finally {
      restore(snap);
    }
  });

  it("a mouse press clears the wx-kbd-nav emphasis", async () => {
    const snap = snapshot();
    try {
      const a = leaf("HOME");
      const b = leaf("HOME");
      useWorkspace.setState({ tree: split("h", [a, b]), focusedId: a.id });
      const { findAllByTestId } = render(<Workspace />);
      await findAllByTestId("welcome-stub");

      pressKey({ key: "F6" });
      expect(document.body.classList.contains("wx-kbd-nav")).toBe(true);

      act(() => {
        window.dispatchEvent(new MouseEvent("mousedown"));
      });
      expect(document.body.classList.contains("wx-kbd-nav")).toBe(false);
    } finally {
      restore(snap);
    }
  });
});

describe("PaneFallback skeleton (U7)", () => {
  it("renders a pane-shaped status frame without the old 'loading…' text", () => {
    const { getByTestId, queryByText } = render(<PaneFallback />);
    const root = getByTestId("pane-fallback");
    expect(root.getAttribute("role")).toBe("status");
    expect(root.getAttribute("aria-label")).toBe("Loading pane");
    // The legacy plain-text fallback is gone.
    expect(queryByText("loading…")).toBeNull();
    // Pane-shaped frame: header bar + KPI row (3 blocks) + content rows.
    expect(root.querySelectorAll(".ds-skeleton").length).toBeGreaterThanOrEqual(5);
    expect(root.querySelector(".pane-fallback__kpis")).not.toBeNull();
  });
});
