/**
 * Palette v2 symbol universe — the tickers the app already knows.
 *
 * Campaign 2026-09-08 (Lane B, U1): typing "AAPL" in ⌘K used to yield
 * "No results" because the palette only indexed function codes. This module
 * composes the symbol universe from sources that already exist:
 *
 *   1. Recent symbols        — lib/symbols.ts localStorage stack (recents
 *                              rank first upstream).
 *   2. Bound symbols         — symbols currently bound to workspace leaves.
 *   3. Curated quick symbols — the same seed the SymbolBar datalist offers.
 *   4. S&P 500 constituents  — static catalog shipped in ui/src/data/sp500.json.
 *
 * Pure data — no network, no new service (the DO-NOT list forbids rebuilding
 * symbol search; this only composes existing lists for palette matching).
 */
import sp500Json from "@/data/sp500.json";
import { listRecentSymbols, normalizeSymbolInput } from "./symbols";
import { useWorkspace, type WorkspaceNode } from "./workspace";

/** Same seed the SymbolBar datalist offers, normalized to canonical tickers. */
const QUICK_SYMBOLS: string[] = [
  "AAPL",
  "MSFT",
  "NVDA",
  "TSLA",
  "SPY",
  "QQQ",
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "EURUSD",
  "GBPUSD=X",
  "GC=F",
  "CL=F",
  "US10Y",
];

function sp500Constituents(): string[] {
  const raw = (sp500Json as { constituents?: unknown }).constituents;
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item !== "string") continue;
    const normalized = normalizeSymbolInput(item);
    if (normalized) out.push(normalized);
  }
  return out;
}

let staticSymbolsCache: string[] | null = null;

/** Curated quick list + the full static catalog (cached, deduped, canonical). */
export function listStaticPaletteSymbols(): string[] {
  if (staticSymbolsCache) return staticSymbolsCache;
  const seen = new Set<string>();
  const out: string[] = [];
  for (const sym of [...QUICK_SYMBOLS, ...sp500Constituents()]) {
    const normalized = normalizeSymbolInput(sym);
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    out.push(normalized);
  }
  staticSymbolsCache = out;
  return out;
}

function collectLeafSymbols(node: WorkspaceNode, out: string[]): void {
  if (node.kind === "leaf") {
    const normalized = normalizeSymbolInput(node.symbol);
    if (normalized) out.push(normalized);
    return;
  }
  for (const child of node.children) collectLeafSymbols(child, out);
}

/** Symbols currently bound to any workspace leaf (the desk's open tickers). */
export function listBoundSymbols(): string[] {
  const out: string[] = [];
  try {
    collectLeafSymbols(useWorkspace.getState().tree, out);
  } catch {
    // Workspace store unavailable (unit-test edge) — bound set is empty.
  }
  return out;
}

/**
 * Full palette symbol universe, ordered by likely relevance:
 * recents → bound (open on the desk) → curated quick → static catalog.
 */
export function listPaletteSymbolUniverse(): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const sym of [
    ...listRecentSymbols(),
    ...listBoundSymbols(),
    ...listStaticPaletteSymbols(),
  ]) {
    const normalized = normalizeSymbolInput(sym);
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    out.push(normalized);
  }
  return out;
}
