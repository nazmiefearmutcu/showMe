import type { RowLimit } from "@/functions/function-control-state";
import {
  STUB_RANGES,
  type BacktestStrategy,
  type ControlProfile,
  type OptionStrategy,
  type OptionType,
  type StubRangeId,
} from "./_types";
import { numericInput } from "./simple-params";

export {
  buildSimpleControlParams,
  defaultSimpleParamsForFunction,
  numericInput,
  parseTargetWeights,
  simpleParamSpecsForFunction,
  splitCsv,
  truthyInput,
} from "./simple-params";

const LIMIT_PARAM_CODES = new Set([
  "AIM",
  "BQL",
  "DAPI",
  "EXEC",
  "FLDS",
  "ISIN",
  "NSE",
  "TOP",
  "CN",
  "NI",
  "TAUC",
]);

const TOP_N_PARAM_CODES = new Set(["HDS"]);
const LIMIT_CATEGORIES = new Set(["news", "screen", "trade"]);

const DAYS_PARAM_CODES = new Set([
  "BLAK",
  "BMTX",
  "BTFW",
  "BTUNE",
  "BGAS",
  "BOIL",
  "CHGS",
  "BQL",
  "CORR",
  "CPF",
  "GC3D",
  "HVT",
  "MARS",
  "MLSIG",
  "MOSS",
  "NGAS",
  "PORT_OPT",
  "PVAR",
  "READ",
  "RPAR",
  "SAT",
  "TECH",
]);

const WEEKS_PARAM_CODES = new Set(["DPF"]);
const HORIZON_PARAM_CODES = new Set(["TAUC"]);
const TRADE_TICKET_CODES = new Set(["BBGT", "EMSX", "FXGO", "TSOX"]);
const QUERY_PARAM_CODES = new Set([
  "AV",
  "BRIEF",
  "BQL",
  "CSRC",
  "DAPI",
  "FLDS",
  "FSRC",
  "FTS",
  "ICX",
  "ISIN",
  "MEET",
  "NSE",
  "PEOP",
  "POLY",
  "SECF",
  "SRCH",
  "TOP",
  "TSAR",
]);
const TOPIC_PARAM_CODES = new Set(["NI"]);
const SYMBOLS_PARAM_CODES = new Set(["BLAK", "BMTX", "CORR", "FRH", "MARS", "PORT_OPT", "RPAR", "TLDR"]);
const WATCHLIST_PARAM_CODES = new Set(["READ"]);
const UNIVERSE_PARAM_CODES = new Set(["MOSS"]);
const BBOX_PARAM_CODES = new Set(["SAT"]);

