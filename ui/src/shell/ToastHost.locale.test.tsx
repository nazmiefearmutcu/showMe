/**
 * Regression — UI-ROBUSTNESS F6.
 *
 * `setLocale` dispatched LOCALE_CHANGE_EVENT but no shell component
 * subscribed: after switching language in Preferences, only the Preferences
 * pane re-rendered — toast copy, Titlebar menus, Sidebar labels and palette
 * text stayed in the old locale until an unrelated state change happened to
 * re-render them.
 *
 * `useLocale()` (useSyncExternalStore over the LOCALE_CHANGE_EVENT) makes
 * the shell reactive. ToastHost is the smallest shell consumer, so it pins
 * the end-to-end behavior: switching locale re-renders the component's
 * translated text.
 */
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { toast, useToastStore } from "@/lib/toast";
import { setLocale, locale, useLocale, CATALOGS, type Locale } from "@/i18n";
import { ToastHost } from "./ToastHost";

beforeEach(() => {
  setLocale("en");
  useToastStore.getState().clear();
});

describe("locale switch re-renders shell text (F6)", () => {
  it("ToastHost dismiss label follows the active locale", () => {
    const { container } = render(<ToastHost />);
    act(() => {
      toast.info("Session saved", "The workspace was persisted.");
    });
    const button = container.querySelector(".toast-host__dismiss");
    expect(button).not.toBeNull();
    expect(button?.getAttribute("aria-label")).toBe(
      CATALOGS.en["shell.toast.dismiss"],
    );

    act(() => {
      setLocale("tr");
    });
    expect(button?.getAttribute("aria-label")).toBe(
      CATALOGS.tr["shell.toast.dismiss"],
    );

    act(() => {
      setLocale("en");
    });
    expect(button?.getAttribute("aria-label")).toBe(
      CATALOGS.en["shell.toast.dismiss"],
    );
  });

  it("useLocale() returns the live locale value", () => {
    let seen: Locale | null = null;
    function Probe() {
      seen = useLocale();
      return null;
    }
    render(<Probe />);
    expect(seen).toBe("en");
    act(() => {
      setLocale("ja");
    });
    expect(seen).toBe("ja");
    expect(locale()).toBe("ja");
    act(() => {
      setLocale("en");
    });
    expect(seen).toBe("en");
  });

  it("screen-reader-visible text actually updates (label query)", () => {
    render(<ToastHost />);
    act(() => {
      toast.warn("Live data disconnected", "Retrying…");
    });
    const before = screen.getByRole("button", {
      name: CATALOGS.en["shell.toast.dismiss"],
    });
    act(() => {
      setLocale("tr");
    });
    // The same DOM node now carries the Turkish accessible name.
    expect(before.getAttribute("aria-label")).toBe(
      CATALOGS.tr["shell.toast.dismiss"],
    );
    act(() => {
      setLocale("en");
    });
  });
});
