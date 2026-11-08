#!/usr/bin/env node
/**
 * Extract the request params every bespoke UI pane sends, per function code.
 *
 * Used by the T9b truth check (backend/showme/audit/gate.py): a param a pane
 * sends that the Python handler never reads is silently dropped (the
 * YAS/TLH/GREEKS defect class found in the 2026-11-07 strict audit).
 *
 * Static, via the TypeScript compiler API (no regexes on code):
 *   - pane file -> codes from ui/src/functions/registry.tsx
 *   - every useFunction({ code, params }) / runFunction(code, { params }) call
 *   - params given as an object literal, a variable (object literal or
 *     useMemo(() => ({...}))), or a builder call whose body switches on the
 *     code (case "PSC": return {...}) or tests `x === "CODE"`
 *   - object keys incl. later `obj.key = ...` / `obj["key"] = ...` writes
 * Spreads and computed keys mark the result dynamic; anything it cannot
 * resolve is listed under "unresolved" (never silently dropped).
 *
 * Output (stdout, JSON): { codes: { CODE: { keys, dynamic, files } }, unresolved: [...] }
 */
import { createRequire } from "node:module";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const UI = join(ROOT, "ui", "src");
const FUNCTIONS = join(UI, "functions");

// ── registry: pane file -> codes ─────────────────────────────────────────
const registry = readFileSync(join(FUNCTIONS, "registry.tsx"), "utf8");
const paneFile = new Map();
for (const m of registry.matchAll(/const (\w+) = lazy\(\s*\(\)\s*=>\s*import\("(\.\/[^"]+)"\)/g)) {
  paneFile.set(m[1], resolve(FUNCTIONS, `${m[2]}.tsx`));
}
const fileCodes = new Map();
for (const m of registry.matchAll(/^\s+"?([A-Z][A-Z0-9_]*)"?:\s*(\w+),\s*$/gm)) {
  const file = paneFile.get(m[2]);
  if (!file) continue;
  if (!fileCodes.has(file)) fileCodes.set(file, new Set());
  fileCodes.get(file).add(m[1]);
}

// ── helpers ──────────────────────────────────────────────────────────────
function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx|ts)$/.test(name) && !/\.test\.|\.spec\./.test(name)) out.push(p);
  }
  return out;
}

function propName(name) {
  if (!name) return null;
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) return name.text;
  return null;
}

/** keys of an object literal; `dynamic` for spreads/computed names. */
function literalKeys(obj, sf, out) {
  for (const p of obj.properties) {
    if (ts.isPropertyAssignment(p) || ts.isShorthandPropertyAssignment(p)) {
      const n = propName(p.name);
      if (n) {
        out.keys.add(n);
        // `key: cond ? value : undefined` is only sometimes sent (JSON drops undefined)
        const init = ts.isPropertyAssignment(p) ? p.initializer : null;
        if (init && ts.isConditionalExpression(init)
          && [init.whenTrue, init.whenFalse].some((b) => ts.isIdentifier(b) && b.text === "undefined")) {
          (out.conditional ||= new Set()).add(n);
        }
      } else out.dynamic = true;
    } else if (ts.isSpreadAssignment(p)) {
      const inner = resolveExpr(p.expression, sf, p, 0);
      if (inner && inner.kind === "keys") {
        inner.keys.forEach((k) => out.keys.add(k));
        out.dynamic = out.dynamic || inner.dynamic;
      } else out.dynamic = true;
    }
  }
}

