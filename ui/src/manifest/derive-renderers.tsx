/**
 * Contract renderer picker + concrete manifest renderers for non-native functions.
 *
 * The goal is immediate UX improvement for equity tools that are driven only by
 * manifest contract (FORM4 and similar): render readable tables and cards from the
 * live payload instead of silent placeholders.
 */
import { type CSSProperties, type JSX, type ReactNode } from "react";

import { DataGrid, Empty, Pill, StatCard } from "@/design-system";
import type { DataGridColumn } from "@/design-system";
import {
  type CardSlot,
  type CardSchema,
  type ChartGrammar,
  type ChartKind,
  type FunctionManifest,
  type TableSchema,
  type ColumnKind,
} from "./types";
import { formatCompactNumber, formatCurrency, formatMissing, formatNumber, formatPercent } from "@/lib/format";

type ManifestPayload = Record<string, unknown> | null | undefined;

const MANIFEST_TABLE_STYLE: CSSProperties = {
  display: "grid",
  gap: 10,
  padding: "8px 0",
};

const MANIFEST_CARD_STYLE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
  gap: 12,
};
const MANIFEST_SECTION_STYLE: CSSProperties = {
  display: "grid",
  gap: 8,
};
const MANIFEST_SECTION_TITLE_STYLE: CSSProperties = {
  fontSize: 11,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};
const MODE_PILL_LABEL: Record<string, string> = {
  live_official: "Live · Official",
  live_exchange: "Live · Exchange",
  delayed_reference: "Delayed reference",
  cached_snapshot: "Cached snapshot",
  provider_unavailable: "Provider unavailable",
  not_configured: "Not configured",
  modeled: "Modeled",
};

type TableRendererProps = {
  schema: TableSchema;
  payload?: ManifestPayload;
};

type CardsRendererProps = {
  schema: CardSchema;
  payload?: ManifestPayload;
};

export type ChartRenderer = (props: {
  grammar: ChartGrammar;
  payload?: ManifestPayload;
}) => JSX.Element;
export type TableRenderer = (props: TableRendererProps) => JSX.Element;
export type CardsRenderer = (props: CardsRendererProps) => JSX.Element;

export interface RendererPicker {
  chart: ChartRenderer | null;
  table: TableRenderer | null;
  cards: CardsRenderer | null;
}

type RowRecord = Record<string, unknown>;

const TABLE_ALIAS: Record<string, string[]> = {
  transaction_date: ["filingDate", "filing_date", "date", "transactionDate", "event_date", "created_at", "time", "period", "published_utc", "timestamp", "ts"],
  filer: ["insider", "reportingOwner", "ownerName", "holder", "person", "filer_name", "name"],
  role: ["position", "filer_type", "holder_type", "transaction_role", "position_title", "officer_title", "directorOfficerTitle", "officerTitle", "title"],
  transaction_type: ["transaction", "action", "action_type", "txn_type", "transactionType", "acquiredDisposedCode", "side", "type"],
  shares: ["share", "share_count", "qty", "quantity", "position", "num_shares", "holding", "share_delta", "share_change", "shares_delta", "net_shares"],
  price: ["px", "unit_price", "pricePerShare", "avgPrice", "px_usd", "price_per_share", "unit_price_usd", "purchase_price", "purchasePricePerShare"],
  filing_url: ["url", "link", "primaryDocument", "source_url", "document_url", "action"],
  pct_held: ["pct_of_portfolio", "pct_of_float", "pct_of_shares", "holding_pct", "owned_pct", "percent_held"],
  source_mode: ["provider", "source_mode", "mode", "status", "state", "data_state"],
};

const CARD_ALIAS: Record<string, string[]> = {
  as_of: ["fetched_at", "snapshot_at", "updated_at", "updated", "timestamp", "asOf", "asOfUtc", "captured_at", "as_of_utc", "asOfDate"],
  filing_count: ["filings_count", "n", "count", "row_count", "events", "num_filings"],
  net_shares: ["netShares", "shares_net", "shares_delta", "net_position", "signed_shares"],
  net_notional: ["net_notional", "notional", "value_net", "net_value", "total_value", "signed_value"],
  buyer_count: ["buyers", "buyers_count", "num_buyers", "buy_count"],
  seller_count: ["sellers", "sellers_count", "num_sellers", "sell_count"],
  data_mode: ["source_mode", "mode", "status", "state"],
};