export function buildControlProfile(code: string, category?: string): ControlProfile {
  const upper = code.toUpperCase();
  const cat = category?.toLowerCase() ?? "";
  const limitParam = TOP_N_PARAM_CODES.has(upper)
    ? "top_n"
    : LIMIT_PARAM_CODES.has(upper) || LIMIT_CATEGORIES.has(cat)
      ? "limit"
      : undefined;
  const rangeParam = WEEKS_PARAM_CODES.has(upper)
    ? "weeks"
    : HORIZON_PARAM_CODES.has(upper)
      ? "horizon_days"
      : DAYS_PARAM_CODES.has(upper)
        ? "days"
        : undefined;
  const queryParam = TOPIC_PARAM_CODES.has(upper)
    ? "topic"
    : SYMBOLS_PARAM_CODES.has(upper)
      ? "symbols"
    : WATCHLIST_PARAM_CODES.has(upper)
      ? "watchlist"
    : UNIVERSE_PARAM_CODES.has(upper)
      ? "universe"
    : BBOX_PARAM_CODES.has(upper)
      ? "bbox"
    : QUERY_PARAM_CODES.has(upper) || cat === "news"
      ? "query"
      : undefined;
  const tradeTicket = TRADE_TICKET_CODES.has(upper);
  const transcriptText = upper === "TRQA";
  const queryLabel = upper === "ICX"
    ? "Index"
    : upper === "SAT"
      ? "BBox"
      : upper === "BQL"
        ? "BQL"
      : upper === "DAPI"
        ? "Endpoint"
      : upper === "FLDS"
        ? "Field"
      : upper === "ISIN"
        ? "Identifier"
      : upper === "FTS"
        ? "Search"
      : upper === "FRH"
        ? "Symbols"
      : upper === "BLAK" || upper === "BMTX" || upper === "CORR" || upper === "PORT_OPT" || upper === "RPAR"
        ? "Universe"
      : upper === "MARS" || upper === "MOSS"
        ? "Universe"
      : upper === "TLDR" || upper === "READ"
        ? "Watchlist"
      : undefined;
  const queryHint = upper === "ICX"
    ? "Index code sent to backend, e.g. SPX, NDX, DJI."
    : upper === "SAT"
      ? "minLon,minLat,maxLon,maxLat sent to backend."
      : upper === "BQL"
        ? "Example: get(close, volume) for(['AAPL','MSFT']) by(date). Range controls the time window."
      : upper === "DAPI"
        ? "Filter actual sidecar endpoints by path or purpose, e.g. quote, order, portfolio."
      : upper === "FLDS"
        ? "Search field names, descriptions, or categories such as price, valuation, duration."
      : upper === "ISIN"
        ? "Ticker, ISIN, CUSIP, SEDOL, or FIGI. Use the ID Type control for lookup mode."
      : upper === "FTS"
        ? "SEC filing text query. Symbol context is added automatically, e.g. risk factors."
      : upper === "FRH"
        ? "Comma-separated perpetual symbols; default is the top crypto USDT watchlist."
      : upper === "BLAK"
        ? "Comma-separated symbols for Black-Litterman weights and views."
      : upper === "BMTX"
        ? "Comma-separated symbols tested across the selected strategy set."
      : upper === "CORR"
        ? "Comma-separated symbols for Pearson/Spearman/downside correlation."
      : upper === "PORT_OPT"
        ? "Comma-separated symbols for optimizer weights and efficient frontier."
      : upper === "RPAR"
        ? "Comma-separated symbols for equal-risk-contribution weights."
      : upper === "MARS"
        ? "Comma-separated symbols used to build the multi-asset portfolio return series."
      : upper === "MOSS"
        ? "Comma-separated symbols ranked by realized volatility."
      : upper === "TLDR" || upper === "READ"
        ? "Comma-separated symbols for the watchlist, e.g. AAPL, MSFT, BTCUSDT."
      : undefined;
  return {
    limitParam,
    rangeParam,
    queryParam,
    queryLabel,
    queryHint,
    tradeTicket,
    transcriptText,
    limit: Boolean(limitParam),
    days: Boolean(rangeParam),
  };
}

export function buildControlParams(
  profile: ControlProfile,
  limit: RowLimit,
  range: StubRangeId,
  queryText: string,
): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (profile.limitParam) params[profile.limitParam] = limit;
  if (profile.rangeParam) {
    const days = STUB_RANGES.find((r) => r.id === range)?.days ?? 365;
    params[profile.rangeParam] =
      profile.rangeParam === "weeks" ? Math.max(4, Math.round(days / 7)) : days;
  }
  if (profile.queryParam && queryText.trim()) {
    params[profile.queryParam] = profile.queryParam === "symbols" ||
      profile.queryParam === "watchlist" ||
      profile.queryParam === "universe"
      ? queryText.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean)
      : queryText.trim();
  }
  return params;
}

export function buildOptionDefaultsForFunction(code: string): Record<string, unknown> {
  switch (code.toUpperCase()) {
    case "OVME":
      return {
        spot: 100,
        strike: 105,
        years_to_expiry: 0.25,
        vol: 0.28,
        rate: 0.045,
        type: "CALL",
      };
    case "OSA":
      return {
        spot: 100,
        strike: 100,
        short_strike: 110,
        years_to_expiry: 0.25,
        vol: 0.25,
        rate: 0.045,
        strategy: "CALL_SPREAD",
        legs: [
          { qty: 1, strike: 100, type: "CALL", expiry: 0.25, vol: 0.25 },
          { qty: -1, strike: 110, type: "CALL", expiry: 0.25, vol: 0.25 },
        ],
      };
    default:
      return {};
  }
}

