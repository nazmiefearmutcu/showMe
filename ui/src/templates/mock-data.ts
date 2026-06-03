/**
 * Per-fn mock content extracted from the Design export. Used as the
 * design-state placeholder when no live sidecar payload is available. Real
 * sidecar payloads (when present) take precedence — these mocks only
 * surface the design layout.
 */

export type Spark = number[];

export interface KpiTile {
  label: string;
  value: string;
  tone?: "pos" | "neg" | "warn" | "neutral";
  sub?: string;
}

export interface FeedEntry {
  source: string;
  time: string;
  title: string;
  summary?: string;
  tags?: string[];
  impact?: number;
  tone?: "pos" | "neg" | "warn" | "neutral";
}

export interface KvPair {
  k: string;
  v: string;
}

export interface TableRow {
  [col: string]: string | number;
}

export interface HeatCell {
  label: string;
  value: string;
  intensity: number;
  tone: "pos" | "neg" | "warn" | "neutral";
}

export interface SparkRow {
  symbol: string;
  name?: string;
  values: number[];
  last: string;
  changePct: number;
}

export interface FormRow {
  label: string;
  value: string;
  tone?: "pos" | "neg" | "warn" | "neutral";
}

export interface MockTemplate {
  /** Headline for the pane hero strip. */
  title: string;
  /** Sub-headline / lead paragraph. */
  sub: string;
  /** Optional KPI grid above the main pattern body. */
  kpis?: KpiTile[];
  /** Optional chip selectors (topics / ranges / providers). */
  chips?: Array<{ id: string; label: string; count?: number | string; tone?: "pos" | "neg" | "warn" | "neutral" }>;
  /** Pattern-specific body. */
  feed?: FeedEntry[];
  kvs?: KvPair[];
  tableCols?: string[];
  tableRows?: TableRow[];
  heatCells?: HeatCell[];
  sparkRows?: SparkRow[];
  formRows?: FormRow[];
  /** Optional eyebrow status text. */
  eyebrow?: string;
  /** Optional callout / "narrative" paragraph at the bottom. */
  narrative?: string;
  /**
   * Whether the mock content is safe to display while the sidecar load is
   * still pending (i.e. before `state === "ok"`).
   *
   * When `false` (the safe default), `TemplateRenderer` renders a skeleton
   * placeholder during loading instead of the mock, so users never confuse
   * hard-coded mock prices/strikes/values with live data for the current
   * ticker. Templates that have *no* numeric pricing or per-symbol values
   * (pure UI catalogues, education modules, language pickers, generic
   * chip-only panes) may explicitly opt in by setting `true` if their mock
   * content is intrinsically harmless to show alongside a symbol.
   */
  allowMockDuringLoad?: boolean;
}

/* ── Helpers ──────────────────────────────────────────────────────── */

function noise(seed: number, n: number, base = 100, amp = 8): number[] {
  let s = seed;
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    s = (s * 9301 + 49297) % 233280;
    const r = (s / 233280 - 0.5) * 2;
    out.push(base + r * amp + Math.sin(i / 3) * amp * 0.3);
  }
  return out;
}

const SPARK_UP = noise(7, 28, 100, 12);
const SPARK_DN = noise(11, 28, 100, 12).map((v, i) => 110 - (v - 90) - i * 0.4);
const SPARK_VOL = noise(31, 28, 100, 18);

/* ── Shared mock data ─────────────────────────────────────────────── */

const FEED_NEWS: FeedEntry[] = [
  {
    source: "FED",
    time: "12:48",
    title:
      "Fed official: inflation confidence improving, but policy needs more proof.",
    summary:
      "Speaking at the Economic Club, the official emphasised that recent benign prints are necessary but not sufficient.",
    tags: ["FED", "RATES", "POLICY"],
    impact: 3,
    tone: "warn",
  },
  {
    source: "NVDA",
    time: "12:41",
    title:
      "Cloud capex checks track ~12% above plan for FY26; data-center demand firm.",
    summary:
      "Hyperscaler bookings remain robust into Q3, with no observed pauses. Order book extends ~22 weeks.",
    tags: ["NVDA", "SEMI", "AI"],
    impact: 4,
    tone: "pos",
  },
  {
    source: "UST",
    time: "12:33",
    title: "Yield curve bear-steepening ahead of 10Y long-end supply.",
    summary:
      "Last five 10Y auctions tailed by 1.2bps average. Today's $39B re-open faces a market that has lifted 10Y yields 9bps.",
    tags: ["UST", "AUCTION", "10Y"],
    impact: 3,
    tone: "warn",
  },
  {
    source: "EU",
    time: "12:27",
    title:
      "EU regulators request additional AI infrastructure disclosures from hyperscalers.",
    summary:
      "The request seeks energy consumption, water use, and supply chain mapping for accelerator deployments above 100MW.",
    tags: ["AI", "REGULATION", "EU"],
    impact: 3,
    tone: "neg",
  },
  {
    source: "EIA",
    time: "12:18",
    title:
      "Crude inventories draw 3.4M bbl, larger than 1.1M expected; energy tape firms.",
    summary:
      "The draw was concentrated in PADD-3 (Gulf), where refinery utilisation jumped to 92.4%. Curve back in steady backwardation through Q3.",
    tags: ["OIL", "INVENTORIES", "ENERGY"],
    impact: 2,
    tone: "pos",
  },
];

const HEAT_WORLD: HeatCell[] = [
  { label: "USA", value: "+0.42%", intensity: 0.5, tone: "pos" },
  { label: "GBR", value: "+0.18%", intensity: 0.25, tone: "pos" },
  { label: "DEU", value: "-0.23%", intensity: 0.3, tone: "neg" },
  { label: "JPN", value: "+0.78%", intensity: 0.8, tone: "pos" },
  { label: "FRA", value: "-0.08%", intensity: 0.15, tone: "neg" },
  { label: "CHN", value: "-0.91%", intensity: 0.9, tone: "neg" },
  { label: "BRA", value: "+1.12%", intensity: 0.95, tone: "pos" },
  { label: "IND", value: "+0.34%", intensity: 0.4, tone: "pos" },
  { label: "AUS", value: "+0.04%", intensity: 0.1, tone: "neutral" },
  { label: "KOR", value: "-0.58%", intensity: 0.6, tone: "neg" },
  { label: "TUR", value: "+2.14%", intensity: 1.0, tone: "pos" },
  { label: "MEX", value: "-0.45%", intensity: 0.5, tone: "neg" },
];

const SPARKS_WL: SparkRow[] = [
  { symbol: "AAPL", name: "Apple Inc.", values: SPARK_UP, last: "228.42", changePct: 1.24 },
  { symbol: "NVDA", name: "NVIDIA Corp.", values: SPARK_UP, last: "1432.18", changePct: 2.61 },
  { symbol: "MSFT", name: "Microsoft", values: SPARK_UP, last: "412.78", changePct: 0.42 },
  { symbol: "GOOG", name: "Alphabet", values: SPARK_DN, last: "168.92", changePct: -0.78 },
  { symbol: "AMZN", name: "Amazon", values: SPARK_UP, last: "182.46", changePct: 1.04 },
];

/* ── Per-code templates ──────────────────────────────────────────── */

