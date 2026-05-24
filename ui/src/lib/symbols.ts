/**
 * Recent symbols + last-symbol persistence (localStorage).
 *
 * Used by the SymbolBar to suggest recently-viewed tickers across pane
 * switches. Stored under `showme.recent-symbols` as a JSON array of {sym, ts}.
 */
import { safeReadLocal } from "./safe-storage";

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
const CRYPTO_NAME_ALIASES: Record<string, string> = {
  btc: "BTCUSDT",
  bitcoin: "BTCUSDT",
  eth: "ETHUSDT",
  ether: "ETHUSDT",
  ethereum: "ETHUSDT",
  sol: "SOLUSDT",
  solana: "SOLUSDT",
  bnb: "BNBUSDT",
  binancecoin: "BNBUSDT",
  xrp: "XRPUSDT",
  ripple: "XRPUSDT",
  ada: "ADAUSDT",
  cardano: "ADAUSDT",
  doge: "DOGEUSDT",
  dogecoin: "DOGEUSDT",
  avax: "AVAXUSDT",
  avalanche: "AVAXUSDT",
  dot: "DOTUSDT",
  polkadot: "DOTUSDT",
  link: "LINKUSDT",
  chainlink: "LINKUSDT",
  matic: "MATICUSDT",
  polygon: "MATICUSDT",
  trx: "TRXUSDT",
  tron: "TRXUSDT",
  ltc: "LTCUSDT",
  litecoin: "LTCUSDT",
  bch: "BCHUSDT",
  bitcoincash: "BCHUSDT",
  uni: "UNIUSDT",
  uniswap: "UNIUSDT",
  atom: "ATOMUSDT",
  cosmos: "ATOMUSDT",
  etc: "ETCUSDT",
  ethereumclassic: "ETCUSDT",
  near: "NEARUSDT",
  nearprotocol: "NEARUSDT",
  fil: "FILUSDT",
  filecoin: "FILUSDT",
  icp: "ICPUSDT",
  internetcomputer: "ICPUSDT",
  apt: "APTUSDT",
  aptos: "APTUSDT",
  arb: "ARBUSDT",
  arbitrum: "ARBUSDT",
  op: "OPUSDT",
  optimism: "OPUSDT",
  sui: "SUIUSDT",
  sei: "SEIUSDT",
  tia: "TIAUSDT",
  celestia: "TIAUSDT",
  inj: "INJUSDT",
  injective: "INJUSDT",
  aave: "AAVEUSDT",
  mkr: "MKRUSDT",
  maker: "MKRUSDT",
  ldo: "LDOUSDT",
  lidodao: "LDOUSDT",
  rune: "RUNEUSDT",
  thorchain: "RUNEUSDT",
  ftm: "FTMUSDT",
  fantom: "FTMUSDT",
  fet: "FETUSDT",
  fetchai: "FETUSDT",
  wld: "WLDUSDT",
  worldcoin: "WLDUSDT",
  render: "RENDERUSDT",
  rendernetwork: "RENDERUSDT",
  rndr: "RENDERUSDT",
  ton: "TONUSDT",
  toncoin: "TONUSDT",
  shib: "SHIBUSDT",
  shibainu: "SHIBUSDT",
  pepe: "PEPEUSDT",
  wif: "WIFUSDT",
  dogwifhat: "WIFUSDT",
  floki: "FLOKIUSDT",
  bonk: "BONKUSDT",
  flock: "FLOCKUSDT",
  flockio: "FLOCKUSDT",
  lunc: "LUNCUSDT",
  terraclassic: "LUNCUSDT",
  gala: "GALAUSDT",
  sand: "SANDUSDT",
  sandbox: "SANDUSDT",
  mana: "MANAUSDT",
  decentraland: "MANAUSDT",
  axs: "AXSUSDT",
  axieinfinity: "AXSUSDT",
  chz: "CHZUSDT",
  chiliz: "CHZUSDT",
  enj: "ENJUSDT",
  enjincoin: "ENJUSDT",
  jasmy: "JASMYUSDT",
  jasmycoin: "JASMYUSDT",
  pyth: "PYTHUSDT",
  pythnetwork: "PYTHUSDT",
  jup: "JUPUSDT",
  jupiter: "JUPUSDT",
  bome: "BOMEUSDT",
  bookofmeme: "BOMEUSDT",
  ordi: "ORDIUSDT",
  ordinals: "ORDIUSDT",
  stx: "STXUSDT",
  stacks: "STXUSDT",
  ens: "ENSUSDT",
  ethereumname: "ENSUSDT",
  dydx: "DYDXUSDT",
  imx: "IMXUSDT",
  immutable: "IMXUSDT",
  algo: "ALGOUSDT",
  algorand: "ALGOUSDT",
  vet: "VETUSDT",
  vechain: "VETUSDT",
  hbar: "HBARUSDT",
  hedera: "HBARUSDT",
  qnt: "QNTUSDT",
  quant: "QNTUSDT",
  xlm: "XLMUSDT",
  stellar: "XLMUSDT",
  xmr: "XMRUSDT",
  monero: "XMRUSDT",
  zec: "ZECUSDT",
  zcash: "ZECUSDT",
  eos: "EOSUSDT",
  kava: "KAVAUSDT",
  flow: "FLOWUSDT",
  crv: "CRVUSDT",
  curve: "CRVUSDT",
  comp: "COMPUSDT",
  compound: "COMPUSDT",
  snx: "SNXUSDT",
  synthetix: "SNXUSDT",
  cake: "CAKEUSDT",
  pancakeswap: "CAKEUSDT",
  "1inch": "1INCHUSDT",
  grt: "GRTUSDT",
  thegraph: "GRTUSDT",
  lrc: "LRCUSDT",
  loopring: "LRCUSDT",
  zil: "ZILUSDT",
  zilliqa: "ZILUSDT",
};
const FX_FUNCTION_CODES = new Set(["FRD", "FXFC", "FXH", "FXIP", "OVDV"]);
const MARKET_REGIME_CODES = new Set(["REGM"]);

