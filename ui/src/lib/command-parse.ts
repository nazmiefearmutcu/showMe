/**
 * Bloomberg-style command grammar (campaign 2026-09-11, Lane L2).
 *
 * The terminal command line accepts a tiny, deterministic grammar:
 *
 *   1. `<GO>` / `GO`  — optional trailing terminator, case-insensitive.
 *   2. Empty (or GO-only)      → { kind: "empty" }
 *   3. One token:
 *        - known function code  → { kind: "function", code }
 *        - known symbol         → { kind: "security", symbol }
 *        - lowercase word       → { kind: "verb", verb }   (app action verb)
 *        - anything else        → { kind: "unknown", input }
 *   4. Two tokens, any order of {code, symbol}:
 *        `MSFT GP`, `GP MSFT`, `DES MSFT`, `MSFT DES`
 *                               → { kind: "security-function", symbol, code }
 *      every other two-token combination → { kind: "unknown", input }
 *   5. Three or more tokens    → { kind: "unknown", input }
 *
 * Codes are canonicalised to UPPERCASE before the `isCode` probe; symbols
 * are canonicalised to UPPERCASE before the `isSymbol` probe (the palette
 * symbol universe is normalized upstream). The caller owns the catalogs —
 * `parseCommandInput` never imports a store and stays a pure function.
 *
 * When `opts` is omitted no token can be recognised as a code or symbol
 * (default probes answer `false`); only `empty`, `verb` and `unknown` are
 * reachable. That is deliberate: without a catalog the parser must not
 * guess, and every real caller (palette, titlebar command line) passes the
 * live predicates via `makeCommandPredicates`.
 */

export type ParsedCommand =
  | { kind: "empty" }
  | { kind: "function"; code: string; go: boolean }
  | { kind: "security"; symbol: string; go: boolean }
  | { kind: "security-function"; symbol: string; code: string; go: boolean }
  | { kind: "verb"; verb: string; go: boolean }
  | { kind: "unknown"; input: string };

export interface CommandParseOptions {
  isCode?: (t: string) => boolean;
  isSymbol?: (t: string) => boolean;
}

/** Trailing terminator: `GO` or `<GO>`, any case. */
const GO_TOKEN = /^(?:go|<go>)$/i;

/**
 * A verb candidate is a lowercase word (optionally with digits/dashes) —
 * the app's action ids (`theme.matrix`, `layout.save-current`) are matched
 * downstream by the action registry, not by this module.
 */
const VERB_WORD = /^[a-z][a-z0-9-]*$/;

const DEFAULT_PREDICATE = () => false;

/**
 * Build `isCode` / `isSymbol` probes from the caller's catalogs. Codes and
 * symbols are compared uppercase-insensitively on both sides.
 */
export function makeCommandPredicates(options: {
  codes: Iterable<string>;
  symbols: Iterable<string>;
}): { isCode: (t: string) => boolean; isSymbol: (t: string) => boolean } {
  const codes = new Set<string>();
  for (const code of options.codes) codes.add(String(code).toUpperCase());
  const symbols = new Set<string>();
  for (const symbol of options.symbols) symbols.add(String(symbol).toUpperCase());
  return {
    isCode: (t) => codes.has(t.toUpperCase()),
    isSymbol: (t) => symbols.has(t.toUpperCase()),
  };
}

export function parseCommandInput(
  input: string,
  opts?: CommandParseOptions,
): ParsedCommand {
  const trimmed = String(input ?? "").trim();
  if (!trimmed) return { kind: "empty" };

  let tokens = trimmed.split(/\s+/).filter(Boolean);
  let go = false;
  const last = tokens[tokens.length - 1];
  if (last && GO_TOKEN.test(last)) {
    go = true;
    tokens = tokens.slice(0, -1);
  }
  if (tokens.length === 0) return { kind: "empty" };

  const isCode = opts?.isCode ?? DEFAULT_PREDICATE;
  const isSymbol = opts?.isSymbol ?? DEFAULT_PREDICATE;

  if (tokens.length === 1) {
    const token = tokens[0];
    const upper = token.toUpperCase();
    if (isCode(upper)) return { kind: "function", code: upper, go };
    if (isSymbol(upper)) return { kind: "security", symbol: upper, go };
    if (VERB_WORD.test(token)) return { kind: "verb", verb: token, go };
    return { kind: "unknown", input: trimmed };
  }

  if (tokens.length === 2) {
    const first = tokens[0].toUpperCase();
    const second = tokens[1].toUpperCase();
    const firstIsCode = isCode(first);
    const firstIsSymbol = isSymbol(first);
    const secondIsCode = isCode(second);
    const secondIsSymbol = isSymbol(second);
    // `CODE SYMBOL` — the code slot must not itself be a known code when
    // it is being read as the symbol (prevents `GP DES` resolving).
    if (firstIsCode && secondIsSymbol && !secondIsCode) {
      return { kind: "security-function", symbol: second, code: first, go };
    }
    if (secondIsCode && firstIsSymbol && !firstIsCode) {
      return { kind: "security-function", symbol: first, code: second, go };
    }
    return { kind: "unknown", input: trimmed };
  }

  return { kind: "unknown", input: trimmed };
}
