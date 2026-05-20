/**
 * Round-2B i18n tests (A11Y-10):
 *   - English/Turkish key parity
 *   - {var} interpolation works
 *   - locale persists across calls (re-pick after setLocale)
 */
import { describe, expect, it } from "vitest";
import en from "./en.json";
import tr from "./tr.json";
import { setLocale, locale, t, isLocaleComplete } from "./index";

describe("i18n catalog parity", () => {
  it("ships English ≥ 100 keys (round-13 had 33)", () => {
    expect(Object.keys(en).length).toBeGreaterThanOrEqual(100);
  });

  it("Turkish covers every English key", () => {
    const enKeys = Object.keys(en);
    const trKeys = new Set(Object.keys(tr));
    const missing = enKeys.filter((k) => !trKeys.has(k));
    expect(missing).toEqual([]);
  });

  it("isLocaleComplete returns true for tr, false for de (no catalog yet)", () => {
    expect(isLocaleComplete("tr")).toBe(true);
    expect(isLocaleComplete("de")).toBe(false);
  });
});

describe("t() interpolation + persistence", () => {
  it("falls back to English when active key is missing in tr (no key→returns key)", () => {
    setLocale("tr");
    expect(t("definitely.missing.key")).toBe("definitely.missing.key");
  });

  it("interpolates {var} placeholders", () => {
    setLocale("en");
    expect(t("shell.sidebar.filtered_count", { count: 4, total: 12 })).toBe("4 of 12");
  });

  it("persists locale to localStorage and re-applies after setLocale", () => {
    setLocale("tr");
    expect(locale()).toBe("tr");
    expect(window.localStorage.getItem("showme.locale.v1")).toBe("tr");
    setLocale("en");
    expect(locale()).toBe("en");
  });
});