export function buildOptionControlParams(
  code: string,
  spotText: string,
  strikeText: string,
  shortStrikeText: string,
  expiryText: string,
  volText: string,
  rateText: string,
  optionType: OptionType,
  strategy: OptionStrategy,
): Record<string, unknown> {
  const upper = code.toUpperCase();
  if (upper !== "OVME" && upper !== "OSA") return {};
  const spot = numericInput(spotText, 100);
  const strike = numericInput(strikeText, upper === "OSA" ? 100 : 105);
  const shortStrike = numericInput(shortStrikeText, 110);
  const years = numericInput(expiryText, 0.25);
  const vol = numericInput(volText, upper === "OSA" ? 0.25 : 0.28);
  const rate = numericInput(rateText, 0.045);
  if (upper === "OVME") {
    return {
      spot,
      strike,
      years_to_expiry: years,
      vol,
      rate,
      type: optionType,
    };
  }
  const legs =
    strategy === "STRADDLE"
      ? [
          { qty: 1, strike, type: "CALL", expiry: years, vol },
          { qty: 1, strike, type: "PUT", expiry: years, vol },
        ]
      : strategy === "LONG_CALL"
        ? [{ qty: 1, strike, type: "CALL", expiry: years, vol }]
        : [
            { qty: 1, strike, type: "CALL", expiry: years, vol },
            { qty: -1, strike: shortStrike, type: "CALL", expiry: years, vol },
          ];
  return {
    spot,
    strike,
    short_strike: shortStrike,
    years_to_expiry: years,
    vol,
    rate,
    strategy,
    legs,
  };
}

export function buildBacktestControlParams(code: string, strategy: BacktestStrategy): Record<string, unknown> {
  const upper = code.toUpperCase();
  if (upper !== "BTFW" && upper !== "BMTX" && upper !== "BTUNE") return {};
  const allStrategies = ["sma_crossover", "rsi_meanrev", "buy_and_hold"];
  if (upper === "BMTX") {
    return {
      strategies: strategy === "ALL" ? allStrategies : [strategy],
    };
  }
  return {
    strategy: strategy === "ALL" ? "sma_crossover" : strategy,
  };
}

export function defaultBacktestStrategyForFunction(code: string): BacktestStrategy {
  return code.toUpperCase() === "BMTX" ? "ALL" : "sma_crossover";
}

export function defaultQueryForFunction(code: string, category?: string): string {
  switch (code.toUpperCase()) {
    case "BQL":
      return "get(close, volume) for(['AAPL','MSFT']) by(date)";
    case "DAPI":
      return "quote";
    case "FLDS":
      return "price";
    case "ISIN":
      return "AAPL";
    case "FTS":
      return "risk factors";
    case "NSE":
      return "bitcoin";
    case "BLAK":
      return "AAPL, MSFT, NVDA";
    case "BMTX":
      return "SPY, QQQ, IWM, AAPL, MSFT, TSLA, NVDA, AMZN";
    case "CORR":
      return "AAPL, SPX, EURUSD, BTCUSDT, GC=F, US10Y, CDXIG";
    case "PORT_OPT":
      return "SPY, QQQ, IWM, TLT, GLD, EFA, EEM, VNQ, DBC";
    case "RPAR":
      return "AAPL, MSFT, BTCUSDT, EURUSD, GC=F";
    case "READ":
      return "AAPL, MSFT, BTCUSDT";
    case "TOP":
    case "BRIEF":
      return "bitcoin market";
    case "NI":
      return "crypto markets";
    case "TLDR":
      return "AAPL, MSFT, BTCUSDT";
    case "FRH":
      return "BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, TRXUSDT, DOTUSDT, MATICUSDT, ARBUSDT, OPUSDT, INJUSDT, TIAUSDT, SUIUSDT, APTUSDT, NEARUSDT, FILUSDT, ATOMUSDT, LTCUSDT, ETCUSDT, BCHUSDT, UNIUSDT";
    case "MOSS":
      return "AAPL, TSLA, NVDA, META, AMZN, MSFT, GOOGL, BTCUSDT, ETHUSDT, SOLUSDT";
    case "MARS":
      return "AAPL, MSFT, BTCUSDT, EURUSD, GC=F";
    case "TSAR":
      return "revenue guidance";
    case "TRQA":
      return "What changed in guidance?";
    case "SAT":
      return "-122.55,37.70,-122.30,37.85";
    case "ICX":
      return "SPX";
    case "SECF":
      return "technology";
    case "SRCH":
      return "yield >= 4 AND duration <= 10";
    case "FSRC":
      return "expenseRatio < 0.01 AND aum_usd > 10000000000";
    case "CSRC":
      return 'sector = "Energy"';
    case "MEET":
    case "PEOP":
      return "Apple management";
    case "POLY":
      return "crypto";
    default:
      return category?.toLowerCase() === "news" ? "market news" : "";
  }
}

