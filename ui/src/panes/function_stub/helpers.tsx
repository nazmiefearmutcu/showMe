import type { ReactNode } from "react";
import type { DataGridColumn } from "@/design-system";
import {
  inferAssetClassName,
  normalizeSymbolInput,
} from "@/lib/symbols";
import type { FunctionEntry } from "@/lib/sidecar";
import { formatTime as fmtTzTime } from "@/lib/timezone";
import { formatMissing } from "@/lib/format";
import { formatAdaptive } from "@/lib/format-helpers";
import {
  METRIC_RECORD_KEYS,
  STABLE_ROW_ID_KEYS,
  SYNTHETIC_MARKERS,
  TABLE_KEYS,
} from "./_types";
import type {
  FunctionCallResult,
  MediaItem,
  MetricCard,
  PayloadStatus,
  RecordRow,
  ResultSummary,
} from "./_types";
import {
  collectFields,
  isRecord,
  objectify,
  toFiniteNumber,
} from "./chart-extract";

export {
  collectChartCandidates,
  collectFields,
  chartTimeSortValue,
  extractChartSeries,
  focusLatestBars,
  formatAxisLabel,
  hasOhlcPoint,
  hasTimePoint,
  hasVolumePoint,
  humanizeKey,
  isRecord,
  normalizeChartTime,
  objectify,
  pickLabelKey,
  rowsHaveOhlc,
  rowsLookLikeOhlc,
  rowsToChartSeries,
  rowsToTimePoints,
  toFiniteNumber,
} from "./chart-extract";

export function motionDelayClass(idx: number): string {
  return `showme-motion-grid__row--${Math.min(idx, 10)}`;
}

export function stableRowKey(row: RecordRow, idx: number): string {
  const parts = STABLE_ROW_ID_KEYS
    .map((key) => row[key])
    .filter((value): value is string | number =>
      (typeof value === "string" && value.trim().length > 0) ||
      typeof value === "number",
    )
    .slice(0, 4)
    .map(String);
  return parts.length ? parts.join(":") : `row-${idx}`;
}

export function summarizeResult(data: unknown): ResultSummary {
  const rows = extractRows(data);
  const fields = rows.length ? collectFields(rows) : [];
  const keyValues = extractKeyValues(data);
  return {
    shape: Array.isArray(data) ? "array" : isRecord(data) ? "object" : typeof data,
    rows,
    fields,
    keyValues,
    columns: buildColumns(rows, fields),
  };
}

export function extractRows(data: unknown): RecordRow[] {
  if (Array.isArray(data)) return data.map(objectify);
  if (!isRecord(data)) return [];
  for (const key of TABLE_KEYS) {
    const value = data[key];
    if (Array.isArray(value) && value.length > 0) return value.map(objectify);
  }
  for (const value of Object.values(data)) {
    if (Array.isArray(value) && value.length > 0) return value.map(objectify);
  }
  for (const value of Object.values(data)) {
    if (!isRecord(value)) continue;
    const nested = Object.entries(value);
    if (!nested.length || !nested.every(([, item]) => isRecord(item))) continue;
    return nested.map(([bucket, item]) => ({ bucket, ...(item as RecordRow) }));
  }
  return [];
}

export function extractKeyValues(data: unknown): Array<[string, unknown]> {
  if (!isRecord(data)) return [];
  return Object.entries(data)
    .filter(([, value]) => !Array.isArray(value) && !isNestedRecord(value))
    .slice(0, 18);
}

