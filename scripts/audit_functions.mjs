#!/usr/bin/env node
import { mkdir, writeFile, appendFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SYMBOL = process.env.SHOWME_AUDIT_SYMBOL || "BTCUSDT";
const ASSET_CLASS = process.env.SHOWME_AUDIT_ASSET_CLASS || "CRYPTO";
const DEFAULT_TIMEOUT_MS = Number(process.env.SHOWME_AUDIT_TIMEOUT_MS || 65000);
const ASSET = ASSET_CLASS.toUpperCase();
const PROFILE_BY_ASSET = {
  CRYPTO: {
    newsQuery: "bitcoin",
    peerSymbols: [SYMBOL, "ETHUSDT", "SOLUSDT"],
    bqlSymbol: "BTC-USD",
    isinQuery: SYMBOL,
    exchange: "BINANCE",
    universe: [SYMBOL, "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    targets: { [SYMBOL]: 0.6, ETHUSDT: 0.4 },
  },
  EQUITY: {
    newsQuery: "apple stock",
    peerSymbols: [SYMBOL, "MSFT", "GOOGL"],
    bqlSymbol: SYMBOL,
    isinQuery: SYMBOL,
    exchange: "NASDAQ",
    universe: [SYMBOL, "MSFT", "GOOGL", "NVDA", "TSLA"],
    targets: { [SYMBOL]: 0.5, MSFT: 0.3, GOOGL: 0.2 },
  },
  FX: {
    newsQuery: "euro dollar foreign exchange",
    peerSymbols: [SYMBOL, "GBPUSD=X", "USDJPY=X"],
    bqlSymbol: "EURUSD=X",
    isinQuery: SYMBOL,
    exchange: "FX",
    universe: [SYMBOL, "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"],
    targets: { [SYMBOL]: 0.5, "GBPUSD=X": 0.3, "USDJPY=X": 0.2 },
  },
  COMMODITY: {
    newsQuery: "gold futures commodity",
    peerSymbols: [SYMBOL, "SI=F", "CL=F"],
    bqlSymbol: "GC=F",
    isinQuery: SYMBOL,
    exchange: "COMEX",
    universe: [SYMBOL, "SI=F", "CL=F", "BZ=F", "NG=F"],
    targets: { [SYMBOL]: 0.5, "SI=F": 0.25, "CL=F": 0.25 },
  },
  INDEX: {
    newsQuery: "s&p 500 index",
    peerSymbols: [SYMBOL, "QQQ", "DIA"],
    bqlSymbol: "SPY",
    isinQuery: SYMBOL,
    exchange: "NYSEARCA",
    universe: [SYMBOL, "QQQ", "DIA", "IWM", "VTI"],
    targets: { [SYMBOL]: 0.5, QQQ: 0.3, DIA: 0.2 },
  },
};
const PROFILE = PROFILE_BY_ASSET[ASSET] || PROFILE_BY_ASSET.EQUITY;

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = resolve(root, "artifacts", "function-audit", stamp);
const jsonlPath = resolve(outDir, "results.jsonl");
const summaryPath = resolve(outDir, "summary.md");

function argValue(name) {
  const prefix = `${name}=`;
  const hit = process.argv.find((arg) => arg.startsWith(prefix));
  if (hit) return hit.slice(prefix.length);
  const idx = process.argv.indexOf(name);
  return idx >= 0 ? process.argv[idx + 1] : undefined;
}

function baseUrl() {
  const explicit = argValue("--base-url") || process.env.SHOWME_BASE_URL;
  if (explicit) return explicit.replace(/\/$/, "");
  const port = argValue("--port") || process.env.SHOWME_PORT;
  if (!port) {
    throw new Error("pass --port <sidecarPort> or SHOWME_BASE_URL=http://127.0.0.1:<port>");
  }
  return `http://127.0.0.1:${port}`;
}

function commonParams(entry) {
  const code = entry.code.toUpperCase();
  const category = entry.category.toLowerCase();
  const params = {
    symbol: SYMBOL,
    asset_class: ASSET_CLASS,
    limit: 10,
    days: 30,
    range: "1M",
    interval: "1d",
    query: PROFILE.newsQuery,
    topic: SYMBOL,
    symbols: PROFILE.peerSymbols,
  };

  if (code === "BQL") {
    params.query = `get(close, volume) for(['${PROFILE.bqlSymbol}']) with(period='1mo', interval='1d') by(date)`;
  } else if (code === "EQS") {
    params.query = "marketCap > 0";
    params.universe = PROFILE.universe;
  } else if (code === "FTS") {
    params.query = PROFILE.newsQuery;
    params.form_type = "8-K";
  } else if (code === "FLDS") {
    params.query = "price";
  } else if (code === "ISIN") {
    params.query = PROFILE.isinQuery;
  } else if (code === "NSE" || code === "NI" || code === "READ" || code === "TOP") {
    params.query = PROFILE.newsQuery;
    params.limit = 10;
  } else if (code === "CN") {
    params.limit = 10;
  } else if (code === "TSAR") {
    params.query = "revenue";
    params.limit = 10;
  } else if (code === "TRQA") {
    params.questions = ["What changed?", "What are the risks?"];
  } else if (code === "FORM4" || code === "HDS" || code === "HFS" || code === "DARK" || code === "DPF") {
    if (ASSET === "EQUITY") {
      params.symbol = "AAPL";
      params.asset_class = "EQUITY";
    }
  } else if (code === "TRDH") {
    params.exchange = PROFILE.exchange;
  } else if (code === "ICX") {
    params.index = "SP500";
  } else if (code === "MICRO" || code === "FRH") {
    params.symbol = SYMBOL;
    params.asset_class = ASSET_CLASS;
    params.exchange = PROFILE.exchange;
  } else if (code === "SAT") {
    params.bbox = "-122.55,37.70,-122.30,37.85";
    params.days = 7;
  } else if (code === "CDE" || code === "ALRT" || code === "LOTS") {
    params.action = "list";
  } else if (code === "POLY") {
    params.query = PROFILE.newsQuery;
  } else if (code === "MEET" || code === "PEOP") {
    params.query = "Satoshi Nakamoto";
  } else if (code === "BTFW" || code === "BMTX" || code === "MLSIG") {
    params.symbol = SYMBOL;
    params.asset_class = ASSET_CLASS;
    params.strategy = "buy_and_hold";
    params.days = 365;
  } else if (code === "BTUNE") {
    params.symbol = SYMBOL;
    params.asset_class = ASSET_CLASS;
    params.strategy = "sma_crossover";
    params.days = 365;
  } else if (ASSET === "EQUITY" && category === "equity" && !["ANR", "BETA", "DES", "FA", "GP", "HP", "TECH"].includes(code)) {
    params.symbol = "AAPL";
    params.asset_class = "EQUITY";
  }
  if (code === "SAT") {
    const today = new Date();
    const prior = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
    params.date_from = prior.toISOString().slice(0, 10);
    params.date_to = today.toISOString().slice(0, 10);
  } else if (code === "ICX") {
    params.index = "SPX";
  } else if (code === "MGN") {
    params.refresh_prices = false;
  } else if (code === "DCFS") {
    params.wacc_range = [0.07, 0.09, 0.11];
    params.g_range = [0.02, 0.03];
  } else if (code === "REBA") {
    params.targets = PROFILE.targets;
  } else if (code === "SECF") {
    params.query = "marketCap > 0";
    params.universe = PROFILE.universe;
  } else if (code === "GREEKS") {
    params.positions = [{
      option_type: "CALL",
      qty: 1,
      spot: 100,
      strike: 105,
      expiry: 0.25,
      vol: 0.35,
      rate: 0.04,
    }];
  }
  return params;
}

function timeoutSignal(ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

async function fetchJson(url, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const t = timeoutSignal(timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: t.signal });
    const text = await res.text();
    let body;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = text;
    }
    return { ok: res.ok, status: res.status, statusText: res.statusText, body };
  } finally {
    t.clear();
  }
}

