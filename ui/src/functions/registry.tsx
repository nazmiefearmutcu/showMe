/**
 * Pane registry — maps a ShowMe function code to its native React component.
 * Codes not present here fall back to `FunctionStub`, which talks to the
 * sidecar via `/api/fn/{code}` and renders the raw payload.
 *
 * ROUND-2B (PERF-02): every pane is loaded via `React.lazy` + Suspense in
 * `Workspace.PaneContent`. The eager modulepreload count drops from 38 → ~3.
 * Welcome / FunctionStub / Preferences are imported lazily as well so the
 * entry chunk only ships shell + design system.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import type { FunctionEntry } from "@/lib/sidecar";
import type { FunctionPaneProps } from "./registry-types";

type PaneComponent =
  | ComponentType<FunctionPaneProps>
  | LazyExoticComponent<ComponentType<FunctionPaneProps>>;

// Each lazy-loaded pane chunk is named via the `webpackChunkName`-style hint
// in the import path; Vite's manualChunks splits by `/src/functions/` already.
const ANRPane = lazy(() => import("./ANR").then((m) => ({ default: m.ANRPane })));
const DESPane = lazy(() => import("./DES").then((m) => ({ default: m.DESPane })));
const FAPane = lazy(() => import("./FA").then((m) => ({ default: m.FAPane })));
const GPPane = lazy(() => import("./GP").then((m) => ({ default: m.GPPane })));
const EQSPane = lazy(() => import("./EQS").then((m) => ({ default: m.EQSPane })));
const PORTPane = lazy(() => import("./PORT").then((m) => ({ default: m.PORTPane })));
const SCANPane = lazy(() => import("./SCAN").then((m) => ({ default: m.SCANPane })));
const MISPane = lazy(() => import("./MIS").then((m) => ({ default: m.MISPane })));
const ASKPane = lazy(() => import("./ASK").then((m) => ({ default: m.ASKPane })));
const TOPPane = lazy(() => import("./TOP").then((m) => ({ default: m.TOPPane })));
const ECOPane = lazy(() => import("./ECO").then((m) => ({ default: m.ECOPane })));
const WATCHPane = lazy(() => import("./WATCH").then((m) => ({ default: m.WATCHPane })));
const ALRTPane = lazy(() => import("./ALRT").then((m) => ({ default: m.ALRTPane })));
const NIPane = lazy(() => import("./NI").then((m) => ({ default: m.NIPane })));
const MOSTPane = lazy(() => import("./MOST").then((m) => ({ default: m.MOSTPane })));
const WEIPane = lazy(() => import("./WEI").then((m) => ({ default: m.WEIPane })));
const HPPane = lazy(() => import("./HP").then((m) => ({ default: m.HPPane })));
const WCRSPane = lazy(() => import("./WCRS").then((m) => ({ default: m.WCRSPane })));
const GLCOPane = lazy(() => import("./GLCO").then((m) => ({ default: m.GLCOPane })));
const AGENTPane = lazy(() => import("./AGENT").then((m) => ({ default: m.AGENTPane })));
const BTMMPane = lazy(() => import("./BTMM").then((m) => ({ default: m.BTMMPane })));
const BIOPane = lazy(() => import("./BIO").then((m) => ({ default: m.BIOPane })));
const GEXPane = lazy(() => import("./GEX").then((m) => ({ default: m.GEXPane })));
const MarketHeatmapPane = lazy(() =>
  import("./MarketHeatmap").then((m) => ({ default: m.MarketHeatmapPane })),
);
const INSTANTPane = lazy(() => import("./INSTANT").then((m) => ({ default: m.INSTANTPane })));
const CORRPane = lazy(() => import("./CORR").then((m) => ({ default: m.CORRPane })));
const XSENPane = lazy(() => import("./XSEN").then((m) => ({ default: m.XSENPane })));
const DPFPane = lazy(() => import("./DPF").then((m) => ({ default: m.DPFPane })));
const DVDPane = lazy(() => import("./DVD").then((m) => ({ default: m.DVDPane })));
const ECFCPane = lazy(() => import("./ECFC").then((m) => ({ default: m.ECFCPane })));
const ECSTPane = lazy(() => import("./ECST").then((m) => ({ default: m.ECSTPane })));
const EEPane = lazy(() => import("./EE").then((m) => ({ default: m.EEPane })));
const EMSXPane = lazy(() => import("./EMSX").then((m) => ({ default: m.EMSXPane })));
const EREVPane = lazy(() => import("./EREV").then((m) => ({ default: m.EREVPane })));
const ESGPane = lazy(() => import("./ESG").then((m) => ({ default: m.ESGPane })));
const TRQAPane = lazy(() => import("./TRQA").then((m) => ({ default: m.TRQAPane })));
const TSARPane = lazy(() => import("./TSAR").then((m) => ({ default: m.TSARPane })));
const TSOXPane = lazy(() => import("./TSOX").then((m) => ({ default: m.TSOXPane })));
const WACCPane = lazy(() => import("./WACC").then((m) => ({ default: m.WACCPane })));
const WBPane = lazy(() => import("./WB").then((m) => ({ default: m.WBPane })));
const WETRPane = lazy(() => import("./WETR").then((m) => ({ default: m.WETRPane })));
const WHALPane = lazy(() => import("./WHAL").then((m) => ({ default: m.WHALPane })));
const WIRPPane = lazy(() => import("./WIRP").then((m) => ({ default: m.WIRPPane })));
const CONNPane = lazy(() => import("./CONN").then((m) => ({ default: m.CONNPane })));
const INDXPane = lazy(() => import("./INDX").then((m) => ({ default: m.INDXPane })));
const STRAPane = lazy(() => import("./STRA").then((m) => ({ default: m.STRAPane })));
const BOTPane = lazy(() => import("./BOT").then((m) => ({ default: m.BOTPane })));
const BOTSPane = lazy(() => import("./BOTS").then((m) => ({ default: m.BOTSPane })));
const PERFPane = lazy(() => import("./PERF").then((m) => ({ default: m.PERFPane })));
const TMPLPane = lazy(() => import("./TMPL").then((m) => ({ default: m.TMPLPane })));

const PANES: Record<string, PaneComponent> = {
  AGENT: AGENTPane,
  ANR: ANRPane,
  DES: DESPane,
  FA: FAPane,
  GP: GPPane,
  EQS: EQSPane,
  PORT: PORTPane,
  SCAN: SCANPane,
  MIS: MISPane,
  ASK: ASKPane,
  TOP: TOPPane,
  ECO: ECOPane,
  WATCH: WATCHPane,
  ALRT: ALRTPane,
  NI: NIPane,
  CN: NIPane,             // CN alias — ShowMe ships either NI or CN.
  MOST: MOSTPane,
  PERF: PERFPane,
  WEI: WEIPane,
  HP: HPPane,
  WCRS: WCRSPane,
  GLCO: GLCOPane,
  BTMM: BTMMPane,
  BIO: BIOPane,
  BOT: BOTPane,
  BOTS: BOTSPane,
  GEX: GEXPane,
  CONN: CONNPane,
  CORR: CORRPane,
  INDX: INDXPane,
  INSTANT: INSTANTPane,
  XSEN: XSENPane,
  MAP: MarketHeatmapPane,
  SECT: MarketHeatmapPane,
  STRA: STRAPane,
  TMPL: TMPLPane,
  DPF: DPFPane,
  DVD: DVDPane,
  ECFC: ECFCPane,
  ECST: ECSTPane,
  EE: EEPane,
  EMSX: EMSXPane,
  EREV: EREVPane,
  ESG: ESGPane,
  TRQA: TRQAPane,
  TSAR: TSARPane,
  TSOX: TSOXPane,
  WACC: WACCPane,
  WB: WBPane,
  WETR: WETRPane,
  WHAL: WHALPane,
  WIRP: WIRPPane,
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
    code: "BOT",
    name: "Bot Manager",
    category: "screen",
    description:
      "Sub-system D user surface: list saved bots with status pills (OFF/SHADOW/LIVE), edit strategy+credential+symbol+timeframe+tick, switch shadow/live mode, enable/disable with re-typed-label confirmation, and view the signal log.",
  },
  {
    code: "BOTS",
    name: "Bot Supervision",
    category: "screen",
    description:
      "Sub-system H supervisor: aggregate KPI strip (total/enabled/live/signals today), per-bot table with mode pill and last-signal column, and unified signal feed across every saved bot. Auto-refreshes every 10s.",
  },
  {
    code: "CN",
    name: "Company News",
    category: "news",
    description: "Live company and market news stream with symbol relevance controls.",
  },
  {
    code: "CONN",
    name: "Connect Exchange",
    category: "portfolio",
    description:
      "Multi-exchange connect/test/manage UI. Search the catalog, add read-only or read+trade credentials, escalate via re-typed-label confirmation.",
  },
  {
    code: "WATCH",
    name: "Live Watchlist",
    category: "portfolio",
    description: "User-managed watchlist with live last price, change, source, and removal controls.",
  },
  {
    code: "MIS",
    name: "Multi Indicator Scan",
    category: "screen",
    description:
      "23 indikatörlü konsensüs ile tüm piyasalarda (kripto, hisse, ETF, FX, emtia, tahvil) yüksek skorlu sembol taraması. Sonuçlardan + butonu ile WATCH listesine ekleme. Her piyasa için ayrı kalibrasyon sekmesi.",
  },
  {
    code: "INDX",
    name: "Indicator Index",
    category: "screen",
    description:
      "Searchable indicator depot: family-filtered grid with confidence chips and a detail view showing description, parameter table, formula, rationale, and suggested strategy. Backed by /api/indicators/catalog.",
  },
  {
    code: "INSTANT",
    name: "Instant Squawk Line",
    category: "news",
    description: "Secondary LiveSquawk-style official-source news, calendar, latency, and audio line.",
  },
  {
    code: "PERF",
    name: "Performance",
    category: "screen",
    description:
      "Sub-system I: cumulative bot performance leaderboard (total PnL desc) + per-bot detail with metrics, trade list, and equity curve. Pure-aggregation from each bot's signal_log; auto-refreshes every 15s.",
  },
  {
    code: "STRA",
    name: "Strategy Editor",
    category: "screen",
    description:
      "Sub-system E user surface: list saved strategies, edit indicators, entry/exit rules, timeframe, and position sizing. Save via /api/strategies, run server-side preview against synthetic bars.",
  },
  {
    code: "TMPL",
    name: "Strategy Templates",
    category: "screen",
    description:
      "Sub-system G user surface: browse the curated bot template library (RSI mean-revert, EMA crossover, etc.) with natural-language explanation, math, and applicability notes. One click instantiates a new strategy via /api/templates/{id}/instantiate.",
  },
  {
    code: "XSEN",
    name: "X Sentiment AI",
    category: "news",
    description:
      "Account-free X scrape + fine-tuned RoBERTa (sentiment / emotion / topic) with a bullish score, examples, and INSTANT feed contribution.",
  },
];

export function resolvePane(code: string): PaneComponent | null {
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
