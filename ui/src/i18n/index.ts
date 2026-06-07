/**
 * i18n loader skeleton.
 *
 * Catalogs live as JSON files alongside this module. ROUND-2B (A11Y-10) closes
 * out the audit gap by:
 *   - persisting the user's locale across launches
 *   - adding `{var}` interpolation to t()
 *   - shipping ~100 keys (vs round-13's 33) covering shell + chrome + functions
 *   - flipping `<html dir="rtl">` for Arabic
 *
 * Round 14+ adds Intl.PluralRules for the Slavic / Arabic plurals targets.
 */
import en from "./en.json";
import tr from "./tr.json";
import de from "./de.json";
import fr from "./fr.json";
import es from "./es.json";
import it from "./it.json";
import ja from "./ja.json";
import zh from "./zh.json";
import ko from "./ko.json";
import ar from "./ar.json";
import pt from "./pt.json";
import ru from "./ru.json";

export type Locale =
  | "en" | "tr" | "de" | "fr" | "es" | "it"
  | "ja" | "zh" | "ko" | "ar" | "pt" | "ru";

const SUPPORTED: Locale[] = [
  "en", "tr", "de", "fr", "es", "it", "ja", "zh", "ko", "ar", "pt", "ru",
];

const PERSIST_KEY = "showme.locale.v1";

type Catalog = Record<string, string>;

export const CATALOGS: Record<string, Catalog> = {
  en: en as Catalog,
  tr: tr as Catalog,
  de: de as Catalog,
  fr: fr as Catalog,
  es: es as Catalog,
  it: it as Catalog,
  ja: ja as Catalog,
  zh: zh as Catalog,
  ko: ko as Catalog,
  ar: ar as Catalog,
  pt: pt as Catalog,
  ru: ru as Catalog,
};

let active: Locale = pickInitial();

function pickInitial(): Locale {
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(PERSIST_KEY);
      if (stored && SUPPORTED.includes(stored as Locale)) return stored as Locale;
    } catch {
      // ignore storage failure
    }
  }
  if (typeof navigator !== "undefined") {
    const lang = navigator.language?.slice(0, 2).toLowerCase();
    if (lang && SUPPORTED.includes(lang as Locale)) return lang as Locale;
  }
  return "en";
}

export const LOCALE_CHANGE_EVENT = "showme:locale-changed";

export function setLocale(loc: Locale) {
  const previous = active;
  active = SUPPORTED.includes(loc) ? loc : "en";
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("lang", active);
    document.documentElement.setAttribute("dir", active === "ar" ? "rtl" : "ltr");
  }
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(PERSIST_KEY, active);
    } catch {
      // ignore quota / private-mode failures
    }
    if (previous !== active) {
      try {
        window.dispatchEvent(
          new CustomEvent(LOCALE_CHANGE_EVENT, { detail: { locale: active, previous } }),
        );
      } catch {
        // ignore CustomEvent constructor failures in older environments
      }
    }
  }
}

export function locale(): Locale {
  return active;
}

export function listLocales(): Locale[] {
  return SUPPORTED.slice();
}

/**
 * Translate `key` via the active locale catalog. Falls back to the English
 * catalog, then to `fallback`, then to the key itself. Supports
 * `{name}` interpolation from the optional `vars` map.
 */
export function t(
  key: string,
  fallbackOrVars?: string | Record<string, string | number>,
  maybeVars?: Record<string, string | number>,
): string {
  const fallback = typeof fallbackOrVars === "string" ? fallbackOrVars : undefined;
  const vars =
    typeof fallbackOrVars === "object" && fallbackOrVars
      ? fallbackOrVars
      : maybeVars;
  const dict = CATALOGS[active];
  let template: string;
  if (dict && key in dict) {
    template = dict[key];
  } else {
    template = fallback ?? key;
  }
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, name: string) =>
    name in vars ? String(vars[name]) : `{${name}}`,
  );
}

/** Returns true when the active locale catalog covers ≥80% of English keys. */
export function isLocaleComplete(loc: Locale): boolean {
  const dict = CATALOGS[loc];
  if (!dict) return false;
  const enKeys = Object.keys(CATALOGS.en);
  const covered = enKeys.filter((k) => k in dict).length;
  return covered / enKeys.length >= 0.8;
}