const CARD_DERIVED_KEYS: ReadonlySet<string> = new Set([
  "filing_count",
  "net_shares",
  "net_notional",
  "buyer_count",
  "seller_count",
  "as_of",
  "data_mode",
]);

const CARD_SUMMARY_ROWS_KEYS: ReadonlyArray<string> = [
  "rows",
  "filings",
  "events",
  "items",
  "records",
  "positions",
  "holdings",
  "trades",
  "signals",
  "news",
  "data",
];

const FIELDS_TO_AVOID_ALIAS_MATCH: ReadonlySet<string> = new Set(["data"]);

function normalizeValueKey(key: string): string {
  return key
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function tokenizeKey(normalized: string): string[] {
  return normalized.split("_").filter((part) => part.length > 0);
}

function keyMatchScore(a: string, b: string): number {
  const target = normalizeValueKey(a);
  const candidate = normalizeValueKey(b);
  if (!target || !candidate) return 0;
  if (target === candidate) return 130;
  let score = 0;
  if (candidate.includes(target) || target.includes(candidate)) {
    score += 60;
    if (candidate.length === target.length + 1 || target.length === candidate.length + 1) score += 10;
  }
  const targetParts = tokenizeKey(target);
  const candidateParts = new Set(tokenizeKey(candidate));
  for (const part of targetParts) {
    if (part.length < 3) continue;
    if (candidateParts.has(part)) score += 22;
  }
  return score;
}

function pickClosestMatch(record: RowRecord, key: string): string | null {
  const target = normalizeValueKey(key);
  if (!target) return null;
  let bestMatch: string | null = null;
  let bestScore = 0;
  for (const candidate of Object.keys(record)) {
    if (FIELDS_TO_AVOID_ALIAS_MATCH.has(normalizeValueKey(candidate))) continue;
    const score = keyMatchScore(target, candidate);
    if (score > bestScore) {
      bestScore = score;
      bestMatch = candidate;
    }
  }
  // threshold keeps collisions low for unrelated keys
  return bestScore >= 30 ? bestMatch : null;
}

function toPayload(payload: unknown): Record<string, unknown> {
  return payload && typeof payload === "object" && !Array.isArray(payload)
    ? (payload as Record<string, unknown>)
    : {};
}

function isRecord(value: unknown): value is RowRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "boolean") return null;
  if (typeof value === "string") {
    const normalized = value.replace(/,/g, "").replace(/%/g, "").trim();
    const parsed = Number(normalized);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function isUrl(value: unknown): value is string {
  return typeof value === "string" && /^https?:\/\//i.test(value.trim());
}

function readValue(record: RowRecord, key: string): unknown | undefined {
  if (Object.prototype.hasOwnProperty.call(record, key)) return record[key];
  const normalized = normalizeValueKey(key);
  for (const [candidate, value] of Object.entries(record)) {
    if (normalizeValueKey(candidate) === normalized) return value;
  }
  const closest = pickClosestMatch(record, key);
  if (closest != null) return record[closest];
  return undefined;
}

function readValueWithAliases(record: RowRecord, key: string): unknown | undefined {
  const direct = readValue(record, key);
  if (direct !== undefined) return direct;
  for (const alias of TABLE_ALIAS[key] ?? []) {
    const aliased = readValue(record, alias);
    if (aliased !== undefined) return aliased;
  }
  for (const alias of CARD_ALIAS[key] ?? []) {
    const aliased = readValue(record, alias);
    if (aliased !== undefined) return aliased;
  }
  return undefined;
}

function readCardValue(
  payload: Record<string, unknown>,
  key: string,
  derivedValues?: Record<string, unknown>,
): unknown | undefined {
  const values = derivedValues ?? buildDerivedCardValues(payload);
  const normalized = normalizeValueKey(key);
  const direct = readValue(payload, key);
  if (direct !== undefined) return direct;
  for (const alias of TABLE_ALIAS[key] ?? []) {
    const aliased = readValue(payload, alias);
    if (aliased !== undefined) return aliased;
  }
  for (const alias of CARD_ALIAS[key] ?? []) {
    const aliased = readValue(payload, alias);
    if (aliased !== undefined) return aliased;
  }
  const payloadObj = payload as RowRecord;
  const closest = pickClosestMatch(payloadObj, key);
  if (closest != null) return payloadObj[closest];
  if (CARD_DERIVED_KEYS.has(normalized) && Object.prototype.hasOwnProperty.call(values, key)) {
    const maybe = values[key];
    if (maybe !== undefined) return maybe;
  }
  return undefined;
}

function isDirectionPositive(value: unknown): -1 | 0 | 1 {
  if (value == null) return 0;
  const raw = String(value).trim().toLowerCase();
  if (!raw) return 0;
  if (raw.startsWith("+")) return 1;
  if (raw.startsWith("-")) return -1;
  if (/\b(sell|disposition|sale|disposed|forfeit|surrender|revoke|exercise out|cancel)\b/.test(raw)) return -1;
  if (/\b(buy|purchase|acquire|acquisition|grant|award|exercise|issued|receive|subscription|bonus|vest|transfer in)\b/.test(raw)) return 1;
  return 0;
}

function inferDirection(row: RowRecord): -1 | 0 | 1 {
  const directionHints = ["direction", "side", "action", "transaction_type", "transaction", "txn_type", "action_type", "code", "type"];
  for (const key of directionHints) {
    const hint = readValue(row, key);
    const inferred = isDirectionPositive(hint);
    if (inferred !== 0) return inferred;
  }
  return 0;
}

function withSignedDirection(raw: unknown, direction: -1 | 0 | 1): number | null {
  const parsed = toFiniteNumber(raw);
  if (parsed == null) return null;
  if (direction > 0) return Math.abs(parsed);
  if (direction < 0) return -Math.abs(parsed);
  return parsed;
}

function isTransactionTypeKey(key: string): boolean {
  const normalized = normalizeValueKey(key);
  return normalized === "transaction_type" || normalized === "side" || normalized === "action" || normalized === "type" || normalized === "code" || normalized === "action_type" || normalized === "txn_type";
}

function prettifyTransactionType(value: unknown): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) return String(formatMissing);
  const compact = normalized
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  const labelMap: Record<string, string> = {
    buy: "Buy",
    sells: "Sell",
    sell: "Sell",
    grant: "Grant",
    option_exercise: "Option Exercise",
    option: "Option Exercise",
    exercised: "Option Exercise",
    exercise: "Option Exercise",
    other: "Other",
    dispose: "Disposition",
    disposal: "Disposition",
    disposition: "Disposition",
    disposed: "Disposition",
    forfeit: "Forfeit",
    acquire: "Acquisition",
    acquisition: "Acquisition",
    award: "Award",
    purchase: "Purchase",
    issued: "Issue",
    issue: "Issue",
    transfer_in: "Transfer In",
    transfer_out: "Transfer Out",
  };
  if (labelMap[compact] != null) return labelMap[compact];
  return compact
    .split("_")
    .filter((part) => part.length > 0)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function transactionTypeTone(value: unknown): "positive" | "negative" | "warn" | "neutral" | "accent" {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) return "neutral";
  if (/\b(sell|disposition|disposed|forfeit|surrender|revoke|exercise out|cancel)\b/.test(normalized)) return "negative";
  if (/\b(buy|purchase|acquire|acquisition|grant|award|exercise|issued|receive|subscription|bonus|vest|transfer in)\b/.test(normalized)) return "positive";
  if (normalized.includes("option")) return "accent";
  return "neutral";
}