interface Entry {
  sym: string;
  ts: number;
}

function load(): Entry[] {
  const parsed = safeReadLocal<unknown[]>(KEY, [], {
    label: "Recent symbols",
    validate: (v): v is unknown[] => Array.isArray(v),
  });
  return parsed
    .filter((e): e is Entry => Boolean(e && typeof (e as { sym?: unknown }).sym === "string"))
    .slice(0, MAX);
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
  const code = String(codeOrCategory ?? "").toUpperCase();
  if (FX_FUNCTION_CODES.has(code)) return ASSET_FALLBACKS.FX;
  if (MARKET_REGIME_CODES.has(code)) return "SPY";
  const supported = normalizeAssetClasses(assetClasses);
  if (code === "BGAS" || code === "NGAS") return "NG=F";
  if (code === "BOIL") return "CL=F";
  const fallbackClass = preferredAssetClass(codeOrCategory, supported);
  const allowedRecentClasses = code === "MICRO"
    ? [fallbackClass]
    : supported.length ? supported : [fallbackClass];
  const recent = listRecentSymbols().find((sym) =>
    isClassCompatible(inferAssetClassName(sym), allowedRecentClasses),
  );
  if (recent) return recent;
  return ASSET_FALLBACKS[fallbackClass] ?? FALLBACK_SYMBOL;
}

export function quickSymbolsForFunction(
  codeOrCategory?: string,
  assetClasses: string[] = [],
): string[] {
  const code = String(codeOrCategory ?? "").toUpperCase();
  if (FX_FUNCTION_CODES.has(code)) return ["EURUSD", "GBPUSD=X", "USDJPY=X", "EURGBP", "EURJPY"];
  if (MARKET_REGIME_CODES.has(code)) return ["SPY", "QQQ", "IWM", "TLT", "^GSPC", "^IXIC"];
  if (code === "BGAS" || code === "NGAS") return ["NG=F", "CL=F", "BZ=F", "GC=F", "HG=F", "ZC=F"];
  if (code === "BOIL") return ["CL=F", "BZ=F", "NG=F", "RB=F", "HO=F", "GC=F"];
  const supported = normalizeAssetClasses(assetClasses);
  const classes = code === "MICRO"
    ? ["CRYPTO"]
    : supported.length ? supported : [preferredAssetClass(codeOrCategory, [])];
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
        symbols.push("US10Y", "US2Y", "US30Y");
        break;
      default:
        symbols.push("AAPL", "NVDA", "MSFT");
    }
  }
  const recent = listRecentSymbols().filter((sym) => {
    const inferred = inferAssetClassName(sym);
    return isClassCompatible(inferred, code === "MICRO" ? classes : supported.length ? supported : classes);
  });
  return uniqueSymbols([...recent, ...symbols]).slice(0, 6);
}

