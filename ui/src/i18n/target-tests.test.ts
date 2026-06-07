import { describe, expect, it, beforeEach } from "vitest";
import en from "./en.json";
import { setLocale, t, CATALOGS } from "./index";

describe("Target i18n Verification", () => {
  beforeEach(() => {
    setLocale("en");
  });

  it("should have exactly 137 keys in all registered catalogs", () => {
    for (const dict of Object.values(CATALOGS)) {
      const keys = Object.keys(dict);
      expect(keys.length).toBe(137);
    }
  });

  it("should have exactly the same keys in all registered catalogs", () => {
    const enKeys = Object.keys(en).sort();
    for (const dict of Object.values(CATALOGS)) {
      const locKeys = Object.keys(dict).sort();
      expect(locKeys).toEqual(enKeys);
    }
  });

  it("should translate via t() and not fallback to English when key is missing in active locale", () => {
    setLocale("tr");
    expect(t("common.save")).toBe("Kaydet");
    
    setLocale("fr");
    expect(t("common.save")).toBe("Enregistrer");

    const originalFr = CATALOGS.fr;
    CATALOGS.fr = { ...originalFr };
    delete CATALOGS.fr["common.save"];
    
    expect(t("common.save")).toBe("common.save"); // should not fallback to "Save"
    expect(t("common.save", "Default")).toBe("Default"); // should return fallback

    CATALOGS.fr = originalFr;
  });

  it("should interpolate variables correctly", () => {
    setLocale("en");
    expect(t("shell.sidebar.filtered_count", { count: 5, total: 20 })).toBe("5 of 20");
    
    setLocale("tr");
    expect(t("shell.sidebar.filtered_count", { count: 5, total: 20 })).toBe("5 / 20");
  });

  it("should update document element lang and dir on setLocale", () => {
    setLocale("ar");
    expect(document.documentElement.getAttribute("lang")).toBe("ar");
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");

    setLocale("en");
    expect(document.documentElement.getAttribute("lang")).toBe("en");
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });
});