function renderTransactionTypePill(value: unknown): JSX.Element {
  return <Pill tone={transactionTypeTone(value)}>{prettifyTransactionType(value)}</Pill>;
}

function maybeSignedNumeric(raw: unknown, row: RowRecord, normalizedKey: string): number | null {
  const parsed = toFiniteNumber(raw);
  if (parsed == null) return null;
  if (normalizedKey !== "shares" && normalizedKey !== "value" && normalizedKey !== "notional") return parsed;
  const direction = inferDirection(row);
  return withSignedDirection(raw, direction) ?? parsed;
}

function toSignedDateValue(value: unknown): number {
  if (value == null) return 0;
  const parsed = toFiniteNumber(value);
  if (parsed != null) return parsed;
  const parsedDate = new Date(String(value));
  if (!Number.isNaN(parsedDate.getTime())) return parsedDate.getTime();
  return 0;
}

function sortRowsByDateDesc(rows: RowRecord[], schema: TableSchema): RowRecord[] {
  const hasDateColumn = schema.columns.some((column) => normalizeValueKey(column.key) === "transaction_date");
  if (!hasDateColumn) return rows;
  return [...rows].sort((a, b) => {
    const aTs = toSignedDateValue(readValueWithAliases(a, "transaction_date"));
    const bTs = toSignedDateValue(readValueWithAliases(b, "transaction_date"));
    if (aTs === 0 && bTs === 0) return 0;
    return bTs - aTs;
  });
}

