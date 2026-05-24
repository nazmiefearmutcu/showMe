/**
 * HIGH #5 (UI-Shell-Bundle UB) — cmd+W/B/K must NOT fire while the user
 * is typing in an editable surface (input/textarea/contenteditable).
 *
 * These tests exercise `isEditableTarget` in isolation. Rendering the
 * full `<App />` requires the Tauri shell + sidecar mocks; the guard
 * itself is small and pure enough to test directly.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { isEditableTarget } from "./App";

function makeEvent(target: Element | Document): KeyboardEvent {
  // Build a real KeyboardEvent so `target` is a true Element.
  const evt = new KeyboardEvent("keydown", {
    key: "w",
    metaKey: true,
    bubbles: true,
  });
  // KeyboardEvent.target is read-only when dispatched via DOM, but
  // assignable on the constructed instance via defineProperty.
  Object.defineProperty(evt, "target", { value: target, configurable: true });
  return evt;
}

function clearBody(): void {
  while (document.body.firstChild) {
    document.body.removeChild(document.body.firstChild);
  }
}

beforeEach(clearBody);
afterEach(clearBody);

describe("isEditableTarget", () => {
  it("returns true when target is an <input>", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    expect(isEditableTarget(makeEvent(input))).toBe(true);
  });

  it("returns true when target is a <textarea>", () => {
    const ta = document.createElement("textarea");
    document.body.appendChild(ta);
    expect(isEditableTarget(makeEvent(ta))).toBe(true);
  });

  it("returns true when target is a <select>", () => {
    const sel = document.createElement("select");
    document.body.appendChild(sel);
    expect(isEditableTarget(makeEvent(sel))).toBe(true);
  });

  it('returns true when target is inside contenteditable="true"', () => {
    const wrap = document.createElement("div");
    wrap.setAttribute("contenteditable", "true");
    const span = document.createElement("span");
    wrap.appendChild(span);
    document.body.appendChild(wrap);
    expect(isEditableTarget(makeEvent(span))).toBe(true);
  });

  it("returns true when target is inside a nested input wrapper", () => {
    const form = document.createElement("form");
    const wrap = document.createElement("div");
    const input = document.createElement("input");
    wrap.appendChild(input);
    form.appendChild(wrap);
    document.body.appendChild(form);
    expect(isEditableTarget(makeEvent(input))).toBe(true);
  });

  it("returns false for non-editable elements (buttons, divs, links)", () => {
    const btn = document.createElement("button");
    const div = document.createElement("div");
    const a = document.createElement("a");
    document.body.appendChild(btn);
    document.body.appendChild(div);
    document.body.appendChild(a);
    expect(isEditableTarget(makeEvent(btn))).toBe(false);
    expect(isEditableTarget(makeEvent(div))).toBe(false);
    expect(isEditableTarget(makeEvent(a))).toBe(false);
  });

  it("falls back to document.activeElement when target is Document", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    // Some legacy event paths report Document as the target — verify
    // we still detect the editable activeElement.
    expect(isEditableTarget(makeEvent(document))).toBe(true);
  });
});
