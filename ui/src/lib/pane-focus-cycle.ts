/**
 * Pane-focus cycling (upgrade U4, 2026-09-08).
 *
 * Lets the trader move focus pane→pane without touching the mouse:
 *   - F6 / Shift+F6      — cycle forward / backward (standard pane idiom)
 *   - ⌘⇧] / ⌘⇧[          — cycle forward / backward (⌘ = Ctrl on Win/Linux)
 *
 * Composition rules with the EXISTING shortcut scheme (verified against
 * source before wiring):
 *   - App.tsx's global handler only reacts to ⌘[\\\,b,k,j,w] — neither F6
 *     nor ⌘⇧[ / ⌘⇧] collide, so this module registers its OWN window
 *     keydown listener instead of extending App.tsx (App.tsx is outside
 *     Lane D's file zone).
 *   - When the command palette is open, ⌘1–9 / arrows / Enter own the
 *     keyboard and this handler bails out on `paletteOpen`.
 *   - When focus is inside an editable surface (input / textarea /
 *     contenteditable) the handler bails — same guard semantics as
 *     App.tsx's `isEditableTarget` (duplicated here as `isTextTarget`
 *     because importing App.tsx from a lib module would create an
 *     import cycle: App → Workspace → this module → App).
 *
 * Visible focus: cycling stamps `wx-kbd-nav` on <body> so the focused
 * leaf picks up the accent outline from styles/workspace-ux.css; the
 * class is dropped on the next mouse press so pointer users keep the
 * quiet resting treatment.
 */
import { useEffect } from "react";
import { useWorkspace, type WorkspaceNode } from "./workspace";
import { useAppStore } from "./store";

/** Depth-first leaf ids in visual (tree) order. `firstLeafId` fold pattern. */
export function listLeafIds(node: WorkspaceNode, out: string[] = []): string[] {
  if (node.kind === "leaf") {
    out.push(node.id);
    return out;
  }
  for (const child of node.children) listLeafIds(child, out);
  return out;
}

/**
 * Pure focus-cycle step. Returns the id of the leaf `delta` positions from
 * `focusedId` (wrapping both ends), or null when there is nothing to move
 * to (single leaf, empty tree). An unknown `focusedId` (stale tree) starts
 * from the first leaf so the cycle still behaves.
 */
export function nextFocusedLeafId(
  tree: WorkspaceNode,
  focusedId: string,
  delta: number,
): string | null {
  const ids = listLeafIds(tree);
  if (ids.length < 2) return null;
  const idx = ids.indexOf(focusedId);
  const base = idx === -1 ? 0 : idx;
  const next = (((base + delta) % ids.length) + ids.length) % ids.length;
  return ids[next] ?? null;
}

/**
 * Same editable-surface guard semantics as App.tsx `isEditableTarget`
 * (HIGH #5): checks BOTH the event target and the active element because
 * `e.target` may be a wrapping form, not the editable child.
 *
 * Lane F (2026-09-09): also honors `node.isContentEditable === true` —
 * the attribute selectors miss hosts made editable programmatically
 * (`el.contentEditable = "true"` with no literal attribute value the
 * selector can match) and `contenteditable="plaintext-only"` hosts.
 */
export function isTextTarget(e: KeyboardEvent): boolean {
  const candidates: (Element | null | undefined)[] = [
    e.target as Element | null,
    typeof document !== "undefined" ? document.activeElement : null,
  ];
  for (const node of candidates) {
    if (!node || !(node instanceof Element)) continue;
    if (node.closest('input,textarea,select,[contenteditable="true"],[contenteditable=""]')) {
      return true;
    }
    // `Element` typings in this repo's TS lib predate `isContentEditable`;
    // the property exists on every Element at runtime.
    if ((node as HTMLElement).isContentEditable) return true;
  }
  return false;
}

/**
 * Map a keydown to a cycle delta: +1 forward, -1 backward, null = not a
 * cycling key (or modifier combination this handler must not own).
 */
export function cycleDeltaFromEvent(e: KeyboardEvent): -1 | 0 | 1 | null {
  // F6 / Shift+F6 — bare key, no ⌘/Ctrl/Alt.
  if (e.key === "F6") {
    if (e.metaKey || e.ctrlKey || e.altKey) return null;
    return e.shiftKey ? -1 : 1;
  }
  // ⌘⇧] / ⌘⇧[ — matched on physical bracket codes too, because some
  // keyboard layouts report "}" / "{" as `e.key` under Shift.
  if (e.metaKey || e.ctrlKey) {
    if (!e.shiftKey || e.altKey) return null;
    if (e.key === "]" || e.key === "}" || e.code === "BracketRight") return 1;
    if (e.key === "[" || e.key === "{" || e.code === "BracketLeft") return -1;
  }
  return null;
}

/**
 * Mount-once global key listener implementing the cycle. Reads all state
 * from store `getState()` so the effect never re-subscribes on tree churn.
 */
export function usePaneFocusCycle(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const delta = cycleDeltaFromEvent(e);
      if (delta === null) return;
      // Palette owns the keyboard while open (⌘1–9, arrows, Enter).
      if (useAppStore.getState().paletteOpen) return;
      // Never steal keys while the user is typing in a pane input.
      if (isTextTarget(e)) return;
      const { tree, focusedId, setFocused } = useWorkspace.getState();
      const next = nextFocusedLeafId(tree, focusedId, delta);
      if (!next || next === focusedId) return;
      e.preventDefault();
      setFocused(next);
      // Visible keyboard-focus emphasis until the mouse takes over.
      try {
        document.body.classList.add("wx-kbd-nav");
      } catch {
        /* non-DOM environment */
      }
    };
    const onMouseDown = () => {
      try {
        document.body.classList.remove("wx-kbd-nav");
      } catch {
        /* non-DOM environment */
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onMouseDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onMouseDown);
    };
  }, []);
}