/** writes like `name.key = …` / `name["key"] = …` inside `scope`. */
function laterWrites(name, scope, out) {
  const visit = (node) => {
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      const left = node.left;
      if (ts.isPropertyAccessExpression(left) && ts.isIdentifier(left.expression) && left.expression.text === name) {
        out.keys.add(left.name.text);
      } else if (ts.isElementAccessExpression(left) && ts.isIdentifier(left.expression) && left.expression.text === name) {
        const arg = left.argumentExpression;
        if (ts.isStringLiteral(arg)) out.keys.add(arg.text);
        else out.dynamic = true;
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(scope);
}

function enclosingFunction(node) {
  let n = node.parent;
  while (n && !ts.isFunctionLike(n) && !ts.isSourceFile(n)) n = n.parent;
  return n || node.getSourceFile();
}

function findDeclaration(name, from, sf) {
  let scope = enclosingFunction(from);
  while (scope) {
    let found = null;
    const visit = (node) => {
      if (found) return;
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === name) found = node;
      else if (ts.isFunctionDeclaration(node) && node.name && node.name.text === name) found = node;
      else ts.forEachChild(node, visit);
    };
    visit(scope);
    if (found) return found;
    if (ts.isSourceFile(scope)) break;
    scope = enclosingFunction(scope);
  }
  return null;
}

function returnsOf(fnNode) {
  const outs = [];
  if (!fnNode.body) return outs;
  if (!ts.isBlock(fnNode.body)) return [fnNode.body];
  const visit = (node) => {
    if (ts.isFunctionLike(node) && node !== fnNode) return;
    if (ts.isReturnStatement(node) && node.expression) outs.push(node.expression);
    ts.forEachChild(node, visit);
  };
  visit(fnNode.body);
  return outs;
}

/** per-code keys from a builder that switches/tests on code strings. */
function builderByCode(fnNode, sf) {
  const byCode = new Map();
  const add = (code, expr) => {
    const r = resolveExpr(expr, sf, expr, 1);
    if (!r || r.kind !== "keys") return;
    const cur = byCode.get(code) || { keys: new Set(), dynamic: false };
    r.keys.forEach((k) => cur.keys.add(k));
    cur.dynamic = cur.dynamic || r.dynamic;
    byCode.set(code, cur);
  };
  const visit = (node) => {
    if (ts.isDefaultClause(node)) {
      for (const stmt of node.statements) {
        const rets = [];
        const v = (n) => { if (ts.isReturnStatement(n) && n.expression) rets.push(n.expression); ts.forEachChild(n, v); };
        v(stmt);
        rets.forEach((e) => add("*", e));
      }
    }
    if (ts.isCaseClause(node) && ts.isStringLiteral(node.expression)) {
      // fall-through groups: collect consecutive empty cases
      const codes = [node.expression.text];
      let clause = node;
      while (clause.statements.length === 0) {
        const idx = clause.parent.clauses.indexOf(clause);
        const next = clause.parent.clauses[idx + 1];
        if (!next || !ts.isCaseClause(next) || !ts.isStringLiteral(next.expression)) break;
        codes.push(next.expression.text);
        clause = next;
      }
      for (const stmt of clause.statements) {
        const rets = [];
        const v = (n) => { if (ts.isReturnStatement(n) && n.expression) rets.push(n.expression); ts.forEachChild(n, v); };
        v(stmt);
        rets.forEach((e) => codes.forEach((c) => add(c, e)));
      }
    } else if (ts.isIfStatement(node) && ts.isBinaryExpression(node.expression)
      && node.expression.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken
      && ts.isStringLiteral(node.expression.right) && /^[A-Z][A-Z0-9_]*$/.test(node.expression.right.text)) {
      const rets = [];
      const v = (n) => { if (ts.isReturnStatement(n) && n.expression) rets.push(n.expression); ts.forEachChild(n, v); };
      v(node.thenStatement);
      rets.forEach((e) => add(node.expression.right.text, e));
    }
    ts.forEachChild(node, visit);
  };
  visit(fnNode);
  return byCode;
}

/** Resolve an expression to {kind:"keys"} | {kind:"byCode"} | null. */
function resolveExpr(expr, sf, at, depth) {
  if (!expr || depth > 4) return null;
  while (ts.isParenthesizedExpression(expr) || ts.isAsExpression(expr) || ts.isSatisfiesExpression?.(expr)) expr = expr.expression;
  if (ts.isObjectLiteralExpression(expr)) {
    const out = { kind: "keys", keys: new Set(), dynamic: false };
    literalKeys(expr, sf, out);
    return out;
  }
  if (ts.isConditionalExpression(expr)) {
    const a = resolveExpr(expr.whenTrue, sf, at, depth + 1);
    const b = resolveExpr(expr.whenFalse, sf, at, depth + 1);
    if (a && b && a.kind === "keys" && b.kind === "keys") {
      return { kind: "keys", keys: new Set([...a.keys, ...b.keys]), dynamic: a.dynamic || b.dynamic };
    }
    return null;
  }
  if (ts.isIdentifier(expr)) {
    const decl = findDeclaration(expr.text, at, sf);
    if (!decl) return null;
    if (ts.isVariableDeclaration(decl) && decl.initializer) {
      const r = resolveExpr(decl.initializer, sf, decl, depth + 1);
      if (r && r.kind === "keys") laterWrites(expr.text, enclosingFunction(decl), r);
      return r;
    }
    return null;
  }
  if (ts.isCallExpression(expr)) {
    const callee = expr.expression;
    const name = ts.isIdentifier(callee) ? callee.text : null;
    if (name === "useMemo" || name === "useCallback") {
      const fn = expr.arguments[0];
      if (fn && (ts.isArrowFunction(fn) || ts.isFunctionExpression(fn))) {
        const merged = { kind: "keys", keys: new Set(), dynamic: false };
        let any = false;
        for (const ret of returnsOf(fn)) {
          const r = resolveExpr(ret, sf, ret, depth + 1);
          if (r && r.kind === "keys") { any = true; r.keys.forEach((k) => merged.keys.add(k)); merged.dynamic ||= r.dynamic; }
          else if (r && r.kind === "byCode") return r;
          else merged.dynamic = true;
        }
        return any ? merged : null;
      }
      return null;
    }
    if (name) {
      const decl = findDeclaration(name, at, sf);
      const fn = decl && (ts.isFunctionDeclaration(decl) ? decl
        : decl.initializer && (ts.isArrowFunction(decl.initializer) || ts.isFunctionExpression(decl.initializer)) ? decl.initializer : null);
      if (fn) {
        const byCode = builderByCode(fn, sf);
        if (byCode.size) return { kind: "byCode", byCode };
        const merged = { kind: "keys", keys: new Set(), dynamic: false };
        let any = false;
        for (const ret of returnsOf(fn)) {
          const r = resolveExpr(ret, sf, ret, depth + 1);
          if (r && r.kind === "keys") { any = true; r.keys.forEach((k) => merged.keys.add(k)); merged.dynamic ||= r.dynamic; }
          else merged.dynamic = true;
        }
        return any ? merged : null;
      }
    }
    return null;
  }
  return null;
}

// ── scan ─────────────────────────────────────────────────────────────────
const result = new Map();
const unresolved = [];
const record = (code, keys, dynamic, file, conditional) => {
  const cur = result.get(code) || { keys: new Set(), dynamic: false, files: new Set(), conditional: new Set() };
  keys.forEach((k) => cur.keys.add(k));
  (conditional || []).forEach((k) => cur.conditional.add(k));
  cur.dynamic = cur.dynamic || dynamic;
  cur.files.add(file);
  result.set(code, cur);
};

for (const file of walk(UI)) {
  const text = readFileSync(file, "utf8");
  if (!/useFunction|runFunction/.test(text)) continue;
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const rel = relative(ROOT, file).replace(/\\/g, "/");
  const visit = (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)
      && (node.expression.text === "useFunction" || node.expression.text === "runFunction")) {
      let codeExpr = null;
      let paramsExpr = null;
      if (node.expression.text === "useFunction") {
        const arg = node.arguments[0];
        if (arg && ts.isObjectLiteralExpression(arg)) {
          for (const p of arg.properties) {
            const n = propName(p.name);
            const value = ts.isShorthandPropertyAssignment(p) ? p.name : p.initializer;
            if (n === "code") codeExpr = value;
            if (n === "params") paramsExpr = value;
          }
        }
      } else {
        codeExpr = node.arguments[0];
        const opts = node.arguments[1];
        if (opts && ts.isObjectLiteralExpression(opts)) {
          for (const p of opts.properties) {
            if (propName(p.name) === "params") paramsExpr = ts.isShorthandPropertyAssignment(p) ? p.name : p.initializer;
          }
        }
      }
      const where = `${rel}:${sf.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
      let codes = [];
      if (codeExpr && ts.isStringLiteral(codeExpr)) codes = [codeExpr.text];
      else codes = [...(fileCodes.get(file) || [])];
      if (!codes.length) { if (paramsExpr) unresolved.push({ where, why: "code not resolvable to a registry entry" }); }
      else if (!paramsExpr) codes.forEach((c) => record(c, new Set(), false, rel));
      else {
        const r = resolveExpr(paramsExpr, sf, paramsExpr, 0);
        if (!r) unresolved.push({ where, why: `params expression not resolvable (${ts.SyntaxKind[paramsExpr.kind]})` });
        else if (r.kind === "keys") codes.forEach((c) => record(c, r.keys, r.dynamic, rel, r.conditional));
        else codes.forEach((c) => {
          const per = r.byCode.get(c) || r.byCode.get("*");
          if (per) record(c, per.keys, per.dynamic, rel, per.conditional);
          else unresolved.push({ where, why: `builder has no branch for ${c}` });
        });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

const codes = {};
for (const [code, v] of [...result.entries()].sort()) {
  codes[code] = { keys: [...v.keys].sort(), conditional: [...v.conditional].sort(), dynamic: v.dynamic,
    files: [...v.files].sort() };
}
process.stdout.write(JSON.stringify({ codes, unresolved }, null, 2) + "\n");
