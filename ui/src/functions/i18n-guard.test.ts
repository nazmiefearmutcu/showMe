/**
 * L6 i18n guard — the L6 pane set + the audit-sweep panes must not regress
 * to Turkish user-facing copy.
 *
 * Scans the owned pane sources (including `anr_pane/**`), stripping comments
 * and test-id hooks first (neither is user-facing). Everything that remains —
 * JSX text, string literals, aria-label/title attributes — must be English.
 * The wordlist below is the campaign's mandated set plus the strings swept
 * in this lane.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const FUNCTIONS_DIR = join(process.cwd(), "src", "functions");

const ANR_FILES = readdirSync(join(FUNCTIONS_DIR, "anr_pane"))
  .filter((f) => f.endsWith(".tsx") || f.endsWith(".ts"))
  .map((f) => `anr_pane/${f}`);

const OWNED_FILES = [
  "EQS.tsx",
  "SCAN.tsx",
  "GLCO.tsx",
  "WCRS.tsx",
  "ASK.tsx",
  "BOT.tsx",
  "BOTS.tsx",
  "MIS.tsx",
  "ECO.tsx",
  "PERF.tsx",
  "TXNS.tsx",
  "TMPL.tsx",
  "BIO.tsx",
  "OrderTicket.tsx",
  // Audit-sweep additions (F12): the panes whose Turkish leftovers were
  // fixed in this lane must stay English.
  "CONN.tsx",
  "BDA.tsx",
  "STRA.tsx",
  "ALRT.tsx",
  "CRPR.tsx",
  "AIM.tsx",
  "DEBT.tsx",
  "INDX.tsx",
  "XSEN.tsx",
  ...ANR_FILES,
];

const TURKISH_CHARS = /[ğüşıöçĞÜŞİÖÇ]/;
// Case-insensitive stems: Turkish words are matched by their distinctive
// prefixes so inflected forms ("Semboller", "Uygulanabilirlik") are caught.
// `\bson\b` / `\bsil\b` / `\bal\b` / `\bsat\b` keep those short words from
// matching English tokens (case-sensitive for `al`/`sat` would miss "AL"/"SAT"
// labels, so the whole list stays case-insensitive and the word boundaries do
// the disambiguating).
const TURKISH_WORDS =
  /(durdur|sorgu|sinyal|ayar|strateji|toplam|durum|kaynak|piyasa|skor|hata|etkin|lider|geride|karli|zararli|gerekli|zaman|konsens|makale|yeniden|bilinmeyen|sadece|saniye|tekrar|botlar|tumunu|iptal|onay|uygulan|sembol|kullan|serbest|kural|hepsi|olamaz|etkilenecek|zorunlu|kaydediliyor|merdiven|kredi|defteri|tanınan|taninan|varsayılan|varsayilan|desteklenmiyor|desteklenm|yok sayıl|yok sayil|ozellestir|pozisyon|belirtilmedi|talep edilmedi|\bson\b|\bsil\b|\bal\b|\bsat\b)/i;

/** Remove line + block comments without touching string contents. */
function stripComments(src: string): string {
  let out = "";
  let i = 0;
  let state: "code" | "line" | "block" = "code";
  let quote: string | null = null;
  while (i < src.length) {
    const c = src[i];
    const n = src[i + 1];
    if (state === "line") {
      if (c === "\n") {
        state = "code";
        out += c;
      }
      i += 1;
      continue;
    }
    if (state === "block") {
      if (c === "*" && n === "/") {
        state = "code";
        i += 2;
      } else {
        i += 1;
      }
      continue;
    }
    if (quote) {
      // Single/double-quoted JS strings cannot contain a raw newline — a
      // newline while "inside" one means the opener was JSX text (e.g. an
      // apostrophe in prose). Self-heal so later comments still strip.
      if (c === "\n" && quote !== "`") {
        quote = null;
        state = "code";
        out += c;
        i += 1;
        continue;
      }
      out += c;
      if (c === "\\") {
        out += src[i + 1] ?? "";
        i += 2;
        continue;
      }
      if (c === quote) quote = null;
      i += 1;
      continue;
    }
    if (c === "/" && n === "/") {
      state = "line";
      i += 2;
      continue;
    }
    if (c === "/" && n === "*") {
      state = "block";
      i += 2;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") quote = c;
    out += c;
    i += 1;
  }
  return out;
}

/**
 * Remove `data-testid=...` / `testId=...` values — test hooks are identifiers,
 * not user-facing copy (e.g. `perf-kpi-top-gainer`, `stra-sil-button`,
 * `tmpl-olustur-button`).
 */
function stripTestIds(src: string): string {
  return src.replace(/\b(?:data-testid|testId)=("[^"]*"|'[^']*'|`[^`]*`)/g, "TESTID");
}

describe("L6 i18n guard", () => {
  it("has no Turkish user-facing copy in the L6-owned panes", () => {
    const violations: string[] = [];
    for (const rel of OWNED_FILES) {
      const raw = readFileSync(join(FUNCTIONS_DIR, rel), "utf8");
      const scanned = stripTestIds(stripComments(raw));
      for (const line of scanned.split("\n")) {
        if (TURKISH_CHARS.test(line) || TURKISH_WORDS.test(line)) {
          violations.push(`${rel}: ${line.trim().slice(0, 160)}`);
        }
      }
    }
    expect(violations).toEqual([]);
  });
});
