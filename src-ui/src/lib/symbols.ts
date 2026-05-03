/**
 * Recent symbols + last-symbol persistence (localStorage).
 *
 * Used by the SymbolBar to suggest recently-viewed tickers across pane
 * switches. Stored under `showme.recent-symbols` as a JSON array of {sym, ts}.
 */
const KEY = "showme.recent-symbols";
const MAX = 12;
export const FALLBACK_SYMBOL = "AAPL";
const ASSET_FALLBACKS: Record<string, string> = {
  CRYPTO: "BTCUSDT",
  EQUITY: "AAPL",
  ETF: "SPY",
  FX: "EURUSD",
  COMMODITY: "GC=F",
  INDEX: "^GSPC",
  BOND: "US10Y",
};
const SYMBOL_ALIASES: Record<string, string> = {
  APPL: "AAPL",
};

interface Entry {
  sym: string;
  ts: number;
}

function load(): Entry[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((e) => typeof e?.sym === "string").slice(0, MAX)
      : [];
  } catch {
    return [];
  }
}

function save(entries: Entry[]): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(KEY, JSON.stringify(entries.slice(0, MAX)));
}

export function listRecentSymbols(): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const entry of load()) {
    const sym = normalizeSymbolInput(entry.sym);
    if (!sym || seen.has(sym)) continue;
    out.push(sym);
    seen.add(sym);
  }
  return out;
}

export function defaultSymbol(): string {
  return listRecentSymbols()[0] ?? FALLBACK_SYMBOL;
}

export function defaultSymbolForFunction(
  codeOrCategory?: string,
  assetClasses: string[] = [],
): string {
  const supported = normalizeAssetClasses(assetClasses);
  const fallbackClass = preferredAssetClass(codeOrCategory, supported);
  const recent = listRecentSymbols().find((sym) =>
    isClassCompatible(inferAssetClassName(sym), supported.length ? supported : [fallbackClass]),
  );
  if (recent) return recent;
  return ASSET_FALLBACKS[fallbackClass] ?? FALLBACK_SYMBOL;
}

export function quickSymbolsForFunction(
  codeOrCategory?: string,
  assetClasses: string[] = [],
): string[] {
  const supported = normalizeAssetClasses(assetClasses);
  const classes = supported.length ? supported : [preferredAssetClass(codeOrCategory, [])];
  const symbols: string[] = [];
  for (const cls of classes) {
    switch (cls) {
      case "CRYPTO":
        symbols.push("BTCUSDT", "ETHUSDT", "SOLUSDT");
        break;
      case "FX":
        symbols.push("EURUSD", "GBPUSD=X", "USDJPY=X");
        break;
      case "COMMODITY":
        symbols.push("GC=F", "CL=F", "NG=F");
        break;
      case "INDEX":
        symbols.push("^GSPC", "^IXIC");
        break;
      case "ETF":
        symbols.push("SPY", "QQQ");
        break;
      case "BOND":
        symbols.push("US10Y");
        break;
      default:
        symbols.push("AAPL", "NVDA", "MSFT");
    }
  }
  const recent = listRecentSymbols().filter((sym) => {
    const inferred = inferAssetClassName(sym);
    return isClassCompatible(inferred, supported.length ? supported : classes);
  });
  return uniqueSymbols([...recent, ...symbols]).slice(0, 6);
}

export function inferAssetClassName(symbol: string | undefined | null): string {
  const value = normalizeSymbolInput(symbol);
  if (!value) return "EQUITY";
  const compact = value.replace(/[-/]/g, "").replace(/=X$/, "");
  if (value.startsWith("^")) return "INDEX";
  if (["GC=F", "CL=F", "NG=F", "SI=F", "XAUUSD", "XAGUSD"].includes(value)) {
    return "COMMODITY";
  }
  if (/^[A-Z]{6}$/.test(compact)) {
    const ccy = new Set(["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]);
    if (ccy.has(compact.slice(0, 3)) && ccy.has(compact.slice(3, 6))) return "FX";
  }
  const cryptoBases = new Set(["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK"]);
  for (const quote of ["USDT", "USDC", "USD", "BTC", "ETH", "EUR"]) {
    const base = compact.endsWith(quote) ? compact.slice(0, -quote.length) : "";
    if (base && cryptoBases.has(base)) return "CRYPTO";
  }
  if (["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD"].includes(value)) return "ETF";
  if (/^US\d+Y$/.test(value)) return "BOND";
  return "EQUITY";
}

export function assetClassForFunctionSymbol(
  symbol: string,
  assetClasses: string[] = [],
): string | undefined {
  const supported = normalizeAssetClasses(assetClasses);
  const inferred = inferAssetClassName(symbol);
  if (!supported.length) return inferred;
  if (supported.includes(inferred)) return inferred;
  if (inferred === "ETF" && supported.includes("EQUITY")) return "EQUITY";
  if (inferred === "EQUITY" && supported.includes("ETF")) return "ETF";
  return supported[0];
}

export function normalizeSymbolInput(symbol: string | undefined | null): string {
  const sym = String(symbol ?? "").trim().toUpperCase();
  if (!sym) return "";
  return SYMBOL_ALIASES[sym] ?? sym;
}

export function pushRecentSymbol(symbol: string): void {
  const sym = normalizeSymbolInput(symbol);
  if (!sym) return;
  const now = Date.now();
  const filtered = load().filter((e) => normalizeSymbolInput(e.sym) !== sym);
  save([{ sym, ts: now }, ...filtered]);
}

export function removeRecentSymbol(symbol: string): void {
  const sym = normalizeSymbolInput(symbol);
  if (!sym) return;
  save(load().filter((e) => normalizeSymbolInput(e.sym) !== sym));
}

export function clearRecentSymbols(): void {
  if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
}

function preferredAssetClass(codeOrCategory: string | undefined, supported: string[]): string {
  const key = String(codeOrCategory ?? "").toUpperCase();
  if (supported.includes("CRYPTO")) return "CRYPTO";
  if (supported.includes("EQUITY")) return "EQUITY";
  if (supported.includes("ETF")) return "ETF";
  if (supported.includes("FX")) return "FX";
  if (supported.includes("COMMODITY")) return "COMMODITY";
  if (supported.includes("INDEX")) return "INDEX";
  if (supported.includes("BOND")) return "BOND";
  if (key === "FX" || key.includes("FX")) return "FX";
  if (key === "COMMODITY") return "COMMODITY";
  if (key === "NEWS" || ["CN", "NI", "NALRT", "NSE"].includes(key)) return "CRYPTO";
  return "EQUITY";
}

function normalizeAssetClasses(assetClasses: string[]): string[] {
  return uniqueSymbols(assetClasses.map((item) => String(item).trim().toUpperCase()).filter(Boolean));
}

function isClassCompatible(inferred: string, supported: string[]): boolean {
  if (supported.includes(inferred)) return true;
  if (inferred === "ETF" && supported.includes("EQUITY")) return true;
  if (inferred === "EQUITY" && supported.includes("ETF")) return true;
  return false;
}

function uniqueSymbols(values: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of values) {
    const value = normalizeSymbolInput(raw);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}
