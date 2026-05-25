/**
 * Pane completeness inventory.
 *
 * Derives a per-code readiness record over the union of:
 *   • native registry codes (ui/src/functions/registry.tsx)
 *   • template codes      (ui/src/templates/mock-data.ts)
 *   • design-export codes (ui/src/design-export/showme-design-export.tsx —
 *                          DESIGN_BASIC_CODES ∪ DESIGN_PRO_CODES)
 *
 * The 10 critical codes (GP, HP, DES, WATCH, SCAN, PORT, TOP, NI, CN, MIS)
 * are the panes the trader-facing surface depends on for real positions
 * and live market data. Per S05 they must render the bespoke native pane
 * or an explicit "critical-missing" guard pane — never a static design
 * export or a `/api/fn/{code}` stub. This module is the canonical source
 * of that list and the derived readiness flags that Workspace.tsx, the
 * regression tests, and any downstream catalog dashboard consult.
 *
 * S05 — 2026-05-20
 */
// 2026-05-24 rebuild: design-export + templates introspection moved to
// dev-only (`ui/src/dev/pane-completeness-dev.ts`). Production paths no
// longer import those modules. The resolver collapses non-critical codes
// to "stub" which Workspace.tsx then renders via ManifestPane (contract-
// driven shell with explicit "manifest not registered" empty state).
import { listNativeCodes, resolvePane } from "@/functions/registry";

// Stub helpers so the legacy adapter shape still type-checks. The dev tool
// at ui/src/dev/pane-completeness-dev.ts re-injects real adapters for the
// catalog dashboard if a developer needs the historical inventory view.
const DESIGN_PRO_CODES: readonly string[] = [];
const DESIGN_BASIC_CODES: readonly string[] = [];
function hasDesignExportComponent(_code: string): boolean {
  return false;
}
function listMockCodes(): string[] {
  return [];
}
function getMockTemplate(_code: string): unknown | null {
  return null;
}

/**
 * Critical pane codes. Render native pane only — never fall through to
 * template, design-export, or stub. If a native renderer is missing for
 * one of these codes the user sees an explicit `<CriticalMissingPane>`
 * instead of a degraded surface that pretends to work.
 */
export const CRITICAL_CODES = [
  "GP",
  "HP",
  "DES",
  "WATCH",
  "SCAN",
  "PORT",
  "TOP",
  "NI",
  "CN",
  "MIS",
] as const;

export type CriticalCode = (typeof CRITICAL_CODES)[number];

const CRITICAL_SET: ReadonlySet<string> = new Set(CRITICAL_CODES);

export function isCriticalCode(code: string): boolean {
  return CRITICAL_SET.has(code.toUpperCase());
}

/**
 * The pane-renderer choice for a code. The first four mirror the
 * non-critical precedence order. `"critical-missing"` is reserved for
 * critical codes whose native renderer is absent — never returned for
 * non-critical codes.
 */
export type PaneRendererChoice =
  | "native"
  | "template"
  | "design-export"
  | "stub"
  | "critical-missing";

/**
 * Optional resolver adapters. Default to the real registry / template /
 * design-export modules; tests inject stubs to simulate a missing
 * native renderer for a critical code.
 */
export interface PaneResolveAdapters {
  hasNative?: (code: string) => boolean;
  hasTemplate?: (code: string) => boolean;
  hasDesignExport?: (code: string) => boolean;
}

function defaultHasNative(code: string): boolean {
  return resolvePane(code) !== null;
}
function defaultHasTemplate(code: string): boolean {
  return getMockTemplate(code) !== null;
}

/**
 * Map a code to its renderer choice. Critical codes get the strict
 * native-or-missing branch; non-critical codes follow the existing
 * native > template > design-export > stub precedence.
 */
export function resolvePaneRenderer(
  code: string,
  adapters?: PaneResolveAdapters,
): PaneRendererChoice {
  const upper = code.toUpperCase();
  const hasNative = adapters?.hasNative ?? defaultHasNative;
  const hasTpl = adapters?.hasTemplate ?? defaultHasTemplate;
  const hasDe = adapters?.hasDesignExport ?? hasDesignExportComponent;

  if (CRITICAL_SET.has(upper)) {
    // Critical short-circuit: native-or-missing, never degrade.
    return hasNative(upper) ? "native" : "critical-missing";
  }
  if (hasNative(upper)) return "native";
  if (hasTpl(upper)) return "template";
  if (hasDe(upper)) return "design-export";
  return "stub";
}