function isEmpty(value) {
  if (value == null) return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length === 0) return true;
    return keys.every((key) => isEmpty(value[key]));
  }
  return false;
}

function classify(entry, response, elapsedMs, thrown) {
  if (thrown) {
    return { status: "FAIL", reason: thrown.name === "AbortError" ? "client timeout" : thrown.message };
  }
  if (!response.ok) {
    const detail = typeof response.body === "object" ? response.body?.detail : response.body;
    return { status: "FAIL", reason: `${response.status} ${response.statusText}${detail ? `: ${detail}` : ""}` };
  }
  const body = response.body || {};
  const warnings = Array.isArray(body.warnings) ? body.warnings.map(String) : [];
  const warningText = warnings.join(" | ");
  const exceptionType = body.metadata?.exception_type;
  if (exceptionType) {
    return { status: "FAIL", reason: `${exceptionType}: ${warningText || "exception payload"}` };
  }
  if (body.code && body.code.toUpperCase() !== entry.code.toUpperCase()) {
    return { status: "FAIL", reason: `code mismatch: ${body.code}` };
  }
  const sources = Array.isArray(body.sources) ? body.sources.map(String) : [];
  const providerErrors = Array.isArray(body.metadata?.provider_errors)
    ? body.metadata.provider_errors.map(String)
    : [];
  const dataStatus = typeof body.data?.status === "string" ? body.data.status : "";
  const syntheticSource = sources.find((source) => /template|sample|synthetic|continuity|no_live_source/i.test(source));
  if (
    body.metadata?.fallback ||
    body.metadata?.synthetic ||
    dataStatus === "provider_unavailable" ||
    dataStatus === "unsupported_asset" ||
    syntheticSource
  ) {
    const reason = providerErrors[0] || dataStatus || `synthetic source: ${syntheticSource}`;
    return { status: "WARN", reason };
  }
  if (/unknown function|argument error|not implemented|no module named|attributeerror|typeerror|keyerror|failed|exception/i.test(warningText)) {
    return { status: "FAIL", reason: warningText };
  }
  if (warnings.length > 0) {
    return { status: "WARN", reason: warningText };
  }
  if (isEmpty(body.data)) {
    return { status: "WARN", reason: "empty data" };
  }
  return { status: "PASS", reason: `${Math.round(elapsedMs)}ms` };
}

