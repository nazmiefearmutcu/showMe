/**
 * MEDIUM (UI-Shell-Bundle UB) — Sidebar must not highlight Settings/PREF
 * when the active route is the not-found surface.
 *
 * The legacy `activeCode` ternary collapsed every non-function, non-
 * welcome route to "PREF" — including "not-found". That made the
 * Settings entry in the sidebar light up with `aria-current="page"`
 * even when the user landed on a bogus URL.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { act } from "react";
import { Sidebar } from "./Sidebar";
import { useAppStore } from "@/lib/store";
import { __resetForTests as resetRecents } from "@/lib/palette-recents";

function seedIndex() {
  useAppStore.setState({
    functionIndex: [
      { code: "DES", name: "Description", category: "equity", description: "" },
    ],
  });
  useAppStore.getState().toggleSidebar(true);
}

beforeEach(() => {
  window.location.hash = "#/";
  resetRecents();
  seedIndex();
});

afterEach(() => {
  cleanup();
});

describe("Sidebar activeCode on not-found route", () => {
  it("PREF entry has NO aria-current when route is not-found", () => {
    act(() => {
      window.location.hash = "#/totally/garbage/route";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    render(<Sidebar />);
    // The Settings shortcut should not advertise as the current page.
    const allCurrent = document.querySelectorAll('[aria-current="page"]');
    const labels = Array.from(allCurrent).map((el) => el.textContent ?? "");
    expect(labels.some((l) => l.includes("Settings"))).toBe(false);
  });

  it("PREF entry still highlights when route is /preferences", () => {
    act(() => {
      window.location.hash = "#/preferences";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    render(<Sidebar />);
    const allCurrent = document.querySelectorAll('[aria-current="page"]');
    const labels = Array.from(allCurrent).map((el) => el.textContent ?? "");
    // Settings/PREF should be active.
    expect(labels.some((l) => l.includes("Settings"))).toBe(true);
  });

  it("DES highlights when route is /fn/DES (regression for the function branch)", () => {
    act(() => {
      window.location.hash = "#/fn/DES";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    render(<Sidebar />);
    // Find any element with aria-current that mentions DES or
    // Description.
    const labels = Array.from(
      document.querySelectorAll('[aria-current="page"]'),
    ).map((el) => el.textContent ?? "");
    const matched = labels.some((l) =>
      /\bDES\b|Description/.test(l),
    );
    expect(matched).toBe(true);
  });
});
