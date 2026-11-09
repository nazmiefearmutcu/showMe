import type { Observation, Payload } from "./types";

function backendSeriesId(row: Observation) {
  return [
    row.source_id,
    row.scope,
    row.geography,
    row.metric,
    row.frequency,
    row.stage,
    row.unit,
    row.sector ?? "",
    row.geography_basis ?? "",
    row.date_basis ?? "",
    row.financing_scope ?? "vc",
  ].join("|");
}
/** A difference is permitted only by a backend comparable pair, on a shared period. */
export function latestComparableDifference(payload: Payload, left: string, right: string) {
  if (
    !payload.comparison?.comparable_pairs.some(
      (pair) => pair.left === left && pair.right === right,
    )
  )
    return null;
  const leftRows = new Map(
    payload.rows
      .filter(
        (row) =>
          backendSeriesId(row) === left &&
          typeof row.value === "number" &&
          Number.isFinite(row.value),
      )
      .map((row) => [row.period, row]),
  );
  const matched = payload.rows
    .filter(
      (row) =>
        backendSeriesId(row) === right &&
        leftRows.has(row.period) &&
        typeof row.value === "number" &&
        Number.isFinite(row.value),
    )
    .sort((a, b) => b.period.localeCompare(a.period));
  const last = matched[0];
  if (!last) return null;
  const first = leftRows.get(last.period)!;
  const difference = last.value! - first.value!;
  if (!Number.isFinite(difference)) return null;
  return { period: last.period, value: difference, unit: last.unit };
}