/**
 * Per-code readiness signal. Every flag is a deterministic derivation
 * from the resolver choice — no runtime introspection. A future
 * "catalog completeness" dashboard can render this directly.
 */
export interface PaneInventoryEntry {
  code: string;
  renderer: PaneRendererChoice;
  critical: boolean;
  native_ui_ready: boolean;
  live_data_ready: boolean;
  interaction_ready: boolean;
  a11y_ready: boolean;
  test_ready: boolean;
  synthetic_risk: "none" | "low" | "medium" | "high";
}

/**
 * Build a flag set from a resolver choice. Kept side-effect-free so the
 * inventory test can pin the mapping with a parametric expectation.
 *
 *   native        → live data + real interaction + a11y + tests, no synthetic risk
 *   template      → live data via overlay, generic layout, low synthetic risk
 *   stub          → live data via /api/fn/{code} but no shape, low synthetic risk
 *   design-export → no live data, static mockup, medium synthetic risk
 *   critical-missing → catastrophic gap, high synthetic risk
 */
export function readinessFlags(
  choice: PaneRendererChoice,
): Omit<PaneInventoryEntry, "code" | "renderer" | "critical"> {
  switch (choice) {
    case "native":
      return {
        native_ui_ready: true,
        live_data_ready: true,
        interaction_ready: true,
        a11y_ready: true,
        test_ready: true,
        synthetic_risk: "none",
      };
    case "template":
      return {
        native_ui_ready: false,
        // TemplateRenderer pulls a live overlay over the mock shape —
        // see ui/src/templates/TemplateRenderer.tsx `mergeLivePayload`.
        live_data_ready: true,
        interaction_ready: false,
        a11y_ready: true,
        test_ready: true,
        synthetic_risk: "low",
      };
    case "stub":
      return {
        native_ui_ready: false,
        // FunctionStub calls /api/fn/{code} so the data is real, even
        // though the rendering is a generic JSON tree.
        live_data_ready: true,
        interaction_ready: false,
        a11y_ready: false,
        test_ready: false,
        synthetic_risk: "low",
      };
    case "design-export":
      return {
        native_ui_ready: false,
        live_data_ready: false,
        interaction_ready: false,
        // Design exports ship as Pro mockups — they have semantic markup
        // but no aria-live regions and no keyboard wiring.
        a11y_ready: false,
        test_ready: false,
        synthetic_risk: "medium",
      };
    case "critical-missing":
      return {
        native_ui_ready: false,
        live_data_ready: false,
        interaction_ready: false,
        a11y_ready: false,
        test_ready: false,
        synthetic_risk: "high",
      };
  }
}

/**
 * Build the full inventory over the deduplicated union of all known
 * codes. Sorted by code so the snapshot is stable across runs.
 */
export function paneInventory(adapters?: PaneResolveAdapters): PaneInventoryEntry[] {
  const all = new Set<string>();
  for (const c of listNativeCodes()) all.add(c.toUpperCase());
  for (const c of listMockCodes()) all.add(c.toUpperCase());
  for (const c of DESIGN_PRO_CODES) all.add(c.toUpperCase());
  for (const c of DESIGN_BASIC_CODES) all.add(c.toUpperCase());
  // The 10 critical codes are explicitly included even if they somehow
  // disappear from every catalog source — the inventory must always be
  // able to report on them so a missing native still surfaces.
  for (const c of CRITICAL_CODES) all.add(c);

  return Array.from(all)
    .sort()
    .map((code) => {
      const renderer = resolvePaneRenderer(code, adapters);
      return {
        code,
        renderer,
        critical: CRITICAL_SET.has(code),
        ...readinessFlags(renderer),
      };
    });
}

/**
 * Helper for callers that just want the critical-pane subset (e.g. a
 * deploy-time guard that fails CI when a critical pane is missing).
 */
export function criticalInventory(
  adapters?: PaneResolveAdapters,
): PaneInventoryEntry[] {
  return paneInventory(adapters).filter((entry) => entry.critical);
}
