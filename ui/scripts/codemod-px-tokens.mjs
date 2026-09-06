#!/usr/bin/env node
/* global console, process */
/**
 * codemod-px-tokens.mjs — Tier-A px → token codemod for ui/src/styles/index.css.
 *
 * Round-3 tokenization pass (2026-09-05 campaign, task C). Applies ONLY the
 * mechanically safe, value-identical Tier-A substitution table from
 * showme-review/reports/survey-css-tokens.md:
 *
 *   - Properties: the padding / margin families (+ logical longhands),
 *     gap/row-gap/column-gap, the border-radius family (+ corner longhands),
 *     width/height + min-/max-, and the top/left/right/bottom offsets.
 *   - Only at paren-depth 0 in the declaration value (never inside calc()/min()/max()/
 *     var()/blur()/gradients/transforms).
 *   - Only positive integer px; comments, quoted strings, custom properties and
 *     at-rule preludes are never touched.
 *   - Kind matching: border-radius* → --radius-*, everything else → --space-*.
 *     Font-scale (--kpi-*) and density-scoped (--grid-*) tokens are never emitted.
 *
 * Boundary rule per occurrence: (?<![\w.-])Npx(?![\w.]) — never matches inside
 * 112px, 10.5px, -12px or `2px.`-style contexts.
 *
 * Usage:
 *   node scripts/codemod-px-tokens.mjs            # apply + assert per-pair counts
 *   node scripts/codemod-px-tokens.mjs --check    # dry run: report counts, no write
 *
 * Idempotency: after a full run there are zero remaining Tier-A candidates, so a
 * second run reports 0 replacements, writes nothing and exits 0. If a run finds
 * candidates but the per-pair counts differ from the expected table, it prints a
 * diagnostic table and exits 1 WITHOUT writing (investigate, never force).
 *
 * Node stdlib only — no dependencies.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const INDEX_CSS = resolve(here, "..", "src", "styles", "index.css");
const TOKENS_CSS = resolve(here, "..", "src", "styles", "tokens.css");

const CHECK_ONLY = process.argv.includes("--check");

/** Expected Tier-A table (survey report §3). Total MUST be 603. */
const EXPECTED = [
  { px: "8px", token: "--space-4", count: 173 },
  { px: "6px", token: "--space-3", count: 121 },
  { px: "12px", token: "--space-5", count: 113 },
  { px: "4px", token: "--space-2", count: 87 },
  { px: "2px", token: "--space-1", count: 31 },
  { px: "16px", token: "--space-6", count: 28 },
  { px: "24px", token: "--space-7", count: 18 },
  { px: "2px", token: "--radius-xs", count: 10 },
  { px: "32px", token: "--space-8", count: 8 },
  { px: "999px", token: "--radius-pill", count: 7 },
  { px: "4px", token: "--radius-sm", count: 6 },
  { px: "10px", token: "--radius-lg", count: 1 },
];
const EXPECTED_TOTAL = EXPECTED.reduce((s, e) => s + e.count, 0); // 603

/** border-radius* → radius tokens; spacing/box properties → space ladder. */
const RADIUS_MAP = {
  "2px": "--radius-xs",
  "4px": "--radius-sm",
  "6px": "--radius-md",
  "10px": "--radius-lg",
  "999px": "--radius-pill",
};
const SPACE_MAP = {
  "2px": "--space-1",
  "4px": "--space-2",
  "6px": "--space-3",
  "8px": "--space-4",
  "12px": "--space-5",
  "16px": "--space-6",
  "24px": "--space-7",
  "32px": "--space-8",
};

/** Property allowlist (exact match after trim + lowercase). Survey §5 rule 4. */
const RADIUS_PROPS = new Set([
  "border-radius",
  "border-top-left-radius",
  "border-top-right-radius",
  "border-bottom-left-radius",
  "border-bottom-right-radius",
]);
const BOX_PROPS = new Set([
  "padding",
  "padding-top",
  "padding-right",
  "padding-bottom",
  "padding-left",
  "padding-inline",
  "padding-block",
  "padding-inline-start",
  "padding-inline-end",
  "padding-block-start",
  "padding-block-end",
  "margin",
  "margin-top",
  "margin-right",
  "margin-bottom",
  "margin-left",
  "margin-inline",
  "margin-block",
  "margin-inline-start",
  "margin-inline-end",
  "margin-block-start",
  "margin-block-end",
  "gap",
  "row-gap",
  "column-gap",
  "width",
  "min-width",
  "max-width",
  "height",
  "min-height",
  "max-height",
  "top",
  "left",
  "right",
  "bottom",
]);

