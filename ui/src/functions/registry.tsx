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
const PortfolioAnalyticsPane = lazy(() =>
  import("./PortfolioAnalytics").then((m) => ({ default: m.PortfolioAnalyticsPane })),
);
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
const BDAPane = lazy(() => import("./BDA").then((m) => ({ default: m.BDAPane })));
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
// De-garbage 2026-06-01: bespoke panes for nine functions whose backends now
// return real keyless live data (SEC EDGAR / World Bank / Treasury / yfinance /
// Binance / CoinGecko / mempool / Polymarket / NASA-GIBS / FINRA). Without these
// the codes fell through to the generic FunctionStub "text" renderer.
const CRPRPane = lazy(() => import("./CRPR").then((m) => ({ default: m.CRPRPane })));
const DEBTPane = lazy(() => import("./DEBT").then((m) => ({ default: m.DEBTPane })));
const IVOLPane = lazy(() => import("./IVOL").then((m) => ({ default: m.IVOLPane })));
const OVDVPane = lazy(() => import("./OVDV").then((m) => ({ default: m.OVDVPane })));
const MICROPane = lazy(() => import("./MICRO").then((m) => ({ default: m.MICROPane })));
const AIMPane = lazy(() => import("./AIM").then((m) => ({ default: m.AIMPane })));
const TCAPane = lazy(() => import("./TCA").then((m) => ({ default: m.TCAPane })));
const SATPane = lazy(() => import("./SAT").then((m) => ({ default: m.SATPane })));
const POLYPane = lazy(() => import("./POLY").then((m) => ({ default: m.POLYPane })));
const TXNSPane = lazy(() => import("./TXNS").then((m) => ({ default: m.TXNSPane })));
// FLW — FlowMap depth heatmap: full-pane WebGL2 order-book density map over
// the sidecar's binary /ws/flowmap feed.
const FLWPane = lazy(() => import("./FLW").then((m) => ({ default: m.FLWPane })));
// FN-WAVE wave-1 (2026-09-07): four of the 74 generic-catalog functions get
// bespoke panes (survey: showme-review/fn-wave/survey-*.md).
const OMONPane = lazy(() => import("./OMON").then((m) => ({ default: m.OMONPane })));
const TAUCPane = lazy(() => import("./TAUC").then((m) => ({ default: m.TAUCPane })));
const TECHPane = lazy(() => import("./TECH").then((m) => ({ default: m.TECHPane })));
const TRANPane = lazy(() => import("./TRAN").then((m) => ({ default: m.TRANPane })));
// FN-WAVE wave-2 (2026-09-07): twelve more generic-catalog functions get
// bespoke panes (survey: showme-review/fn-wave/survey-*.md).
const SRSKPane = lazy(() => import("./SRSK").then((m) => ({ default: m.SRSKPane })));
const FRDPane = lazy(() => import("./FRD").then((m) => ({ default: m.FRDPane })));
const FXHPane = lazy(() => import("./FXH").then((m) => ({ default: m.FXHPane })));
const YASPane = lazy(() => import("./YAS").then((m) => ({ default: m.YASPane })));
const GMMPane = lazy(() => import("./GMM").then((m) => ({ default: m.GMMPane })));
const SECFPane = lazy(() => import("./SECF").then((m) => ({ default: m.SECFPane })));
const ISINPane = lazy(() => import("./ISIN").then((m) => ({ default: m.ISINPane })));
const DAPIPane = lazy(() => import("./DAPI").then((m) => ({ default: m.DAPIPane })));
const FORM4Pane = lazy(() => import("./FORM4").then((m) => ({ default: m.FORM4Pane })));
const MOSSPane = lazy(() => import("./MOSS").then((m) => ({ default: m.MOSSPane })));
const ONCHPane = lazy(() => import("./ONCH").then((m) => ({ default: m.ONCHPane })));
const BRIEFPane = lazy(() => import("./BRIEF").then((m) => ({ default: m.BRIEFPane })));
// FN-WAVE wave-3 (2026-09-08): equity-research + news/search lanes.
const HDSPane = lazy(() => import("./HDS").then((m) => ({ default: m.HDSPane })));
const HFSPane = lazy(() => import("./HFS").then((m) => ({ default: m.HFSPane })));
const RVPane = lazy(() => import("./RV").then((m) => ({ default: m.RVPane })));
const CACTPane = lazy(() => import("./CACT").then((m) => ({ default: m.CACTPane })));
const TLDRPane = lazy(() => import("./TLDR").then((m) => ({ default: m.TLDRPane })));
const FTSPane = lazy(() => import("./FTS").then((m) => ({ default: m.FTSPane })));
const TRDHPane = lazy(() => import("./TRDH").then((m) => ({ default: m.TRDHPane })));
const COUNPane = lazy(() => import("./COUN").then((m) => ({ default: m.COUNPane })));
// Wave-2 valuation lane.
const DDMPane = lazy(() => import("./DDM").then((m) => ({ default: m.DDMPane })));
const DCFSPane = lazy(() => import("./DCFS").then((m) => ({ default: m.DCFSPane })));
const BetaPane = lazy(() => import("./BETA").then((m) => ({ default: m.BetaPane })));
const GreeksPane = lazy(() => import("./GREEKS").then((m) => ({ default: m.GreeksPane })));
// FN-WAVE wave-3 exec/bond lane.
const EXECPane = lazy(() => import("./EXEC").then((m) => ({ default: m.EXECPane })));
const DDISPane = lazy(() => import("./DDIS").then((m) => ({ default: m.DDISPane })));
const BQLPane = lazy(() => import("./BQL").then((m) => ({ default: m.BQLPane })));
const NALRTPane = lazy(() => import("./NALRT").then((m) => ({ default: m.NALRTPane })));
// FN-WAVE wave-3 options/vol lane.
const OSAPane = lazy(() => import("./OSA").then((m) => ({ default: m.OSAPane })));
const OVMEPane = lazy(() => import("./OVME").then((m) => ({ default: m.OVMEPane })));
const HVTPane = lazy(() => import("./HVT").then((m) => ({ default: m.HVTPane })));
const DARKPane = lazy(() => import("./DARK").then((m) => ({ default: m.DARKPane })));
// FN-WAVE wave-4 (2026-09-08): bond/valuation, screeners, equity-info, news/macro lanes.
const CRVFPane = lazy(() => import("./CRVF").then((m) => ({ default: m.CRVFPane })));
const GC3DPane = lazy(() => import("./GC3D").then((m) => ({ default: m.GC3DPane })));
const ALLQPane = lazy(() => import("./ALLQ").then((m) => ({ default: m.ALLQPane })));
const DCFPane = lazy(() => import("./DCF").then((m) => ({ default: m.DCFPane })));
const CSRCPane = lazy(() => import("./CSRC").then((m) => ({ default: m.CSRCPane })));
const FSRCPane = lazy(() => import("./FSRC").then((m) => ({ default: m.FSRCPane })));
const SRCHPane = lazy(() => import("./SRCH").then((m) => ({ default: m.SRCHPane })));
const ICXPane = lazy(() => import("./ICX").then((m) => ({ default: m.ICXPane })));
const PIBPane = lazy(() => import("./PIB").then((m) => ({ default: m.PIBPane })));
const LITMPane = lazy(() => import("./LITM").then((m) => ({ default: m.LITMPane })));
const SPLCPane = lazy(() => import("./SPLC").then((m) => ({ default: m.SPLCPane })));
const APPLPane = lazy(() => import("./APPL").then((m) => ({ default: m.APPLPane })));
const NSEPane = lazy(() => import("./NSE").then((m) => ({ default: m.NSEPane })));
const READPane = lazy(() => import("./READ").then((m) => ({ default: m.READPane })));
const REGMPane = lazy(() => import("./REGM").then((m) => ({ default: m.REGMPane })));
const FRHPane = lazy(() => import("./FRH").then((m) => ({ default: m.FRHPane })));
// FN-WAVE wave-5 (2026-09-08): tools/api + fx/misc lanes — the last generics.
const FLDSPane = lazy(() => import("./FLDS").then((m) => ({ default: m.FLDSPane })));
const FXIPPane = lazy(() => import("./FXIP").then((m) => ({ default: m.FXIPPane })));
const CDEPane = lazy(() => import("./CDE").then((m) => ({ default: m.CDEPane })));
const GRABPane = lazy(() => import("./GRAB").then((m) => ({ default: m.GRABPane })));
const BBGTPane = lazy(() => import("./BBGT").then((m) => ({ default: m.BBGTPane })));
const BQUANTPane = lazy(() => import("./BQUANT").then((m) => ({ default: m.BQUANTPane })));
const FXGOPane = lazy(() => import("./FXGO").then((m) => ({ default: m.FXGOPane })));
const FXFCPane = lazy(() => import("./FXFC").then((m) => ({ default: m.FXFCPane })));
const DINEPane = lazy(() => import("./DINE").then((m) => ({ default: m.DINEPane })));
const FLYPane = lazy(() => import("./FLY").then((m) => ({ default: m.FLYPane })));
const LANGPane = lazy(() => import("./LANG").then((m) => ({ default: m.LANGPane })));
// FN-WAVE wave-5 (2026-09-08): final lane — social/news/misc.
const SOSCPane = lazy(() => import("./SOSC").then((m) => ({ default: m.SOSCPane })));
const EVTSPane = lazy(() => import("./EVTS").then((m) => ({ default: m.EVTSPane })));
const PEOPPane = lazy(() => import("./PEOP").then((m) => ({ default: m.PEOPPane })));
const MEETPane = lazy(() => import("./MEET").then((m) => ({ default: m.MEETPane })));
const AVPane = lazy(() => import("./AV").then((m) => ({ default: m.AVPane })));
const BMCPane = lazy(() => import("./BMC").then((m) => ({ default: m.BMCPane })));
// FN-WAVE wave-5 commodity/chart lane.
const BGASPane = lazy(() => import("./BGAS").then((m) => ({ default: m.BGASPane })));
const BOILPane = lazy(() => import("./BOIL").then((m) => ({ default: m.BOILPane })));
const NGASPane = lazy(() => import("./NGAS").then((m) => ({ default: m.NGASPane })));
const CPFPane = lazy(() => import("./CPF").then((m) => ({ default: m.CPFPane })));
const CHGSPane = lazy(() => import("./CHGS").then((m) => ({ default: m.CHGSPane })));