export function getPayloadStatus(result: FunctionCallResult<unknown>): PayloadStatus {
  const metadata = result.metadata ?? {};
  const sources = result.sources ?? [];
  const explicitStatus = String(
    result.status ?? (isRecord(result.data) ? result.data.status ?? result.data.state : "") ?? "",
  ).toLowerCase();
  const reasons = [
    ...asStringArray(result.reason),
    ...asStringArray(result.warnings),
    ...asStringArray(metadata.provider_errors),
  ];
  const dataReason = dataReasonLine(result.data);
  if (dataReason) reasons.unshift(dataReason);
  const actions = unique([...asStringArray(result.nextAction), ...extractActions(result.data)]);
  const syntheticSources = sources.filter(isSyntheticText);
  const metadataSynthetic = Boolean(
    metadata.synthetic ||
      metadata.fallback ||
      metadata.degraded ||
      isSyntheticText(String(metadata.mode ?? "")) ||
      isSyntheticText(String(metadata.compatibility_mode ?? "")),
  );
  const empty = explicitStatus === "empty" || explicitStatus === "empty_portfolio";
  const unavailable =
    Boolean(metadata.fallback) ||
    dataIsUnavailable(result.data) ||
    ["provider_unavailable", "input_error", "calc_error", "unsupported_asset", "not_configured"].includes(
      explicitStatus,
    );
  const degraded = metadataSynthetic || syntheticSources.length > 0 || reasons.length > 0;

  if (empty) {
    return {
      state: "empty",
      label: "empty",
      title: "No data for this input",
      reasons: unique(reasons.length ? reasons : ["The function returned an intentional empty state."]),
      actions: unique(actions.length ? actions : defaultActions(result)),
    };
  }
  if (unavailable) {
    return {
      state: "unavailable",
      label: "needs data",
      title: "Provider or input required",
      reasons: unique(reasons.length ? reasons : ["The backend did not return usable live data."]),
      actions: unique(actions.length ? actions : defaultActions(result)),
    };
  }
  if (degraded) {
    return {
      state: "degraded",
      label: "degraded",
      title: "Payload returned with provider or source warnings",
      reasons: unique([
        ...reasons,
        ...syntheticSources.map((s) => `Synthetic source marker: ${s}`),
      ]),
      actions: unique(actions.length ? actions : ["Check sources and rerun with Live or Deep enabled."]),
    };
  }
  return {
    state: "live",
    label: "live",
    title: "Live payload",
    reasons: [],
    actions: [],
  };
}

export function dataIsUnavailable(data: unknown): boolean {
  if (!isRecord(data)) return false;
  const status = String(data.status ?? data.state ?? "").toLowerCase();
  return [
    "unavailable",
    "provider_unavailable",
    "unsupported_asset",
    "empty_portfolio",
    "not_configured",
    "input_error",
    "calc_error",
  ].some((token) => status.includes(token));
}

export function dataReasonLine(data: unknown): string | null {
  if (!isRecord(data)) return null;
  const status = firstString(data, ["status", "state"]);
  const reason = firstString(data, ["reason", "message", "note"]);
  const statusKey = status?.toLowerCase();
  if (statusKey && ["ok", "preview", "live", "ready"].includes(statusKey) && !reason) return null;
  if (status && reason) return `${status}: ${reason}`;
  return reason || (statusKey && ["ok", "preview", "live", "ready"].includes(statusKey) ? null : status);
}

export function defaultActions(result: FunctionCallResult<unknown>): string[] {
  const symbol = result.instrument?.symbol;
  return [
    symbol ? `Verify ${symbol} is supported by this function.` : "Provide the required symbol, account, or query input.",
    "Connect the required API key or local portfolio state when this function depends on private data.",
    "Open Advanced or Raw function payload to inspect exact provider errors.",
  ];
}

export function extractActions(data: unknown): string[] {
  if (!isRecord(data)) return [];
  return unique([
    ...asStringArray(data.next_actions),
    ...asStringArray(data.required_setup),
    ...asStringArray(data.actions),
  ]);
}

export function parseParams(text: string): Record<string, unknown> | undefined {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  const parsed = JSON.parse(trimmed) as unknown;
  if (!isRecord(parsed)) {
    throw new Error("Params JSON must be an object");
  }
  return parsed;
}

export function mergeParams(text: string, patch: Record<string, unknown>): string {
  let base: Record<string, unknown> = {};
  try {
    base = parseParams(text) ?? {};
  } catch {
    base = {};
  }
  return JSON.stringify({ ...base, ...patch }, null, 2);
}

export function buildColumns(
  rows: RecordRow[],
  fields = rows.length ? collectFields(rows) : [],
): DataGridColumn<RecordRow>[] {
  return fields.slice(0, 14).map((field) => ({
    key: field,
    header: field,
    numeric: rows.some((row) => toFiniteNumber(row[field]) !== null),
    render: (row) => formatCellValue(field, row[field]),
  }));
}

