#!/usr/bin/env node
/**
 * scripts/verify_routing_coverage.mjs
 *
 * Asserts the 155/155 routing-coverage invariant for the ShowMe terminal:
 *   - UI catalog (STATIC_FUNCTION_INDEX) is 141 entries.
 *   - Native registry (NATIVE_FUNCTION_ENTRIES) contributes 14 codes not in
 *     the static index (AGENT, ASK, BDA, BOT, BOTS, CONN, INDX, INSTANT, MIS,
 *     PERF, STRA, TMPL, WATCH, XSEN — CN overlaps and is dedup'd).
 *   - mergeNativeFunctionIndex(STATIC_FUNCTION_INDEX) yields 155.
 *   - When SHOWME_SIDECAR_URL is set, GET /api/function-index returns the
 *     same set of codes minus the native-only exceptions.
 *
 * Exit 0 on success, exit 1 on any failed invariant. Output is JSON for CI
 * consumption.
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const staticTs = readFileSync(
  resolve(ROOT, "ui/src/functions/static-index.ts"),
  "utf8",
);
const staticCodes = [
  ...staticTs.matchAll(/"code":\s*"([A-Z0-9_]+)"/g),
].map((m) => m[1]);

const registryTs = readFileSync(
  resolve(ROOT, "ui/src/functions/registry.tsx"),
  "utf8",
);
const panesBlock =
  registryTs.match(
    /const PANES:\s*Record<string,\s*PaneComponent>\s*=\s*\{([\s\S]*?)\};/,
  )?.[1] ?? "";
const paneKeys = [...panesBlock.matchAll(/^\s*([A-Z0-9_]+)\s*:/gm)].map(
  (m) => m[1],
);
const nativeBlock =
  registryTs.match(
    /const NATIVE_FUNCTION_ENTRIES:\s*FunctionEntry\[\]\s*=\s*\[([\s\S]*?)\];/,
  )?.[1] ?? "";
const nativeCodes = [
  ...nativeBlock.matchAll(/code:\s*"([A-Z0-9_]+)"/g),
].map((m) => m[1]);

const merged = new Set(staticCodes);
for (const c of nativeCodes) merged.add(c);
const mergedArr = [...merged].sort();

const NATIVE_ENDPOINT_EXCEPTIONS = new Set([
  "AGENT",
  "ASK",
  "BDA",
  "BOT",
  "BOTS",
  "CONN",
  "INDX",
  "INSTANT",
  "MIS",
  "PERF",
  "STRA",
  "TMPL",
  "WATCH",
  "XSEN",
]);

const errors = [];
if (staticCodes.length !== 141) {
  errors.push(
    `STATIC_FUNCTION_INDEX has ${staticCodes.length} entries, expected 141`,
  );
}
if (mergedArr.length !== 155) {
  errors.push(
    `merged catalog has ${mergedArr.length} entries, expected 155`,
  );
}
for (const c of NATIVE_ENDPOINT_EXCEPTIONS) {
  if (!paneKeys.includes(c)) {
    errors.push(
      `native-endpoint code ${c} is missing from PANES (no native pane)`,
    );
  }
}

const sidecarUrl =
  process.env.SHOWME_SIDECAR_URL || process.env.SHOWME_AUDIT_URL || null;
let liveCodes = null;
if (sidecarUrl) {
  try {
    const res = await fetch(`${sidecarUrl}/api/function-index`);
    if (!res.ok) {
      errors.push(`live /api/function-index returned HTTP ${res.status}`);
    } else {
      const idx = await res.json();
      liveCodes = Array.from(new Set(idx.map((e) => e.code))).sort();
      if (liveCodes.length < 141) {
        errors.push(
          `live /api/function-index has ${liveCodes.length} codes, expected >= 141`,
        );
      }
      const liveSet = new Set(liveCodes);
      for (const code of mergedArr) {
        if (!NATIVE_ENDPOINT_EXCEPTIONS.has(code) && !liveSet.has(code)) {
          errors.push(`UI code ${code} has no /api/fn/${code} handler`);
        }
      }
    }
  } catch (err) {
    errors.push(`could not reach sidecar at ${sidecarUrl}: ${err.message}`);
  }
}

const report = {
  ok: errors.length === 0,
  staticCount: staticCodes.length,
  nativeOnlyCount: nativeCodes.filter((c) => !staticCodes.includes(c)).length,
  paneCount: paneKeys.length,
  mergedCount: mergedArr.length,
  liveCount: liveCodes?.length ?? null,
  errors,
};
process.stdout.write(JSON.stringify(report, null, 2) + "\n");
process.exit(report.ok ? 0 : 1);