const PANES: Record<string, PaneComponent> = {
  AGENT: AGENTPane,
  ANR: ANRPane,
  DES: DESPane,
  FA: FAPane,
  GP: GPPane,
  EQS: EQSPane,
  PORT: PORTPane,
  ACCT: PortfolioAnalyticsPane,
  BLAK: PortfolioAnalyticsPane,
  BMTX: PortfolioAnalyticsPane,
  BTFW: PortfolioAnalyticsPane,
  BTUNE: PortfolioAnalyticsPane,
  LOTS: PortfolioAnalyticsPane,
  MARS: PortfolioAnalyticsPane,
  MGN: PortfolioAnalyticsPane,
  MLSIG: PortfolioAnalyticsPane,
  PCAS: PortfolioAnalyticsPane,
  PFA: PortfolioAnalyticsPane,
  PORT_OPT: PortfolioAnalyticsPane,
  PORT_WHATIF: PortfolioAnalyticsPane,
  PSC: PortfolioAnalyticsPane,
  PVAR: PortfolioAnalyticsPane,
  REBA: PortfolioAnalyticsPane,
  RPAR: PortfolioAnalyticsPane,
  STRS: PortfolioAnalyticsPane,
  TLH: PortfolioAnalyticsPane,
  TRA: PortfolioAnalyticsPane,
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
  BDA: BDAPane,
  BTMM: BTMMPane,
  BIO: BIOPane,
  BOT: BOTPane,
  BOTS: BOTSPane,
  GEX: GEXPane,
  FLW: FLWPane,
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
  // De-garbage 2026-06-01 — nine newly real-data functions get bespoke panes.
  CRPR: CRPRPane,
  DEBT: DEBTPane,
  IVOL: IVOLPane,
  OVDV: OVDVPane,
  MICRO: MICROPane,
  AIM: AIMPane,
  TCA: TCAPane,
  SAT: SATPane,
  POLY: POLYPane,
  // Trade Blotter bespoke pane
  TXNS: TXNSPane,
  // FN-WAVE wave-1 bespoke panes (codes already in static-index — no
  // NATIVE_FUNCTION_ENTRIES duplicates, the sidebar N badge comes from PANES)
  OMON: OMONPane,
  TAUC: TAUCPane,
  TECH: TECHPane,
  TRAN: TRANPane,
  // FN-WAVE wave-2 bespoke panes (codes already in static-index)
  SRSK: SRSKPane,
  FRD: FRDPane,
  FXH: FXHPane,
  YAS: YASPane,
  GMM: GMMPane,
  SECF: SECFPane,
  ISIN: ISINPane,
  DAPI: DAPIPane,
  FORM4: FORM4Pane,
  MOSS: MOSSPane,
  ONCH: ONCHPane,
  BRIEF: BRIEFPane,
  // Wave-2 valuation lane
  DDM: DDMPane,
  DCFS: DCFSPane,
  BETA: BetaPane,
  GREEKS: GreeksPane,
  // FN-WAVE wave-3 bespoke panes (codes already in static-index)
  HDS: HDSPane,
  HFS: HFSPane,
  RV: RVPane,
  CACT: CACTPane,
  TLDR: TLDRPane,
  FTS: FTSPane,
  TRDH: TRDHPane,
  COUN: COUNPane,
  EXEC: EXECPane,
  DDIS: DDISPane,
  BQL: BQLPane,
  NALRT: NALRTPane,
  OSA: OSAPane,
  OVME: OVMEPane,
  HVT: HVTPane,
  DARK: DARKPane,
  // FN-WAVE wave-4
  CRVF: CRVFPane,
  GC3D: GC3DPane,
  ALLQ: ALLQPane,
  DCF: DCFPane,
  CSRC: CSRCPane,
  FSRC: FSRCPane,
  SRCH: SRCHPane,
  ICX: ICXPane,
  PIB: PIBPane,
  LITM: LITMPane,
  SPLC: SPLCPane,
  APPL: APPLPane,
  NSE: NSEPane,
  READ: READPane,
  REGM: REGMPane,
  FRH: FRHPane,
  SOSC: SOSCPane,
  EVTS: EVTSPane,
  PEOP: PEOPPane,
  MEET: MEETPane,
  AV: AVPane,
  BMC: BMCPane,
  BGAS: BGASPane,
  BOIL: BOILPane,
  NGAS: NGASPane,
  CPF: CPFPane,
  CHGS: CHGSPane,
  // FN-WAVE wave-5 tools/api + fx/misc lanes — every catalog code is now native
  FLDS: FLDSPane,
  FXIP: FXIPPane,
  CDE: CDEPane,
  GRAB: GRABPane,
  BBGT: BBGTPane,
  BQUANT: BQUANTPane,
  FXGO: FXGOPane,
  FXFC: FXFCPane,
  DINE: DINEPane,
  FLY: FLYPane,
  LANG: LANGPane,
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
    code: "BDA",
    name: "Bot Dev Assistant",
    category: "screen",
    description:
      "Sub-system J: rule-based NL → strategy spec parser + saved-strategy explainer. Type a request like \"RSI 30 altında, 70 üstünde, BTC/USDT 1h\" and get a draft StrategySpec (optionally persisted); below, pick any saved strategy for a TR-dili rule-based explanation.",
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
    code: "FLW",
    name: "FlowMap",
    category: "chart",
    description:
      "FlowMap depth heatmap: time-weighted order-book density as a price×time WebGL heatmap with live BBO, bars and CVD, streamed over the sidecar /ws/flowmap feed.",
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
  {
    code: "TXNS",
    name: "Trade Blotter",
    category: "portfolio",
    description: "Bloomberg-grade transaction ledger showing realized P&L and metrics.",
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
