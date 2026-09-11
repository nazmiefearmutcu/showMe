#!/usr/bin/env node
/* global console, process */
/**
 * codemod-fontsize-tokens.mjs — inline `fontSize` literal → var(--font-size-*)
 * codemod for the function panes (campaign 2026-09-11, wave-1.5 lane L15).
 *
 * Scope: ui/src/functions/**, *.tsx only — `__tests__/` directories and
 * `*.test.tsx` files are skipped. The goal is global density/type tuning:
 * once every pane's inline fontSize reads a token, a single :root density
 * change rescales the terminal.
 *
 * Transforms ONLY style-object property literals whose value is:
 *   - a bare integer:             fontSize: 10
 *   - a double-quoted px string:  fontSize: "10px"
 *   - a single-quoted px string:  fontSize: '10px'
 *
 * It does NOT touch:
 *   - JSX / SVG attributes (`fontSize={10}` / `fontSize="10"`) — not style objects;
 *   - non-integer numerics (9.5, 10.5, 12.5) — no exact token slot;
 *   - integer values without an exact token (14 / 16 / 20 / 30) — stay literals;
 *   - dynamic values (expressions, theme reads, existing var() strings);
 *   - lightweight-charts options: `fontSize` inside a `createChart(...)` call is a
 *     canvas-rendered library option (typed `number`), not a DOM style object and
 *     it cannot resolve a CSS variable — those 2 sites stay numeric;
 *   - anything inside comments or string literals (AST-based, immune to both).
 *
 * Exact token scale (ui/src/styles/tokens.css, 1rem = 14px):
 *   9  → --font-size-xs      10 → --font-size-2xs    11 → --font-size-sm
 *   12 → --font-size-md      13 → --font-size-lg     15 → --font-size-xl
 *   18 → --font-size-2xl     22 → --font-size-3xl
 *
 * Replacement shape: `fontSize: "var(--font-size-sm)"` (string value).
 *
 * Usage:
 *   node scripts/codemod-fontsize-tokens.mjs           # dry run: report, no write
 *   node scripts/codemod-fontsize-tokens.mjs --apply   # write + assert counts
 *
 * Auditability: per-file change counts, per-value before/after table, expected
 * count table from the campaign survey (606 strict literal matches = 595 mappable
 * transforms across 110 files + 2 lightweight-charts exclusions + 9 residual
 * integers; plus 6 non-integer literals left alone). A mismatch prints a
 * diagnostic and exits 1 WITHOUT writing — investigate, never force.
 *
 * Idempotency: after a full run every mappable literal is a var() string, so a
 * second `--apply` reports 0 replacements, writes nothing and exits 0.
 *
 * Uses the repo's existing TypeScript dev dependency for exact AST matching
 * (no new dependencies).
 */
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const here = dirname(fileURLToPath(import.meta.url));
const UI_ROOT = resolve(here, "..");
const FUNCTIONS_DIR = resolve(UI_ROOT, "src", "functions");
const TOKENS_CSS = resolve(UI_ROOT, "src", "styles", "tokens.css");
const APPLY = process.argv.includes("--apply");

/** px value → exact token. Values with no exact token are intentionally absent. */
const SCALE = new Map([
  [9, "--font-size-xs"],
  [10, "--font-size-2xs"],
  [11, "--font-size-sm"],
  [12, "--font-size-md"],
  [13, "--font-size-lg"],
  [15, "--font-size-xl"],
  [18, "--font-size-2xl"],
  [22, "--font-size-3xl"],
]);

/** Values deliberately left as literals (no exact token slot). */
const RESIDUAL_VALUES = [14, 16, 20, 30];

/** Campaign survey pins (strict AST matches, ui/src/functions/**, non-test tsx). */
const EXPECTED = [
  { value: 9, token: "--font-size-xs", count: 81 },
  { value: 10, token: "--font-size-2xs", count: 180 },
  { value: 11, token: "--font-size-sm", count: 175 },
  { value: 12, token: "--font-size-md", count: 132 },
  { value: 13, token: "--font-size-lg", count: 16 },
  { value: 15, token: "--font-size-xl", count: 2 },
  { value: 18, token: "--font-size-2xl", count: 3 },
  { value: 22, token: "--font-size-3xl", count: 6 },
];
const EXPECTED_TOTAL = EXPECTED.reduce((s, e) => s + e.count, 0); // 595
/** Expected count of non-mappable literals (14/16/20/30 plus 9.5/10.5/12.5) — 15. */
const EXPECTED_RESIDUAL = 15;
/** lightweight-charts `createChart` layout options — canvas number, never tokenized. */
const EXPECTED_EXCLUDED = 2;