function rowParticipant(row: RowRecord): string | null {
  const candidates = ["filer", "insider", "reportingOwner", "ownerName", "person", "holder", "owner", "name", "reporting_owner"];
  for (const key of candidates) {
    const raw = readValue(row, key);
    if (typeof raw !== "string") continue;
    const cleaned = raw.trim();
    if (!cleaned) continue;
    const lower = cleaned.toLowerCase();
    if (lower === "unknown" || lower === "n/a" || lower === "-") continue;
    return cleaned;
  }
  return null;
}

function resolveRowsFromPayload(payload: Record<string, unknown>): RowRecord[] {
  const root = toPayload(payload);
  for (const key of CARD_SUMMARY_ROWS_KEYS) {
    const value = root[key];
    if (!Array.isArray(value)) continue;
    const rows = value.filter((item) => isRecord(item)) as RowRecord[];
    if (rows.length === 0) continue;
    if (rows.length === value.length) return rows;
  }
  for (const value of Object.values(root)) {
    if (!Array.isArray(value)) continue;
    const rows = value.filter((item) => isRecord(item)) as RowRecord[];
    if (rows.length === 0) continue;
    if (rows.length === value.length) return rows;
  }
  return [];
}

function buildDerivedCardValues(payload: Record<string, unknown>): Record<string, unknown> {
  const rows = resolveRowsFromPayload(payload);
  const derived: Record<string, unknown> = {};

  if (rows.length > 0) {
    derived.filing_count = rows.length;
  } else if (toFiniteNumber(readValue(payload, "n")) != null) {
    derived.filing_count = toFiniteNumber(readValue(payload, "n"));
  }

  let netShares = 0;
  let hasShares = false;
  let netNotional = 0;
  let hasNotional = false;
  const buyers = new Set<string>();
  const sellers = new Set<string>();
  let latestTs = 0;

  for (const row of rows) {
    const rowDirection = inferDirection(row);
    const sharesRaw = readValueWithAliases(row, "shares");
    const signedShares = withSignedDirection(sharesRaw, rowDirection);
    const signedSharesOrRaw = signedShares ?? toFiniteNumber(sharesRaw);
    const rawValue = readValueWithAliases(row, "value");
    const rowNotional = withSignedDirection(rawValue, rowDirection);
    const sharesForEstimate = signedSharesOrRaw;
    const priceForEstimate = readValueWithAliases(row, "price");

    if (signedShares != null || toFiniteNumber(sharesRaw) != null) {
      const resolvedShares = signedSharesOrRaw ?? 0;
      const direction = rowDirection === 0 && resolvedShares > 0 ? 1 : rowDirection === 0 && resolvedShares < 0 ? -1 : rowDirection;
      netShares += resolvedShares;
      hasShares = true;

      const person = rowParticipant(row);
      if (person != null) {
        if (direction > 0) {
          buyers.add(person);
        } else if (direction < 0) {
          sellers.add(person);
        }
      }
    }

    if (rowNotional != null) {
      netNotional += rowNotional;
      hasNotional = true;
    } else if (sharesForEstimate != null && sharesForEstimate !== 0 && priceForEstimate != null) {
      const parsedPrice = toFiniteNumber(priceForEstimate);
      if (parsedPrice != null) {
        netNotional += sharesForEstimate * parsedPrice;
        hasNotional = true;
      }
    }

    const txDate = readValueWithAliases(row, "transaction_date");
    const parsedDate = toFiniteNumber(txDate);
    if (parsedDate != null && !Number.isNaN(parsedDate)) {
      latestTs = Math.max(latestTs, parsedDate);
    } else {
      const parsed = new Date(String(txDate ?? "")).getTime();
      if (!Number.isNaN(parsed)) {
        latestTs = Math.max(latestTs, parsed);
      }
    }
  }

  if (hasShares) {
    derived.net_shares = netShares;
  } else {
    const directNetShares = toFiniteNumber(readValue(payload, "net_shares"));
    if (directNetShares != null) derived.net_shares = directNetShares;
  }

  if (hasNotional) {
    derived.net_notional = netNotional;
  } else {
    const directNetNotional = toFiniteNumber(readValue(payload, "net_notional"));
    if (directNetNotional != null) derived.net_notional = directNetNotional;
  }

  if (buyers.size > 0) {
    derived.buyer_count = buyers.size;
  } else {
    const directBuyerCount = toFiniteNumber(readValue(payload, "buyer_count"));
    if (directBuyerCount != null) derived.buyer_count = directBuyerCount;
  }

  if (sellers.size > 0) {
    derived.seller_count = sellers.size;
  } else {
    const directSellerCount = toFiniteNumber(readValue(payload, "seller_count"));
    if (directSellerCount != null) derived.seller_count = directSellerCount;
  }

  if (rows.length > 0 && latestTs > 0) {
    derived.as_of = new Date(latestTs).toISOString();
  }

  if (readValue(payload, "data_mode") == null) {
    const status = readValue(payload, "status");
    if (typeof status === "string") {
      derived.data_mode = status === "ok" ? "live_official" : status;
    } else if (typeof readValue(payload, "source_mode") === "string") {
      derived.data_mode = readValue(payload, "source_mode");
    } else {
      const sources = readValue(payload, "sources");
      if (Array.isArray(sources) && sources.length > 0 && typeof sources[0] === "string") {
        derived.data_mode = sources[0];
      }
    }
  }

  return derived;
}

