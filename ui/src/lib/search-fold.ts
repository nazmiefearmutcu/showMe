/**
 * Locale-safe case folding for substring search (LOC-7).
 *
 * JS toLowerCase() maps U+0130 (İ) to "i" followed by a combining dot, so
 * "İstanbul" never contains "istanbul". Dotless ı (U+0131) never matches "i".
 * Folding both to ASCII I/i before lowercasing fixes the match. Each code unit
 * maps to one code unit, so the length (and highlight offsets) is preserved.
 */
export function foldSearchText(value: string): string {
  return value.replace(/\u0130/g, "I").replace(/\u0131/g, "i").toLowerCase();
}
