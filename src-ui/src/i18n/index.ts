/**
 * i18n loader skeleton.
 *
 * Catalogs live as JSON files alongside this module. Round 13 ships English +
 * Turkish (the project's two primary languages) plus stubs for the other 10
 * Rapor 1 §17.4 targets — they fall back to English until a translator fills
 * the keys.
 *
 * Round 14+ adds Intl.NumberFormat / Intl.DateTimeFormat helpers + RTL.
 */
import en from "./en.json";
import tr from "./tr.json";

export type Locale =
  | "en" | "tr" | "de" | "fr" | "es" | "it"
  | "ja" | "zh" | "ko" | "ar" | "pt" | "ru";

const SUPPORTED: Locale[] = [
  "en", "tr", "de", "fr", "es", "it", "ja", "zh", "ko", "ar", "pt", "ru",
];

type Catalog = Record<string, string>;

const CATALOGS: Record<string, Catalog> = {
  en: en as Catalog,
  tr: tr as Catalog,
};

let active: Locale = pickInitial();

function pickInitial(): Locale {
  if (typeof navigator !== "undefined") {
    const lang = navigator.language?.slice(0, 2).toLowerCase();
    if (lang && SUPPORTED.includes(lang as Locale)) return lang as Locale;
  }
  return "en";
}

export function setLocale(loc: Locale) {
  active = SUPPORTED.includes(loc) ? loc : "en";
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("lang", active);
    document.documentElement.setAttribute("dir", active === "ar" ? "rtl" : "ltr");
  }
}

export function locale(): Locale {
  return active;
}

export function listLocales(): Locale[] {
  return SUPPORTED.slice();
}

export function t(key: string, fallback?: string): string {
  const dict = CATALOGS[active] ?? CATALOGS.en;
  if (key in dict) return dict[key];
  // Fallback chain: active → en → caller fallback → key.
  if (active !== "en" && key in CATALOGS.en) return CATALOGS.en[key];
  return fallback ?? key;
}
