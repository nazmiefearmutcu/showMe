/**
 * SEC-8: a provider-supplied link becomes an href only when it is an absolute
 * http(s) URL. Anything else (javascript:, data:, file:, relative paths,
 * non-strings) yields undefined, so the anchor renders as plain text. The
 * Tauri CSP already blocks javascript: execution; this closes the remaining
 * non-http schemes at the source.
 */
export function safeHref(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const text = value.trim();
  if (!/^https?:\/\/[^\s]+$/i.test(text)) return undefined;
  try {
    const url = new URL(text);
    return url.protocol === "http:" || url.protocol === "https:" ? text : undefined;
  } catch {
    return undefined;
  }
}