/** Combined value matcher, spec boundary rule (?<![\w.-])Npx(?![\w.]). */
const PX_RE = /(?<![\w.-])(\d+)px(?![\w.])/g;

/**
 * Sanitize pass: blank the interiors of block comments and quoted strings with
 * spaces (length-preserving) so downstream declaration parsing and px matching
 * only ever see real code. Offsets in the sanitized text map 1:1 to the source.
 * Escape sequences inside strings consume the escaped char (CSS strings).
 */
function sanitize(src) {
  const out = src.split("");
  const n = src.length;
  let i = 0;
  while (i < n) {
    const c = src[i];
    if (c === "/" && src[i + 1] === "*") {
      out[i] = " ";
      out[i + 1] = " ";
      i += 2;
      while (i < n) {
        if (src[i] === "*" && src[i + 1] === "/") {
          out[i] = " ";
          out[i + 1] = " ";
          i += 2;
          break;
        }
        out[i] = " ";
        i += 1;
      }
      continue;
    }
    if (c === '"' || c === "'") {
      const quote = c;
      i += 1;
      while (i < n) {
        if (src[i] === "\\") {
          out[i] = " ";
          if (i + 1 < n) out[i + 1] = " ";
          i += 2;
          continue;
        }
        if (src[i] === quote) {
          out[i] = " ";
          i += 1;
          break;
        }
        out[i] = " ";
        i += 1;
      }
      continue;
    }
    i += 1;
  }
  return out.join("");
}

/**
 * Find declaration chunks in sanitized CSS: segments between `;`, `{`, `}`
 * at paren-depth 0. A chunk is a declaration candidate only when it starts
 * inside a declaration block (previous boundary `{` or `;` with depth > 0) —
 * this keeps selector / at-rule preludes out (e.g. @media (min-width: 720px)
 * has its colon inside parens and is excluded twice over).
 */
function findDeclarationChunks(s) {
  const chunks = [];
  let parenDepth = 0;
  let blockDepth = 0;
  let start = 0;
  let declContext = false; // true when inside a block and after `{`/`;`
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "(") parenDepth += 1;
    else if (c === ")") parenDepth = Math.max(0, parenDepth - 1);
    else if (parenDepth === 0) {
      if (c === "{") {
        blockDepth += 1;
        declContext = true;
        pushChunk(i);
        start = i + 1;
      } else if (c === "}") {
        pushChunk(i);
        blockDepth = Math.max(0, blockDepth - 1);
        declContext = false;
        start = i + 1;
      } else if (c === ";") {
        pushChunk(i);
        start = i + 1;
        // declContext unchanged: still inside the same block
      }
    }
  }
  pushChunk(s.length);
  return chunks;

  function pushChunk(end) {
    if (declContext && blockDepth > 0 && end > start) {
      chunks.push([start, end]);
    }
  }
}

/** Depth-0 segments (exclusive of parenthesized groups) within a value. */
function depth0Segments(s, from, to) {
  const segs = [];
  let depth = 0;
  let segStart = from;
  for (let i = from; i < to; i++) {
    const c = s[i];
    if (c === "(") {
      if (depth === 0 && i > segStart) segs.push([segStart, i]);
      depth += 1;
    } else if (c === ")") {
      depth = Math.max(0, depth - 1);
      if (depth === 0) segStart = i + 1;
    }
  }
  if (depth === 0 && to > segStart) segs.push([segStart, to]);
  return segs;
}