const TPL: Record<string, MockTemplate> = {
  /* ─ Equity ─────────────────────────────────────────────────── */
  ACCT: {
    title: "Multi-Account Aggregation",
    sub: "Per-account position roll-up + cross-account exposure totals.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Accounts", value: "5" },
      { label: "Total NAV", value: "$1.84M", tone: "pos" },
      { label: "Day P&L", value: "+$8,412", tone: "pos", sub: "+0.46%" },
      { label: "Cross exposure", value: "62%", sub: "concentration risk" },
    ],
    tableCols: ["Account", "Type", "NAV", "Day P&L", "Positions"],
    tableRows: [
      { Account: "DESK-01", Type: "Live", NAV: "$642,150", "Day P&L": "+$3,210", Positions: 14 },
      { Account: "PAPER", Type: "Paper", NAV: "$500,000", "Day P&L": "+$2,140", Positions: 22 },
      { Account: "IRA-A", Type: "Tax", NAV: "$418,820", "Day P&L": "+$1,840", Positions: 9 },
      { Account: "PRIME", Type: "Margin", NAV: "$182,400", "Day P&L": "+$840", Positions: 6 },
      { Account: "CRYPTO", Type: "Cold", NAV: "$96,820", "Day P&L": "+$382", Positions: 4 },
    ],
  },
  AIM: {
    title: "Order Management",
    sub: "Working orders across brokers — fills, cancels, partials.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Working", value: "12" },
      { label: "Filled · today", value: "38", tone: "pos" },
      { label: "Cancelled", value: "4", sub: "33% within 5s" },
      { label: "Slippage avg", value: "0.8bps" },
    ],
    tableCols: ["Time", "Symbol", "Side", "Qty", "Status", "Px"],
    tableRows: [
      { Time: "14:48:02", Symbol: "NVDA", Side: "BUY", Qty: 250, Status: "FILLED", Px: 1432.18 },
      { Time: "14:46:51", Symbol: "MSFT", Side: "SELL", Qty: 100, Status: "WORKING", Px: 412.5 },
      { Time: "14:44:18", Symbol: "AAPL", Side: "BUY", Qty: 400, Status: "FILLED", Px: 228.4 },
      { Time: "14:41:09", Symbol: "GOOG", Side: "BUY", Qty: 75, Status: "PARTIAL", Px: 168.9 },
      { Time: "14:38:33", Symbol: "TSLA", Side: "SELL", Qty: 60, Status: "CANCELLED", Px: 248.6 },
    ],
  },
  ALLQ: {
    title: "Dealer Quotes (TRACE)",
    sub: "Live dealer-quote stack for the selected CUSIP / ISIN.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Bid stack", value: "8 dealers" },
      { label: "Best bid", value: "99.842" },
      { label: "Best offer", value: "99.871" },
      { label: "Spread", value: "0.029" },
    ],
    tableCols: ["Dealer", "Side", "Px", "Size", "Age"],
    tableRows: [
      { Dealer: "GS", Side: "BID", Px: 99.842, Size: "5MM", Age: "12s" },
      { Dealer: "MS", Side: "BID", Px: 99.838, Size: "10MM", Age: "31s" },
      { Dealer: "JPM", Side: "BID", Px: 99.836, Size: "5MM", Age: "48s" },
      { Dealer: "CITI", Side: "OFFER", Px: 99.871, Size: "5MM", Age: "18s" },
      { Dealer: "BAML", Side: "OFFER", Px: 99.875, Size: "10MM", Age: "22s" },
    ],
  },
  APPL: {
    title: "Industry Taxonomy",
    sub: "Sector / industry mapping — GICS-style hierarchy with peer counts.",
    chips: [
      { id: "tech", label: "Technology", count: 412 },
      { id: "fin", label: "Financials", count: 318 },
      { id: "hc", label: "Healthcare", count: 264 },
      { id: "cd", label: "Consumer Disc", count: 198 },
      { id: "energy", label: "Energy", count: 92 },
    ],
    kvs: [
      { k: "Sector", v: "Technology" },
      { k: "Industry Group", v: "Semiconductors & Equipment" },
      { k: "Industry", v: "Semiconductors" },
      { k: "Sub-Industry", v: "AI Accelerators" },
      { k: "Peers (N)", v: "14" },
      { k: "Index members", v: "SPX · NDX · SOX" },
    ],
  },
  AV: {
    title: "Audio / Video Archive",
    sub: "Replays — earnings calls, conferences, expert calls.",
    chips: [
      { id: "all", label: "All", count: 286 },
      { id: "calls", label: "Earnings", count: 142 },
      { id: "conf", label: "Conferences", count: 96 },
      { id: "expert", label: "Expert calls", count: 48 },
    ],
    feed: [
      { source: "NVDA", time: "Q3", title: "NVDA Q3 earnings call · 2026-02", tags: ["EARN"], impact: 4, tone: "pos", summary: "67 minutes · transcript ready · 4 analyst Q&As." },
      { source: "AAPL", time: "Q1", title: "AAPL Investor Day · 2026-01", tags: ["INVESTOR"], impact: 3, tone: "neutral", summary: "112 minutes · slides + transcript." },
      { source: "JPM", time: "Conf", title: "Healthcare Conference · keynote", tags: ["HC", "CONF"], impact: 2, tone: "neutral", summary: "32 minutes · video only." },
    ],
  },
  BBGT: {
    title: "Multi-Asset Trade Ticket",
    sub: "Equities · futures · FX · options · crypto from a single ticket.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "Symbol", value: "NVDA" },
      { label: "Asset class", value: "EQUITY" },
      { label: "Side", value: "BUY" },
      { label: "Quantity", value: "250" },
      { label: "Order type", value: "LIMIT" },
      { label: "Limit price", value: "1432.18" },
      { label: "TIF", value: "DAY" },
      { label: "Venue", value: "NASDAQ" },
      { label: "Est. notional", value: "$358,045", tone: "pos" },
    ],
  },
  BETA: {
    title: "CAPM Beta",
    sub: "β = cov(r_i, r_m) / var(r_m); rolling windows + multi-benchmark.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "β (SPX, 12M)", value: "1.42", tone: "pos" },
      { label: "β (SPX, 36M)", value: "1.18", sub: "long-run" },
      { label: "R²", value: "0.78" },
      { label: "Alpha (12M)", value: "+4.2%", tone: "pos" },
    ],
    tableCols: ["Window", "β SPX", "β NDX", "α %", "R²"],
    tableRows: [
      { Window: "1M", "β SPX": 1.62, "β NDX": 1.34, "α %": 0.6, "R²": 0.82 },
      { Window: "3M", "β SPX": 1.51, "β NDX": 1.28, "α %": 1.2, "R²": 0.79 },
      { Window: "6M", "β SPX": 1.46, "β NDX": 1.21, "α %": 2.1, "R²": 0.81 },
      { Window: "12M", "β SPX": 1.42, "β NDX": 1.19, "α %": 4.2, "R²": 0.78 },
      { Window: "36M", "β SPX": 1.18, "β NDX": 1.07, "α %": 3.8, "R²": 0.74 },
    ],
  },
  BGAS: {
    title: "Natural Gas Spot",
    sub: "Henry Hub spot, regional differentials, weather sensitivity.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Henry Hub", value: "$2.84", tone: "pos", sub: "+1.2% day" },
      { label: "5d range", value: "$2.71–$2.92" },
      { label: "Storage Δ", value: "-128 Bcf", sub: "5y avg -94" },
      { label: "Cooling DD", value: "+4 above" },
    ],
  },
  BLAK: {
    title: "Black-Litterman",
    sub: "Posterior expected returns combining market prior + views.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Views", value: "4" },
      { label: "Risk aversion δ", value: "2.5" },
      { label: "Confidence τ", value: "0.05" },
      { label: "Max sharpe", value: "1.42", tone: "pos" },
    ],
    tableCols: ["Asset", "Prior μ", "View", "Posterior", "Weight"],
    tableRows: [
      { Asset: "SPX", "Prior μ": "8.2%", View: "+50bp", Posterior: "8.7%", Weight: "42%" },
      { Asset: "NDX", "Prior μ": "11.4%", View: "+120bp", Posterior: "12.6%", Weight: "28%" },
      { Asset: "RTY", "Prior μ": "9.1%", View: "—", Posterior: "9.1%", Weight: "12%" },
      { Asset: "EFA", "Prior μ": "6.4%", View: "-80bp", Posterior: "5.6%", Weight: "10%" },
      { Asset: "EEM", "Prior μ": "7.2%", View: "-50bp", Posterior: "6.7%", Weight: "8%" },
    ],
  },
  BMC: {
    title: "Market Concepts Education",
    sub: "Curriculum module — 12 lessons, 4 quizzes, certification.",
    kpis: [
      { label: "Lessons done", value: "8 / 12", tone: "pos" },
      { label: "Quiz avg", value: "92%", tone: "pos" },
      { label: "Streak", value: "14 days" },
      { label: "Cert", value: "Pending" },
    ],
    chips: [
      { id: "fx", label: "FX Basics", count: "✓" },
      { id: "fi", label: "Fixed Income", count: "✓" },
      { id: "eq", label: "Equity", count: "✓" },
      { id: "deriv", label: "Derivatives", count: "5/6" },
      { id: "macro", label: "Macro", count: "0/4" },
    ],
  },
  BMTX: {
    title: "Backtest Matrix",
    sub: "Run multiple strategies across a symbol universe in parallel.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Strategies", value: "8" },
      { label: "Symbols", value: "120" },
      { label: "Best Sharpe", value: "2.18", tone: "pos" },
      { label: "Avg drawdown", value: "-12.4%", tone: "neg" },
    ],
    tableCols: ["Strategy", "Universe", "Sharpe", "Total ret", "Max DD"],
    tableRows: [
      { Strategy: "Trend ATR", Universe: "CRYPTO 24", Sharpe: 2.18, "Total ret": "+182%", "Max DD": "-18%" },
      { Strategy: "Mean Revert", Universe: "EQUITY 96", Sharpe: 1.84, "Total ret": "+124%", "Max DD": "-14%" },
      { Strategy: "Vol carry", Universe: "FX 18", Sharpe: 1.62, "Total ret": "+88%", "Max DD": "-11%" },
      { Strategy: "Momentum", Universe: "EQUITY 96", Sharpe: 1.42, "Total ret": "+92%", "Max DD": "-22%" },
      { Strategy: "Pairs", Universe: "EQUITY 48", Sharpe: 1.28, "Total ret": "+64%", "Max DD": "-9%" },
    ],
  },
  BOIL: {
    title: "Oil Spot",
    sub: "WTI · Brent · Dubai spreads + curve back/contango state.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "WTI", value: "$78.42", tone: "pos", sub: "+0.4%" },
      { label: "Brent", value: "$82.18", tone: "pos", sub: "+0.3%" },
      { label: "Brent–WTI", value: "$3.76" },
      { label: "Curve", value: "Backwardation" },
    ],
  },
  BQL: {
    title: "ShowMe Query Language",
    sub: "Bloomberg-style DSL — `get(...) for(...) with(...) by(...)`.",
    kvs: [
      { k: "Examples", v: "get(price) for('NVDA US Equity') with(date>2026-01-01)" },
      { k: "Operators", v: "get · for · with · by · sort" },
      { k: "Functions", v: "avg · max · min · sum · count" },
      { k: "Output", v: "JSON · CSV · table" },
      { k: "API endpoint", v: "/api/bql" },
    ],
  },
  BQUANT: {
    title: "BQuant Notebook",
    sub: "JupyterLab launch shim — run notebooks against the live engine.",
    kvs: [
      { k: "Launcher", v: "python run_dashboard.py" },
      { k: "Kernels", v: "python3.13 · julia 1.10" },
      { k: "Engine bind", v: "showme.engine.notebook" },
      { k: "Storage", v: "~/.showme/notebooks" },
    ],
  },
  BRIEF: {
    title: "Daily Brief",
    sub: "06:00 UTC cron — overnight news + portfolio impact summary.",
    chips: [
      { id: "today", label: "Today" },
      { id: "yesterday", label: "Yesterday" },
      { id: "week", label: "This week" },
    ],
    feed: FEED_NEWS.slice(0, 4),
  },
  BTFW: {
    title: "Walk-Forward Backtest",
    sub: "Train · test split with rolling re-estimation; equity / Sharpe / DD.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Sharpe", value: "1.84", tone: "pos" },
      { label: "CAGR", value: "+24.2%", tone: "pos" },
      { label: "Max DD", value: "-14.6%", tone: "neg" },
      { label: "Win rate", value: "58%" },
    ],
  },
  BTUNE: {
    title: "Backtest Auto-Tuner",
    sub: "Hyperparameter sweep — rank by Sharpe / total return / Calmar.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Combinations", value: "384" },
      { label: "Best Sharpe", value: "2.41", tone: "pos" },
      { label: "Median", value: "1.18" },
      { label: "Top params", value: "ATR(14) · TF=1h" },
    ],
    tableCols: ["Rank", "ATR", "TF", "Stop %", "Sharpe", "Ret %"],
    tableRows: [
      { Rank: 1, ATR: 14, TF: "1h", "Stop %": 2.0, Sharpe: 2.41, "Ret %": "+186%" },
      { Rank: 2, ATR: 12, TF: "4h", "Stop %": 1.5, Sharpe: 2.32, "Ret %": "+172%" },
      { Rank: 3, ATR: 21, TF: "1d", "Stop %": 3.0, Sharpe: 2.18, "Ret %": "+154%" },
      { Rank: 4, ATR: 10, TF: "1h", "Stop %": 2.5, Sharpe: 2.04, "Ret %": "+142%" },
      { Rank: 5, ATR: 14, TF: "4h", "Stop %": 2.0, Sharpe: 1.94, "Ret %": "+128%" },
    ],
  },
  CACT: {
    title: "Corporate Actions",
    sub: "8-K, splits, M&A, name changes, ticker changes.",
    feed: [
      { source: "NVDA", time: "Today", title: "10-for-1 stock split effective 2026-06-10", impact: 4, tone: "pos", tags: ["SPLIT"] },
      { source: "AAPL", time: "Yesterday", title: "8-K · CFO transition announcement", impact: 3, tone: "warn", tags: ["MGMT"] },
      { source: "MSFT", time: "2d ago", title: "Acquisition of XYZ Corp announced ($2.4B cash)", impact: 4, tone: "pos", tags: ["M&A"] },
    ],
  },
  CDE: {
    title: "Custom Data Fields",
    sub: "User-defined formulas — JSON spec, attached to ticker.",
    kvs: [
      { k: "Active fields", v: "12" },
      { k: "Inputs", v: "OHLCV + fundamentals" },
      { k: "Sandbox", v: "Python eval / WASM" },
      { k: "Storage", v: "~/.showme/cde.json" },
    ],
  },
  CHGS: {
    title: "Chart Studies",
    sub: "Preset TECH bundle — RSI / MACD / BB / Stochastic / ATR.",
    chips: [
      { id: "rsi", label: "RSI(14)" },
      { id: "macd", label: "MACD" },
      { id: "bb", label: "BB(20,2)" },
      { id: "atr", label: "ATR(14)" },
      { id: "stoch", label: "Stochastic" },
    ],
  },
  COUN: {
    title: "Country Guide",
    sub: "Economy · politics · fiscal · external — single page per country.",
    allowMockDuringLoad: false,
    chips: [
      { id: "usa", label: "USA" },
      { id: "deu", label: "Germany" },
      { id: "jpn", label: "Japan" },
      { id: "tur", label: "Turkey" },
      { id: "bra", label: "Brazil" },
    ],
    kpis: [
      { label: "GDP YoY", value: "+2.4%", tone: "pos" },
      { label: "CPI", value: "3.1%" },
      { label: "Policy rate", value: "5.25%" },
      { label: "10Y yield", value: "4.42%" },
    ],
  },
  CPF: {
    title: "Commodity Price Forecasts",
    sub: "World Bank Pink Sheet projections + private forecaster consensus.",
    allowMockDuringLoad: false,
    tableCols: ["Commodity", "Spot", "Q+1", "Q+2", "Y+1"],
    tableRows: [
      { Commodity: "Crude oil", Spot: "$78.4", "Q+1": "$80.0", "Q+2": "$82.5", "Y+1": "$84.0" },
      { Commodity: "Natural gas", Spot: "$2.84", "Q+1": "$3.20", "Q+2": "$3.60", "Y+1": "$3.80" },
      { Commodity: "Copper", Spot: "$4.18", "Q+1": "$4.30", "Q+2": "$4.42", "Y+1": "$4.65" },
      { Commodity: "Wheat", Spot: "$5.42", "Q+1": "$5.60", "Q+2": "$5.75", "Y+1": "$6.00" },
    ],
  },
  CRPR: {
    title: "Credit Rating Profile",
    sub: "S&P · Moody's · Fitch — latest action + outlook + watch.",
    kvs: [
      { k: "S&P", v: "AAA · Stable" },
      { k: "Moody's", v: "Aaa · Stable" },
      { k: "Fitch", v: "AAA · Stable" },
      { k: "Last action", v: "2025-08-12 — affirmed (S&P)" },
      { k: "CDS 5Y", v: "32 bps" },
    ],
  },
  CRVF: {
    title: "Yield Curve",
    sub: "FRED-sourced UST curve — spot + 12M ago + slope analytics.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "2Y", value: "4.62%" },
      { label: "10Y", value: "4.42%" },
      { label: "10Y-2Y", value: "-0.20%", tone: "neg" },
      { label: "Bias", value: "Inverted" },
    ],
  },
  CSRC: {
    title: "Commodity Screener",
    sub: "DSL filter across futures + commodity ETFs.",
    kpis: [
      { label: "Universe", value: "82" },
      { label: "Matched", value: "14", tone: "pos" },
      { label: "Top mover", value: "+4.2% NG" },
      { label: "Worst", value: "-2.1% HG" },
    ],
  },
  DAPI: {
    title: "ShowMe Data API",
    sub: "REST surface — Excel / Sheets / external client bridge.",
    kvs: [
      { k: "Base URL", v: "http://localhost:8000/api" },
      { k: "Auth", v: "Bearer · SHOWME_AUTH_TOKEN" },
      { k: "Rate limit", v: "120 req/min" },
      { k: "Functions", v: "147" },
      { k: "WebSocket", v: "/ws/stream" },
    ],
  },
  DARK: {
    title: "Dark Pool Volume",
    sub: "FINRA ATS weekly off-exchange volume by venue.",
    allowMockDuringLoad: false,
    tableCols: ["Venue", "Shares", "% of total", "Trend"],
    tableRows: [
      { Venue: "IEXG", Shares: "42.1M", "% of total": "18%", Trend: "↑ 2.4%" },
      { Venue: "UBSA", Shares: "38.6M", "% of total": "16%", Trend: "↓ 0.8%" },
      { Venue: "DRCT", Shares: "32.4M", "% of total": "14%", Trend: "↑ 1.2%" },
      { Venue: "JPMS", Shares: "28.2M", "% of total": "12%", Trend: "→ flat" },
      { Venue: "MSCO", Shares: "24.8M", "% of total": "11%", Trend: "↓ 0.4%" },
    ],
  },
  DCF: {
    title: "Discounted Cash Flow",
    sub: "Two-stage DCF — explicit forecast + terminal value.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "WACC", value: "8.4%" },
      { label: "Terminal growth", value: "2.5%" },
      { label: "Explicit yrs", value: "5" },
      { label: "FCF base", value: "$24.8B" },
      { label: "Enterprise value", value: "$542.0B", tone: "pos" },
      { label: "Implied / share", value: "$246.18", tone: "pos" },
    ],
  },
  DCFS: {
    title: "DCF Sensitivity",
    sub: "WACC × terminal-growth grid + ±20% tornado.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Base PV", value: "$246.18" },
      { label: "Bear (-20%)", value: "$197.84", tone: "neg" },
      { label: "Bull (+20%)", value: "$295.42", tone: "pos" },
      { label: "Skew", value: "Asymmetric +" },
    ],
  },
  DDIS: {
    title: "Debt Distribution by Maturity",
    sub: "Issuer debt stack — bucketed by years to maturity.",
    allowMockDuringLoad: false,
    tableCols: ["Bucket", "Face value", "Avg coupon", "Weight"],
    tableRows: [
      { Bucket: "0-1Y", "Face value": "$1.2B", "Avg coupon": "4.6%", Weight: "8%" },
      { Bucket: "1-3Y", "Face value": "$2.8B", "Avg coupon": "4.2%", Weight: "18%" },
      { Bucket: "3-5Y", "Face value": "$3.4B", "Avg coupon": "4.0%", Weight: "22%" },
      { Bucket: "5-10Y", "Face value": "$5.6B", "Avg coupon": "3.8%", Weight: "36%" },
      { Bucket: "10Y+", "Face value": "$2.4B", "Avg coupon": "4.6%", Weight: "16%" },
    ],
  },
  DDM: {
    title: "Dividend Discount Model",
    sub: "Gordon Growth — implied price = D₁ / (r − g).",
    allowMockDuringLoad: false,
    formRows: [
      { label: "D₀ (TTM)", value: "$2.40" },
      { label: "Growth g", value: "5.0%" },
      { label: "Required return r", value: "8.5%" },
      { label: "D₁", value: "$2.52" },
      { label: "Implied price", value: "$72.00", tone: "pos" },
    ],
  },
  DEBT: {
    title: "Sovereign Debt Exposure",
    sub: "Government debt holdings stack — domestic vs foreign holders.",
    allowMockDuringLoad: false,
    tableCols: ["Country", "Debt / GDP", "Foreign held", "10Y yield", "Rating"],
    tableRows: [
      { Country: "USA", "Debt / GDP": "121%", "Foreign held": "24%", "10Y yield": "4.42%", Rating: "AA+" },
      { Country: "JPN", "Debt / GDP": "264%", "Foreign held": "8%", "10Y yield": "1.18%", Rating: "A+" },
      { Country: "DEU", "Debt / GDP": "64%", "Foreign held": "50%", "10Y yield": "2.42%", Rating: "AAA" },
      { Country: "ITA", "Debt / GDP": "140%", "Foreign held": "32%", "10Y yield": "3.92%", Rating: "BBB" },
      { Country: "TUR", "Debt / GDP": "32%", "Foreign held": "44%", "10Y yield": "28.4%", Rating: "B" },
    ],
  },
  DINE: {
    title: "Restaurants",
    sub: "Yelp Fusion — nearby venues, hours, ratings.",
    feed: [
      { source: "★ 4.6", time: "0.4mi", title: "Karaköy Lokantası — Turkish · $$", summary: "Closing 23:00 · 18 reviews this week" },
      { source: "★ 4.4", time: "0.6mi", title: "Mikla — Mediterranean · $$$", summary: "Rooftop · reservation only" },
      { source: "★ 4.8", time: "0.8mi", title: "Çiya Sofrası — Anatolian · $$", summary: "Walk-in OK · 12 photos this week" },
    ],
  },
  DPF: {
    title: "Dark Pool / ATS Volume",
    sub: "FINRA off-exchange (ATS) volume + dark-pool % of total.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Dark %", value: "42.4%" },
      { label: "ATS share", value: "61.2%" },
      { label: "WoW change", value: "+1.8pp", tone: "pos" },
      { label: "Top venue", value: "IEXG" },
    ],
  },
  DVD: {
    title: "Dividends & Splits",
    sub: "Cash dividends + stock splits history; forward yield projection.",
    allowMockDuringLoad: false,
    tableCols: ["Date", "Type", "Amount", "Yield", "Split"],
    tableRows: [
      { Date: "2026-Q2", Type: "Cash", Amount: "$0.62", Yield: "0.42%", Split: "—" },
      { Date: "2026-Q1", Type: "Cash", Amount: "$0.60", Yield: "0.40%", Split: "—" },
      { Date: "2025-Q4", Type: "Cash", Amount: "$0.58", Yield: "0.38%", Split: "—" },
      { Date: "2024-06", Type: "Split", Amount: "—", Yield: "—", Split: "10-for-1" },
      { Date: "2024-Q1", Type: "Cash", Amount: "$0.50", Yield: "0.33%", Split: "—" },
    ],
  },
  ECFC: {
    title: "Economic Forecasts",
    sub: "OECD / IMF / private consensus — GDP · CPI · unemployment.",
    allowMockDuringLoad: false,
    tableCols: ["Region", "GDP 2026", "CPI 2026", "Unemploy", "Source"],
    tableRows: [
      { Region: "USA", "GDP 2026": "+2.4%", "CPI 2026": "2.6%", Unemploy: "4.1%", Source: "OECD" },
      { Region: "EUR", "GDP 2026": "+1.2%", "CPI 2026": "2.2%", Unemploy: "6.4%", Source: "ECB" },
      { Region: "JPN", "GDP 2026": "+0.8%", "CPI 2026": "2.0%", Unemploy: "2.5%", Source: "BOJ" },
      { Region: "CHN", "GDP 2026": "+4.6%", "CPI 2026": "1.6%", Unemploy: "5.1%", Source: "IMF" },
    ],
  },
  ECST: {
    title: "Economic Statistics",
    sub: "FRED-backed series viewer — cross-region overlay.",
    chips: [
      { id: "gdp", label: "GDP" },
      { id: "cpi", label: "CPI" },
      { id: "unemp", label: "Unemployment" },
      { id: "yields", label: "Yields" },
      { id: "trade", label: "Trade balance" },
    ],
  },
  EE: {
    title: "Earnings & Estimates",
    sub: "Actual vs consensus + revision velocity + surprise %.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Next print", value: "2026-04-22", sub: "AMC" },
      { label: "Consensus EPS", value: "$1.42" },
      { label: "Whisper", value: "$1.48", tone: "pos" },
      { label: "Surprise (TTM)", value: "+6.4%", tone: "pos" },
    ],
  },
  EMSX: {
    title: "Execution Management",
    sub: "Multi-broker routing, child slicing, VWAP / TWAP / IS.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Working", value: "8" },
      { label: "Algos active", value: "VWAP · IS" },
      { label: "Slippage", value: "1.2 bps" },
      { label: "Fill rate", value: "92%", tone: "pos" },
    ],
  },
  EREV: {
    title: "Earnings Revisions",
    sub: "Analyst bucket changes month-over-month + revision velocity.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Strong Buy", value: "12" },
      { label: "Buy", value: "18" },
      { label: "Hold", value: "6" },
      { label: "Δ MoM", value: "+3", tone: "pos", sub: "net upgrades" },
    ],
  },
  ESG: {
    title: "ESG Scores",
    sub: "MSCI · Sustainalytics · ISS — three-pillar breakdown.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "E", value: "78", tone: "pos" },
      { label: "S", value: "64" },
      { label: "G", value: "82", tone: "pos" },
      { label: "Composite", value: "A", tone: "pos" },
    ],
  },
  EVTS: {
    title: "Corporate Events",
    sub: "Earnings · ex-div · conferences · investor days.",
    feed: [
      { source: "NVDA", time: "Apr 22", title: "Earnings · AMC", impact: 4, tone: "pos", tags: ["EARN"] },
      { source: "AAPL", time: "May 02", title: "Investor Day", impact: 3, tags: ["IR"] },
      { source: "MSFT", time: "May 18", title: "Build Conference", impact: 2, tags: ["CONF"] },
    ],
  },
  EXEC: {
    title: "Execution Monitor",
    sub: "Live VWAP / TWAP slice-by-slice fill quality + pace.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Working", value: "5" },
      { label: "VWAP track", value: "-0.4 bps", tone: "pos" },
      { label: "Pace", value: "104%" },
      { label: "Slippage", value: "0.8 bps" },
    ],
  },
  FLDS: {
    title: "Field Lookup",
    sub: "Excel autocomplete dictionary — every available field.",
    kpis: [
      { label: "Fields", value: "2,184" },
      { label: "Categories", value: "12" },
      { label: "TTL cache", value: "60s" },
    ],
  },
  FLY: {
    title: "Flight Tracking",
    sub: "OpenSky live aircraft positions + filed routes.",
    kpis: [
      { label: "Aircraft tracked", value: "8" },
      { label: "Live", value: "5" },
      { label: "Filed (today)", value: "12" },
    ],
  },
  FORM4: {
    title: "Insider Transactions",
    sub: "Recent SEC Form 4 filings — insider buys / sells / awards.",
    allowMockDuringLoad: false,
    tableCols: ["Date", "Insider", "Side", "Shares", "Price", "Δ Position"],
    tableRows: [
      { Date: "2026-05-12", Insider: "Huang J. (CEO)", Side: "SELL", Shares: "120,000", Price: "$1,432", "Δ Position": "-1.8%" },
      { Date: "2026-05-10", Insider: "Kress C. (CFO)", Side: "BUY", Shares: "5,000", Price: "$1,418", "Δ Position": "+8.4%" },
      { Date: "2026-05-08", Insider: "Catanzaro J.", Side: "AWARD", Shares: "12,000", Price: "$0", "Δ Position": "+12%" },
    ],
  },
  FRD: {
    title: "FX Forward Rates",
    sub: "Covered interest parity — spot + forward points.",
    allowMockDuringLoad: false,
    tableCols: ["Pair", "Spot", "1M fwd", "3M fwd", "6M fwd", "1Y fwd"],
    tableRows: [
      { Pair: "EURUSD", Spot: 1.0842, "1M fwd": 1.0852, "3M fwd": 1.0876, "6M fwd": 1.0908, "1Y fwd": 1.0962 },
      { Pair: "USDJPY", Spot: 156.42, "1M fwd": 156.12, "3M fwd": 155.48, "6M fwd": 154.62, "1Y fwd": 152.82 },
      { Pair: "GBPUSD", Spot: 1.2682, "1M fwd": 1.2691, "3M fwd": 1.2712, "6M fwd": 1.2742, "1Y fwd": 1.2796 },
    ],
  },
  FRH: {
    title: "Funding Rate Heatmap",
    sub: "Binance · Bybit · OKX — top 25 perp pairs, 8h funding.",
    allowMockDuringLoad: false,
    heatCells: [
      { label: "BTC", value: "+0.012%", intensity: 0.5, tone: "pos" },
      { label: "ETH", value: "+0.018%", intensity: 0.6, tone: "pos" },
      { label: "SOL", value: "+0.042%", intensity: 0.9, tone: "pos" },
      { label: "DOGE", value: "-0.008%", intensity: 0.3, tone: "neg" },
      { label: "XRP", value: "+0.006%", intensity: 0.2, tone: "pos" },
      { label: "LINK", value: "-0.024%", intensity: 0.7, tone: "neg" },
      { label: "AVAX", value: "+0.032%", intensity: 0.8, tone: "pos" },
      { label: "ADA", value: "-0.014%", intensity: 0.4, tone: "neg" },
    ],
  },
  FSRC: {
    title: "Fund Screener",
    sub: "ETF + mutual fund + closed-end discovery.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Universe", value: "3,184" },
      { label: "Matched", value: "42", tone: "pos" },
      { label: "Avg ER", value: "0.42%" },
      { label: "Avg AUM", value: "$4.2B" },
    ],
  },
  FTS: {
    title: "SEC Full-Text Search",
    sub: "EDGAR — text + form type + date range + insider name.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Results", value: "182" },
      { label: "10-K hits", value: "42" },
      { label: "10-Q hits", value: "84" },
      { label: "8-K hits", value: "36" },
    ],
  },
  FXFC: {
    title: "FX Forecasts",
    sub: "Forward carry + vol bands → 1M / 3M / 12M direction.",
    allowMockDuringLoad: false,
    tableCols: ["Pair", "Spot", "3M target", "12M target", "Bias"],
    tableRows: [
      { Pair: "EURUSD", Spot: 1.0842, "3M target": 1.10, "12M target": 1.12, Bias: "Bullish USD?" },
      { Pair: "USDJPY", Spot: 156.4, "3M target": 152, "12M target": 145, Bias: "BoJ tightening" },
      { Pair: "GBPUSD", Spot: 1.268, "3M target": 1.28, "12M target": 1.32, Bias: "BoE cuts priced" },
    ],
  },
  FXGO: {
    title: "FX Trading",
    sub: "Spot + forward execution — multi-bank RFQ.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "Pair", value: "EURUSD" },
      { label: "Side", value: "BUY EUR" },
      { label: "Notional", value: "€5,000,000" },
      { label: "Value date", value: "T+2" },
      { label: "Best bid", value: "1.0840" },
      { label: "Best ask", value: "1.0844" },
      { label: "Total cost", value: "$5,422,000", tone: "neutral" },
    ],
  },
  FXH: {
    title: "FX Hedge",
    sub: "Foreign-currency exposure — forward overlay calculator.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "Exposure", value: "€8,400,000" },
      { label: "Spot", value: "1.0842" },
      { label: "1Y forward", value: "1.0962" },
      { label: "Cost (bps)", value: "+1.11%" },
      { label: "USD locked", value: "$9,207,000", tone: "pos" },
    ],
  },
  FXIP: {
    title: "FX Information Portal",
    sub: "Cross-pair dashboard — vol, carry, sentiment, news.",
    chips: [
      { id: "majors", label: "Majors", count: 8 },
      { id: "em", label: "EM", count: 14 },
      { id: "exotic", label: "Exotic", count: 22 },
    ],
  },
  GC3D: {
    title: "Yield Curve 3D",
    sub: "Curve × time → 3D surface (live FRED).",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Slope 10-2", value: "-0.20%", tone: "neg" },
      { label: "Slope 30-5", value: "+0.18%", tone: "pos" },
      { label: "Curvature", value: "Inverted" },
      { label: "Curve mode", value: "Smooth (SVI)" },
    ],
  },
  GEX: {
    title: "Gamma Exposure",
    sub: "Per-strike dealer gamma exposure + flip + walls.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Net GEX", value: "+$8.4B", tone: "pos" },
      { label: "Flip strike", value: "5,180" },
      { label: "Call wall", value: "5,300" },
      { label: "Put wall", value: "5,050" },
    ],
    tableCols: ["Strike", "Call GEX", "Put GEX", "Net", "Vol"],
    tableRows: [
      { Strike: 5050, "Call GEX": "+$1.2B", "Put GEX": "-$2.4B", Net: "-$1.2B", Vol: "82K" },
      { Strike: 5100, "Call GEX": "+$1.8B", "Put GEX": "-$1.4B", Net: "+$0.4B", Vol: "104K" },
      { Strike: 5180, "Call GEX": "+$2.4B", "Put GEX": "-$0.8B", Net: "+$1.6B", Vol: "142K" },
      { Strike: 5250, "Call GEX": "+$2.8B", "Put GEX": "-$0.4B", Net: "+$2.4B", Vol: "128K" },
      { Strike: 5300, "Call GEX": "+$4.2B", "Put GEX": "-$0.2B", Net: "+$4.0B", Vol: "168K" },
    ],
  },
  GMM: {
    title: "Global Macro Movers",
    sub: "Surprise vs expected — macro data ranked by impact.",
    feed: [
      { source: "US CPI", time: "08:30", title: "Headline CPI 3.1% vs 3.2% expected; core 3.4% (in-line)", impact: 4, tone: "pos", tags: ["INFL"] },
      { source: "DE IFO", time: "09:00", title: "Business climate 88.4 vs 87.2 expected", impact: 3, tone: "pos", tags: ["CONF"] },
      { source: "JP PMI", time: "00:30", title: "Manufacturing PMI 49.8 vs 50.2 expected", impact: 2, tone: "neg", tags: ["PMI"] },
    ],
  },
  GRAB: {
    title: "Screenshot Email",
    sub: "Capture current pane and email it to a configured address.",
    kvs: [
      { k: "Default recipient", v: "trade-desk@firm.com" },
      { k: "Format", v: "PNG · 2x retina" },
      { k: "Compression", v: "Lossless" },
      { k: "Last send", v: "12:42 · today" },
    ],
  },
  GREEKS: {
    title: "Portfolio Greeks",
    sub: "Δ / Γ / ν / Θ / ρ totals across the option book.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Δ", value: "+1,840" },
      { label: "Γ", value: "+182" },
      { label: "ν", value: "-$24,000" },
      { label: "Θ", value: "-$4,200" },
    ],
  },
  HDS: {
    title: "Holders",
    sub: "13F-derived institutional ownership stack.",
    allowMockDuringLoad: false,
    tableCols: ["Holder", "Shares", "% out", "Δ qtr", "Value"],
    tableRows: [
      { Holder: "Vanguard", Shares: "82.4M", "% out": "8.2%", "Δ qtr": "+1.2M", Value: "$118.0B" },
      { Holder: "BlackRock", Shares: "74.2M", "% out": "7.4%", "Δ qtr": "+0.8M", Value: "$106.4B" },
      { Holder: "State Street", Shares: "42.6M", "% out": "4.2%", "Δ qtr": "-0.4M", Value: "$61.0B" },
      { Holder: "Fidelity", Shares: "28.4M", "% out": "2.8%", "Δ qtr": "+0.2M", Value: "$40.7B" },
      { Holder: "T. Rowe Price", Shares: "18.6M", "% out": "1.9%", "Δ qtr": "+0.6M", Value: "$26.6B" },
    ],
  },
  HFS: {
    title: "Holder Search",
    sub: "13F reverse lookup — funds holding the issuer / CUSIP.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Holders found", value: "284" },
      { label: "Total shares", value: "642M" },
      { label: "% of float", value: "64%" },
      { label: "Top 10 conc.", value: "42%" },
    ],
  },
  HVT: {
    title: "Historical Volatility Trends",
    sub: "20d / 50d / 100d realised vol bands — percentile rank.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "HV 20d", value: "32.4%" },
      { label: "HV 50d", value: "28.6%" },
      { label: "HV 100d", value: "26.2%" },
      { label: "Rank", value: "84th", tone: "warn" },
    ],
  },
  ICX: {
    title: "Index Constituents",
    sub: "Wikipedia-backed cache — SPX, NDX, RUT, MSCI, etc.",
    chips: [
      { id: "spx", label: "SPX", count: 500 },
      { id: "ndx", label: "NDX", count: 100 },
      { id: "dji", label: "DJIA", count: 30 },
      { id: "rut", label: "RUT", count: 2000 },
    ],
  },
  ISIN: {
    title: "Symbol Cross-Reference",
    sub: "ISIN / CUSIP / SEDOL / Ticker → OpenFIGI canonical record.",
    kvs: [
      { k: "Ticker", v: "NVDA" },
      { k: "ISIN", v: "US67066G1040" },
      { k: "CUSIP", v: "67066G104" },
      { k: "SEDOL", v: "2379504" },
      { k: "FIGI", v: "BBG000BBJQV0" },
      { k: "Exchange", v: "NASDAQ" },
    ],
  },
  IVOL: {
    title: "Implied Vol Surface",
    sub: "Strike × tenor → IV surface, percentile per-expiry.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "ATM 1M", value: "22.4%" },
      { label: "ATM 3M", value: "24.8%" },
      { label: "Skew 25Δ", value: "+2.4%" },
      { label: "Term", value: "Contango" },
    ],
  },
  LANG: {
    title: "Language Switch",
    sub: "i18n — 12 locales, hot-swap without reload.",
    chips: [
      { id: "en", label: "English" },
      { id: "tr", label: "Türkçe" },
      { id: "de", label: "Deutsch" },
      { id: "fr", label: "Français" },
      { id: "es", label: "Español" },
      { id: "it", label: "Italiano" },
      { id: "ja", label: "日本語" },
      { id: "zh", label: "中文" },
    ],
  },
  LITM: {
    title: "Litigation Monitor",
    sub: "8-K Items 1.03 / 1.04 / 3.03 — bankruptcy, mine safety, security holder.",
    feed: [
      { source: "XYZ", time: "2d", title: "Item 1.03 — voluntary Ch.11 filing", impact: 5, tone: "neg", tags: ["BANKRUPT"] },
      { source: "ABC", time: "4d", title: "Item 1.04 — mine safety event", impact: 2, tone: "warn", tags: ["MSHA"] },
      { source: "DEF", time: "1w", title: "Item 3.03 — bylaw amendment", impact: 1, tone: "neutral", tags: ["GOV"] },
    ],
  },
  LOTS: {
    title: "Tax Lots",
    sub: "Open / list / sell — FIFO · LIFO · HIFO · specific ID.",
    allowMockDuringLoad: false,
    tableCols: ["Lot ID", "Open date", "Qty", "Cost", "Mkt", "Unrealized", "Method"],
    tableRows: [
      { "Lot ID": "L-4218", "Open date": "2024-03-12", Qty: 100, Cost: 484.2, Mkt: 1432.18, Unrealized: "+$94,798", Method: "HIFO" },
      { "Lot ID": "L-4314", "Open date": "2024-08-04", Qty: 50, Cost: 612.4, Mkt: 1432.18, Unrealized: "+$40,989", Method: "HIFO" },
      { "Lot ID": "L-4502", "Open date": "2025-01-22", Qty: 200, Cost: 824.6, Mkt: 1432.18, Unrealized: "+$121,516", Method: "FIFO" },
    ],
  },
  MARS: {
    title: "Multi-Asset Risk",
    sub: "Fama-French 5-factor regression on returns.",
    allowMockDuringLoad: false,
    tableCols: ["Factor", "Beta", "T-stat", "Contribution"],
    tableRows: [
      { Factor: "MKT", Beta: 1.42, "T-stat": 18.4, Contribution: "+8.4%" },
      { Factor: "SMB", Beta: -0.18, "T-stat": -2.4, Contribution: "-0.6%" },
      { Factor: "HML", Beta: -0.42, "T-stat": -4.8, Contribution: "-1.8%" },
      { Factor: "RMW", Beta: 0.32, "T-stat": 3.4, Contribution: "+1.2%" },
      { Factor: "CMA", Beta: -0.24, "T-stat": -2.8, Contribution: "-0.8%" },
    ],
  },
  MEET: {
    title: "Meeting Briefing",
    sub: "Notion + Granola + portfolio + news + DES → pre-meeting brief.",
    feed: [
      { source: "AAPL", time: "10:00", title: "Call with C. Lee — Q2 capex outlook", summary: "DES · positions · last 5 news mentions attached.", tags: ["BRIEF"], impact: 3 },
      { source: "JPM", time: "13:30", title: "Lunch — sell-side energy specialist", summary: "Granola transcript ready · meeting notes pre-filled.", tags: ["NOTES"], impact: 2 },
    ],
  },
  MGN: {
    title: "Cross-Account Margin",
    sub: "Margin requirements + buying power per account.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Margin used", value: "$182,400" },
      { label: "Buying power", value: "$842,180", tone: "pos" },
      { label: "Margin %", value: "18%" },
      { label: "Closest call", value: "$95K cushion" },
    ],
  },
  MICRO: {
    title: "Market Microstructure",
    sub: "Order-book depth, imbalance, spread, Kyle's λ proxy.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Top-of-book", value: "0.4 / 0.6" },
      { label: "Imbalance", value: "+42%", tone: "pos" },
      { label: "Spread (bps)", value: "0.6" },
      { label: "Kyle's λ", value: "0.018" },
    ],
  },
  MLSIG: {
    title: "ML Signal Classifier",
    sub: "Train classifier on technical features → next-N-day direction.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Model", value: "GBM" },
      { label: "Features", value: "32" },
      { label: "Accuracy", value: "0.62", tone: "pos" },
      { label: "AUC", value: "0.68", tone: "pos" },
    ],
  },
  MOSS: {
    title: "Most Volatile",
    sub: "Realised vol leaderboard across watchlist / universe.",
    allowMockDuringLoad: false,
    tableCols: ["Symbol", "HV 20d", "HV 50d", "Δ", "Px"],
    tableRows: [
      { Symbol: "TSLA", "HV 20d": "62%", "HV 50d": "48%", "Δ": "+14pp", Px: 248 },
      { Symbol: "NVDA", "HV 20d": "48%", "HV 50d": "42%", "Δ": "+6pp", Px: 1432 },
      { Symbol: "MARA", "HV 20d": "84%", "HV 50d": "72%", "Δ": "+12pp", Px: 24 },
      { Symbol: "COIN", "HV 20d": "72%", "HV 50d": "62%", "Δ": "+10pp", Px: 282 },
    ],
  },
  NALRT: {
    title: "Critical News Alerts",
    sub: "Live headlines scored by market impact — critical / high tier.",
    feed: FEED_NEWS.slice(0, 3).map((f) => ({ ...f, impact: 5, tone: "warn" as const })),
  },
  NGAS: {
    title: "Natural Gas",
    sub: "Henry Hub spot + futures curve + storage flow.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Spot", value: "$2.84", tone: "pos" },
      { label: "Front month", value: "$2.92" },
      { label: "EIA storage", value: "1,820 Bcf" },
      { label: "Y/Y", value: "-12.4%", tone: "neg" },
    ],
  },
  NSE: {
    title: "News Search Engine",
    sub: "Cross-source search — Meilisearch backend when available.",
    chips: [
      { id: "today", label: "Today" },
      { id: "week", label: "This week" },
      { id: "month", label: "This month" },
      { id: "all", label: "All time" },
    ],
    feed: FEED_NEWS.slice(0, 4),
  },
  OMON: {
    title: "Option Monitor",
    sub: "Full option chain — IV, Greeks, volume, OI per strike.",
    allowMockDuringLoad: false,
    tableCols: ["Strike", "IV", "Δ", "Γ", "Vol", "OI"],
    tableRows: [
      { Strike: 1400, IV: "28.4%", "Δ": 0.62, "Γ": 0.018, Vol: "12K", OI: "84K" },
      { Strike: 1430, IV: "26.2%", "Δ": 0.52, "Γ": 0.024, Vol: "18K", OI: "142K" },
      { Strike: 1450, IV: "25.6%", "Δ": 0.42, "Γ": 0.026, Vol: "22K", OI: "164K" },
      { Strike: 1500, IV: "24.8%", "Δ": 0.28, "Γ": 0.022, Vol: "16K", OI: "98K" },
    ],
  },
  ONCH: {
    title: "On-Chain Metrics",
    sub: "BTC · ETH · L2 — fees, hash rate, active addresses, gas.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "BTC Hash", value: "682 EH/s", tone: "pos" },
      { label: "ETH Gas", value: "18 gwei" },
      { label: "BTC Fees", value: "$24 avg" },
      { label: "Active addr", value: "1.18M" },
    ],
  },
  OSA: {
    title: "Option Strategy Analysis",
    sub: "Multi-leg P&L + Greeks at expiry, IV scenarios.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "Strategy", value: "Iron Condor 1430/1450/1500/1520" },
      { label: "Max profit", value: "+$1,420", tone: "pos" },
      { label: "Max loss", value: "-$580", tone: "neg" },
      { label: "B/E lower", value: "1,439" },
      { label: "B/E upper", value: "1,511" },
    ],
  },
  OVDV: {
    title: "FX Option Volatility Surface",
    sub: "FX option IV surface — strike × tenor.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "ATM 1M", value: "8.2%" },
      { label: "ATM 3M", value: "8.8%" },
      { label: "25Δ RR", value: "+0.4%" },
      { label: "BFly", value: "0.18%" },
    ],
  },
  OVME: {
    title: "Option Valuation",
    sub: "Black-Scholes — value + Greeks + breakeven.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "Underlying", value: "$1,432" },
      { label: "Strike", value: "$1,450" },
      { label: "Volatility", value: "26.2%" },
      { label: "Tenor", value: "30d" },
      { label: "Value (call)", value: "$42.18", tone: "pos" },
      { label: "Δ", value: "0.42" },
    ],
  },
  PCAS: {
    title: "PCA Factor Stress",
    sub: "Apply k-σ shock along principal components.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Components", value: "5" },
      { label: "Cumul. var", value: "94%" },
      { label: "Worst k=-3σ", value: "-$84,000", tone: "neg" },
      { label: "Worst k=+3σ", value: "+$92,000", tone: "pos" },
    ],
  },
  PEOP: {
    title: "People Search",
    sub: "Executives, analysts, contacts — local directory.",
    feed: [
      { source: "C. Lee", time: "AAPL", title: "VP Capital Markets · Apple Inc.", summary: "Last contact: 2 weeks ago. Sector: Tech.", tags: ["EXEC"] },
      { source: "M. Patel", time: "GS", title: "Sell-side · Energy", summary: "Active analyst — covers XOM, CVX, OXY.", tags: ["ANALYST"] },
      { source: "R. Schäfer", time: "DB", title: "DCM · EUR rates", summary: "Available for calls 14-17 CET.", tags: ["BANK"] },
    ],
  },
  PFA: {
    title: "Performance Attribution (Brinson)",
    sub: "Brinson-Hood-Beebower — allocation + selection + interaction.",
    allowMockDuringLoad: false,
    tableCols: ["Sector", "Alloc bp", "Select bp", "Interact bp", "Total bp"],
    tableRows: [
      { Sector: "Technology", "Alloc bp": "+12", "Select bp": "+24", "Interact bp": "+3", "Total bp": "+39" },
      { Sector: "Energy", "Alloc bp": "-4", "Select bp": "+18", "Interact bp": "+1", "Total bp": "+15" },
      { Sector: "Financials", "Alloc bp": "+2", "Select bp": "-8", "Interact bp": "0", "Total bp": "-6" },
      { Sector: "Healthcare", "Alloc bp": "+6", "Select bp": "+4", "Interact bp": "+1", "Total bp": "+11" },
    ],
  },
  PIB: {
    title: "Public Information Book",
    sub: "Latest SEC filings + AI summary + key risks.",
    feed: [
      { source: "10-K", time: "Mar 22", title: "Annual report — AI strategy expansion section", impact: 3, tone: "neutral", tags: ["FILING"] },
      { source: "10-Q", time: "Apr 18", title: "Q1 results — gross margin commentary", impact: 4, tone: "pos", tags: ["FILING"] },
      { source: "8-K", time: "May 02", title: "Item 5.02 — CFO transition", impact: 3, tone: "warn", tags: ["FILING"] },
    ],
  },
  POLY: {
    title: "Polymarket",
    sub: "Prediction-market odds (Polymarket public CLOB).",
    feed: [
      { source: "Election", time: "2026", title: "US 2026 midterm — GOP House majority", summary: "Yes 62¢ · No 38¢ · 184M traded.", tags: ["POLITICS"], impact: 3 },
      { source: "Crypto", time: "2026", title: "BTC > $100K by year-end", summary: "Yes 72¢ · No 28¢ · 124M traded.", tags: ["CRYPTO"], impact: 4 },
      { source: "Macro", time: "2026", title: "First Fed cut by July FOMC", summary: "Yes 42¢ · No 58¢ · 86M traded.", tags: ["RATES"], impact: 3 },
    ],
  },
  PORT_OPT: {
    title: "Portfolio Optimizer",
    sub: "Markowitz min-vol / max-Sharpe / risk-parity / efficient frontier.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Best Sharpe", value: "1.84", tone: "pos" },
      { label: "Min vol", value: "11.2%" },
      { label: "Max return", value: "18.4%", tone: "pos" },
      { label: "Method", value: "Max Sharpe" },
    ],
    tableCols: ["Asset", "Min vol w", "Max Sharpe w", "Risk parity"],
    tableRows: [
      { Asset: "Stocks", "Min vol w": "32%", "Max Sharpe w": "58%", "Risk parity": "42%" },
      { Asset: "Bonds", "Min vol w": "48%", "Max Sharpe w": "24%", "Risk parity": "32%" },
      { Asset: "Real est.", "Min vol w": "12%", "Max Sharpe w": "10%", "Risk parity": "14%" },
      { Asset: "Comm.", "Min vol w": "4%", "Max Sharpe w": "4%", "Risk parity": "6%" },
      { Asset: "Cash", "Min vol w": "4%", "Max Sharpe w": "4%", "Risk parity": "6%" },
    ],
  },
  PORT_WHATIF: {
    title: "Portfolio What-If",
    sub: "Add hypothetical trades — recompute risk + return totals.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "Hypothetical buy", value: "100 NVDA @ market" },
      { label: "New NAV", value: "$1,847,200", tone: "pos" },
      { label: "ΔRisk", value: "+0.8%", tone: "warn" },
      { label: "ΔSharpe", value: "+0.04", tone: "pos" },
      { label: "Max DD est.", value: "-14.8%" },
    ],
  },
  PSC: {
    title: "Position Sizing Calculator",
    sub: "R-multiples + Kelly fraction — risk-based sizing.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "Account", value: "$642,150" },
      { label: "Risk per trade", value: "1.0%" },
      { label: "Entry", value: "$1,432" },
      { label: "Stop", value: "$1,400" },
      { label: "Size (shares)", value: "200", tone: "pos" },
      { label: "Notional", value: "$286,400" },
    ],
  },
  PVAR: {
    title: "Position-level VaR / MCR",
    sub: "Per-symbol marginal contribution to portfolio risk.",
    allowMockDuringLoad: false,
    tableCols: ["Symbol", "Weight", "MCR", "% of risk"],
    tableRows: [
      { Symbol: "NVDA", Weight: "22%", MCR: "$8,420", "% of risk": "34%" },
      { Symbol: "AAPL", Weight: "18%", MCR: "$4,180", "% of risk": "18%" },
      { Symbol: "MSFT", Weight: "16%", MCR: "$3,640", "% of risk": "15%" },
      { Symbol: "GOOG", Weight: "12%", MCR: "$2,820", "% of risk": "12%" },
    ],
  },
  READ: {
    title: "Personalized News (For You)",
    sub: "Watchlist · portfolio · followed topics → ranked feed.",
    feed: FEED_NEWS,
  },
  REBA: {
    title: "Portfolio Rebalancer",
    sub: "Compute orders to bring current portfolio to target weights.",
    allowMockDuringLoad: false,
    tableCols: ["Symbol", "Current", "Target", "Order"],
    tableRows: [
      { Symbol: "NVDA", Current: "22%", Target: "18%", Order: "SELL 4%" },
      { Symbol: "AAPL", Current: "14%", Target: "18%", Order: "BUY 4%" },
      { Symbol: "MSFT", Current: "16%", Target: "16%", Order: "—" },
      { Symbol: "Cash", Current: "8%", Target: "10%", Order: "BUY 2%" },
    ],
  },
  REGM: {
    title: "Market Regime",
    sub: "Trend + vol + DD + curve → regime class; optional clustering.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Regime", value: "Goldilocks", tone: "pos" },
      { label: "Trend", value: "Up · 2σ" },
      { label: "Vol", value: "Low · 0.6σ" },
      { label: "Curve", value: "Inverted" },
    ],
  },
  RPAR: {
    title: "Risk Parity (ERC)",
    sub: "Equal-risk-contribution weights for given universe.",
    allowMockDuringLoad: false,
    tableCols: ["Asset", "Volatility", "Correlation", "Weight"],
    tableRows: [
      { Asset: "Stocks", Volatility: "18%", Correlation: "—", Weight: "24%" },
      { Asset: "Bonds", Volatility: "6%", Correlation: "-0.4", Weight: "48%" },
      { Asset: "Comm.", Volatility: "20%", Correlation: "+0.2", Weight: "16%" },
      { Asset: "Real est.", Volatility: "14%", Correlation: "+0.3", Weight: "12%" },
    ],
  },
  RV: {
    title: "Relative Valuation",
    sub: "Peer set — P/E, EV/EBITDA, P/B, P/S vs sector.",
    allowMockDuringLoad: false,
    tableCols: ["Peer", "P/E", "EV/EBITDA", "P/B", "P/S"],
    tableRows: [
      { Peer: "NVDA", "P/E": 62, "EV/EBITDA": 48, "P/B": 24, "P/S": 32 },
      { Peer: "AMD", "P/E": 42, "EV/EBITDA": 28, "P/B": 4, "P/S": 8 },
      { Peer: "INTC", "P/E": 18, "EV/EBITDA": 12, "P/B": 2, "P/S": 2 },
      { Peer: "MU", "P/E": 22, "EV/EBITDA": 14, "P/B": 3, "P/S": 4 },
    ],
  },
  SAT: {
    title: "Satellite Imagery",
    sub: "Sentinel-2 true-color + NDVI — bbox + date window.",
    kvs: [
      { k: "Provider", v: "Sentinel-2" },
      { k: "Resolution", v: "10m / pixel" },
      { k: "NDVI mean", v: "0.62" },
      { k: "Cloud cover", v: "12%" },
    ],
  },
  SECF: {
    title: "Security Finder",
    sub: "Natural-language → DSL query translator.",
    kvs: [
      { k: "Example", v: "'tech stocks with PE < 20 and dividend yield > 2%'" },
      { k: "Translated", v: "sector=Tech AND pe<20 AND divYield>0.02" },
      { k: "Results", v: "18" },
      { k: "Latency", v: "0.4s" },
    ],
  },
  SOSC: {
    title: "Social Sentiment",
    sub: "StockTwits + Reddit aggregator — bullish/bearish, mentions, velocity.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Bullish %", value: "62%", tone: "pos" },
      { label: "Bearish %", value: "24%", tone: "neg" },
      { label: "Mentions 24h", value: "8,420" },
      { label: "Vel · Δ", value: "+18%", tone: "pos" },
    ],
  },
  SPLC: {
    title: "Supply Chain",
    sub: "10-K text mining + filings — supplier / customer graph.",
    tableCols: ["Counterparty", "Type", "Disclosed", "Mentions"],
    tableRows: [
      { Counterparty: "TSMC", Type: "Supplier", Disclosed: "Yes", Mentions: 24 },
      { Counterparty: "Foxconn", Type: "Supplier", Disclosed: "Yes", Mentions: 18 },
      { Counterparty: "Microsoft", Type: "Customer", Disclosed: "Yes", Mentions: 14 },
      { Counterparty: "Amazon AWS", Type: "Customer", Disclosed: "Yes", Mentions: 12 },
    ],
  },
  SRCH: {
    title: "Bond Screener",
    sub: "Filter by issuer / coupon / maturity / rating / YTM.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Universe", value: "12,840" },
      { label: "Matched", value: "82" },
      { label: "Avg YTM", value: "5.2%" },
      { label: "Avg duration", value: "6.8y" },
    ],
  },
  SRSK: {
    title: "Sovereign Risk",
    sub: "CDS-implied PD + macro overlay → sovereign risk score.",
    allowMockDuringLoad: false,
    tableCols: ["Country", "5Y CDS", "Implied PD", "Rating"],
    tableRows: [
      { Country: "USA", "5Y CDS": "32 bps", "Implied PD": "0.5%", Rating: "AA+" },
      { Country: "DEU", "5Y CDS": "16 bps", "Implied PD": "0.3%", Rating: "AAA" },
      { Country: "ITA", "5Y CDS": "84 bps", "Implied PD": "1.4%", Rating: "BBB" },
      { Country: "TUR", "5Y CDS": "284 bps", "Implied PD": "4.6%", Rating: "B" },
    ],
  },
  STRS: {
    title: "Portfolio Stress Test",
    sub: "Historical + custom shock scenarios applied to portfolio.",
    allowMockDuringLoad: false,
    tableCols: ["Scenario", "Equity Δ", "Rates Δ", "FX Δ", "P&L"],
    tableRows: [
      { Scenario: "GFC '08", "Equity Δ": "-50%", "Rates Δ": "-200bp", "FX Δ": "Flight to USD", "P&L": "-$420K" },
      { Scenario: "Covid '20", "Equity Δ": "-32%", "Rates Δ": "-150bp", "FX Δ": "Mixed", "P&L": "-$268K" },
      { Scenario: "Custom 1", "Equity Δ": "-20%", "Rates Δ": "+100bp", "FX Δ": "+5% USD", "P&L": "-$182K" },
      { Scenario: "Vol surge", "Equity Δ": "-8%", "Rates Δ": "+0bp", "FX Δ": "Flat", "P&L": "-$96K" },
    ],
  },
  TAUC: {
    title: "Treasury Auction Calendar",
    sub: "Upcoming + recent auctions — Bills, Notes, Bonds, TIPS, FRN.",
    feed: [
      { source: "10Y", time: "Today 17:00", title: "$39B 10Y re-open · indirect bid focus", impact: 4, tone: "warn", tags: ["AUCTION"] },
      { source: "30Y", time: "Tomorrow", title: "$22B new 30Y · curve steepener risk", impact: 3, tone: "warn", tags: ["AUCTION"] },
      { source: "TIPS", time: "Apr 25", title: "$18B 5Y TIPS · breakeven focus", impact: 2, tags: ["TIPS"] },
    ],
  },
  TCA: {
    title: "Trade Cost Analysis",
    sub: "Implementation shortfall, slippage, opportunity cost across fills.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Avg slippage", value: "1.2 bps" },
      { label: "IS shortfall", value: "0.8 bps" },
      { label: "Opp. cost", value: "0.4 bps" },
      { label: "Total", value: "2.4 bps", tone: "warn" },
    ],
  },
  TECH: {
    title: "Technical Indicators",
    sub: "30+ indicators — RSI, MACD, ATR, BB, Stochastic, ADX, OBV, Ichimoku…",
    chips: [
      { id: "rsi", label: "RSI(14)" },
      { id: "macd", label: "MACD" },
      { id: "atr", label: "ATR(14)" },
      { id: "bb", label: "BB(20,2)" },
      { id: "stoch", label: "Stoch" },
      { id: "adx", label: "ADX" },
      { id: "obv", label: "OBV" },
      { id: "ichi", label: "Ichimoku" },
    ],
  },
  TLDR: {
    title: "Daily TL;DR",
    sub: "Portfolio + watchlist day in 5 LLM-summarised bullets.",
    feed: [
      { source: "DESK", time: "Top", title: "NVDA carries +$3.2K of today's gains; data-center channel checks strong.", impact: 5, tone: "pos", tags: ["TOP"] },
      { source: "FX", time: "2nd", title: "JPY carry sleeping — BoJ on hold; positioning unchanged.", impact: 3, tone: "neutral", tags: ["FX"] },
      { source: "RATES", time: "3rd", title: "10Y auction tails 1.2 bps; modest sell-off into close.", impact: 3, tone: "warn", tags: ["UST"] },
      { source: "COMMS", time: "4th", title: "Energy +0.4% on crude inventory draw; refining margins widen.", impact: 2, tone: "pos", tags: ["OIL"] },
      { source: "ALERT", time: "5th", title: "AAPL CFO transition — watch for guidance update at Q3.", impact: 4, tone: "warn", tags: ["MGMT"] },
    ],
  },
  TLH: {
    title: "Tax-Loss Harvesting",
    sub: "Loss lots, tax savings estimate, wash-sale-safe swaps.",
    allowMockDuringLoad: false,
    tableCols: ["Symbol", "Loss lot", "Loss", "Est. tax saved", "Swap"],
    tableRows: [
      { Symbol: "ARKK", "Loss lot": "L-2218", Loss: "-$8,400", "Est. tax saved": "$2,100", Swap: "VGT" },
      { Symbol: "META", "Loss lot": "L-3104", Loss: "-$4,800", "Est. tax saved": "$1,200", Swap: "GOOG" },
      { Symbol: "PYPL", "Loss lot": "L-4218", Loss: "-$2,400", "Est. tax saved": "$600", Swap: "V" },
    ],
  },
  TRA: {
    title: "Total Return Analysis",
    sub: "TWR + IRR + price + dividends — total return decomposition.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "TWR YTD", value: "+18.4%", tone: "pos" },
      { label: "IRR YTD", value: "+19.2%", tone: "pos" },
      { label: "Price", value: "+16.8%", tone: "pos" },
      { label: "Income", value: "+1.6%", tone: "pos" },
    ],
  },
  TRAN: {
    title: "Earnings Call Transcripts",
    sub: "Most recent transcripts + IR fallback for missing quarters.",
    feed: [
      { source: "NVDA", time: "Q3 '26", title: "Q3 FY26 earnings call · transcript ready", summary: "67 minutes · 4 analyst questions · pricing power emphasised.", tags: ["EARN", "TRAN"], impact: 4, tone: "pos" },
      { source: "AAPL", time: "Q2 '26", title: "Q2 FY26 earnings call · transcript ready", summary: "82 minutes · services growth led commentary.", tags: ["EARN", "TRAN"], impact: 3, tone: "pos" },
    ],
  },
  TRDH: {
    title: "Trading Hours",
    sub: "Per-exchange session status + next open / close (UTC).",
    allowMockDuringLoad: false,
    tableCols: ["Exchange", "Status", "Open", "Close"],
    tableRows: [
      { Exchange: "NYSE", Status: "OPEN", Open: "13:30", Close: "20:00" },
      { Exchange: "NASDAQ", Status: "OPEN", Open: "13:30", Close: "20:00" },
      { Exchange: "LSE", Status: "CLOSED", Open: "08:00 (tmr)", Close: "—" },
      { Exchange: "TSE", Status: "CLOSED", Open: "00:00 (tmr)", Close: "—" },
    ],
  },
  TRQA: {
    title: "Transcript Q&A",
    sub: "Run a list of questions against a transcript / audio.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Questions", value: "12" },
      { label: "Answered", value: "10", tone: "pos" },
      { label: "Insufficient", value: "2" },
      { label: "Latency", value: "0.8s" },
    ],
  },
  TSAR: {
    title: "Transcript Search",
    sub: "Search across stored transcripts (SQLite FTS5).",
    allowMockDuringLoad: false,
    kpis: [
      { label: "Stored", value: "8,420 calls" },
      { label: "Matched", value: "42" },
      { label: "Top symbol", value: "NVDA" },
      { label: "Date span", value: "2020-2026" },
    ],
  },
  TSOX: {
    title: "Treasury Order Entry",
    sub: "Treasury / bond order ticket — CUSIP, par, settlement.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "CUSIP", value: "912828ZK4" },
      { label: "Side", value: "BUY" },
      { label: "Par", value: "$5,000,000" },
      { label: "Settlement", value: "T+2" },
      { label: "Yield", value: "4.420%" },
      { label: "Price", value: "99.842" },
      { label: "Accrued", value: "$2,418" },
    ],
  },
  WACC: {
    title: "Weighted Average Cost of Capital",
    sub: "Cost of equity + cost of debt + tax shield.",
    allowMockDuringLoad: false,
    formRows: [
      { label: "Risk-free (10Y)", value: "4.42%" },
      { label: "Beta", value: "1.42" },
      { label: "ERP", value: "5.0%" },
      { label: "Cost of equity", value: "11.5%" },
      { label: "Cost of debt", value: "5.2%" },
      { label: "Tax rate", value: "21%" },
      { label: "WACC", value: "8.4%", tone: "pos" },
    ],
  },
  WB: {
    title: "World Bonds",
    sub: "Sovereign 10Y yield heatmap, day-change tinted.",
    allowMockDuringLoad: false,
    heatCells: HEAT_WORLD,
  },
  WETR: {
    title: "Weather Trends",
    sub: "Commodity-relevant region weather trends.",
    allowMockDuringLoad: false,
    kpis: [
      { label: "PADD-3 temp", value: "92°F" },
      { label: "Cooling DD", value: "+4" },
      { label: "Drought %", value: "12%" },
      { label: "Trend", value: "Warming" },
    ],
  },
  WHAL: {
    title: "Whale Alerts",
    sub: "Large on-chain transfers + balance moves + liquidity shocks.",
    feed: [
      { source: "BTC", time: "0:22", title: "1,840 BTC moved to Binance hot wallet ($118M)", impact: 4, tone: "warn", tags: ["WHALE"] },
      { source: "ETH", time: "1:14", title: "42,000 ETH staked via Lido", impact: 3, tone: "pos", tags: ["WHALE"] },
      { source: "USDT", time: "2:08", title: "USDT mint — $500M new supply (Tron)", impact: 4, tone: "warn", tags: ["STABLE"] },
    ],
  },
  WIRP: {
    title: "World Interest Rate Probability",
    sub: "CME FedWatch-style policy-path probabilities.",
    allowMockDuringLoad: false,
    tableCols: ["FOMC", "−25bp", "Hold", "+25bp"],
    tableRows: [
      { FOMC: "Jun '26", "−25bp": "42%", Hold: "56%", "+25bp": "2%" },
      { FOMC: "Jul '26", "−25bp": "62%", Hold: "36%", "+25bp": "2%" },
      { FOMC: "Sep '26", "−25bp": "72%", Hold: "26%", "+25bp": "2%" },
      { FOMC: "Nov '26", "−25bp": "82%", Hold: "16%", "+25bp": "2%" },
    ],
  },
  YAS: {
    title: "Yield & Spread Analytics",
    sub: "Bond YTM + modified duration + convexity + spread vs benchmark with ±100bp sensitivity curve.",
    allowMockDuringLoad: false,
    eyebrow: "BOND ANALYTICS · UST10Y reference",
    kpis: [
      { label: "YTM", value: "4.42%", tone: "neutral", sub: "Newton solver, 2/yr coupon" },
      { label: "Mod Duration", value: "8.4y", tone: "neutral", sub: "≈ −8.4% per 100bp" },
      { label: "Convexity", value: "0.84", tone: "pos", sub: "2nd-order cushion" },
      { label: "Spread vs UST", value: "+18 bps", tone: "warn", sub: "vs DGS10 from FRED" },
    ],
    tableCols: ["Metric", "Value", "Unit"],
    tableRows: [
      { Metric: "Yield-to-maturity", Value: "4.4200%", Unit: "decimal annual" },
      { Metric: "Macaulay duration", Value: "8.78", Unit: "years" },
      { Metric: "Modified duration", Value: "8.40", Unit: "years" },
      { Metric: "Convexity", Value: "0.84", Unit: "price-convexity" },
      { Metric: "Spread vs benchmark", Value: "+18.0", Unit: "bps" },
    ],
    formRows: [
      { label: "Shock −100 bp", value: "price ≈ 108.84", tone: "pos" },
      { label: "Shock  −50 bp", value: "price ≈ 104.31", tone: "pos" },
      { label: "Shock   0 bp", value: "price = 99.50",   tone: "neutral" },
      { label: "Shock  +50 bp", value: "price ≈ 95.41",  tone: "neg" },
      { label: "Shock +100 bp", value: "price ≈ 91.66",  tone: "neg" },
    ],
    narrative:
      "Solves YTM by Newton iteration, then derives Macaulay/modified duration, convexity, and spread vs the selected benchmark (FRED DGS10 when live=true). The sensitivity rows estimate dirty-price moves around the current yield using duration + convexity.",
  },
};

/* Aliases — design ships separate templates that map to existing fn codes. */

const ALIASES: Record<string, string> = {
  // No aliases needed for now — the design already uses the canonical names
  // (CN handled in registry by aliasing to NI native pane).
};

export function getMockTemplate(code: string): MockTemplate | null {
  const upper = code.toUpperCase();
  if (TPL[upper]) return TPL[upper];
  const alias = ALIASES[upper];
  if (alias && TPL[alias]) return TPL[alias];
  return null;
}

export function listMockCodes(): string[] {
  return Object.keys(TPL).sort();
}

export { SPARK_UP, SPARK_DN, SPARK_VOL, SPARKS_WL };
