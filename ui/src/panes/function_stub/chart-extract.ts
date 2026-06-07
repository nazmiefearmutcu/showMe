import type { IChartApi, Time } from "lightweight-charts";
import {
  CHART_KEYS,
  NUMERIC_X_KEYS,
  TIME_KEYS,
  VALUE_KEYS,
  type ChartPoint,
  type ChartSeries,
  type RecordRow,
} from "./_types";

export function extractChartSeries(data: unknown, fallbackRows: RecordRow[]): ChartSeries | null {
  const candidates = collectChartCandidates(data);
  if (fallbackRows.length > 1) candidates.push({ title: "rows", rows: fallbackRows });

  const ranked = candidates
    .map((candidate) => {
      const series = rowsToChartSeries(candidate.rows, candidate.title);
      if (!series) return null;
      const priority = CHART_KEYS.indexOf(candidate.title);
      const surfaceLike = /heat|map|surface|matrix/i.test(candidate.title);
      const score =
        (series.kind === "ohlc" ? 80 : series.kind === "curve" ? 72 : series.kind === "line" ? 60 : series.kind === "heatmap" ? 48 : 30) +
        (priority >= 0 ? 30 - priority : 0) +
        (surfaceLike && series.kind === "heatmap" ? 40 : 0) +
        (candidate.rows.length > 20 ? 12 : 0) +
        (VALUE_KEYS.includes(series.yKey) ? 10 : 0);
      return { series, score };
    })
    .filter((item): item is { series: ChartSeries; score: number } => Boolean(item))
    .sort((a, b) => b.score - a.score);

  return ranked[0]?.series ?? null;
}

export function collectChartCandidates(data: unknown): Array<{ title: string; rows: RecordRow[] }> {
  const candidates: Array<{ title: string; rows: RecordRow[] }> = [];
  const visit = (value: unknown, title: string, depth: number) => {
    if (depth > 4) return;
    if (Array.isArray(value)) {
      if (value.length > 1) {
        const rows = value.map(objectify);
        if (rows.some((row) => Object.values(row).some((item) => toFiniteNumber(item) !== null))) {
          candidates.push({ title, rows });
        }
      }
      return;
    }
    if (!isRecord(value)) return;
    for (const key of CHART_KEYS) {
      if (key in value) visit(value[key], key, depth + 1);
    }
    for (const [key, nested] of Object.entries(value)) {
      if (CHART_KEYS.includes(key)) continue;
      if (Array.isArray(nested) || isRecord(nested)) visit(nested, key, depth + 1);
    }
  };
  visit(data, "payload", 0);
  return candidates;
}

