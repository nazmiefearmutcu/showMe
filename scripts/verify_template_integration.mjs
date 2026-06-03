#!/usr/bin/env node
/**
 * scripts/verify_template_integration.mjs
 *
 * Enumerates every `window.Basic*` / `window.Pro*` template in the
 * Design export, maps each to its ShowMe fn code, and checks that the real
 * repo has a dedicated template-backed renderer (TemplateRenderer pattern
 * or a bespoke native pane) for it. Generic FunctionStub fallback for a
 * code that HAS a design template is reported as a failure.
 *
 * Usage:
 *   node scripts/verify_template_integration.mjs
 *
 * Exit 0 when every design-templated code resolves to a dedicated renderer;
 * exit 1 otherwise. Output is JSON for CI consumption.
 */
import { readdirSync, readFileSync, existsSync, statSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DESIGN_SRC =
  process.env.SHOWME_DESIGN_SRC ||
  "/Users/nazmi/Desktop/ShowMe_Designs_2026-05-16/conversation-2-ShowMe-0.01-019e2b82/src";
const TEMPLATES_DIR = resolve(ROOT, "ui/src/templates");
const REGISTRY_TSX = resolve(ROOT, "ui/src/functions/registry.tsx");
const DESIGN_EXPORT_TSX = resolve(ROOT, "ui/src/design-export/showme-design-export.tsx");
const WORKSPACE_TSX = resolve(ROOT, "ui/src/shell/Workspace.tsx");
const PREFS_TSX = resolve(ROOT, "ui/src/panes/preferences_pane/index.tsx");

// Names that appear in design but are app-shell surfaces, NOT fn codes.
const SHELL_ONLY = new Set(["Home", "Cala", "Keyb", "Nsex", "Prtl", "Catalog"]);

// Special PascalCase-to-fn-code transforms.
const SPECIAL_CODE_MAP = {
  PortOpt: "PORT_OPT",
  PortWhatif: "PORT_WHATIF",
  Form4: "FORM4",
  Gc3d: "GC3D",
};

function designToFnCode(name) {
  if (SHELL_ONLY.has(name)) return null;
  return SPECIAL_CODE_MAP[name] ?? name.toUpperCase();
}

function readSrcFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    if (!/\.jsx$/.test(name)) continue;
    if (!/^(pages|basic|pro)/.test(name)) continue;
    out.push(join(dir, name));
  }
  return out;
}

function collectDesignCodes() {
  if (!existsSync(DESIGN_SRC)) {
    return { error: `design export not found at ${DESIGN_SRC}` };
  }
  const files = readSrcFiles(DESIGN_SRC);
  const basic = new Map();
  const pro = new Map();
  for (const f of files) {
    const text = readFileSync(f, "utf8");
    for (const m of text.matchAll(/^window\.(Basic|Pro)([A-Za-z0-9_]+)\s*=/gm)) {
      const variant = m[1];
      const name = m[2];
      const map = variant === "Basic" ? basic : pro;
      if (!map.has(name)) map.set(name, []);
      map.get(name).push(f.slice(DESIGN_SRC.length + 1));
    }
  }
  return { basic, pro };
}

function collectRepoCoverage() {
  const dedicated = new Set();
  const templated = new Set();
  const generatedBasic = new Set();
  const generatedPro = new Set();
  const generatedSettings = new Set();

  // Native panes from registry.tsx PANES map.
  if (existsSync(REGISTRY_TSX)) {
    const text = readFileSync(REGISTRY_TSX, "utf8");
    const panesBlock =
      text.match(/const PANES:[^=]*=\s*\{([\s\S]*?)\};/)?.[1] ?? "";
    for (const m of panesBlock.matchAll(/^\s*([A-Z0-9_]+)\s*:/gm)) {
      dedicated.add(m[1]);
    }
  }

  // Template-backed codes come from ui/src/templates/mock-data.ts. We
  // parse the top-level TPL object literal and collect its keys.
  const mockPath = join(TEMPLATES_DIR, "mock-data.ts");
  if (existsSync(mockPath)) {
    const text = readFileSync(mockPath, "utf8");
    const tplBlock = text.match(/const TPL:[^=]*=\s*\{([\s\S]*?)\n\};/)?.[1] ?? "";
    for (const m of tplBlock.matchAll(/^\s{2}([A-Z0-9_]+):/gm)) {
      templated.add(m[1]);
    }
  }

  if (existsSync(DESIGN_EXPORT_TSX)) {
    const text = readFileSync(DESIGN_EXPORT_TSX, "utf8");
    for (const [exportName, target] of [
      ["DESIGN_BASIC_CODES", generatedBasic],
      ["DESIGN_PRO_CODES", generatedPro],
      ["DESIGN_SETTINGS_CODES", generatedSettings],
    ]) {
      const raw = text.match(new RegExp(`export const ${exportName} = (\\[[^\\n]+\\]) as const;`))?.[1];
      if (!raw) continue;
      for (const code of JSON.parse(raw)) target.add(code);
    }
  }

  return { dedicated, templated, generatedBasic, generatedPro, generatedSettings };
}

