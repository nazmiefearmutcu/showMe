import { beforeEach, describe, expect, it } from "vitest";
import { listLocales, locale, setLocale, t } from "./index";

describe("i18n", () => {
  beforeEach(() => setLocale("en"));

  it("supports the 12 locales targeted in Rapor 1 §17.4", () => {
    expect(listLocales()).toEqual([
      "en", "tr", "de", "fr", "es", "it", "ja", "zh", "ko", "ar", "pt", "ru",
    ]);
  });

  it("falls back to English when key missing in active locale", () => {
    setLocale("de"); // not authored yet → falls back to en
    expect(t("app.name")).toBe("showMe");
  });

  it("returns Turkish translation when active", () => {
    setLocale("tr");
    expect(t("preferences.title")).toBe("Tercihler");
  });

  it("returns key when translation missing everywhere", () => {
    expect(t("nonexistent.key")).toBe("nonexistent.key");
  });

  it("uses caller-supplied fallback if key missing", () => {
    expect(t("nonexistent.other", "(default)")).toBe("(default)");
  });

  it("flips html lang/dir on setLocale", () => {
    setLocale("ar");
    expect(document.documentElement.getAttribute("lang")).toBe("ar");
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
    setLocale("en");
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("rejects unknown locales (silently falls to en)", () => {
    setLocale("xx" as never);
    expect(locale()).toBe("en");
  });
});