export function rowsToChartSeries(rows: RecordRow[], title: string): ChartSeries | null {
  if (rows.length < 2) return null;
  const fields = collectFields(rows);
  const xKey = TIME_KEYS.find((key) => fields.includes(key)) ?? null;
  const labelKey = pickLabelKey(fields);
  const numericKeys = fields.filter((field) =>
    rows.some((row) => toFiniteNumber(row[field]) !== null),
  );
  const yKey =
    VALUE_KEYS.find((key) => numericKeys.includes(key)) ??
    numericKeys.find((key) => key !== xKey) ??
    null;
  if (!yKey) return null;
  const ohlc = rowsHaveOhlc(fields);
  const timePoints = xKey ? rowsToTimePoints(rows, xKey, yKey, ohlc) : [];
  const titleLabel = title.toLowerCase() === "rows" && xKey ? humanizeKey(xKey) : humanizeKey(title);
  if (/heat|map|surface|matrix/i.test(title)) {
    const surfaceLabelKey =
      ["exchange", "market", "name", "tenor", "tenor_years", "maturity", "country", "sector", "bucket", "symbol", "scenario", "metric"].find((key) =>
        fields.includes(key),
      ) ??
      labelKey ??
      xKey;
    const points = rows
      .map((row, idx) => {
        const y = toFiniteNumber(row[yKey]);
        if (y === null) return null;
        const timeLabel = xKey ? formatAxisLabel(row[xKey], idx) : null;
        const surfaceLabel = surfaceLabelKey ? formatAxisLabel(row[surfaceLabelKey], idx) : String(idx + 1);
        const xLabel = timeLabel && surfaceLabelKey && surfaceLabelKey !== xKey
          ? `${timeLabel} · ${surfaceLabel}`
          : surfaceLabel;
        return { xLabel, y };
      })
      .filter((point): point is ChartPoint => Boolean(point));
    if (points.length >= 2) {
      return {
        kind: "heatmap",
        title: `${humanizeKey(title)} · ${humanizeKey(yKey)}`,
        rows,
        xKey: null,
        labelKey: surfaceLabelKey,
        yKey,
        points,
      };
    }
  }
  if (ohlc && timePoints.length >= 2) {
    return {
      kind: "ohlc",
      title: `${titleLabel} · OHLC`,
      rows,
      xKey,
      labelKey,
      yKey: "close",
      points: timePoints,
    };
  }
  if (timePoints.length >= 2) {
    return {
      kind: "line",
      title: `${titleLabel} · ${humanizeKey(yKey)}`,
      rows,
      xKey,
      labelKey,
      yKey,
      points: timePoints,
    };
  }
  const numericXKey =
    NUMERIC_X_KEYS.find((key) => key !== yKey && fields.includes(key) && numericKeys.includes(key)) ??
    null;
  if (numericXKey && /curve|frontier|sensitivity|pnl/i.test(title)) {
    const points: Array<ChartPoint & { x: number }> = rows
      .map((row) => {
        const x = toFiniteNumber(row[numericXKey]);
        const y = toFiniteNumber(row[yKey]);
        if (x === null || y === null) return null;
        return { x, xLabel: formatValueShort(x), y };
      })
      .filter((point): point is ChartPoint & { x: number } => point !== null)
      .sort((a, b) => Number(a.x) - Number(b.x));
    if (points.length >= 3) {
      return {
        kind: "curve",
        title: `${humanizeKey(title)} · ${humanizeKey(yKey)}`,
        rows,
        xKey: numericXKey,
        labelKey,
        yKey,
        points,
      };
    }
  }
  if (!labelKey) return null;
  const points = rows
    .map((row, idx) => {
      const y = toFiniteNumber(row[yKey]);
      if (y === null) return null;
      const xRaw = row[labelKey];
      return { xLabel: formatAxisLabel(xRaw, idx), y };
    })
    .filter((point): point is ChartPoint => Boolean(point));
  if (points.length < 2) return null;
  const heatmap =
    /heat|map|sector|surface|matrix/i.test(title) ||
    ["country", "sector"].includes(labelKey.toLowerCase());
  return {
    kind: heatmap ? "heatmap" : "bar",
    title: `${humanizeKey(title)} · ${humanizeKey(yKey)}`,
    rows,
    xKey: null,
    labelKey,
    yKey,
    points,
  };
}

export function rowsToTimePoints(
  rows: RecordRow[],
  xKey: string,
  yKey: string,
  ohlc: boolean,
): ChartPoint[] {
  const points: Array<ChartPoint | null> = rows
    .map((row, idx) => {
      const time = normalizeChartTime(row[xKey]);
      if (!time) return null;
      if (ohlc) {
        const open = toFiniteNumber(row.open);
        const high = toFiniteNumber(row.high);
        const low = toFiniteNumber(row.low);
        const close = toFiniteNumber(row.close);
        if (open === null || high === null || low === null || close === null) return null;
        return {
          xLabel: formatAxisLabel(row[xKey], idx),
          y: close,
          time,
          open,
          high,
          low,
          close,
          volume: toFiniteNumber(row.volume) ?? undefined,
        };
      }
      const y = toFiniteNumber(row[yKey]);
      if (y === null) return null;
      const compareY = toFiniteNumber(row["compare_value"]);
      return {
        xLabel: formatAxisLabel(row[xKey], idx),
        y,
        time,
        ...(compareY !== null ? { compareY } : {}),
      };
    })
  return points
    .filter((point): point is ChartPoint => point !== null)
    .sort((a, b) => chartTimeSortValue(a.time) - chartTimeSortValue(b.time));
}

