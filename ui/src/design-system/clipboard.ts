/**
 * Clipboard + TSV helpers for the design system.
 *
 * The terminal is keyboard-first: DataGrid cell/row copy and per-row copy
 * buttons in panes all funnel through `copyTextToClipboard` so the fallback
 * ladder stays in one place:
 *
 *   1. `navigator.clipboard.writeText` (Tauri WebView + modern browsers)
 *   2. `document.execCommand("copy")` (legacy fallback)
 *   3. silent `false` — callers must never crash on a denied clipboard
 *
 * `buildTsvRow` renders a tab-separated, newline-free row for spreadsheet
 * paste targets (Excel / Sheets).
 */

/** Scalar → clipboard-safe text. Nullish → "" (never "null"/"undefined"). */
export function scalarToText(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) {
    return v.map((item) => scalarToText(item)).filter(Boolean).join(" / ");
  }
  return "";
}

/** Join cell values into a tab-separated row (newlines collapsed to spaces). */
export function buildTsvRow(values: unknown[]): string {
  return values
    .map((v) => scalarToText(v).replace(/\r?\n/g, " "))
    .join("\t");
}

/**
 * Copy text to the OS clipboard. Returns true when a write was attempted
 * through the async Clipboard API (the promise itself is fire-and-forget),
 * false when no clipboard path exists (e.g. jsdom without a polyfill).
 */
export function copyTextToClipboard(text: string): boolean {
  const nav =
    typeof navigator !== "undefined"
      ? (navigator as Navigator & { clipboard?: { writeText?: (t: string) => Promise<void> } })
      : undefined;
  if (nav?.clipboard && typeof nav.clipboard.writeText === "function") {
    try {
      void nav.clipboard.writeText(text).catch(() => undefined);
      return true;
    } catch {
      // fall through to execCommand
    }
  }
  try {
    if (typeof document !== "undefined" && typeof document.execCommand === "function") {
      return document.execCommand("copy");
    }
  } catch {
    // no-op
  }
  return false;
}