const designs = collectDesignCodes();
if (designs.error) {
  process.stdout.write(
    JSON.stringify({ ok: false, error: designs.error }, null, 2) + "\n",
  );
  process.exit(1);
}

const designCodes = new Set();
const designShellOnly = new Set();
for (const name of designs.basic.keys()) {
  const code = designToFnCode(name);
  if (code) designCodes.add(code);
  else designShellOnly.add(name);
}

const { dedicated, templated, generatedBasic, generatedPro, generatedSettings } = collectRepoCoverage();

const missing = [];
const missingGeneratedExport = [];
for (const code of designCodes) {
  const hasDedicated = dedicated.has(code);
  const hasTemplate = templated.has(code);
  const hasGeneratedExport = generatedBasic.has(code) && generatedPro.has(code);
  if (!hasGeneratedExport) missingGeneratedExport.push(code);
  if (!hasDedicated && !hasTemplate) {
    missing.push(code);
  } else if (!hasDedicated && hasTemplate) {
    // template-backed (good)
  }
  // dedicated is the best (bespoke React pane)
}

const settingsRequired = [
  "APPEARANCE",
  "DATA",
  "STREAMS",
  "SECRETS",
  "MIGRATION",
  "LLM",
  "ABOUT",
];
const missingSettings = settingsRequired.filter((code) => !generatedSettings.has(code));

const workspaceText = existsSync(WORKSPACE_TSX) ? readFileSync(WORKSPACE_TSX, "utf8") : "";
const completenessTs = resolve(ROOT, "ui/src/lib/pane-completeness.ts");
const completenessText = existsSync(completenessTs) ? readFileSync(completenessTs, "utf8") : "";

// The resolution logic is now encapsulated in `ui/src/lib/pane-completeness.ts`.
// We assert that the priority order is native > template > design-export.
const hasNativeIdx = completenessText.indexOf("hasNative(upper)");
const hasDeIdx = completenessText.indexOf("hasDe(upper)");
const workspacePrefersNative =
  hasNativeIdx !== -1 &&
  hasDeIdx !== -1 &&
  hasNativeIdx < hasDeIdx;

const workspaceKeepsDesignFallback =
  workspaceText.includes("hasDesignExportComponent(node.code)") ||
  completenessText.includes("hasDesignExportComponent");
const prefsText = existsSync(PREFS_TSX) ? readFileSync(PREFS_TSX, "utf8") : "";
// After the Session 16 BugHunt the Preferences pane re-enables the native
// section components and uses the SettingsDesignExportRenderer only as a
// chrome shell. We require BOTH to be wired so theme + density + slot
// controls are reachable.
const prefsUsesDesign = prefsText.includes("SettingsDesignExportRenderer");
const prefsUsesNativeSections =
  prefsText.includes("AppearanceSection") &&
  prefsText.includes("DataSection") &&
  prefsText.includes("LlmSection") &&
  prefsText.includes("AboutSection");

// Coverage shape
const report = {
  ok:
    missing.length === 0 &&
    missingGeneratedExport.length === 0 &&
    missingSettings.length === 0 &&
    workspacePrefersNative &&
    workspaceKeepsDesignFallback &&
    prefsUsesDesign &&
    prefsUsesNativeSections,
  designBasicTemplates: designs.basic.size,
  designProTemplates: designs.pro.size,
  designShellOnly: [...designShellOnly].sort(),
  designFnCodes: designCodes.size,
  generatedBasicCodes: [...generatedBasic].sort(),
  generatedBasicCount: generatedBasic.size,
  generatedProCodes: [...generatedPro].sort(),
  generatedProCount: generatedPro.size,
  generatedSettingsCodes: [...generatedSettings].sort(),
  generatedSettingsCount: generatedSettings.size,
  dedicatedNativePanes: [...dedicated].sort(),
  dedicatedCount: dedicated.size,
  mockTemplateBackedCodes: [...templated].sort(),
  mockTemplateBackedCount: templated.size,
  missingDedicatedAndTemplate: missing.sort(),
  missingGeneratedExport: missingGeneratedExport.sort(),
  missingSettings,
  workspacePrefersNative,
  workspaceKeepsDesignFallback,
  prefsUsesDesign,
  prefsUsesNativeSections,
  missingCount: missing.length,
};
process.stdout.write(JSON.stringify(report, null, 2) + "\n");
process.exit(report.ok ? 0 : 1);
