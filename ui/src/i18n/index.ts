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
 *
 * UI-ROBUSTNESS F6: `useLocale()` subscribes React components to
 * LOCALE_CHANGE_EVENT via useSyncExternalStore so shell components that
 * render `t()` output re-render when the user switches language. `t()`
 * itself stays a plain function for non-React callers.
 */
import { useSyncExternalStore } from "react";

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
  /* Owner (2026-09-16): the product is English-first - do NOT auto-follow the
     OS/browser locale ("her şey ingilizce neden hâlâ türkçe şeyler var"):
     a Turkish Windows profile used to flip every shell string to Turkish.
     An explicitly chosen locale still wins via the stored key above. */
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

// UI-ROBUSTNESS F6 — reactive locale for React components. The store is the
// module-scoped `active` variable; subscribers are notified through the
// existing LOCALE_CHANGE_EVENT that `setLocale` dispatches (only on actual
// change, so re-subscribes are cheap and loop-free).
function subscribeLocale(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(LOCALE_CHANGE_EVENT, onStoreChange);
  return () => window.removeEventListener(LOCALE_CHANGE_EVENT, onStoreChange);
}

/**
 * Hook: the active locale. Re-renders the calling component whenever
 * `setLocale` changes it. Pair with `t()` so shell chrome (Titlebar menus,
 * Sidebar groups, palette placeholder/footer, toast copy, …) re-renders on
 * locale switch instead of staying in the previous language until an
 * unrelated state change happens to re-render it.
 */
export function useLocale(): Locale {
  return useSyncExternalStore(
    subscribeLocale,
    () => active,
    () => active,
  );
}

export function listLocales(): Locale[] {
  return SUPPORTED.slice();
}

/**
 * Translate `key` via the active locale catalog. Zero-English-fallback
 * contract (i18n/README rule 2): the lookup is active catalog → `fallback`
 * (when provided) → the key itself. There is deliberately NO English-catalog
 * step. Supports `{name}` interpolation from the optional `vars` map.
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
