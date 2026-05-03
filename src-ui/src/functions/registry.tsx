/**
 * Pane registry — maps a ShowMe function code to its native React component.
 * Codes not present here fall back to `FunctionStub`, which talks to the
 * sidecar via `/api/fn/{code}` and renders the raw payload.
 */
import type { ComponentType } from "react";
import type { FunctionEntry } from "@/lib/sidecar";
import type { FunctionPaneProps } from "./registry-types";
import { DESPane } from "./DES";
import { FAPane } from "./FA";
import { GPPane } from "./GP";
import { EQSPane } from "./EQS";
import { PORTPane } from "./PORT";
import { SCANPane } from "./SCAN";
import { ASKPane } from "./ASK";
import { TOPPane } from "./TOP";
import { ECOPane } from "./ECO";
import { WATCHPane } from "./WATCH";
import { ALRTPane } from "./ALRT";
import { NIPane } from "./NI";
import { MOSTPane } from "./MOST";
import { WEIPane } from "./WEI";
import { HPPane } from "./HP";
import { TRANPane } from "./TRAN";
import { WCRSPane } from "./WCRS";
import { GLCOPane } from "./GLCO";
import { AGENTPane } from "./AGENT";
import { BTMMPane } from "./BTMM";

const PANES: Record<string, ComponentType<FunctionPaneProps>> = {
  AGENT: AGENTPane,
  DES: DESPane,
  FA: FAPane,
  GP: GPPane,
  TECH: GPPane,           // TECH alias to the same chart pane (Round 14).
  EQS: EQSPane,
  PORT: PORTPane,
  SCAN: SCANPane,
  ASK: ASKPane,
  TOP: TOPPane,
  ECO: ECOPane,
  WATCH: WATCHPane,
  ALRT: ALRTPane,
  NI: NIPane,
  CN: NIPane,             // CN alias — ShowMe ships either NI or CN.
  MOST: MOSTPane,
  WEI: WEIPane,
  HP: HPPane,
  TRAN: TRANPane,
  WCRS: WCRSPane,
  GLCO: GLCOPane,
  BTMM: BTMMPane,
};

const NATIVE_FUNCTION_ENTRIES: FunctionEntry[] = [
  {
    code: "AGENT",
    name: "Symbol Agent",
    category: "screen",
    description: "Ranks the open function set for a selected market symbol.",
  },
  {
    code: "ASK",
    name: "Ask",
    category: "screen",
    description: "Interactive research assistant pane backed by ShowMe functions.",
  },
  {
    code: "CN",
    name: "Company News",
    category: "news",
    description: "Live company and market news stream with symbol relevance controls.",
  },
  {
    code: "WATCH",
    name: "Live Watchlist",
    category: "portfolio",
    description: "User-managed watchlist with live last price, change, source, and removal controls.",
  },
];

export function resolvePane(code: string): ComponentType<FunctionPaneProps> | null {
  return PANES[code.toUpperCase()] ?? null;
}

export function listNativeCodes(): string[] {
  return Object.keys(PANES).sort();
}

export function listNativeFunctionEntries(): FunctionEntry[] {
  return [...NATIVE_FUNCTION_ENTRIES].sort((a, b) => a.code.localeCompare(b.code));
}

export function mergeNativeFunctionIndex(index: FunctionEntry[]): FunctionEntry[] {
  const seen = new Set(index.map((entry) => entry.code.toUpperCase()));
  const merged = [...index];
  for (const entry of listNativeFunctionEntries()) {
    if (seen.has(entry.code)) continue;
    merged.push(entry);
    seen.add(entry.code);
  }
  return merged;
}