export function inferAssetClassName(symbol: string | undefined | null): string {
  const value = normalizeSymbolInput(symbol);
  if (!value) return "EQUITY";
  const compact = value.replace(/[-/]/g, "").replace(/=X$/, "");
  if (value.startsWith("^")) return "INDEX";
  if (value.endsWith("=F") || ["XAUUSD", "XAGUSD"].includes(value)) {
    return "COMMODITY";
  }
  if (/^[A-Z]{6}$/.test(compact)) {
    const ccy = new Set(["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]);
    if (ccy.has(compact.slice(0, 3)) && ccy.has(compact.slice(3, 6))) return "FX";
  }
  const cryptoBases = new Set(
    Object.values(CRYPTO_NAME_ALIASES).map((pair) => pair.replace(/(USDT|USDC|FDUSD|USD|BTC|ETH|EUR)$/, "")),
  );
  if (/^[A-Z0-9]{1,12}(USDT|USDC|FDUSD)$/.test(compact)) return "CRYPTO";
  for (const quote of ["USDT", "USDC", "FDUSD", "USD", "BTC", "ETH", "EUR"]) {
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
  return SYMBOL_ALIASES[sym] ?? resolveCryptoSymbolAlias(symbol) ?? sym;
}

export function resolveCryptoSymbolAlias(symbol: string | undefined | null): string | undefined {
  const key = cryptoAliasKey(symbol);
  if (!key) return undefined;
  return CRYPTO_NAME_ALIASES[key];
}

function cryptoAliasKey(symbol: string | undefined | null): string {
  return String(symbol ?? "").trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

export function pushRecentSymbol(symbol: string): void {
  const sym = normalizeSymbolInput(symbol);
  if (!sym) return;
  const now = Date.now();
  const filtered = load().filter((e) => normalizeSymbolInput(e.sym) !== sym);
  save([{ sym, ts: now }, ...filtered]);
  notifyRecentSymbolsChanged();
}

export function removeRecentSymbol(symbol: string): void {
  const sym = normalizeSymbolInput(symbol);
  if (!sym) return;
  save(load().filter((e) => normalizeSymbolInput(e.sym) !== sym));
  notifyRecentSymbolsChanged();
}

export function clearRecentSymbols(): void {
  if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
  notifyRecentSymbolsChanged();
}

/**
 * Bundle D / MULTITAB-03. Lightweight subscribe API so SymbolBar (and any
 * future consumer) can refresh `listRecentSymbols()` when another tab
 * pushes a new ticker. Same-tab `pushRecentSymbol` / `removeRecentSymbol`
 * notify synchronously; the cross-tab `storage` listener feeds the same
 * pipe.
 */
type SymbolListener = () => void;
const _symbolListeners = new Set<SymbolListener>();

function notifyRecentSymbolsChanged(): void {
  _symbolListeners.forEach((fn) => {
    try {
      fn();
    } catch {
      // never let one bad listener break peers
    }
  });
}

export function subscribeRecentSymbols(fn: SymbolListener): () => void {
  _symbolListeners.add(fn);
  return () => {
    _symbolListeners.delete(fn);
  };
}

if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => {
    if (event.key !== KEY) return;
    notifyRecentSymbolsChanged();
  });
}

function preferredAssetClass(codeOrCategory: string | undefined, supported: string[]): string {
  const key = String(codeOrCategory ?? "").toUpperCase();
  if (key === "MICRO") return "CRYPTO";
  if (MARKET_REGIME_CODES.has(key)) return "ETF";
  if (key === "YAS") return "BOND";
  if (supported.includes("CRYPTO")) return "CRYPTO";
  if (supported.includes("EQUITY")) return "EQUITY";
  if (supported.includes("ETF")) return "ETF";
  if (supported.includes("FX")) return "FX";
  if (supported.includes("COMMODITY")) return "COMMODITY";
  if (supported.includes("INDEX")) return "INDEX";
  if (supported.includes("BOND")) return "BOND";
  if (FX_FUNCTION_CODES.has(key)) return "FX";
  if (["EVTS", "SOSC", "TRAN"].includes(key)) return "EQUITY";
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