/** Recursively collect target files (skip __tests__ dirs and *.test.tsx). */
function collectFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (entry === "__tests__" || entry === "node_modules") continue;
      out.push(...collectFiles(full));
    } else if (entry.endsWith(".tsx") && !entry.endsWith(".test.tsx")) {
      out.push(full);
    }
  }
  return out;
}

/**
 * AST pass: find `fontSize` PropertyAssignments with a literal initializer.
 * Returns the edit list (offsets into src) plus reporting maps. Because this is
 * an AST walk, comments, string literals, JSX/SVG attributes and type-space
 * declarations are structurally out of scope. `fontSize` nested inside a
 * `createChart(...)` call is a lightweight-charts option object (numeric,
 * canvas-rendered) and is reported as excluded instead of edited.
 */
function collectFile(src, fileName) {
  const sf = ts.createSourceFile(fileName, src, ts.ScriptTarget.Latest, false, ts.ScriptKind.TSX);
  const edits = [];
  /** all matched literal values (incl. residuals), for the before/after table */
  const values = new Map();
  const shapes = { number: 0, doubleQuoted: 0, singleQuoted: 0 };
  /** non-style sites deliberately left numeric */
  const excluded = [];

  const visit = (node, inChartOptions) => {
    let childInChartOptions = inChartOptions;
    if (ts.isCallExpression(node)) {
      const callee = node.expression.getText(sf);
      if (/(^|\.)createChart$/.test(callee)) childInChartOptions = true;
    }
    if (ts.isPropertyAssignment(node) && ts.isIdentifier(node.name) && node.name.text === "fontSize") {
      const init = node.initializer;
      let value = null;
      let shape = null;
      if (ts.isNumericLiteral(init)) {
        value = Number(init.text);
        shape = "number";
      } else if (ts.isStringLiteral(init)) {
        const m = /^(\d+)px$/.exec(init.text);
        if (m) {
          value = Number(m[1]);
          const raw = src.slice(init.getStart(sf), init.getEnd());
          shape = raw.startsWith("'") ? "singleQuoted" : "doubleQuoted";
        }
      }
      if (value !== null) {
        const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
        if (inChartOptions) {
          excluded.push({ line, value, raw: init.getText(sf) });
        } else {
          values.set(value, (values.get(value) ?? 0) + 1);
          shapes[shape] += 1;
          const token = SCALE.get(value);
          if (token !== undefined) {
            edits.push({
              start: init.getStart(sf),
              end: init.getEnd(),
              replacement: `"var(${token})"`,
              value,
              token,
            });
          }
        }
      }
    }
    ts.forEachChild(node, (child) => visit(child, childInChartOptions));
  };
  visit(sf, false);
  return { edits, values, shapes, excluded };
}

/** Count existing `fontSize: "var(--font-size-*)` uses in a source text. */
function countTokenUses(src) {
  const m = src.match(/fontSize\s*:\s*"var\(--font-size-[\w-]+\)"/g);
  return m ? m.length : 0;
}

