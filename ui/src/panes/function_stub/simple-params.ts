import type { SimpleParamSpec } from "./_types";

export function numericInput(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function truthyInput(value: string): boolean {
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

export function splitCsv(text: string): string[] {
  return text.split(",").map((item) => item.trim()).filter(Boolean);
}

export function parseTargetWeights(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const token of text.split(",")) {
    const [rawSymbol, rawWeight] = token.split(":");
    const symbol = rawSymbol?.trim().toUpperCase();
    const weight = Number(rawWeight);
    if (symbol && Number.isFinite(weight)) out[symbol] = weight;
  }
  return Object.keys(out).length ? out : { AAPL: 0.5, MSFT: 0.3, GOOGL: 0.2 };
}

export function simpleParamSpecsForFunction(code: string): SimpleParamSpec[] {
  switch (code.toUpperCase()) {
    case "ALLQ":
      return [
        { key: "symbol", label: "Bond", hint: "US10Y" },
        { key: "mid", label: "Mid", hint: "99.75" },
        { key: "spread", label: "Spread", hint: "0.18" },
        { key: "size", label: "Size", hint: "1000000" },
      ];
    case "CHGS":
    case "TECH":
      return [
        { key: "interval", label: "Interval", hint: "1m/5m/15m/1h/4h/1d" },
        { key: "bars", label: "Bars", hint: "1000/3000/10000" },
        { key: "rsi_period", label: "RSI", hint: "14" },
        { key: "sma_fast", label: "SMA fast", hint: "20" },
        { key: "sma_slow", label: "SMA slow", hint: "50" },
        { key: "ema_period", label: "EMA", hint: "20" },
        { key: "bb_period", label: "BB period", hint: "20" },
        { key: "bb_std", label: "BB stdev", hint: "2" },
      ];
    case "BGAS":
    case "NGAS":
      return [{ key: "contract", label: "Contract", hint: "NG=F" }];
    case "BETA":
      return [
        { key: "benchmark", label: "Benchmark", hint: "SPY" },
        { key: "windows", label: "Windows", hint: "1Y,2Y,5Y" },
        { key: "rolling_window", label: "Rolling", hint: "60" },
      ];
    case "DCF":
      return [
        { key: "years", label: "Years", hint: "5" },
        { key: "growth_high", label: "Growth", hint: "0.08" },
        { key: "growth_terminal", label: "Terminal g", hint: "0.025" },
        { key: "wacc", label: "WACC", hint: "0.09" },
        { key: "fcfe", label: "FCFE", hint: "100000000000" },
        { key: "shares_outstanding", label: "Shares", hint: "15000000000" },
      ];
    case "DCFS":
      return [
        { key: "years", label: "Years", hint: "5" },
        { key: "growth_high", label: "Growth", hint: "0.08" },
        { key: "wacc", label: "Base WACC", hint: "0.09" },
        { key: "fcfe", label: "FCFE", hint: "100000000000" },
        { key: "shares_outstanding", label: "Shares", hint: "15000000000" },
      ];
    case "DDM":
      return [
        { key: "dividend_ttm", label: "DPS TTM", hint: "1.04" },
        { key: "growth_rate", label: "Growth", hint: "0.03" },
        { key: "required_return", label: "Req return", hint: "0.08" },
      ];
    case "WACC":
      return [
        { key: "erp", label: "ERP", hint: "0.05" },
        { key: "tax_rate", label: "Tax", hint: "0.21" },
        { key: "rf", label: "Risk-free", hint: "0.04" },
        { key: "rd", label: "Debt cost", hint: "0.05" },
        { key: "beta", label: "Beta", hint: "1.1" },
      ];
    case "EE":
      return [{ key: "history", label: "Periods", hint: "8" }];
    case "FTS":
      return [
        { key: "forms", label: "Forms", hint: "10-K,10-Q" },
        { key: "start", label: "From", hint: "2025-01-01" },
        { key: "end", label: "To", hint: "2026-05-03" },
      ];
    case "FRD":
      return [
        { key: "spot", label: "Spot", hint: "blank = live" },
        { key: "r_base", label: "Base rate", hint: "0.035" },
        { key: "r_quote", label: "Quote rate", hint: "0.045" },
        { key: "tenors", label: "Tenors", hint: "1W,1M,3M,6M,1Y" },
      ];
    case "FXFC":
      return [
        { key: "spot", label: "Spot", hint: "blank = live" },
        { key: "r_base", label: "Base rate", hint: "0.035" },
        { key: "r_quote", label: "Quote rate", hint: "0.045" },
        { key: "vol_annualized", label: "Ann vol", hint: "0.085" },
        { key: "tenors", label: "Tenors", hint: "1M,3M,6M,12M" },
      ];
    case "FXH":
      return [
        { key: "currency", label: "Exposure ccy", hint: "EUR" },
        { key: "home_currency", label: "Home ccy", hint: "USD" },
        { key: "notional", label: "Notional", hint: "1000000" },
        { key: "hedge_ratio", label: "Hedge", hint: "0.75" },
        { key: "days", label: "Days", hint: "90" },
        { key: "usd_shock_pct", label: "Shock", hint: "0.05" },
      ];
    case "FXIP":
      return [
        { key: "spot", label: "Spot", hint: "blank = live" },
        { key: "r_base", label: "Base rate", hint: "0.035" },
        { key: "r_quote", label: "Quote rate", hint: "0.045" },
        { key: "atm_vol", label: "ATM vol", hint: "0.0845" },
      ];
    case "OVDV":
      return [
        { key: "atm_vol", label: "ATM vol", hint: "0.085" },
        { key: "rr_25d", label: "25D RR", hint: "0.002" },
        { key: "bf_25d", label: "25D BF", hint: "0.0015" },
        { key: "tenors", label: "Tenors", hint: "1W,1M,3M,6M,1Y" },
      ];
    case "COUN":
      return [{ key: "country", label: "Country", hint: "US/EU/GB/TR" }];
    case "ECFC":
      return [
        { key: "country", label: "Country", hint: "USA" },
        { key: "indicators", label: "Indicators", hint: "NGDP_RPCH,PCPIPCH,LUR" },
      ];
    case "ECST":
      return [
        { key: "series_id", label: "Series", hint: "CPIAUCSL/GDPC1/UNRATE/DGS10" },
        { key: "compare_with", label: "Compare with", hint: "e.g. DGS2, PCE" },
        { key: "frequency", label: "Frequency", hint: "native/daily/weekly/monthly/quarterly/annual" },
        { key: "date_range", label: "Date Range", hint: "1Y/3Y/5Y/10Y/20Y/MAX" },
        { key: "vintage", label: "Vintage", hint: "latest or YYYY-MM-DD" },
      ];
    case "GMM":
      return [
        { key: "country", label: "Country", hint: "blank = global" },
        { key: "importance", label: "Importance", hint: "all/high/medium" },
      ];
    case "REGM":
      return [
        { key: "action", label: "Mode", hint: "current/history" },
        { key: "days", label: "Days", hint: "1095" },
        { key: "window", label: "Window", hint: "60" },
      ];
    case "TRDH":
      return [{ key: "exchanges", label: "Exchanges", hint: "NYSE,NASDAQ,LSE,TYO" }];
    case "WIRP":
      return [
        { key: "central_bank", label: "Central bank", hint: "FED/ECB/BOE" },
        { key: "meetings", label: "Meetings", hint: "4" },
      ];
    case "BIO":
      return [{ key: "reason", label: "Reason", hint: "ShowMe biometric verification" }];
    case "BMC":
      return [{ key: "module", label: "Module", hint: "Equities / Fixed Income / FX / Macro" }];
    case "CDE":
      return [
        { key: "action", label: "Action", hint: "list/add/remove/evaluate" },
        { key: "name", label: "Name", hint: "large_cap_tech" },
        { key: "formula", label: "Formula", hint: 'sector = "Technology" AND marketCap > 50000000000' },
        { key: "row_json", label: "Row JSON", hint: '{"sector":"Technology","marketCap":100000000000}' },
      ];
    case "DINE":
      return [
        { key: "location", label: "Location", hint: "New York / Istanbul / London" },
        { key: "query", label: "Search", hint: "restaurant, sushi, coffee" },
      ];
    case "FLY":
      return [
        { key: "callsign", label: "Callsign", hint: "THY / UAL / blank = any" },
        { key: "country", label: "Country", hint: "Turkey / United States / blank = any" },
      ];
    case "GRAB":
      return [
        { key: "url", label: "Target", hint: "current_pane or URL" },
        { key: "recipient", label: "Recipient", hint: "draft only; sending requires confirmation" },
      ];
    case "LANG":
      return [{ key: "lang", label: "Language", hint: "tr/en/de/fr/es/it/pt/ru/zh/ja/ko/ar" }];
    case "ONCH":
      return [
        { key: "symbol", label: "Asset", hint: "BTCUSDT/ETHUSDT" },
        { key: "chain", label: "Chain", hint: "BTC/ETH" },
      ];
    case "POLY":
      return [{ key: "include_closed", label: "Closed", hint: "false/true" }];
    case "WHAL":
      return [
        { key: "symbol", label: "Symbol", hint: "BTCUSDT / AAPL / EURUSD / GC=F" },
        { key: "market", label: "Market", hint: "CRYPTO/EQUITY/ETF/FX/COMMODITY/INDEX" },
        { key: "chain", label: "Chain", hint: "BTC/ETH/SOL/BNB" },
        { key: "threshold_usd", label: "Threshold USD", hint: "1000000" },
        { key: "lookback_hours", label: "Lookback h", hint: "24" },
        { key: "interval", label: "Interval", hint: "1m/5m/15m/1d" },
      ];
    case "HFS":
      return [
        { key: "issuer", label: "Issuer", hint: "AAPL" },
        { key: "cusip", label: "CUSIP", hint: "037833100" },
        { key: "quarter", label: "Quarter", hint: "latest" },
        { key: "top_n", label: "Top", hint: "30" },
      ];
    case "RV":
      return [{ key: "peers", label: "Peers", hint: "MSFT, GOOGL, NVDA, META" }];
    case "BOIL":
      return [{ key: "benchmark", label: "Benchmark", hint: "WTI/BRENT" }];
    case "CPF":
      return [
        { key: "commodities", label: "Commodities", hint: "oil, gas, gold, copper" },
        { key: "scenario", label: "Scenario", hint: "baseline/upside/downside" },
        { key: "horizon_years", label: "Horizon", hint: "4" },
      ];
    case "WETR":
      return [
        { key: "days", label: "Days", hint: "7" },
        { key: "location", label: "Location", hint: "US_NORTHEAST" },
        { key: "commodity", label: "Commodity", hint: "natural gas and power demand" },
        { key: "lat", label: "Lat", hint: "41.01" },
        { key: "lon", label: "Lon", hint: "-74.0" },
      ];
    case "CRPR":
      return [{ key: "issuer", label: "Issuer", hint: "US Treasury" }];
    case "CRVF":
    case "GC3D":
      return [{ key: "country", label: "Country", hint: "US" }];
    case "DDIS":
      return [{ key: "issuer", label: "Issuer", hint: "AAPL" }];
    case "DEBT":
      return [{ key: "countries", label: "Countries", hint: "US, JP, DE, TR" }];
    case "SRSK":
      return [
        { key: "countries", label: "Countries", hint: "TR, US, DE, JP" },
        { key: "recovery", label: "Recovery", hint: "0.4" },
        { key: "proxy_spread_pct", label: "Fallback spread", hint: "3.25" },
      ];
    case "TAUC":
      return [
        { key: "action", label: "Action", hint: "upcoming/recent" },
        { key: "security_type", label: "Type", hint: "Bill/Note/Bond" },
      ];
    case "WB":
      return [{ key: "countries", label: "Countries", hint: "US, DE, JP, GB, FR, IT, ES, AU" }];
    case "YAS":
      return [
        { key: "price", label: "Price", hint: "99.5" },
        { key: "coupon", label: "Coupon", hint: "4.25 or 0.0425" },
        { key: "maturity_years", label: "Years", hint: "10" },
        { key: "freq", label: "Freq", hint: "2" },
        { key: "benchmark_rate", label: "Benchmark", hint: "4.45 or 0.0445" },
      ];
    case "ISIN":
      return [{ key: "id_type", label: "ID Type", hint: "AUTO/TICKER/ID_ISIN/ID_CUSIP/ID_SEDOL" }];
    case "PCAS":
      return [
        { key: "pc_index", label: "PC", hint: "0" },
        { key: "k_sigma", label: "K sigma", hint: "3" },
        { key: "top_n", label: "Top", hint: "8" },
      ];
    case "PVAR":
      return [
        { key: "confidence", label: "Confidence", hint: "0.95" },
        { key: "max_positions", label: "Positions", hint: "12" },
      ];
    case "PSC":
      return [
        { key: "account", label: "Account $", hint: "10000" },
        { key: "risk_pct", label: "Risk %", hint: "0.01" },
        { key: "entry", label: "Entry", hint: "100" },
        { key: "stop", label: "Stop", hint: "95" },
        { key: "target", label: "Target", hint: "115" },
        { key: "win_rate", label: "Win rate", hint: "0.55" },
      ];
    case "PORT_WHATIF":
      return [
        { key: "quantity", label: "Qty", hint: "1" },
        { key: "cost", label: "Cost", hint: "100" },
      ];
    case "REBA":
      return [
        { key: "targets", label: "Targets", hint: "AAPL:0.5, MSFT:0.3, GOOGL:0.2" },
        { key: "min_drift_pct", label: "Min drift", hint: "0.005" },
      ];
    case "STRS":
      return [
        { key: "scenarios", label: "Scenarios", hint: "GFC_2008, COVID_2020, RATE_SHOCK_300BP" },
        { key: "scale", label: "Scale", hint: "1" },
      ];
    case "TLH":
      return [
        { key: "tax_bracket", label: "Tax rate", hint: "0.24" },
        { key: "lt_cap_rate", label: "LT rate", hint: "0.15" },
        { key: "max_positions", label: "Positions", hint: "10" },
      ];
    case "LOTS":
      return [
        { key: "action", label: "Action", hint: "list/open/sell/summary" },
        { key: "symbol", label: "Symbol", hint: "AAPL" },
        { key: "quantity", label: "Qty", hint: "1" },
        { key: "price", label: "Price", hint: "100" },
        { key: "method", label: "Method", hint: "FIFO" },
      ];
    case "MGN":
      return [
        { key: "cash", label: "Cash", hint: "10000" },
        { key: "margin_type", label: "Margin", hint: "reg_t" },
      ];
    default:
      return [];
  }
}

export function defaultSimpleParamsForFunction(code: string): Record<string, string> {
  const defaults: Record<string, Record<string, string>> = {
    ALLQ: { symbol: "US10Y", mid: "99.75", spread: "0.18", size: "1000000" },
    CHGS: { rsi_period: "14", sma_fast: "20", sma_slow: "50", ema_period: "20", bb_period: "20", bb_std: "2" },
    BGAS: { contract: "NG=F" },
    NGAS: { contract: "NG=F" },
    BETA: { benchmark: "SPY", windows: "1Y,2Y,5Y", rolling_window: "60" },
    DCF: { years: "5", growth_high: "0.08", growth_terminal: "0.025", wacc: "0.09", fcfe: "", shares_outstanding: "" },
    DCFS: { years: "5", growth_high: "0.08", wacc: "0.09", fcfe: "100000000000", shares_outstanding: "15000000000" },
    DDM: { dividend_ttm: "", growth_rate: "0.03", required_return: "0.08" },
    WACC: { erp: "0.05", tax_rate: "0.21", rf: "", rd: "", beta: "" },
    EE: { history: "8" },
    FTS: { forms: "10-K,10-Q", start: "", end: "" },
    FRD: { spot: "", r_base: "0.035", r_quote: "0.045", tenors: "1W,1M,3M,6M,1Y" },
    FXFC: { spot: "", r_base: "0.035", r_quote: "0.045", vol_annualized: "0.085", tenors: "1M,3M,6M,12M" },
    FXH: { currency: "EUR", home_currency: "USD", notional: "1000000", hedge_ratio: "0.75", days: "90", usd_shock_pct: "0.05" },
    FXIP: { spot: "", r_base: "0.035", r_quote: "0.045", atm_vol: "0.0845" },
    OVDV: { atm_vol: "0.085", rr_25d: "0.002", bf_25d: "0.0015", tenors: "1W,1M,3M,6M,1Y" },
    COUN: { country: "US" },
    ECFC: { country: "USA", indicators: "NGDP_RPCH,PCPIPCH,LUR,GGXCNL_NGDP,GGXWDG_NGDP" },
    ECST: { series_id: "CPIAUCSL", compare_with: "", frequency: "", date_range: "10Y", vintage: "latest" },
    GMM: { country: "", importance: "all" },
    REGM: { action: "current", days: "1095", window: "60" },
    TRDH: { exchanges: "NYSE,NASDAQ,LSE,FWB,TYO,HKEX,ASX,BIST,BINANCE,DERIBIT" },
    WIRP: { central_bank: "FED", meetings: "4" },
    BIO: { reason: "ShowMe biometric verification" },
    BMC: { module: "" },
    CDE: {
      action: "list",
      name: "large_cap_tech",
      formula: 'sector = "Technology" AND marketCap > 50000000000',
      row_json: '{"sector":"Technology","marketCap":100000000000,"pe":21,"beta":1.1}',
    },
    DINE: { location: "New York", query: "restaurant" },
    FLY: { callsign: "", country: "" },
    GRAB: { url: "current_pane", recipient: "" },
    LANG: { lang: "tr" },
    ONCH: { symbol: "BTCUSDT", chain: "BTC" },
    POLY: { include_closed: "false" },
    WHAL: { symbol: "BTCUSDT", market: "CRYPTO", chain: "BTC", threshold_usd: "1000000", lookback_hours: "24", interval: "1m" },
    HFS: { issuer: "AAPL", cusip: "", quarter: "", top_n: "30" },
    RV: { peers: "MSFT, GOOGL, NVDA, META, AMZN, TSLA" },
    BOIL: { benchmark: "WTI/BRENT" },
    CPF: { commodities: "oil, gas, gold, copper", scenario: "baseline", horizon_years: "4" },
    WETR: { days: "7", location: "US_NORTHEAST", commodity: "natural gas and power demand", lat: "41.01", lon: "-74.0" },
    CRPR: { issuer: "US Treasury" },
    CRVF: { country: "US" },
    GC3D: { country: "US" },
    DDIS: { issuer: "AAPL" },
    DEBT: { countries: "US, JP, DE, TR" },
    SRSK: { countries: "TR, US, DE, JP", recovery: "0.4", proxy_spread_pct: "3.25" },
    TAUC: { action: "upcoming", security_type: "" },
    WB: { countries: "US, DE, JP, GB, FR, IT, ES, AU" },
    YAS: { price: "99.5", coupon: "4.25", maturity_years: "10", freq: "2", benchmark_rate: "4.45" },
    TECH: { interval: "1d", bars: "1000", rsi_period: "14", sma_fast: "20", sma_slow: "50", ema_period: "20", bb_period: "20", bb_std: "2" },
    ISIN: { id_type: "AUTO" },
    PCAS: { pc_index: "0", k_sigma: "3", top_n: "8" },
    PVAR: { confidence: "0.95", max_positions: "12" },
    PSC: { account: "10000", risk_pct: "0.01", entry: "100", stop: "95", target: "115", win_rate: "0.55" },
    PORT_WHATIF: { quantity: "1", cost: "100" },
    REBA: { targets: "AAPL:0.5, MSFT:0.3, GOOGL:0.2", min_drift_pct: "0.005" },
    STRS: { scenarios: "GFC_2008, COVID_2020, RATE_SHOCK_300BP, CRYPTO_WINTER", scale: "1" },
    TLH: { tax_bracket: "0.24", lt_cap_rate: "0.15", max_positions: "10" },
    LOTS: { action: "list", symbol: "AAPL", quantity: "1", price: "100", method: "FIFO" },
    MGN: { cash: "10000", margin_type: "reg_t" },
  };
  return defaults[code.toUpperCase()] ?? {};
}

export function buildSimpleControlParams(code: string, values: Record<string, string>): Record<string, unknown> {
  const upper = code.toUpperCase();
  const numeric = (key: string, fallback: number) => numericInput(values[key] ?? "", fallback);
  if (upper === "ALLQ") {
    return {
      symbol: (values.symbol || "US10Y").trim().toUpperCase(),
      mid: numeric("mid", 99.75),
      spread: numeric("spread", 0.18),
      size: numeric("size", 1_000_000),
    };
  }
  if (upper === "CHGS" || upper === "TECH") {
    return {
      live_chart: true,
      interval: (values.interval || "1d").trim().toLowerCase(),
      bars: Math.max(60, Math.min(5000, Math.round(numeric("bars", 1000)))),
      tail: Math.max(60, Math.min(5000, Math.round(numeric("bars", 1000)))),
      rsi_period: Math.max(2, Math.round(numeric("rsi_period", 14))),
      sma_fast: Math.max(2, Math.round(numeric("sma_fast", 20))),
      sma_slow: Math.max(2, Math.round(numeric("sma_slow", 50))),
      ema_period: Math.max(2, Math.round(numeric("ema_period", 20))),
      bb_period: Math.max(2, Math.round(numeric("bb_period", 20))),
      bb_std: numeric("bb_std", 2),
    };
  }
  if (upper === "BGAS" || upper === "NGAS") {
    return { contract: (values.contract || "NG=F").trim().toUpperCase() };
  }
  if (upper === "BETA") {
    return {
      benchmark: (values.benchmark || "SPY").trim().toUpperCase(),
      windows: splitCsv(values.windows || "1Y,2Y,5Y").map((item) => item.toUpperCase()),
      rolling_window: Math.max(30, Math.round(numeric("rolling_window", 60))),
    };
  }
  if (upper === "DCF") {
    return {
      years: Math.max(1, Math.round(numeric("years", 5))),
      growth_high: numeric("growth_high", 0.08),
      growth_terminal: numeric("growth_terminal", 0.025),
      wacc: numeric("wacc", 0.09),
      ...(values.fcfe?.trim() ? { fcfe: numeric("fcfe", 0) } : {}),
      ...(values.shares_outstanding?.trim() ? { shares_outstanding: numeric("shares_outstanding", 0) } : {}),
    };
  }
  if (upper === "DCFS") {
    return {
      years: Math.max(1, Math.round(numeric("years", 5))),
      growth_high: numeric("growth_high", 0.08),
      wacc: numeric("wacc", 0.09),
      fcfe: numeric("fcfe", 100_000_000_000),
      shares_outstanding: numeric("shares_outstanding", 15_000_000_000),
      live_valuation: true,
    };
  }
  if (upper === "DDM") {
    return {
      ...(values.dividend_ttm?.trim() ? { dividend_ttm: numeric("dividend_ttm", 0) } : {}),
      growth_rate: numeric("growth_rate", 0.03),
      required_return: numeric("required_return", 0.08),
    };
  }
  if (upper === "WACC") {
    return {
      erp: numeric("erp", 0.05),
      tax_rate: numeric("tax_rate", 0.21),
      ...(values.rf?.trim() ? { rf: numeric("rf", 0.04) } : {}),
      ...(values.rd?.trim() ? { rd: numeric("rd", 0.05) } : {}),
      ...(values.beta?.trim() ? { beta: numeric("beta", 1) } : {}),
    };
  }
  if (upper === "EE") {
    return { history: Math.max(1, Math.round(numeric("history", 8))), live_earnings: true };
  }
  if (upper === "FTS") {
    return {
      forms: splitCsv(values.forms || "10-K,10-Q"),
      ...(values.start?.trim() ? { start: values.start.trim() } : {}),
      ...(values.end?.trim() ? { end: values.end.trim() } : {}),
      live_search: true,
    };
  }
  if (upper === "FRD") {
    return {
      ...(values.spot?.trim() ? { spot: numeric("spot", 1.0835) } : {}),
      r_base: numeric("r_base", 0.035),
      r_quote: numeric("r_quote", 0.045),
      tenors: splitCsv(values.tenors || "1W,1M,3M,6M,1Y"),
      live: true,
    };
  }
  if (upper === "FXFC") {
    return {
      ...(values.spot?.trim() ? { spot: numeric("spot", 1.0835) } : {}),
      r_base: numeric("r_base", 0.035),
      r_quote: numeric("r_quote", 0.045),
      vol_annualized: numeric("vol_annualized", 0.085),
      tenors: splitCsv(values.tenors || "1M,3M,6M,12M"),
      live: true,
    };
  }
  if (upper === "FXH") {
    return {
      currency: (values.currency || "EUR").trim().toUpperCase(),
      home_currency: (values.home_currency || "USD").trim().toUpperCase(),
      notional: numeric("notional", 1_000_000),
      hedge_ratio: numeric("hedge_ratio", 0.75),
      days: Math.max(1, Math.round(numeric("days", 90))),
      usd_shock_pct: numeric("usd_shock_pct", 0.05),
      live: true,
    };
  }
  if (upper === "FXIP") {
    return {
      ...(values.spot?.trim() ? { spot: numeric("spot", 1.0835) } : {}),
      r_base: numeric("r_base", 0.035),
      r_quote: numeric("r_quote", 0.045),
      atm_vol: numeric("atm_vol", 0.0845),
      days: 90,
      live: true,
    };
  }
  if (upper === "OVDV") {
    return {
      atm_vol: numeric("atm_vol", 0.085),
      rr_25d: numeric("rr_25d", 0.002),
      bf_25d: numeric("bf_25d", 0.0015),
      tenors: splitCsv(values.tenors || "1W,1M,3M,6M,1Y"),
      live: true,
    };
  }
  if (upper === "COUN") {
    return { country: (values.country || "US").trim().toUpperCase(), live_macro: true };
  }
  if (upper === "ECFC") {
    return {
      country: (values.country || "USA").trim().toUpperCase(),
      indicators: splitCsv(values.indicators || "NGDP_RPCH,PCPIPCH,LUR,GGXCNL_NGDP,GGXWDG_NGDP"),
      live_forecast: true,
    };
  }
  if (upper === "ECST") {
    const frequency = (values.frequency || "").trim();
    return {
      series_id: (values.series_id || "CPIAUCSL").trim().toUpperCase(),
      ...(frequency ? { frequency } : {}),
    };
  }
  if (upper === "GMM") {
    const country = (values.country || "").trim().toUpperCase();
    return {
      ...(country ? { country } : {}),
      importance: (values.importance || "all").trim().toLowerCase(),
      live: true,
    };
  }
  if (upper === "REGM") {
    return {
      action: (values.action || "current").trim().toLowerCase(),
      days: Math.max(120, Math.round(numeric("days", 1095))),
      window: Math.max(20, Math.round(numeric("window", 60))),
      live: true,
    };
  }
  if (upper === "TRDH") {
    return { exchanges: splitCsv(values.exchanges || "NYSE,NASDAQ,LSE,FWB,TYO,HKEX,ASX,BIST,BINANCE,DERIBIT") };
  }
  if (upper === "WIRP") {
    return {
      central_bank: (values.central_bank || "FED").trim().toUpperCase(),
      meetings: Math.max(1, Math.round(numeric("meetings", 4))),
    };
  }
  if (upper === "BIO") {
    return { reason: values.reason || "ShowMe biometric verification" };
  }
  if (upper === "BMC") {
    return { ...(values.module?.trim() ? { module: values.module.trim() } : {}) };
  }
  if (upper === "CDE") {
    return {
      action: (values.action || "list").trim().toLowerCase(),
      ...(values.name?.trim() ? { name: values.name.trim() } : {}),
      ...(values.formula?.trim() ? { formula: values.formula.trim() } : {}),
      ...(values.row_json?.trim() ? { row_json: values.row_json.trim() } : {}),
    };
  }
  if (upper === "DINE") {
    return {
      location: values.location?.trim() || "New York",
      query: values.query?.trim() || "restaurant",
      live: true,
    };
  }
  if (upper === "FLY") {
    return {
      ...(values.callsign?.trim() ? { callsign: values.callsign.trim().toUpperCase() } : {}),
      ...(values.country?.trim() ? { country: values.country.trim() } : {}),
      live_flight: true,
    };
  }
  if (upper === "GRAB") {
    return {
      url: values.url?.trim() || "current_pane",
      ...(values.recipient?.trim() ? { recipient: values.recipient.trim() } : {}),
      send: false,
    };
  }
  if (upper === "LANG") {
    return { lang: (values.lang || "tr").trim().toLowerCase() };
  }
  if (upper === "ONCH") {
    return {
      symbol: (values.symbol || "BTCUSDT").trim().toUpperCase(),
      chain: (values.chain || "BTC").trim().toUpperCase(),
      live_onchain: true,
    };
  }
  if (upper === "POLY") {
    return { include_closed: truthyInput(values.include_closed || "false") };
  }
  if (upper === "WHAL") {
    return {
      symbol: (values.symbol || "BTCUSDT").trim().toUpperCase(),
      market: (values.market || "CRYPTO").trim().toUpperCase(),
      chain: (values.chain || "BTC").trim().toUpperCase(),
      threshold_usd: numeric("threshold_usd", 1_000_000),
      lookback_hours: Math.max(1, Math.round(numeric("lookback_hours", 24))),
      interval: (values.interval || "1m").trim().toLowerCase(),
      live_onchain: true,
    };
  }
  if (upper === "HFS") {
    return {
      issuer: (values.issuer || "AAPL").trim().toUpperCase(),
      ...(values.cusip?.trim() ? { cusip: values.cusip.trim().toUpperCase() } : {}),
      ...(values.quarter?.trim() ? { quarter: values.quarter.trim() } : {}),
      top_n: Math.max(1, Math.round(numeric("top_n", 30))),
      live_holders: true,
    };
  }
  if (upper === "RV") {
    return { peers: splitCsv(values.peers || "").map((item) => item.toUpperCase()) };
  }
  if (upper === "BOIL") {
    return { benchmark: (values.benchmark || "WTI/BRENT").trim().toUpperCase() };
  }
  if (upper === "CPF") {
    return {
      commodities: splitCsv(values.commodities || "oil, gas, gold, copper"),
      scenario: (values.scenario || "baseline").trim().toLowerCase(),
      horizon_years: Math.max(1, Math.round(numeric("horizon_years", 4))),
    };
  }
  if (upper === "WETR") {
    return {
      days: Math.max(3, Math.round(numeric("days", 7))),
      location: (values.location || "US_NORTHEAST").trim().toUpperCase(),
      commodity: (values.commodity || "natural gas and power demand").trim(),
      lat: numeric("lat", 41.01),
      lon: numeric("lon", -74.0),
    };
  }
  if (upper === "CRPR") {
    return { issuer: (values.issuer || "US Treasury").trim() };
  }
  if (upper === "CRVF" || upper === "GC3D") {
    return { country: (values.country || "US").trim().toUpperCase(), live_curve: true };
  }
  if (upper === "DDIS") {
    return { issuer: (values.issuer || "AAPL").trim().toUpperCase() };
  }
  if (upper === "DEBT") {
    return { countries: splitCsv(values.countries || "US, JP, DE, TR").map((item) => item.toUpperCase()) };
  }
  if (upper === "SRSK") {
    return {
      countries: splitCsv(values.countries || "TR, US, DE, JP").map((item) => item.toUpperCase()),
      recovery: numeric("recovery", 0.4),
      proxy_spread_pct: numeric("proxy_spread_pct", 3.25),
    };
  }
  if (upper === "TAUC") {
    const securityType = (values.security_type || "").trim();
    return {
      action: (values.action || "upcoming").trim().toLowerCase(),
      ...(securityType ? { security_type: securityType } : {}),
      live_auctions: true,
    };
  }
  if (upper === "WB") {
    return { countries: splitCsv(values.countries || "US, DE, JP, GB, FR, IT, ES, AU").map((item) => item.toUpperCase()), live_bonds: true };
  }
  if (upper === "YAS") {
    return {
      price: numeric("price", 99.5),
      coupon: numeric("coupon", 4.25),
      maturity_years: numeric("maturity_years", 10),
      freq: Math.max(1, Math.round(numeric("freq", 2))),
      benchmark_rate: numeric("benchmark_rate", 4.45),
      live_benchmark: true,
    };
  }
  if (upper === "ISIN") {
    const idType = (values.id_type || "AUTO").trim().toUpperCase();
    return idType && idType !== "AUTO" ? { id_type: idType } : {};
  }
  if (upper === "PCAS") {
    return { pc_index: Math.max(0, Math.round(numeric("pc_index", 0))), k_sigma: numeric("k_sigma", 3), top_n: Math.max(1, Math.round(numeric("top_n", 8))), include_legacy: true, live_prices: true };
  }
  if (upper === "PVAR") {
    return { confidence: numeric("confidence", 0.95), max_positions: Math.max(1, Math.round(numeric("max_positions", 12))), live_risk: true };
  }
  if (upper === "PSC") {
    return { account: numeric("account", 10000), risk_pct: numeric("risk_pct", 0.01), entry: numeric("entry", 100), stop: numeric("stop", 95), target: numeric("target", 115), win_rate: numeric("win_rate", 0.55) };
  }
  if (upper === "PORT_WHATIF") {
    return { quantity: numeric("quantity", 1), cost: numeric("cost", 100) };
  }
  if (upper === "REBA") {
    return { targets: parseTargetWeights(values.targets ?? ""), min_drift_pct: numeric("min_drift_pct", 0.005), live_portfolio: true, include_legacy: true };
  }
  if (upper === "STRS") {
    return { action: "compare", scenarios: splitCsv(values.scenarios ?? ""), scale: numeric("scale", 1) };
  }
  if (upper === "TLH") {
    return { tax_bracket: numeric("tax_bracket", 0.24), lt_cap_rate: numeric("lt_cap_rate", 0.15), max_positions: Math.max(1, Math.round(numeric("max_positions", 10))), live_tax: true, include_legacy: true };
  }
  if (upper === "LOTS") {
    return {
      action: (values.action || "list").trim().toLowerCase(),
      symbol: (values.symbol || "AAPL").trim().toUpperCase(),
      quantity: numeric("quantity", 1),
      price: numeric("price", 100),
      method: (values.method || "FIFO").trim().toUpperCase(),
    };
  }
  if (upper === "MGN") {
    return { cash: numeric("cash", 10000), margin_type: values.margin_type || "reg_t", include_saved: true, include_legacy: true };
  }
  if (upper === "ECST") {
    const frequency = (values.frequency || "").trim();
    const compare_with = (values.compare_with || "").trim();
    const date_range = (values.date_range || "").trim();
    const vintage = (values.vintage || "").trim();
    return {
      series_id: (values.series_id || "CPIAUCSL").trim().toUpperCase(),
      ...(frequency ? { frequency } : {}),
      ...(compare_with ? { compare_with } : {}),
      ...(date_range ? { date_range } : {}),
      ...(vintage ? { vintage } : {}),
    };
  }
  return {};
}