function extractFormatPrecision(format: string | null): number | null {
  if (!format) return null;
  const match = format.match(/%\.(\d+)f/);
  if (match == null) return null;
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatDateValue(value: unknown): ReactNode {
  if (typeof value !== "string" && typeof value !== "number") return formatMissing;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

function formatDateTimeValue(value: unknown): ReactNode {
  if (typeof value !== "string" && typeof value !== "number") return formatMissing;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDuration(ms: unknown): ReactNode {
  const secs = toFiniteNumber(ms);
  if (secs == null) return formatMissing;
  if (secs < 60) return `${secs}s`;
  const mins = secs / 60;
  if (mins < 60) return `${mins.toFixed(0)}m`;
  const hrs = mins / 60;
  if (hrs < 24) return `${hrs.toFixed(1)}h`;
  const days = hrs / 24;
  if (days < 365) return `${days.toFixed(1)}d`;
  return `${(days / 365).toFixed(2)}y`;
}

function formatUnknown(value: unknown): ReactNode {
  if (value == null) return formatMissing;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (value instanceof Date) return value.toISOString();
  if (Array.isArray(value)) return value.map((v) => String(v)).join(", ");
  try {
    return JSON.stringify(value);
  } catch {
    return formatMissing;
  }
}

function renderValueForKind(value: unknown, kind: ColumnKind, format: string | null, unit: string | null): ReactNode {
  if (value == null || value === "") return formatMissing;
  const numberValue = toFiniteNumber(value);
  const digits = extractFormatPrecision(format);
  if (kind === "action") {
    if (isUrl(value)) {
      return (
        <a href={String(value)} target="_blank" rel="noreferrer" className="u-text-accent">
          open
        </a>
      );
    }
    if (typeof value === "string" && value.startsWith("http")) {
      return (
        <a href={value} target="_blank" rel="noreferrer" className="u-text-accent">
          open
        </a>
      );
    }
    return String(value);
  }
  if (kind === "number") {
    if (numberValue == null) return formatMissing;
    const precision = digits ?? 0;
    return formatNumber(numberValue, precision);
  }
  if (kind === "percent") {
    if (numberValue == null) return formatMissing;
    return formatPercent(numberValue, { digits: digits ?? 2, signed: false });
  }
  if (kind === "currency") {
    if (numberValue == null) return formatMissing;
    return formatCurrency(numberValue, {
      compact: Math.abs(numberValue) >= 1_000_000,
      fractionDigits: digits ?? 0,
    });
  }
  if (kind === "duration") return formatDuration(numberValue);
  if (kind === "date") return formatDateValue(value);
  if (kind === "datetime") return formatDateTimeValue(value);
  if (kind === "tag") {
    const text = typeof value === "string" ? value : String(value);
    return (
      <Pill tone="neutral" variant="soft">
        {text}
      </Pill>
    );
  }
  const str = typeof value === "string" ? value : String(value);
  if (isUrl(str)) {
    return (
      <a href={str} target="_blank" rel="noreferrer" className="u-text-accent">
        open
      </a>
    );
  }
  if (unit) return `${str} ${unit}`;
  return unit == null ? formatUnknown(value) : `${formatUnknown(value)} ${unit}`;
}

function buildColumns(schema: TableSchema): DataGridColumn<RowRecord>[] {
  return schema.columns.map((col) => ({
    key: col.key,
    header: col.label,
    width: col.width_hint ?? undefined,
    align: ["number", "currency", "percent"].includes(col.kind) ? "right" : "left",
    numeric: ["number", "currency", "percent"].includes(col.kind),
    render: (row: RowRecord) => {
      const raw = readValueWithAliases(row, col.key);
      const normalized = normalizeValueKey(col.key);
      if (isTransactionTypeKey(col.key)) {
        return renderTransactionTypePill(raw);
      }
      if (col.kind === "number") {
        return renderValueForKind(maybeSignedNumeric(raw, row, normalized), col.kind, col.format, col.unit);
      }
      if (col.kind === "currency" && (normalized === "value" || normalized === "notional" || normalized === "price")) {
        return renderValueForKind(maybeSignedNumeric(raw, row, normalized), col.kind, col.format, col.unit);
      }
      return renderValueForKind(raw, col.kind, col.format, col.unit);
    },
  }));
}

function resolveRowKey(row: RowRecord, idx: number): string {
  const direct = readValue(row, "id") ??
    readValue(row, "symbol") ??
    readValue(row, "ticker") ??
    readValue(row, "filer") ??
    readValue(row, "date") ??
    readValue(row, "filingDate") ??
    readValue(row, "timestamp") ??
    readValue(row, "time") ??
    readValue(row, "period");
  if (direct != null && direct !== "") return `${idx}-${String(direct)}`;
  return `${idx}-${String(Object.keys(row)[0] ?? "row")}`;
}

function rowScoreForSchema(row: RowRecord, schemaKeys: Set<string>): number {
  return Object.keys(row).reduce((acc, key) => (schemaKeys.has(normalizeValueKey(key)) ? acc + 1 : acc), 0);
}

function resolveRows(payload: ManifestPayload, schema: TableSchema): RowRecord[] {
  if (payload == null) return [];
  const root = payload as RowRecord;
  if (Object.prototype.hasOwnProperty.call(root, "rows") && Array.isArray(root.rows)) {
    return root.rows.filter((row): row is RowRecord => isRecord(row)) as RowRecord[];
  }

  const preferredRowsKeys = [
    "items",
    "records",
    "data",
    "positions",
    "holdings",
    "events",
    "news",
    "trades",
    "signals",
    "filings",
    "series",
    "cells",
  ];
  for (const key of preferredRowsKeys) {
    if (Array.isArray(root[key]) && root[key]!.every((item) => isRecord(item))) {
      return root[key]!.filter((row): row is RowRecord => isRecord(row)) as RowRecord[];
    }
  }

  const schemaKeys = new Set(schema.columns.map((col) => normalizeValueKey(col.key)));
  let bestRows: RowRecord[] | null = null;
  let bestScore = -1;
  for (const value of Object.values(root)) {
    if (!Array.isArray(value) || value.length === 0 || !isRecord(value[0])) continue;
    const rows = value.filter((row) => isRecord(row)) as RowRecord[];
    if (rows.length === 0) continue;
    const score = rows.reduce(
      (acc, item) => acc + rowScoreForSchema(item, schemaKeys),
      0,
    );
    if (score > bestScore) {
      bestScore = score;
      bestRows = rows;
    }
  }
  if (bestRows) return bestRows;

  for (const value of Object.values(root)) {
    if (Array.isArray(value) && value.every((row) => isRecord(row))) return value as RowRecord[];
  }
  return [];
}

function formatCardValue(slot: CardSlot, raw: unknown): ReactNode {
  if (raw == null || raw === "") return formatMissing;
  if (slot.kind === "trend_pill") {
    const n = toFiniteNumber(raw);
    if (n == null) return String(raw);
    if (slot.unit === "%") return formatPercent(n, { digits: 2, signed: true });
    const sign = n > 0 ? "+" : n < 0 ? "-" : "";
    const abs = Math.abs(n);
    const digits = Number.isInteger(abs) ? 0 : 2;
    const nText = n.toFixed(digits);
    return `${sign}${nText}${slot.unit ? ` ${slot.unit}` : ""}`;
  }
  if (slot.kind === "mode_pill") {
    if (typeof raw === "string") return raw.toUpperCase();
    return String(raw);
  }
  if (slot.kind === "timestamp") {
    if (typeof raw === "string" || typeof raw === "number") return formatDateTimeValue(raw);
    return String(raw);
  }
  const n = toFiniteNumber(raw);
  if (typeof raw === "number" || n != null) {
    if (slot.unit === "%" && n != null) return formatPercent(n);
    if (slot.unit === "quote_ccy" && n != null) {
      return formatCurrency(n, { compact: true, fractionDigits: 2, currency: "USD" });
    }
    if (slot.unit === "USD" && n != null) return formatCurrency(n, { compact: true, fractionDigits: 2, currency: "USD" });
    if (n != null) return formatCompactNumber(n);
  }
  const text = typeof raw === "string" ? raw : String(raw);
  return slot.unit ? `${text} ${slot.unit}` : text;
}

function formatModePill(raw: unknown): string {
  if (raw == null) return formatMissing;
  const mode = String(raw).trim().toLowerCase();
  return MODE_PILL_LABEL[mode] ?? String(raw).toUpperCase();
}

function cardToneForMode(raw: unknown): "neutral" | "positive" | "negative" | "warn" | "muted" {
  const text = String(raw ?? "").toLowerCase();
  if (text.includes("live") && !text.includes("not")) return "positive";
  if (text.includes("modeled") || text.includes("cached")) return "warn";
  if (text.includes("provider") || text.includes("unavailable")) return "negative";
  return "neutral";
}

function renderCardSlot(
  slot: CardSlot,
  payload: Record<string, unknown>,
  derived: Record<string, unknown>,
): JSX.Element | null {
  const raw = readCardValue(payload, slot.key, derived);
  const title = slot.label || slot.key;
  const value = slot.kind === "mode_pill" ? formatModePill(raw) : formatCardValue(slot, raw);
  const rightSlot =
    slot.kind === "trend_pill"
      ? <Pill tone={toFiniteNumber(raw) == null ? "neutral" : toFiniteNumber(raw)! > 0 ? "positive" : toFiniteNumber(raw)! < 0 ? "negative" : "neutral"}>{value}</Pill>
      : null;

  if (slot.kind === "trend_pill") {
    return (
      <StatCard
        label={title}
        value={value}
        rightSlot={rightSlot}
        tone={toFiniteNumber(raw) == null ? "neutral" : toFiniteNumber(raw)! > 0 ? "positive" : toFiniteNumber(raw)! < 0 ? "negative" : "neutral"}
      />
    );
  }
  if (slot.kind === "mode_pill") {
    const modeTone = cardToneForMode(raw);
    return (
      <StatCard
        label={title}
        value={value}
        tone={modeTone === "positive" ? "positive" : modeTone === "warn" || modeTone === "negative" ? "negative" : "neutral"}
      />
    );
  }
  if (slot.kind === "badge") {
    return (
      <div style={{ padding: "6px 0" }}>
        <div style={{ fontSize: 10, opacity: 0.75 }}>{title}</div>
        <Pill tone="neutral">{value}</Pill>
      </div>
    );
  }
  return <StatCard label={title} value={value} />;
}

function deriveChartPointCount(payload: ManifestPayload): number {
  const root = toPayload(payload);
  for (const key of ["series", "rows", "data", "items", "values"]) {
    const value = root[key];
    if (!Array.isArray(value)) continue;
    if (value.every((item) => isRecord(item))) return value.length;
    return value.filter((item) => item != null).length;
  }
  return 0;
}

// ---------------------------------------------------------------------------
// Concrete renderer implementations.
// ---------------------------------------------------------------------------

function chartRendererFor(kind: ChartKind): ChartRenderer {
  return function ManifestChart({
    grammar,
    payload,
  }): JSX.Element {
    const pointCount = deriveChartPointCount(payload);
    return (
      <div
        data-renderer-category="chart"
        data-renderer-kind={kind}
        data-overlay-support={grammar.overlay_support ? "1" : "0"}
        data-compare-support={grammar.compare_support ? "1" : "0"}
        data-pane-count={grammar.panes.length}
        style={{
          padding: 12,
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          background: "var(--bg-elev-2)",
          display: "grid",
          gap: 8,
        }}
      >
        <strong style={MANIFEST_SECTION_TITLE_STYLE}>Chart</strong>
        <div style={{ color: "var(--text-mute)", fontSize: 12 }}>
          {pointCount > 0 ? `${kind.replace(/_/g, " ")} · ${pointCount} points` : `${kind.replace(/_/g, " ")} · no chart data in payload`}
        </div>
      </div>
    );
  };
}

function tableRenderer(): TableRenderer {
  return function ManifestTable({ schema, payload }): JSX.Element {
    const rows = sortRowsByDateDesc(resolveRows(payload, schema), schema);
    const columns = buildColumns(schema);
    if (rows.length === 0) {
      return (
        <div
          data-renderer-category="table"
          data-renderer-kind="table"
          data-column-count={schema.columns.length}
          data-sortable={schema.sortable ? "1" : "0"}
          data-filterable={schema.filterable ? "1" : "0"}
          style={MANIFEST_SECTION_STYLE}
        >
          <strong style={MANIFEST_SECTION_TITLE_STYLE}>Rows</strong>
          <Empty title="No table rows" body="This function returned an empty payload." />
        </div>
      );
    }
    return (
      <div
        data-renderer-category="table"
        data-renderer-kind="table"
        data-column-count={schema.columns.length}
        style={MANIFEST_SECTION_STYLE}
      >
        <strong style={MANIFEST_SECTION_TITLE_STYLE}>Rows</strong>
        <div style={MANIFEST_TABLE_STYLE}>
          <DataGrid
            columns={columns}
            rows={rows}
            rowKey={(row, idx) => resolveRowKey(row, idx)}
            ariaLabel="Function table"
            virtualize={rows.length > 200}
            empty={<span>No rows</span>}
          />
        </div>
      </div>
    );
  };
}

function cardsRenderer(): CardsRenderer {
  return function ManifestCards({ schema, payload }): JSX.Element {
    const payloadObj = toPayload(payload);
    const derived = buildDerivedCardValues(payloadObj);
    if (schema.slots.length === 0) {
      return (
        <div
          data-renderer-category="cards"
          data-renderer-kind="cards"
          data-slot-count={schema.slots.length}
          style={MANIFEST_SECTION_STYLE}
        >
          <strong style={MANIFEST_SECTION_TITLE_STYLE}>Summary</strong>
          <Empty title="No cards configured" />
        </div>
      );
    }
    return (
      <div
        data-renderer-category="cards"
        data-renderer-kind="cards"
        data-slot-count={schema.slots.length}
        style={MANIFEST_SECTION_STYLE}
      >
        <strong style={MANIFEST_SECTION_TITLE_STYLE}>Summary</strong>
        <div style={MANIFEST_CARD_STYLE}>
          {schema.slots.map((slot) => (
            <div key={slot.key} style={{ minWidth: 0 }}>
              {renderCardSlot(slot, payloadObj, derived)}
            </div>
          ))}
        </div>
      </div>
    );
  };
}

export function pickRenderer(manifest: FunctionManifest): RendererPicker {
  return {
    chart: manifest.chart_grammar ? chartRendererFor(manifest.chart_grammar.kind) : null,
    table: manifest.table_schema ? tableRenderer() : null,
    cards: manifest.card_schema ? cardsRenderer() : null,
  };
}

export default pickRenderer;