export function extractMetricCards(data: unknown): MetricCard[] {
  if (!isRecord(data)) return [];
  const cards: MetricCard[] = [];
  const seen = new Set<string>();
  const add = (label: string, value: unknown) => {
    if (seen.has(label) || !isMetricValue(value)) return;
    seen.add(label);
    cards.push({ label, value });
  };

  for (const key of METRIC_RECORD_KEYS) {
    const value = data[key];
    if (!isRecord(value)) continue;
    for (const [metricKey, metricValue] of Object.entries(value)) {
      add(metricKey, metricValue);
    }
  }

  for (const [key, value] of Object.entries(data)) {
    if (Array.isArray(value) || isRecord(value)) continue;
    if (/equity|return|sharpe|drawdown|vol|beta|alpha|score|pnl|cagr|yield|price|alert_count|ok_rate/i.test(key)) {
      add(key, value);
    }
  }

  return cards;
}

export function extractMethodology(data: unknown): string | null {
  if (!isRecord(data)) return null;
  const value = data.methodology ?? data.formula ?? data.method;
  if (typeof value === "string" && value.trim()) return value.trim();
  if (Array.isArray(value)) {
    const lines = value
      .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      .map((item) => item.trim());
    return lines.length ? lines.join("\n") : null;
  }
  return null;
}

export function extractFieldDictionary(data: unknown): Array<[string, string]> {
  if (!isRecord(data)) return [];
  const value = data.field_dictionary ?? data.field_definitions ?? data.glossary;
  if (!isRecord(value)) return [];
  return Object.entries(value)
    .map<[string, string]>(([key, description]) => [
      key,
      typeof description === "string" ? description : JSON.stringify(description),
    ])
    .filter(([, description]) => description.length > 0)
    .slice(0, 16);
}

export function extractMediaItems(data: unknown): MediaItem[] {
  if (!isRecord(data)) return [];
  const items: MediaItem[] = [];
  const addDataUrl = (label: string, value: unknown, note?: string, isSatellite?: boolean) => {
    if (typeof value !== "string" || !value.trim()) return;
    const src = value.startsWith("data:") ? value : `data:image/png;base64,${value}`;
    items.push({ label, src, note, isSatellite });
  };
  const trueColor = data.true_color_png;
  if (isRecord(trueColor)) {
    addDataUrl(
      firstString(trueColor, ["label"]) ?? "True-color image",
      trueColor.data_url ?? trueColor.png_base64,
      "Sentinel-2 true-color output",
      true,
    );
  }
  const preview = data.preview;
  if (isRecord(preview)) {
    const previewIsSatellite = Boolean(preview.is_satellite);
    addDataUrl(
      firstString(preview, ["label"]) ?? "Preview",
      preview.data_url,
      previewIsSatellite ? undefined : "Preview only; not satellite imagery.",
      previewIsSatellite,
    );
  }
  addDataUrl("PNG image", data.png_data_url ?? data.image_data_url ?? data.png_base64, undefined, true);
  return items.slice(0, 3);
}

export function isNestedRecord(value: unknown): boolean {
  return isRecord(value) && Object.values(value).some((item) => isRecord(item));
}

export function isArticleRow(row: RecordRow): boolean {
  return Boolean(firstString(row, ["headline", "title"]) && firstString(row, ["source", "url", "link"]));
}

export function firstString(row: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return null;
}

