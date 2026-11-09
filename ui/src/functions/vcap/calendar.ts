import type { CoverageSeries, Observation, Payload, Query } from "./types";

export type CalendarQuery = Pick<Query, "start_year" | "end_year" | "frequency"> &
  Partial<Pick<Query, "unit">>;

export function calendarPeriods(query: CalendarQuery): string[] {
  const currentYear = new Date().getFullYear();
  const start = Math.max(1900, Math.min(currentYear, Math.trunc(query.start_year)));
  const end = Math.min(currentYear, Math.trunc(query.end_year));
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
  return Array.from({ length: end - start + 1 }, (_, i) => String(start + i)).flatMap(
    (year) =>
      query.frequency === "quarterly" ? [1, 2, 3, 4].map((q) => `${year}-Q${q}`) : [year],
  );
}

export function coverageKey(series: Pick<CoverageSeries, "source_id" | "geography">) {
  return `${series.source_id}|${series.geography}`;
}

// API coverage describes the whole matching release before the date filter. An older
// backend can only establish returned-row coverage; do not infer broader availability.
export function selectedCoverage(payload: Payload, query: Query): CoverageSeries[] {
  const entries = new Map(
    payload.coverage?.series.map((series) => [coverageKey(series), series]),
  );
  return query.source_ids.flatMap((source_id) =>
    query.geographies.map((geography) => {
      const authoritative = entries.get(`${source_id}|${geography}`);
      if (authoritative) return authoritative;
      const rows = payload.coverage
        ? []
        : payload.rows.filter(
            (row) => row.source_id === source_id && row.geography === geography,
          );
      const periods = [...new Set(rows.map((row) => row.period))].sort();
      return {
        source_id,
        geography,
        source_name:
          payload.sources.find((source) => source.source_id === source_id)?.source_name ??
          rows[0]?.source_name ??
          source_id,
        first_period: periods[0] ?? null,
        last_period: periods.at(-1) ?? null,
        periods,
        snapshot_id: rows[0]?.snapshot_id,
        published_at: rows[0]?.published_at,
      };
    }),
  );
}

export function unavailablePeriod(series: CoverageSeries, period: string) {
  if (!series.first_period || !series.last_period) return "No matching source coverage";
  if (period < series.first_period) return `Unavailable before ${series.first_period}`;
  if (period > series.last_period) return `Unavailable after ${series.last_period}`;
  return "Not reported";
}

export function observationIndex(rows: Observation[]) {
  return new Map(rows.map((row) => [`${coverageKey(row)}|${row.period}`, row]));
}
