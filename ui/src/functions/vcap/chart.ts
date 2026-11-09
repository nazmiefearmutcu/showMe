import type { Observation } from "./types";
import { calendarPeriods, type CalendarQuery } from "./calendar";

export const CHART_COLORS = [
  "var(--accent)",
  "#62a8d9",
  "#b98cd6",
  "#7ba98a",
  "#da9572",
  "#a9a35b",
  "#d47c9b",
  "#65b6b4",
];
export function periodTime(row: Pick<Observation, "period">): number | null {
  const match = /^(\d{4})(?:-Q([1-4]))?$/.exec(row.period);
  if (!match || +match[1] < 1900 || +match[1] > 2100) return null;
  return Date.UTC(+match[1], match[2] ? (+match[2] - 1) * 3 : 0, 1);
}
export function seriesKey(row: Observation) {
  return `${row.source_id}|${row.geography}|${row.stage}`;
}
export function exactValue(row: Observation) {
  return typeof row.value === "number" && Number.isFinite(row.value)
    ? `${row.value} ${row.unit}`
    : "Missing";
}
export function axisValue(value: number) {
  const digits =
    value > 0 && value < 1
      ? Math.min(8, Math.max(2, 1 - Math.floor(Math.log10(value))))
      : 2;
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}
export function chartGeometry(rows: Observation[], query?: CalendarQuery) {
  const width = 960,
    height = 290,
    left = 88,
    right = 20,
    top = 28,
    bottom = 48;
  const calendar = query ? calendarPeriods(query) : [];
  const points = rows
    .flatMap((row) => {
      const time = periodTime(row);
      return time === null || (query && !calendar.includes(row.period))
        ? []
        : [{ row, time }];
    })
    .sort((a, b) => a.time - b.time || seriesKey(a.row).localeCompare(seriesKey(b.row)));
  const series = [
    ...new Map(
      points.map(({ row }) => [
        seriesKey(row),
        {
          id: seriesKey(row),
          label: `${row.source_name} / ${row.geography} / ${row.stage}`,
        },
      ]),
    ).values(),
  ];
  const periods = query ? calendar : [...new Set(points.map((point) => point.row.period))];
  const times = periods.map((period) => periodTime({ period })!);
  const min = times[0] ?? Date.UTC(2025, 0, 1);
  const max = times[times.length - 1] ?? min;
  const nominal = (
    query
      ? query.frequency === "quarterly"
      : rows.some((row) => row.frequency === "quarterly")
  )
    ? 91.3125 * 86400000
    : 365.25 * 86400000;
  const rangeStart = min - nominal * 0.5,
    span = max - min + nominal;
  const plotWidth = width - left - right,
    plotHeight = height - top - bottom;
  const maxValue = points.reduce(
    (largest, { row }) =>
      typeof row.value === "number" && Number.isFinite(row.value)
        ? Math.max(largest, row.value)
        : largest,
    0,
  );
  const ceiling = maxValue || 1;
  const unit = rows[0]?.unit ?? query?.unit ?? "USD";
  const divisor = unit === "USD" ? (maxValue >= 1e9 ? 1e9 : maxValue >= 1e6 ? 1e6 : 1) : 1;
  const axisLabel =
    unit === "USD"
      ? divisor === 1e9
        ? "USD billions"
        : divisor === 1e6
          ? "USD millions"
          : "USD"
      : unit === "COUNT"
        ? "Deal count"
        : "% GDP";
  const groupWidth = Math.min(70, (nominal / span) * plotWidth * 0.72);
  const barWidth = Math.max(0.3, groupWidth / Math.max(series.length, 1));
  const x = (time: number) => left + ((time - rangeStart) / span) * plotWidth;
  const marks = points.map(({ row, time }) => {
    const index = series.findIndex((item) => item.id === seriesKey(row));
    const valid =
      typeof row.value === "number" && Number.isFinite(row.value) && row.value >= 0;
    const barHeight = valid ? ((row.value as number) / ceiling) * plotHeight : 0;
    return {
      row,
      x: x(time) - groupWidth / 2 + index * barWidth,
      y: top + plotHeight - barHeight,
      width: Math.max(0.3, barWidth - 1),
      height: barHeight,
      missing: !valid,
      color: CHART_COLORS[index % CHART_COLORS.length],
    };
  });
  const tickStep = Math.max(1, Math.ceil(times.length / 8));
  const ticks = times
    .filter((_, i) => i % tickStep === 0 || i === times.length - 1)
    .map((time) => ({
      x: x(time),
      label: periods[times.indexOf(time)],
    }));
  return {
    width,
    height,
    left,
    right,
    top,
    bottom,
    plotHeight,
    marks,
    series,
    ticks,
    ceiling,
    divisor,
    axisLabel,
  };
}