export function defaultRuntimeParams(code: string): Record<string, unknown> {
  switch (code.toUpperCase()) {
    case "NALRT":
      return { live: true, health: true, threshold: 70, news_timeout: 6 };
    case "BETA":
      return { benchmark: "^GSPC", live: true, yfinance_timeout: 4 };
    case "CORR":
      return {
        live: true,
        days: 365,
        return_method: "log",
        frequency: "daily",
        missing_data_policy: "pairwise",
        impactor: true,
      };
    case "GEX":
      return { live: true, live_options: true, max_expiries: 2, yfinance_timeout: 4 };
    case "HVT":
      return { live: true, live_vol: true, days: 365, yfinance_timeout: 5 };
    case "IVOL":
      return { live: true, live_options: true, max_expiries: 3, yfinance_timeout: 5 };
    case "OMON":
      return { live: true, live_options: true, yfinance_timeout: 5 };
    case "SAT":
      return { live: true, width: 512, height: 512, timeout: 8 };
    default:
      return { live: true, timeout: 4, yfinance_timeout: 4, quote_timeout: 4, news_timeout: 4 };
  }
}

export function functionTimeoutMs(code: string, category?: string): number {
  const upper = code.toUpperCase();
  if (upper === "NALRT" || upper === "CN" || upper === "NI" || upper === "NSE" || upper === "TOP") {
    return 18_000;
  }
  if (category?.toLowerCase() === "news") return 18_000;
  return 35_000;
}

export function paramsPlaceholder(code: string): string {
  switch (code.toUpperCase()) {
    case "BQL":
      return "{\"query\":\"get(close, volume) for(['AAPL','MSFT']) by(date)\",\"days\":90,\"live\":true}";
    case "DAPI":
      return '{"query":"portfolio"}';
    case "FLDS":
      return '{"query":"valuation","limit":25}';
    case "ISIN":
      return '{"query":"AAPL","id_type":"TICKER","limit":20}';
    case "BETA":
      return '{"benchmark":"^GSPC","windows":["1Y","2Y","5Y"]}';
    case "BLAK":
    case "RPAR":
    case "PORT_OPT":
      return '{"symbols":["AAPL","MSFT","NVDA"]}';
    case "DPF":
      return '{"weeks":12}';
    case "EQS":
      return '{"universe":"sp500","limit":25}';
    case "NSE":
      return '{"query":"BTCUSDT","limit":25}';
    case "NEWS":
    case "TOP":
      return '{"query":"AAPL","limit":10}';
    case "OVME":
      return '{"spot":100,"strike":105,"years_to_expiry":0.25,"vol":0.28,"rate":0.045,"type":"CALL"}';
    case "OSA":
      return '{"spot":100,"legs":[{"qty":1,"strike":100,"type":"CALL","expiry":0.25,"vol":0.25}]}';
    default:
      return "{}";
  }
}
