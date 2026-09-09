/**
 * Lane D — U4 pane-focus cycling: pure helpers + editable-target guard.
 *
 * The DOM wiring (window keydown → setFocused) is covered by
 * shell/Workspace.kbd-focus.test.tsx; here we pin the fold/ordering math
 * so wrap-around, single-leaf no-ops, and stale-focus recovery can't
 * regress.
 */
import { describe, expect, it } from "vitest";
import { leaf, split, type WorkspaceNode } from "./workspace";
import {
  cycleDeltaFromEvent,
  isTextTarget,
  listLeafIds,
  nextFocusedLeafId,
} from "./pane-focus-cycle";

function tree3(): { node: WorkspaceNode; ids: string[] } {
  const a = leaf("HOME");
  const b = leaf("GP");
  const c = leaf("DES");
  const node = split("v", [a, split("h", [b, c])]);
  return { node, ids: [a.id, b.id, c.id] };
}

describe("listLeafIds", () => {
  it("returns leaves in depth-first visual order", () => {
    const { node, ids } = tree3();
    expect(listLeafIds(node)).toEqual(ids);
  });

  it("returns a single id for a bare leaf", () => {
    const a = leaf("HOME");
    expect(listLeafIds(a)).toEqual([a.id]);
  });
});

describe("nextFocusedLeafId", () => {
  it("steps forward and backward through the tree order", () => {
    const { node, ids } = tree3();
    expect(nextFocusedLeafId(node, ids[0]!, 1)).toBe(ids[1]);
    expect(nextFocusedLeafId(node, ids[1]!, 1)).toBe(ids[2]);
    expect(nextFocusedLeafId(node, ids[2]!, -1)).toBe(ids[1]);
    expect(nextFocusedLeafId(node, ids[1]!, -1)).toBe(ids[0]);
  });

  it("wraps both ends", () => {
    const { node, ids } = tree3();
    expect(nextFocusedLeafId(node, ids[2]!, 1)).toBe(ids[0]);
    expect(nextFocusedLeafId(node, ids[0]!, -1)).toBe(ids[2]);
  });

  it("returns null for a single leaf (nothing to cycle)", () => {
    const a = leaf("HOME");
    expect(nextFocusedLeafId(a, a.id, 1)).toBeNull();
  });

  it("recovers from a stale focusedId by starting from the first leaf", () => {
    const { node, ids } = tree3();
    expect(nextFocusedLeafId(node, "n-gone", 1)).toBe(ids[1]);
    expect(nextFocusedLeafId(node, "n-gone", -1)).toBe(ids[ids.length - 1]);
  });
});

describe("cycleDeltaFromEvent", () => {
  it("maps F6 / Shift+F6 to +1 / -1", () => {
    expect(cycleDeltaFromEvent(kb({ key: "F6" }))).toBe(1);
    expect(cycleDeltaFromEvent(kb({ key: "F6", shiftKey: true }))).toBe(-1);
  });

  it("ignores F6 with ⌘/Ctrl/Alt", () => {
    expect(cycleDeltaFromEvent(kb({ key: "F6", metaKey: true }))).toBeNull();
    expect(cycleDeltaFromEvent(kb({ key: "F6", ctrlKey: true }))).toBeNull();
    expect(cycleDeltaFromEvent(kb({ key: "F6", altKey: true }))).toBeNull();
  });

  it("maps ⌘⇧] / ⌘⇧[ (and brace variants) to +1 / -1", () => {
    expect(cycleDeltaFromEvent(kb({ key: "]", metaKey: true, shiftKey: true }))).toBe(1);
    expect(cycleDeltaFromEvent(kb({ key: "}", metaKey: true, shiftKey: true }))).toBe(1);
    expect(cycleDeltaFromEvent(kb({ key: "[", ctrlKey: true, shiftKey: true }))).toBe(-1);
    expect(cycleDeltaFromEvent(kb({ key: "{", ctrlKey: true, shiftKey: true }))).toBe(-1);
  });

  it("ignores bracket keys without shift, and plain brackets", () => {
    expect(cycleDeltaFromEvent(kb({ key: "]", metaKey: true }))).toBeNull();
    expect(cycleDeltaFromEvent(kb({ key: "[" }))).toBeNull();
    expect(cycleDeltaFromEvent(kb({ key: "]", metaKey: true, shiftKey: true, altKey: true }))).toBeNull();
  });

  it("ignores unrelated keys", () => {
    expect(cycleDeltaFromEvent(kb({ key: "k", metaKey: true }))).toBeNull();
    expect(cycleDeltaFromEvent(kb({ key: "?" }))).toBeNull();
  });
});

describe("isTextTarget", () => {
  it("skips when the event originates in an input", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    try {
      expect(isTextTarget(kb({ key: "F6", target: input }))).toBe(true);
    } finally {
      input.remove();
    }
  });

  it("skips when the ACTIVE element is editable even if target is a wrapper", () => {
    const wrap = document.createElement("div");
    const input = document.createElement("textarea");
    wrap.appendChild(input);
    document.body.appendChild(wrap);
    input.focus();
    try {
      expect(isTextTarget(kb({ key: "F6", target: wrap }))).toBe(true);
    } finally {
      input.blur();
      wrap.remove();
    }
  });

  it("does not skip plain pane surfaces", () => {
    const div = document.createElement("div");
    document.body.appendChild(div);
    try {
      expect(isTextTarget(kb({ key: "F6", target: div }))).toBe(false);
    } finally {
      div.remove();
    }
  });

  it("skips a programmatically contenteditable host (isContentEditable, no matchable attribute)", () => {
    const div = document.createElement("div");
    document.body.appendChild(div);
    // `el.contentEditable = "true"` via script leaves no attribute value
    // the closest() selector can match — only the property saves us.
    Object.defineProperty(div, "isContentEditable", {
      value: true,
      configurable: true,
    });
    try {
      expect(isTextTarget(kb({ key: "F6", target: div }))).toBe(true);
    } finally {
      div.remove();
    }
  });

  it("skips when the ACTIVE element is programmatically contenteditable", () => {
    const wrap = document.createElement("div");
    const editor = document.createElement("div");
    wrap.appendChild(editor);
    document.body.appendChild(wrap);
    Object.defineProperty(editor, "isContentEditable", {
      value: true,
      configurable: true,
    });
    editor.tabIndex = 0;
    editor.focus();
    try {
      // Target is the non-editable wrapper; the guard must still catch the
      // editable activeElement via the property check.
      expect(isTextTarget(kb({ key: "F6", target: wrap }))).toBe(true);
    } finally {
      editor.blur();
      wrap.remove();
    }
  });
});

/** Minimal KeyboardEvent stand-in (jsdom constructors are enough for most cases). */
function kb(
  opts: {
    key: string;
    shiftKey?: boolean;
    metaKey?: boolean;
    ctrlKey?: boolean;
    altKey?: boolean;
    target?: EventTarget | null;
  },
): KeyboardEvent {
  const event = new KeyboardEvent("keydown", {
    key: opts.key,
    shiftKey: opts.shiftKey ?? false,
    metaKey: opts.metaKey ?? false,
    ctrlKey: opts.ctrlKey ?? false,
    altKey: opts.altKey ?? false,
  });
  if (opts.target !== undefined) {
    Object.defineProperty(event, "target", { value: opts.target });
  }
  return event;
}