function main() {
  const files = collectFiles(FUNCTIONS_DIR).sort((a, b) =>
    relative(FUNCTIONS_DIR, a) < relative(FUNCTIONS_DIR, b) ? -1 : 1,
  );

  /** relPath → { edits, values, shapes, tokenUses } */
  const results = new Map();
  const found = new Map(); // value → count (all matched literals)
  const shapes = { number: 0, doubleQuoted: 0, singleQuoted: 0 };
  let totalEdits = 0;
  let residualFound = 0;
  let tokensBefore = 0;
  let excludedTotal = 0;
  const excludedSites = [];

  for (const file of files) {
    const src = readFileSync(file, "utf8");
    const { edits, values, shapes: fileShapes, excluded } = collectFile(src, file);
    const rel = relative(FUNCTIONS_DIR, file).split(sep).join("/");
    tokensBefore += countTokenUses(src);
    for (const [v, c] of values) found.set(v, (found.get(v) ?? 0) + c);
    shapes.number += fileShapes.number;
    shapes.doubleQuoted += fileShapes.doubleQuoted;
    shapes.singleQuoted += fileShapes.singleQuoted;
    totalEdits += edits.length;
    excludedTotal += excluded.length;
    for (const ex of excluded) excludedSites.push({ rel, ...ex });
    if (edits.length > 0) {
      results.set(rel, { src, file, edits });
    }
    for (const [v, c] of values) {
      if (!SCALE.has(v)) residualFound += c;
    }
  }

  // --- per-file report ---------------------------------------------------
  console.log(`scan: ${files.length} tsx files under ui/src/functions (tests excluded)`);
  console.log("");
  console.log("file".padEnd(34), "changes");
  console.log("─".repeat(50));
  for (const [rel, r] of results) {
    console.log(rel.padEnd(34), String(r.edits.length).padStart(3));
  }
  console.log("─".repeat(50));
  console.log("FILES".padEnd(34), String(results.size).padStart(3));
  console.log("TOTAL".padEnd(34), String(totalEdits).padStart(3), `(expected ${EXPECTED_TOTAL})`);
  console.log(
    `literal shapes: bare=${shapes.number} double-quoted=${shapes.doubleQuoted} single-quoted=${shapes.singleQuoted}`,
  );
  if (excludedTotal > 0) {
    console.log(`excluded non-style sites (stay numeric): ${excludedTotal}`);
    for (const ex of excludedSites) {
      console.log(`  ${ex.rel}:${ex.line}  fontSize: ${ex.raw}  (createChart layout option)`);
    }
  }

  // --- per-value before/after table --------------------------------------
  console.log("");
  console.log("value  token                 before  after   note");
  console.log("─".repeat(66));
  for (const [v, c] of [...found.entries()].sort((a, b) => a[0] - b[0])) {
    const token = SCALE.get(v);
    if (token) {
      console.log(
        String(v).padStart(5),
        token.padEnd(20),
        String(c).padStart(6),
        String(0).padStart(6),
        " mapped",
      );
    } else {
      console.log(
        String(v).padStart(5),
        "—".padEnd(20),
        String(c).padStart(6),
        String(c).padStart(6),
        RESIDUAL_VALUES.includes(v) ? " residual (no exact token)" : " residual (non-integer)",
      );
    }
  }
  console.log("─".repeat(66));
  console.log(
    `mappable total ${totalEdits} (expected ${EXPECTED_TOTAL}); residual literals ${residualFound} (expected ${EXPECTED_RESIDUAL}); excluded non-style ${excludedTotal} (expected ${EXPECTED_EXCLUDED})`,
  );
  console.log(`fontSize var() uses in scope: before=${tokensBefore}, after=${tokensBefore + totalEdits}`);

  const mismatch =
    totalEdits !== EXPECTED_TOTAL ||
    excludedTotal !== EXPECTED_EXCLUDED ||
    residualFound !== EXPECTED_RESIDUAL ||
    EXPECTED.some((e) => (found.get(e.value) ?? 0) !== e.count);
  if (totalEdits > 0 && mismatch) {
    console.error(
      "[abort] counts differ from the campaign survey table — investigate, not force. File NOT modified.",
    );
    if (APPLY) process.exit(1);
  }

  if (totalEdits === 0) {
    console.log("[ok] 0 mappable literals remaining — already tokenized (idempotent no-op).");
    process.exit(0);
  }

  // --- assert every emitted token is defined in tokens.css ---------------
  const tokensCss = readFileSync(TOKENS_CSS, "utf8");
  const defined = new Set();
  for (const m of tokensCss.matchAll(/(^|\n)\s*(--[a-zA-Z0-9-]+)\s*:/g)) defined.add(m[2]);
  const used = new Set(EXPECTED.map((e) => e.token));
  const unresolved = [...used].filter((t) => !defined.has(t));
  if (unresolved.length > 0) {
    console.error(`[abort] tokens not defined in tokens.css: ${unresolved.join(", ")}`);
    process.exit(1);
  }

  if (!APPLY) {
    console.log("[dry-run] no files modified — pass --apply to write.");
    process.exit(mismatch ? 1 : 0);
  }

  if (mismatch) {
    console.error("[abort] refusing to write while counts mismatch the survey table.");
    process.exit(1);
  }

  // --- apply edits right-to-left so earlier offsets stay valid -----------
  let written = 0;
  for (const [, r] of results) {
    const sorted = [...r.edits].sort((a, b) => b.start - a.start);
    let out = r.src;
    for (const e of sorted) {
      out = out.slice(0, e.start) + e.replacement + out.slice(e.end);
    }
    writeFileSync(r.file, out, "utf8");
    written += sorted.length;
  }
  console.log(`[ok] wrote ${written} replacements across ${results.size} files.`);
}

main();
