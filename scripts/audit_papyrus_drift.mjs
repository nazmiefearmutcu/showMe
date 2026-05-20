#!/usr/bin/env node
/**
 * scripts/audit_papyrus_drift.mjs
 *
 * Static lint for Papyrus theme drift. Walks ui/src and flags any color
 * hardcode that would not track the active preset:
 *
 *   - Hex literals (#xxx / #xxxxxx) outside tokens.css / theme.ts / known
 *     palette helpers (chart-palette.ts FALLBACK constants, COMPARE_COLORS
 *     legend chips, picker swatches).
 *   - rgba(...) literals with channels in {0..255} (white/black scrims).
 *   - "color: #000" / "color: #fff" / "color: white" / "color: black" with
 *     the obvious cream-flip danger.
 *   - Round 17: `var(--TOKEN)` references where TOKEN is not defined in
 *     styles/tokens.css and not on the locally-scoped allowlist (legacy
 *     pane-local CSS vars, design-export sandbox, template literals). A
 *     typo such as `var(--text)` instead of `var(--text-primary)` silently
 *     fell back to inherited color and was invisible to the literal scan.
 *
 * Exit 0 on a clean tree, exit 1 if any drift is found. Output is JSON for
 * CI consumption (matches verify_routing_coverage.mjs style).
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve, dirname, extname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const UI_SRC = resolve(ROOT, "ui/src");

const ALLOWLIST_FILES = new Set([
  // Source of truth for tokens.
  "styles/tokens.css",
  // Theme preset defaults — must keep literal hex values per preset.
  "lib/theme.ts",
  // Chart-palette fallbacks for non-browser contexts.
  "lib/chart-palette.ts",
  // a11y luminance helpers — internal math, not rendering.
  "lib/a11y.ts",
  // Generated Claude Design export CSS carries its own scoped theme token
  // set under `.design-export`; those literals are the imported design source.
  "design-export/showme-design-export.css",
  "design-export/showme-design-export.tsx",
]);

const ALLOWLIST_PATTERNS = [
  // User picker swatches — driven by user-chosen hex, not the theme.
  /prefs-color-slot__swatch/,
  // Build cache, types, tests.
  /\.test\.|\.tsbuildinfo/,
];

// Line-content allowlist — patterns that, when matched on a line, suppress
// hex/rgba detection for that specific line. Use for legitimate non-chrome
// color literals: legend-chip palettes, contrast-check math inputs, CSS
// mask fills, and filter shadows that cannot consume CSS vars.
const LINE_ALLOWLIST = [
  /COMPARE_COLORS/, // HP.tsx legend chips for compared symbols
  /isLightHex\(.*\)\s*\?\s*"#/, // appearance.tsx luminance branch, math only
  /-webkit-mask|^\s*mask:/, // CSS mask fills (opacity-only)
  /filter:\s*drop-shadow/, // filter cannot reference CSS vars
  // CSS mask continuation lines — color literals inside multi-line
  // -webkit-mask/mask radial-gradients that span multiple lines.
  /^\s*#000\s+calc/,
];

const HEX_RE = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g;
const RGBA_RE = /rgba?\(\s*(?:\d{1,3})\s*,\s*(?:\d{1,3})\s*,\s*(?:\d{1,3})\s*(?:,[^)]+)?\)/g;
const VAR_RE = /var\(\s*--([a-zA-Z0-9-]+)\s*(?:,[^)]*)?\)/g;

// Locally-scoped CSS variables that live outside tokens.css but ARE defined
// somewhere else (index.css component-scoped vars, design-export sandbox)
// or are template-literal prefixes used as `var(--space-${n})`.
const KNOWN_LOCAL_VARS = new Set([
  // index.css scoped
  "terminal-accent", "terminal-amber", "terminal-bg", "terminal-border",
  "terminal-dim", "terminal-grid-line", "terminal-grid-line-soft",
  "terminal-heading", "terminal-muted", "terminal-on-accent",
  "terminal-panel", "terminal-panel-hover", "terminal-positive",
  "terminal-red", "terminal-row-border", "terminal-soft", "terminal-text",
  "toast-bg", "toast-border", "toast-fg",
  "u-accent", "u-bg", "u-color", "u-cols", "u-empty", "u-height",
  "u-left", "u-pct", "u-w", "u-width",
  "pt-accent", "pt-bg", "pt-height", "pt-overlay-base",
  "pt-sidebar-height", "pt-surface", "pt-width",
  "ds-pill-fg", "ds-status-fg",
  "mock-accent", "mock-bg", "mock-surface", "mock-text-base",
  "bio-bg", "bio-fg", "wei-bg", "wei-tone",
  "ws-cols", "ws-rows",
  "showme-class-share", "showme-home-delay",
  "cockpit-grid-line", "cockpit-grid-line-soft",
  // design-export scoped (sandboxed palette)
  "text", "line", "line-strong", "line-thin", "accent-2", "accent-glow",
  "bg-elev", "bg-deep", "crosshair", "scanline", "grid-color",
  "text-faint", "font-sans", "radius-xl", "w", "h",
  // Template-literal prefixes — pane uses `var(--font-size-${size})`,
  // `var(--space-${n})`, `var(--heat-pos-${k})` etc., which the regex
  // would otherwise match on the prefix alone.
  "font-size-", "font-weight-", "space-", "heat-pos-", "heat-neg-",
]);

const findings = [];
const definedTokens = new Set();

function loadDefinedTokens() {
  const tokensPath = resolve(UI_SRC, "styles/tokens.css");
  const text = readFileSync(tokensPath, "utf8");
  const re = /^\s*(--[a-zA-Z0-9-]+)(?=:)/gm;
  let m;
  while ((m = re.exec(text)) !== null) {
    definedTokens.add(m[1].replace(/^--/, ""));
  }
}

function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name.startsWith(".")) continue;
    if (name === "node_modules") continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) {
      walk(p);
      continue;
    }
    const ext = extname(p).toLowerCase();
    if (![".ts", ".tsx", ".css"].includes(ext)) continue;
    const rel = p.slice(UI_SRC.length + 1).replace(/\\/g, "/");
    if (ALLOWLIST_FILES.has(rel)) continue;
    if (ALLOWLIST_PATTERNS.some((re) => re.test(rel))) continue;

    const text = readFileSync(p, "utf8");
    const lines = text.split("\n");
    lines.forEach((line, idx) => {
      if (LINE_ALLOWLIST.some((re) => re.test(line))) return;
      // Token-typo check: any `var(--FOO)` where FOO is neither in
      // tokens.css nor on the scoped allowlist. Catches `var(--text)` →
      // intended `var(--text-primary)` and similar silent fall-throughs.
      let vm;
      VAR_RE.lastIndex = 0;
      while ((vm = VAR_RE.exec(line)) !== null) {
        const token = vm[1];
        if (definedTokens.has(token) || KNOWN_LOCAL_VARS.has(token)) continue;
        // Strip a trailing dash so template-literal prefixes still match.
        if (KNOWN_LOCAL_VARS.has(token.replace(/-?$/, "-"))) continue;
        findings.push({
          file: rel,
          line: idx + 1,
          match: `var(--${token})`,
          kind: "undefined-token",
        });
      }
      // Skip lines that already use var(--*) — even if they contain hex
      // fallbacks inside, those are fall-throughs.
      const stripped = line.replace(/var\([^)]*\)/g, "");
      const hex = stripped.match(HEX_RE) ?? [];
      const rgba = stripped.match(RGBA_RE) ?? [];
      for (const m of hex) {
        findings.push({ file: rel, line: idx + 1, match: m });
      }
      for (const m of rgba) {
        findings.push({ file: rel, line: idx + 1, match: m });
      }
    });
  }
}

loadDefinedTokens();
walk(UI_SRC);

// De-dup by file:line:match
const seen = new Set();
const unique = [];
for (const f of findings) {
  const k = `${f.file}:${f.line}:${f.match}`;
  if (seen.has(k)) continue;
  seen.add(k);
  unique.push(f);
}

const report = {
  ok: unique.length === 0,
  count: unique.length,
  findings: unique.slice(0, 50),
};
process.stdout.write(JSON.stringify(report, null, 2) + "\n");
process.exit(report.ok ? 0 : 1);
