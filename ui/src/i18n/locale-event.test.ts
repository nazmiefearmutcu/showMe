/**
 * Session-08 BugHunt pin: setLocale must dispatch a LOCALE_CHANGE_EVENT so
 * the shell, sidebar, and statusbar can re-render after LANG persists the
 * runtime/lang.txt file. Without this event the FunctionStub LANG hook
 * silently writes localStorage and `<html lang>` but leaves stale strings.
 */
import { describe, expect, it, beforeEach } from "vitest";
import { setLocale, locale, LOCALE_CHANGE_EVENT } from "./index";

describe("i18n setLocale", () => {
  beforeEach(() => {
    setLocale("en");
  });

  it("dispatches LOCALE_CHANGE_EVENT when the locale actually changes", () => {
    const captured: string[] = [];
    const listener = (e: Event) => {
      captured.push((e as CustomEvent<{ locale: string }>).detail?.locale);
    };
    window.addEventListener(LOCALE_CHANGE_EVENT, listener);
    setLocale("tr");
    window.removeEventListener(LOCALE_CHANGE_EVENT, listener);

    expect(captured).toEqual(["tr"]);
    expect(locale()).toBe("tr");
    expect(document.documentElement.getAttribute("lang")).toBe("tr");
  });

  it("does NOT dispatch when the same locale is set twice", () => {
    setLocale("en");
    const captured: string[] = [];
    const listener = (e: Event) => {
      captured.push((e as CustomEvent<{ locale: string }>).detail?.locale);
    };
    window.addEventListener(LOCALE_CHANGE_EVENT, listener);
    setLocale("en");
    window.removeEventListener(LOCALE_CHANGE_EVENT, listener);
    expect(captured).toEqual([]);
  });

  it("flips dir=rtl for Arabic", () => {
    setLocale("ar");
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
    setLocale("tr");
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });
});