export function stripHtml(value: string): string {
  return value
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

export function stripMarkdown(value: string): string {
  return value
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .trim();
}

export function asStringArray(value: unknown): string[] {
  if (typeof value === "string") return value.trim() ? [value.trim()] : [];
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

export function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

export function isSyntheticText(value: unknown): boolean {
  const text = String(value ?? "").toLowerCase();
  return SYNTHETIC_MARKERS.some((marker) => text.includes(marker));
}

export function isMetricValue(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return value.trim().length > 0 && value.length < 80;
  if (typeof value === "boolean") return true;
  return false;
}

export function formatValue(value: unknown): string {
  if (value == null || value === "") return formatMissing;
  if (typeof value === "number") {
    // Adaptive precision — sub-cent numbers keep digits, big numbers drop them.
    return formatAdaptive(value);
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return `${value.length} items`;
  if (isRecord(value)) return formatRecordPreview(value);
  return String(value);
}

export function formatCellValue(field: string, value: unknown): ReactNode {
  if (typeof value === "string" && /^https?:\/\//i.test(value)) {
    return (
      <a href={value} target="_blank" rel="noreferrer" className="u-text-accent">
        open
      </a>
    );
  }
  if (Array.isArray(value)) return `${value.length} ${field}`;
  return formatValue(value);
}

export function formatRecordPreview(value: RecordRow): string {
  const entries = Object.entries(value)
    .filter(([, item]) => item == null || ["number", "string", "boolean"].includes(typeof item))
    .slice(0, 3);
  if (!entries.length) return `${Object.keys(value).length} fields`;
  return entries.map(([key, item]) => `${key}: ${formatValue(item)}`).join(" · ");
}

export function formatElapsed(ms: number | null | undefined): string {
  if (ms == null) return formatMissing;
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatTime(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return fmtTzTime(d, { seconds: true });
}

export function newsRowTimestamp(row: RecordRow): string | null | undefined {
  return firstString(row, [
    "published_at",
    "publishedAt",
    "published_on",
    "published",
    "date",
    "datetime",
    "time",
    "ts",
  ]);
}

export function renderMarkdownLine(text: string): ReactNode {
  const clean = stripMarkdown(text);
  const match = clean.match(/^(.*)\[([^\]]+)\]\((https?:\/\/[^)]+)\)(.*)$/);
  if (!match) return clean;
  const [, before, label, url, after] = match;
  return (
    <>
      {before}
      <a href={url} target="_blank" rel="noreferrer" className="u-text-accent">
        {label}
      </a>
      {after}
    </>
  );
}

export function compatibleRequestedSymbol(
  symbol: string | undefined | null,
  entry: FunctionEntry | null,
): string {
  const normalized = normalizeSymbolInput(symbol);
  if (!normalized) return "";
  const inferred = inferAssetClassName(normalized);
  const supported = (entry?.asset_classes ?? [])
    .map((item) => String(item).trim().toUpperCase())
    .filter(Boolean);
  if (supported.length) {
    if (supported.includes(inferred)) return normalized;
    if (inferred === "ETF" && supported.includes("EQUITY")) return normalized;
    if (inferred === "EQUITY" && supported.includes("ETF")) return normalized;
    return "";
  }
  const category = entry?.category?.toLowerCase();
  if (category === "equity" && !["EQUITY", "ETF"].includes(inferred)) return "";
  if (category === "fx" && inferred !== "FX") return "";
  if (category === "commodity" && inferred !== "COMMODITY") return "";
  if (category === "bond" && inferred !== "BOND") return "";
  return normalized;
}

export function suggestedSymbolsForFunction(
  quickSymbols: string[],
  assetClasses: string[],
  category?: string,
): string[] {
  const supported = assetClasses.map((item) => item.toUpperCase());
  const categoryKey = category?.toUpperCase() ?? "";
  const byClass: Record<string, string[]> = {
    CRYPTO: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"],
    EQUITY: ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "JPM"],
    ETF: ["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD"],
    FX: ["EURUSD", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X"],
    COMMODITY: ["GC=F", "CL=F", "NG=F", "SI=F", "HG=F"],
    INDEX: ["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX"],
    BOND: ["US10Y", "US2Y", "US30Y"],
  };
  const classes = supported.length
    ? supported
    : categoryKey === "FX"
      ? ["FX"]
      : categoryKey === "COMMODITY"
        ? ["COMMODITY"]
        : categoryKey === "BOND"
          ? ["BOND"]
          : categoryKey === "NEWS"
            ? ["CRYPTO", "EQUITY"]
            : ["EQUITY", "CRYPTO", "FX"];
  return unique([
    ...quickSymbols,
    ...classes.flatMap((cls) => byClass[cls] ?? []),
  ]).slice(0, 24);
}