function compactDataShape(value) {
  if (Array.isArray(value)) return `array(${value.length})`;
  if (value && typeof value === "object") {
    return `object(${Object.keys(value).slice(0, 8).join(",")})`;
  }
  return typeof value;
}

async function main() {
  const base = baseUrl();
  await mkdir(outDir, { recursive: true });
  const health = await fetchJson(`${base}/api/health`, {}, Math.max(10000, DEFAULT_TIMEOUT_MS));
  if (!health.ok) throw new Error(`health failed: ${health.status}`);
  const indexRes = await fetchJson(`${base}/api/function-index`, {}, Math.max(15000, DEFAULT_TIMEOUT_MS));
  if (!indexRes.ok || !Array.isArray(indexRes.body)) {
    throw new Error(`function-index failed: ${indexRes.status}`);
  }
  const entries = indexRes.body;
  console.log(`audit start: ${entries.length} functions, base=${base}, symbol=${SYMBOL}`);
  await appendFile(jsonlPath, "");
  const results = [];
  for (let i = 0; i < entries.length; i += 1) {
    const entry = entries[i];
    const code = entry.code.toUpperCase();
    const params = commonParams(entry);
    const started = Date.now();
    let response = null;
    let thrown = null;
    try {
      response = await fetchJson(`${base}/api/fn/${encodeURIComponent(code)}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(params),
      });
    } catch (err) {
      thrown = err;
    }
    const elapsedMs = Date.now() - started;
    const classification = classify(entry, response || {}, elapsedMs, thrown);
    const body = response?.body || {};
    const row = {
      index: i + 1,
      total: entries.length,
      code,
      name: entry.name,
      category: entry.category,
      status: classification.status,
      reason: classification.reason,
      elapsed_ms: elapsedMs,
      http_status: response?.status ?? 0,
      warnings: Array.isArray(body.warnings) ? body.warnings : [],
      sources: Array.isArray(body.sources) ? body.sources : [],
      data_shape: compactDataShape(body.data),
      params,
    };
    results.push(row);
    await appendFile(jsonlPath, `${JSON.stringify(row)}\n`);
    console.log(`[${row.index}/${row.total}] ${row.status.padEnd(4)} ${code.padEnd(9)} ${entry.category.padEnd(10)} ${Math.round(elapsedMs).toString().padStart(6)}ms ${row.reason}`);
  }

  const counts = results.reduce((acc, row) => {
    acc[row.status] = (acc[row.status] || 0) + 1;
    return acc;
  }, {});
  const byCategory = results.reduce((acc, row) => {
    const bucket = (acc[row.category] ||= { PASS: 0, WARN: 0, FAIL: 0 });
    bucket[row.status] += 1;
    return acc;
  }, {});
  const lines = [
    `# showMe Function Audit`,
    ``,
    `- base: ${base}`,
    `- symbol: ${SYMBOL}`,
    `- asset_class: ${ASSET_CLASS}`,
    `- total: ${results.length}`,
    `- pass: ${counts.PASS || 0}`,
    `- warn: ${counts.WARN || 0}`,
    `- fail: ${counts.FAIL || 0}`,
    `- generated: ${new Date().toISOString()}`,
    ``,
    `## By Category`,
    ``,
    `| category | pass | warn | fail |`,
    `|---|---:|---:|---:|`,
    ...Object.entries(byCategory)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([category, bucket]) => `| ${category} | ${bucket.PASS} | ${bucket.WARN} | ${bucket.FAIL} |`),
    ``,
    `## Failures`,
    ``,
    `| code | category | reason | elapsed ms |`,
    `|---|---|---|---:|`,
    ...results
      .filter((row) => row.status === "FAIL")
      .map((row) => `| ${row.code} | ${row.category} | ${String(row.reason).replaceAll("|", "\\|")} | ${row.elapsed_ms} |`),
    ``,
    `## Warnings`,
    ``,
    `| code | category | reason | elapsed ms |`,
    `|---|---|---|---:|`,
    ...results
      .filter((row) => row.status === "WARN")
      .map((row) => `| ${row.code} | ${row.category} | ${String(row.reason).replaceAll("|", "\\|")} | ${row.elapsed_ms} |`),
    ``,
    `## All Results`,
    ``,
    `| # | code | category | status | reason | elapsed ms | shape |`,
    `|---:|---|---|---|---|---:|---|`,
    ...results.map(
      (row) =>
        `| ${row.index} | ${row.code} | ${row.category} | ${row.status} | ${String(row.reason).replaceAll("|", "\\|")} | ${row.elapsed_ms} | ${row.data_shape} |`,
    ),
    ``,
    `Raw JSONL: ${jsonlPath}`,
  ];
  await writeFile(summaryPath, lines.join("\n"));
  console.log(`audit summary: PASS=${counts.PASS || 0} WARN=${counts.WARN || 0} FAIL=${counts.FAIL || 0}`);
  console.log(`summary: ${summaryPath}`);
  console.log(`jsonl: ${jsonlPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