function main() {
  const src = readFileSync(INDEX_CSS, "utf8");
  const s = sanitize(src);
  const chunks = findDeclarationChunks(s);

  /** counts per "px->token" pair key */
  const found = new Map();
  /** replacement list: [startOffset, endOffset, replacementText] */
  const edits = [];

  for (const [cStart, cEnd] of chunks) {
    const chunk = s.slice(cStart, cEnd);
    // First top-level colon splits property: value.
    let colon = -1;
    let parenDepth = 0;
    for (let i = 0; i < chunk.length; i++) {
      const c = chunk[i];
      if (c === "(") parenDepth += 1;
      else if (c === ")") parenDepth = Math.max(0, parenDepth - 1);
      else if (c === ":" && parenDepth === 0) {
        colon = i;
        break;
      }
    }
    if (colon < 0) continue;
    const prop = chunk.slice(0, colon).trim().toLowerCase();
    if (prop.startsWith("--")) continue; // custom property declarations
    const isRadius = RADIUS_PROPS.has(prop);
    const isBox = BOX_PROPS.has(prop);
    if (!isRadius && !isBox) continue;
    const map = isRadius ? RADIUS_MAP : SPACE_MAP;

    const vFrom = cStart + colon + 1;
    const vTo = cEnd;
    for (const [segFrom, segTo] of depth0Segments(s, vFrom, vTo)) {
      const seg = s.slice(segFrom, segTo);
      PX_RE.lastIndex = 0;
      let m;
      while ((m = PX_RE.exec(seg)) !== null) {
        const px = `${m[1]}px`;
        const token = map[px];
        if (token === undefined) continue; // Tier C: no kind-matched token
        const key = `${px}->${token}`;
        found.set(key, (found.get(key) ?? 0) + 1);
        const absStart = segFrom + m.index;
        edits.push([absStart, absStart + m[0].length, `var(${token})`]);
      }
    }
  }

  // --- report per-pair before/after -------------------------------------
  const varBefore = countVarTokens(src);
  let total = 0;
  console.log("pair                   found");
  console.log("─".repeat(34));
  const expectedByKey = new Map(EXPECTED.map((e) => [`${e.px}->${e.token}`, e]));
  const allKeys = new Set([...expectedByKey.keys(), ...found.keys()]);
  let mismatch = false;
  for (const key of [...allKeys].sort()) {
    const n = found.get(key) ?? 0;
    total += n;
    const exp = expectedByKey.get(key);
    const expStr = exp ? String(exp.count) : "0";
    const flag = String(n) === expStr ? "" : `  <-- expected ${expStr}`;
    if (flag) mismatch = true;
    console.log(key.padEnd(23), String(n).padStart(3), flag);
  }
  console.log("─".repeat(34));
  console.log("TOTAL".padEnd(23), String(total).padStart(3), `(expected ${EXPECTED_TOTAL})`);
  console.log(`var(--space-*/--radius-*) in file: before=${varBefore}, after=${varBefore + total}`);

  if (CHECK_ONLY) {
    console.log("[check] dry run — file not modified.");
    process.exit(mismatch ? 1 : 0);
  }

  if (total === 0) {
    // Idempotent re-run: nothing left to do. Verify no Tier-A candidates remain.
    console.log("[ok] 0 candidates remaining — file already fully tokenized (idempotent no-op).");
    process.exit(0);
  }

  if (mismatch || total !== EXPECTED_TOTAL) {
    console.error(
      "[abort] per-pair counts differ from the expected Tier-A table — investigate, not force. File NOT modified.",
    );
    process.exit(1);
  }

  // --- assert every emitted token is defined in tokens.css --------------
  const tokensCss = readFileSync(TOKENS_CSS, "utf8");
  const defined = new Set();
  for (const m of tokensCss.matchAll(/(^|\n)\s*(--[a-zA-Z0-9-]+)\s*:/g)) defined.add(m[2]);
  const used = new Set(EXPECTED.map((e) => e.token));
  const unresolved = [...used].filter((t) => !defined.has(t));
  if (unresolved.length > 0) {
    console.error(`[abort] tokens not defined in tokens.css: ${unresolved.join(", ")}`);
    process.exit(1);
  }

  // --- apply edits right-to-left so earlier offsets stay valid ----------
  edits.sort((a, b) => b[0] - a[0]);
  let out = src;
  for (const [start, end, text] of edits) {
    out = out.slice(0, start) + text + out.slice(end);
  }
  writeFileSync(INDEX_CSS, out, "utf8");
  console.log(`[ok] wrote ${edits.length} replacements to ui/src/styles/index.css`);
}

function countVarTokens(text) {
  const m = text.match(/var\(--(?:space-[1-8]|radius-(?:xs|sm|md|lg|pill))\)/g);
  return m ? m.length : 0;
}

main();