export function rowsHaveOhlc(fields: string[]): boolean {
  return ["open", "high", "low", "close"].every((field) => fields.includes(field));
}

export function rowsLookLikeOhlc(rows: RecordRow[]): boolean {
  return rows.length > 0 && rowsHaveOhlc(collectFields(rows));
}

export function pickLabelKey(fields: string[]): string | null {
  const labels = [
    "label",
    "symbol",
    "ticker",
    "country",
    "sector",
    "scenario",
    "account",
    "pair",
    "tenor",
    "strike",
    "expiry",
    "option_type",
    "leg",
    "feature",
    "factor",
    "component",
    "risk_factor",
    "window_days",
    "name",
    "asset",
    "etf",
    "metric",
    "bucket",
    "base",
    "quote",
  ];
  return labels.find((field) => fields.includes(field)) ?? null;
}

export function normalizeChartTime(value: unknown): Time | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return (value > 10_000_000_000 ? Math.floor(value / 1000) : value) as Time;
  }
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  // lightweight-charts only accepts strict yyyy-mm-dd or a unix-seconds number.
  // RFC 822 inputs like "Sat, 09 May 2024 12:00:00 -0400" used to slip through
  // the old slice(0,10) heuristic as "Sat, 09 Ma" and crash setData().
  const isoDateMatch = trimmed.match(/^(\d{4}-\d{2}-\d{2})(?:[T ]|$)/);
  if (isoDateMatch && !trimmed.includes("T") && !/\d{2}:\d{2}/.test(trimmed)) {
    return isoDateMatch[1] as Time;
  }
  const date = new Date(trimmed);
  if (Number.isNaN(date.getTime())) return null;
  return Math.floor(date.getTime() / 1000) as Time;
}

export function chartTimeSortValue(value: Time | null | undefined): number {
  if (typeof value === "number") return value;
  if (!value) return 0;
  return Date.parse(String(value)) || 0;
}

export function hasOhlcPoint(
  point: ChartPoint,
): point is ChartPoint & {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
} {
  return Boolean(
    point.time != null &&
      Number.isFinite(Number(point.open)) &&
      Number.isFinite(Number(point.high)) &&
      Number.isFinite(Number(point.low)) &&
      Number.isFinite(Number(point.close)),
  );
}

export function hasTimePoint(point: ChartPoint): point is ChartPoint & { time: Time } {
  return point.time != null;
}

export function hasVolumePoint(
  point: ChartPoint,
): point is ChartPoint & { time: Time; volume: number } {
  return point.time != null && Number.isFinite(Number(point.volume));
}

export function collectFields(rows: RecordRow[]): string[] {
  const fields = new Set<string>();
  for (const row of rows.slice(0, 50)) {
    for (const key of Object.keys(row)) fields.add(key);
  }
  return [...fields];
}

export function objectify(value: unknown): RecordRow {
  if (isRecord(value)) return value;
  return { value };
}

export function focusLatestBars(chart: IChartApi, count: number, width: number): void {
  if (count <= 0) return;
  const visible = Math.max(80, Math.min(220, Math.floor(width / 7)));
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(0, count - visible),
    to: count + 8,
  });
}

export function isRecord(value: unknown): value is RecordRow {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const cleaned = value.replace(/[%,$\s]/g, "");
  if (!cleaned) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatAxisLabel(value: unknown, idx: number): string {
  if (typeof value === "string" && value.trim()) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime()) && /\d{4}-\d{2}-\d{2}|T/.test(value)) {
      return date.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
    }
    return value.length > 18 ? value.slice(0, 18) : value;
  }
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return String(idx + 1);
}

export function humanizeKey(value: string): string {
  return value.replace(/_/g, " ");
}

// Compact format-value used internally (avoids dep on helpers.tsx).
function formatValueShort(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 6 });
}
