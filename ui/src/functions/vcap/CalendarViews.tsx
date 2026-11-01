import { useMemo, useState } from "react";
import {
  calendarPeriods,
  coverageKey,
  observationIndex,
  selectedCoverage,
  unavailablePeriod,
} from "./calendar";
import { exactValue } from "./chart";
import type { CoverageSeries, Payload, Query } from "./types";

const PERIOD_PAGE = 32;
const SERIES_PAGE = 6;

function PageButtons({
  page,
  pages,
  onPage,
  label,
}: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
  label: string;
}) {
  return (
    <div className="vcap-actions">
      <span>
        {label} page {page + 1} of {pages}
      </span>
      <button className="btn" disabled={page === 0} onClick={() => onPage(page - 1)}>
        Previous {label}
      </button>
      <button className="btn" disabled={page >= pages - 1} onClick={() => onPage(page + 1)}>
        Next {label}
      </button>
    </div>
  );
}

function CoverageExplanation({
  series,
  query,
  authoritative,
}: {
  series: CoverageSeries[];
  query: Query;
  authoritative: boolean;
}) {
  const [page, setPage] = useState(0);
  const periods = calendarPeriods(query);
  const requestedStart = periods[0] ?? "";
  const requestedEnd = periods.at(-1) ?? "";
  const pages = Math.max(1, Math.ceil(series.length / SERIES_PAGE));
  const current = Math.min(page, pages - 1);
  return (
    <section
      className="vcap-coverage-summary"
      data-testid="vcap-coverage-summary"
      aria-label="Requested and available source coverage"
    >
      <div className="vcap-section-title">
        <h3>
          Source coverage · requested {query.start_year}–{query.end_year}
        </h3>
        {pages > 1 && (
          <PageButtons page={current} pages={pages} onPage={setPage} label="coverage" />
        )}
      </div>
      {!authoritative && (
        <p className="vcap-muted">
          Returned-row coverage only; full release bounds are unavailable from this backend.
        </p>
      )}
      <ul>
        {series.slice(current * SERIES_PAGE, (current + 1) * SERIES_PAGE).map((item) => (
          <li key={coverageKey(item)}>
            <strong>
              {item.source_name} / {item.geography}
            </strong>
            {" · "}
            {item.first_period && item.last_period ? (
              <>
                Available {item.first_period}–{item.last_period} ({item.periods.length}{" "}
                recorded periods).
                {authoritative && requestedStart < item.first_period && (
                  <> No data before {item.first_period}.</>
                )}
                {authoritative && requestedEnd > item.last_period && (
                  <> No data after {item.last_period}.</>
                )}
              </>
            ) : (
              "No matching source coverage; no value is implied for the requested years."
            )}
            {item.published_at && <> Published {item.published_at}.</>}
            {item.snapshot_id && (
              <span title={item.snapshot_id}>
                {" "}
                Release {item.snapshot_id.slice(0, 12)}.
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="vcap-muted">
        Blank years are unavailable or not reported, never zero. Report editions can overlap
        with revised values and shared data lineage; they are shown separately, never
        spliced or summed. Numeric comparability requires explicit compatible definitions.
      </p>
    </section>
  );
}

function YearTable({
  payload,
  query,
  series,
}: {
  payload: Payload;
  query: Query;
  series: CoverageSeries[];
}) {
  const periods = useMemo(() => calendarPeriods(query), [query]);
  const index = useMemo(() => observationIndex(payload.rows), [payload.rows]);
  const [periodPage, setPeriodPage] = useState(0);
  const [seriesPage, setSeriesPage] = useState(0);
  const periodPages = Math.max(1, Math.ceil(periods.length / PERIOD_PAGE));
  const seriesPages = Math.max(1, Math.ceil(series.length / SERIES_PAGE));
  const currentPeriod = Math.min(periodPage, periodPages - 1);
  const currentSeries = Math.min(seriesPage, seriesPages - 1);
  const shown = series.slice(
    currentSeries * SERIES_PAGE,
    (currentSeries + 1) * SERIES_PAGE,
  );
  return (
    <section className="vcap-year-table" data-testid="vcap-year-table">
      <div className="vcap-section-title">
        <h3>{query.frequency === "annual" ? "Year" : "Quarter"} table</h3>
        <span>
          {periods.length} calendar periods · {series.length} source/geography series ·
          exact {query.unit}
        </span>
      </div>
      <div className="vcap-calendar-paging">
        {periodPages > 1 && (
          <PageButtons
            page={currentPeriod}
            pages={periodPages}
            onPage={setPeriodPage}
            label="periods"
          />
        )}
        {seriesPages > 1 && (
          <PageButtons
            page={currentSeries}
            pages={seriesPages}
            onPage={setSeriesPage}
            label="series"
          />
        )}
      </div>
      <div
        className="vcap-table-scroll"
        tabIndex={0}
        aria-label="Scrollable calendar year table"
      >
        <table>
          <caption className="vcap-sr-only">
            Selected calendar periods with separate source edition and geography columns.
            Missing amounts and unreported periods differ from reported zero.
          </caption>
          <thead>
            <tr>
              <th scope="col">Period</th>
              {shown.map((item) => (
                <th scope="col" key={coverageKey(item)}>
                  {item.source_name}
                  <span>{item.geography}</span>
                  <span>Published {item.published_at ?? "unknown"}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {periods
              .slice(currentPeriod * PERIOD_PAGE, (currentPeriod + 1) * PERIOD_PAGE)
              .map((period) => (
                <tr key={period}>
                  <th scope="row">{period}</th>
                  {shown.map((item) => {
                    const row = index.get(`${coverageKey(item)}|${period}`);
                    const missing =
                      row && (row.value === null || !Number.isFinite(row.value));
                    return (
                      <td
                        key={coverageKey(item)}
                        data-status={row ? (missing ? "missing" : "reported") : "absent"}
                      >
                        {row ? (
                          <>
                            <span className="vcap-number">
                              {missing ? "Missing amount" : exactValue(row)}
                            </span>
                            <span className="vcap-muted">
                              {row.status}
                              {row.is_partial ? " · partial period" : ""}
                            </span>
                          </>
                        ) : (
                          <span className="vcap-muted">
                            {unavailablePeriod(item, period)}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <p className="vcap-muted">
        0 is a reported numeric zero. Missing amount is an explicit source observation
        without a value. Not reported is an absent period inside source coverage;
        unavailable periods fall outside it. Calendar cells do not add observations to
        counts or exports.
      </p>
    </section>
  );
}

export function CalendarViews({
  payload,
  query,
  view,
  onView,
  chart,
}: {
  payload: Payload;
  query: Query;
  view: "chart" | "table";
  onView: (view: "chart" | "table") => void;
  chart: React.ReactNode;
}) {
  const series = useMemo(() => selectedCoverage(payload, query), [payload, query]);
  return (
    <>
      <CoverageExplanation
        series={series}
        query={query}
        authoritative={!!payload.coverage}
      />
      <div className="vcap-actions" role="group" aria-label="Observation view">
        <button
          className="btn"
          aria-pressed={view === "chart"}
          onClick={() => onView("chart")}
        >
          Chart
        </button>
        <button
          className="btn"
          aria-pressed={view === "table"}
          onClick={() => onView("table")}
        >
          Year table
        </button>
      </div>
      {view === "table" ? (
        <YearTable payload={payload} query={query} series={series} />
      ) : (
        chart
      )}
    </>
  );
}
