import { useEffect, useMemo, useRef, useState } from "react";
import { Pane, PaneBody, PaneFooter, PaneHeader, Pill } from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { runFunction } from "@/lib/functions";
import type { FunctionPaneProps } from "./registry-types";
import { VCAPChart } from "./vcap/VcapChart";
import { CalendarViews } from "./vcap/CalendarViews";
import { ImportHelp } from "./vcap/ImportHelp";
import { latestComparableDifference } from "./vcap/comparison";
import { exactValue } from "./vcap/chart";
import { CSV_COLUMNS, emptyJSONTemplate, MAX_BYTES, parseImport } from "./vcap/imports";
import { download, exportCSV, exportJSON } from "./vcap/exports";
import {
  defaultQuery,
  safeReference,
  SCOPE_LABELS,
  type Dataset,
  type Metric,
  type Observation,
  type Payload,
  type Query,
  type Scope,
  type Snapshot,
  type Source,
  type Unit,
} from "./vcap/types";
import "./vcap/vcap.css";

const STORAGE_KEY = "showme.vcap.query";
interface Draft {
  query: Query;
  geographies: string;
  start: string;
  end: string;
}
function draftFor(query: Query): Draft {
  return {
    query,
    geographies: query.geographies.join(", "),
    start: String(query.start_year),
    end: String(query.end_year),
  };
}
function validatedQuery(draft: Draft): Query {
  const query = {
    ...draft.query,
    source_ids: [...new Set(draft.query.source_ids)].sort(),
    geographies: [
      ...new Set(
        draft.geographies
          .toUpperCase()
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      ),
    ].sort(),
    start_year: Number(draft.start),
    end_year: Number(draft.end),
  };
  if (!Object.hasOwn(SCOPE_LABELS, query.scope))
    throw new Error("Choose a research scope.");
  if (
    !query.source_ids.length ||
    query.source_ids.length > 64 ||
    query.source_ids.some((s) => !/^[a-z][a-z0-9_-]{0,63}$/.test(s))
  )
    throw new Error("Select at least one source (maximum 64).");
  if (
    !query.geographies.length ||
    query.geographies.length > 64 ||
    query.geographies.some((s) => !/^(?:[A-Z]{3}|WORLD|TUR_DIASPORA)$/.test(s))
  )
    throw new Error("Enter comma-separated ISO3 geography codes (maximum 64).");
  if (
    query.geographies.some((s) =>
      query.scope === "global"
        ? s !== "WORLD"
        : query.scope === "countries"
          ? ["WORLD", "TUR_DIASPORA"].includes(s)
          : query.scope === "turkey"
            ? !["TUR", "TUR_DIASPORA"].includes(s)
            : false,
    )
  )
    throw new Error(
      "Geographies must match the selected scope: countries use ISO3; global uses WORLD; Turkey uses TUR or TUR_DIASPORA.",
    );
  if (
    ![draft.start, draft.end].every((s) => /^\d{4}$/.test(s)) ||
    query.start_year < 1900 ||
    query.end_year > new Date().getFullYear() ||
    query.start_year > query.end_year
  )
    throw new Error(
      "Enter years from 1900 through the current year, with the start no later than the end.",
    );
  if (
    !["investment", "deals", "fundraising"].includes(query.metric) ||
    !["total", "seed", "early", "late"].includes(query.stage) ||
    !["annual", "quarterly"].includes(query.frequency) ||
    !["vc", "all_raises"].includes(query.financing_scope)
  )
    throw new Error("Choose valid measurement controls.");
  if (query.metric === "deals") query.unit = "COUNT";
  else if (
    query.unit !== "USD" &&
    !(
      query.unit === "PERCENT_GDP" &&
      query.scope === "countries" &&
      query.metric === "investment"
    )
  )
    query.unit = "USD";
  if (query.scope !== "crypto") query.financing_scope = "vc";
  if (query.vintage && !/^[a-f0-9]{64}$/.test(query.vintage))
    throw new Error("Choose a saved release or latest.");
  return query;
}
function initialQuery(): Query {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? validatedQuery(draftFor(JSON.parse(raw) as Query)) : defaultQuery();
  } catch {
    return defaultQuery();
  }
}
function identity(query?: Query) {
  return query
    ? JSON.stringify([
        query.scope,
        [...query.source_ids].sort(),
        [...query.geographies].sort(),
        query.metric,
        query.stage,
        query.frequency,
        query.unit,
        query.start_year,
        query.end_year,
        query.financing_scope,
        query.vintage ?? null,
      ])
    : "";
}
function describe(query: Query) {
  return `${SCOPE_LABELS[query.scope]} · ${query.geographies.join(", ")} · ${query.frequency} ${query.metric} · ${query.stage} · ${query.start_year}–${query.end_year} · ${query.unit}${query.scope === "crypto" ? (query.financing_scope === "vc" ? " · strict VC" : " · all reported raises") : ""}`;
}
function queryForImport(
  dataset: Dataset,
  snapshot: string,
): { query: Query; totalGeographies: number } {
  const first = dataset.observations[0];
  const query = defaultQuery(first.scope as Scope);
  const matching = dataset.observations.filter(
    (row) =>
      row.scope === first.scope &&
      row.metric === first.metric &&
      row.stage === first.stage &&
      row.unit === first.unit &&
      String(row.period).includes("-Q") === String(first.period).includes("-Q") &&
      (row.financing_scope ?? dataset.financing_scope ?? "vc") ===
        (first.financing_scope ?? dataset.financing_scope ?? "vc"),
  );
  const years = matching.map((row) => Number(String(row.period).slice(0, 4)));
  const geographies = [...new Set(matching.map((row) => String(row.geography)))].sort();
  return {
    totalGeographies: geographies.length,
    query: {
      ...query,
      source_ids: [dataset.source_id],
      geographies: geographies.slice(0, 64),
      metric: first.metric as Metric,
      stage: String(first.stage),
      unit: first.unit as Unit,
      frequency: String(first.period).includes("-Q") ? "quarterly" : "annual",
      start_year: Math.min(new Date().getFullYear(), ...years),
      end_year: Math.min(new Date().getFullYear(), Math.max(...years)),
      financing_scope: (first.financing_scope ??
        dataset.financing_scope ??
        "vc") as Query["financing_scope"],
      vintage: snapshot,
    },
  };
}

export function VCAPPane({ code }: FunctionPaneProps) {
  const [query, setQuery] = useState(initialQuery);
  const [view, setView] = useState<"chart" | "table">(() =>
    query.scope === "global" ? "table" : "chart",
  );
  const [draft, setDraft] = useState(() => draftFor(query));
  const [forceRefresh, setForceRefresh] = useState(false);
  const [catalogue, setCatalogue] = useState<Source[]>([]);
  const [history, setHistory] = useState<Snapshot[] | null>(null);
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");
  const [importing, setImporting] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [page, setPage] = useState(0);
  const importInput = useRef<HTMLInputElement>(null);
  const params = useMemo(
    () => ({ action: "query", ...query, refresh: forceRefresh }),
    [query, forceRefresh],
  );
  const { state, data, error, refetch } = useFunction<Payload>({ code, params });
  const payload = data?.data;
  const rows = useMemo(
    () =>
      Array.isArray(payload?.rows)
        ? [...payload.rows].sort(
            (a, b) =>
              a.period.localeCompare(b.period) ||
              a.source_id.localeCompare(b.source_id) ||
              a.geography.localeCompare(b.geography),
          )
        : [],
    [payload?.rows],
  );
  useEffect(() => {
    if (Array.isArray(payload?.sources)) setCatalogue(payload.sources);
  }, [payload?.sources]);
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(query));
    } catch {
      /* Private browsing may disable persistence. */
    }
  }, [query]);
  useEffect(() => {
    setPage(0);
  }, [payload]);
  const sources = payload?.sources ?? catalogue;
  const sourceChoices = sources.filter(
    (source) =>
      source.scopes.includes(draft.query.scope) ||
      source.available_scopes?.includes(draft.query.scope),
  );
  const availableGeographies = [
    ...new Set(
      sources
        .filter((source) => draft.query.source_ids.includes(source.source_id))
        .flatMap((source) => source.available_geographies ?? []),
    ),
  ].sort();
  const gdpSupported = sources.some(
    (source) =>
      draft.query.source_ids.includes(source.source_id) &&
      (source.source_id === "oecd" || source.available_units?.includes("PERCENT_GDP")),
  );
  const latestPeriod = rows.reduce(
    (latest, row) => (row.period > latest ? row.period : latest),
    "",
  );
  const transition =
    state === "idle" ||
    state === "loading" ||
    state === "refreshing" ||
    (!!payload?.query && identity(payload.query) !== identity(query));
  const exportDisabled = !payload?.query || transition || importing;
  const metadata = data?.metadata ?? {};
  const snapshots = history ?? payload?.snapshots ?? [];
  const selectedSnapshots = snapshots.filter((snapshot) =>
    draft.query.source_ids.includes(snapshot.source_id),
  );
  const selectQuery = (next: Query) => {
    if (next.scope !== query.scope) setView(next.scope === "global" ? "table" : "chart");
    setQuery(next);
    setDraft(draftFor(next));
    setForceRefresh(false);
    setFormError("");
    setPage(0);
  };
  const apply = () => {
    try {
      selectQuery(validatedQuery(draft));
      setNotice("");
    } catch (err) {
      setFormError((err as Error).message);
    }
  };
  const update = (values: Partial<Query>) =>
    setDraft((current) => ({ ...current, query: { ...current.query, ...values } }));
  const refresh = () => {
    if (forceRefresh) refetch();
    else setForceRefresh(true);
  };
  const importFile = async (file?: File) => {
    if (!file) return;
    setFormError("");
    setNotice("");
    setImporting(true);
    try {
      if (file.size > MAX_BYTES)
        throw new Error("Choose a JSON or CSV file no larger than 2 MB.");
      const text = await file.text();
      const dataset = parseImport(text, file.name);
      const result = await runFunction<Payload>(code, {
        params: { action: "import", dataset },
      });
      if (result.data.status !== "ok" || !result.data.snapshot_id)
        throw new Error(
          result.data.reason ??
            "Import failed validation; existing observations were kept.",
        );
      setCatalogue(result.data.sources);
      setHistory(result.data.snapshots);
      const selection = queryForImport(dataset, result.data.snapshot_id);
      selectQuery(selection.query);
      const remaining = selection.totalGeographies - selection.query.geographies.length;
      const coverageNotice =
        remaining > 0
          ? ` Showing ${selection.query.geographies.length} of ${selection.totalGeographies} geographies in this measurement group; ${remaining} additional ${remaining === 1 ? "geography remains" : "geographies remain"} available. Replace codes in the geography control to view the remaining coverage (up to 64 at once).`
          : "";
      setNotice(
        `${result.data.idempotent ? "Existing identical release selected" : "Imported release saved locally"}: ${dataset.source_name || dataset.source_id}, ${dataset.observations.length.toLocaleString("en-US")} observations. Showing the first measurement group; use the controls for other groups.${coverageNotice} Each import replaces the selected source release's coverage; prior releases remain in history.`,
      );
      // Same idempotent release may already be selected; refresh its query too.
      refetch();
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setImporting(false);
      if (importInput.current) importInput.current.value = "";
    }
  };
  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const result = await runFunction<Payload>(code, { params: { action: "versions" } });
      if (result.data.status !== "ok")
        throw new Error(result.data.reason ?? "Could not load release history.");
      setHistory(result.data.snapshots);
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setHistoryLoading(false);
    }
  };
  return (
    <div className="u-pane-host vcap-pane" data-testid="vcap-pane">
      <Pane>
        <PaneHeader
          code={code}
          title="Venture capital research"
          subtitle={
            payload?.query
              ? describe(payload.query)
              : "Source-specific investment, deals and fund fundraising"
          }
          help={
            <p>
              Choose a scope, sources and measurement, then Apply. Values retain each
              publisher's definitions and release history. Import a complete owned or
              licensed source release as JSON or long-format CSV; exports stay on this
              device.
            </p>
          }
          trailing={
            <div className="vcap-actions">
              <Pill tone={metadata.stale ? "warn" : "muted"} withDot={false}>
                {metadata.stale
                  ? "Stale cached release"
                  : metadata.data_mode === "official"
                    ? "Publisher data"
                    : metadata.data_mode === "mixed"
                      ? "Mixed sources"
                      : metadata.data_mode === "imported"
                        ? "Imported data"
                        : "No matching data"}
              </Pill>
              {metadata.cached === true && !metadata.stale && (
                <span className="vcap-muted">Cached</span>
              )}
              <button className="btn" disabled={transition || importing} onClick={refresh}>
                Refresh sources
              </button>
            </div>
          }
        />
        <PaneBody className="vcap-body">
          <div className="vcap-scopes" role="group" aria-label="Research scope">
            {(Object.keys(SCOPE_LABELS) as Scope[]).map((scope) => (
              <button
                key={scope}
                type="button"
                aria-pressed={query.scope === scope}
                className="btn"
                disabled={importing}
                onClick={() => {
                  selectQuery({
                    ...defaultQuery(scope),
                    start_year: query.start_year,
                    end_year: query.end_year,
                  });
                  setNotice("");
                }}
              >
                {SCOPE_LABELS[scope]}
              </button>
            ))}
          </div>
          <form
            className="vcap-controls"
            onSubmit={(event) => {
              event.preventDefault();
              apply();
            }}
          >
            <fieldset className="vcap-source-picker" disabled={importing}>
              <legend>Sources</legend>
              {sourceChoices.length ? (
                sourceChoices.map((source) => (
                  <label key={source.source_id}>
                    <input
                      type="checkbox"
                      checked={draft.query.source_ids.includes(source.source_id)}
                      onChange={(event) =>
                        update({
                          source_ids: event.target.checked
                            ? [...draft.query.source_ids, source.source_id]
                            : draft.query.source_ids.filter(
                                (sid) => sid !== source.source_id,
                              ),
                          vintage: null,
                        })
                      }
                    />
                    {source.source_name}
                  </label>
                ))
              ) : (
                <span className="vcap-muted">
                  {transition
                    ? "Loading source catalogue…"
                    : "No source catalogue is available. Refresh or import a documented dataset."}
                </span>
              )}
            </fieldset>
            <div className="vcap-filter-grid">
              <label className="vcap-geographies">
                Geographies
                <input
                  value={draft.geographies}
                  onChange={(event) =>
                    setDraft({ ...draft, geographies: event.target.value })
                  }
                  aria-describedby="vcap-geography-help"
                  placeholder="USA, GBR, DEU"
                />
              </label>
              <label>
                Metric
                <select
                  value={draft.query.metric}
                  onChange={(event) => {
                    const metric = event.target.value as Metric;
                    update({ metric, unit: metric === "deals" ? "COUNT" : "USD" });
                  }}
                >
                  <option value="investment">Investment</option>
                  <option value="deals">Deal count</option>
                  <option value="fundraising">Fund fundraising</option>
                </select>
              </label>
              <label>
                Stage
                <select
                  value={draft.query.stage}
                  onChange={(event) => update({ stage: event.target.value })}
                >
                  {["total", "seed", "early", "late"].map((value) => (
                    <option key={value} value={value}>
                      {value === "total"
                        ? "Total"
                        : value[0].toUpperCase() + value.slice(1)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Frequency
                <select
                  value={draft.query.frequency}
                  onChange={(event) =>
                    update({ frequency: event.target.value as Query["frequency"] })
                  }
                >
                  <option value="annual">Annual</option>
                  <option value="quarterly">Quarterly</option>
                </select>
              </label>
              <label>
                Unit
                <select
                  value={draft.query.unit}
                  onChange={(event) => update({ unit: event.target.value as Unit })}
                >
                  {draft.query.metric === "deals" ? (
                    <option value="COUNT">Count</option>
                  ) : (
                    <>
                      <option value="USD">USD</option>
                      {draft.query.scope === "countries" &&
                        draft.query.metric === "investment" &&
                        gdpSupported && (
                          <option value="PERCENT_GDP">% GDP (where supported)</option>
                        )}
                    </>
                  )}
                </select>
              </label>
              <label>
                Start year
                <input
                  inputMode="numeric"
                  value={draft.start}
                  onChange={(event) => setDraft({ ...draft, start: event.target.value })}
                />
              </label>
              <label>
                End year
                <input
                  inputMode="numeric"
                  value={draft.end}
                  onChange={(event) => setDraft({ ...draft, end: event.target.value })}
                />
              </label>
              <label className="vcap-vintage">
                Release
                <select
                  value={draft.query.vintage ?? ""}
                  onChange={(event) => update({ vintage: event.target.value || null })}
                >
                  <option value="">Latest per source</option>
                  {selectedSnapshots.map((snapshot) => (
                    <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>
                      {snapshot.source_name} · published{" "}
                      {snapshot.published_at ?? "unknown"} ·{" "}
                      {snapshot.snapshot_id.slice(0, 10)}
                    </option>
                  ))}
                </select>
              </label>
              {draft.query.scope === "crypto" && (
                <label className="vcap-financing">
                  Financing scope
                  <select
                    value={draft.query.financing_scope}
                    onChange={(event) =>
                      update({
                        financing_scope: event.target.value as Query["financing_scope"],
                      })
                    }
                  >
                    <option value="vc">Strict venture capital</option>
                    <option value="all_raises">
                      All reported raises (including tokens / ICOs)
                    </option>
                  </select>
                </label>
              )}
              <button
                className="btn btn--accent vcap-apply"
                type="submit"
                disabled={importing}
              >
                Apply
              </button>
            </div>
            <p id="vcap-geography-help" className="vcap-muted">
              Observed codes for selected sources:{" "}
              {availableGeographies.length
                ? availableGeographies.join(", ")
                : "none loaded"}
              . Enter comma-separated codes. WORLD is used only for an explicit source
              total.
            </p>
            {draft.query.scope === "crypto" && (
              <p className="vcap-muted">
                {draft.query.financing_scope === "all_raises"
                  ? "Broad reported crypto financing includes token sales, ICOs and other raises. It is not a pure venture capital total."
                  : "Strict VC requires a classified series. DefiLlama's documented raises data does not classify equity versus token financing."}
              </p>
            )}
          </form>
          <div className="vcap-file-tools">
            <input
              ref={importInput}
              className="vcap-file-input"
              type="file"
              accept=".json,.csv,application/json,text/csv"
              aria-label="Import VCAP dataset file"
              disabled={importing}
              onChange={(event) => {
                void importFile(event.target.files?.[0]);
              }}
            />
            <button
              className="btn"
              disabled={importing}
              onClick={() => importInput.current?.click()}
            >
              {importing ? "Importing…" : "Import JSON / CSV"}
            </button>
            <button
              className="btn"
              onClick={() =>
                download(
                  emptyJSONTemplate(draft.query.source_ids[0] ?? "custom"),
                  "vcap-template.json",
                  "application/json",
                )
              }
            >
              JSON template
            </button>
            <button
              className="btn"
              onClick={() =>
                download(CSV_COLUMNS.join(",") + "\r\n", "vcap-template.csv", "text/csv")
              }
            >
              CSV template
            </button>
            <span className="vcap-muted">
              Local files · 2 MB · 10,000 observations · complete source releases
            </span>
            <div className="vcap-exports">
              <button
                className="btn"
                disabled={exportDisabled}
                onClick={() =>
                  payload &&
                  download(exportCSV(payload), "vcap-observations.csv", "text/csv")
                }
              >
                Export CSV
              </button>
              <button
                className="btn"
                disabled={exportDisabled}
                onClick={() =>
                  payload &&
                  download(
                    exportJSON(payload),
                    "vcap-observations.json",
                    "application/json",
                  )
                }
              >
                Export JSON
              </button>
            </div>
          </div>
          <ImportHelp />
          {formError && (
            <p role="alert" className="vcap-message vcap-error">
              {formError}
            </p>
          )}
          {notice && (
            <p role="status" className="vcap-message">
              {notice}
            </p>
          )}
          {transition && (
            <p role="status" className="vcap-message">
              {payload?.query
                ? `Updating selection. Displayed data: ${describe(payload.query)}.`
                : "Loading source catalogue and reported observations…"}
            </p>
          )}
          {state === "error" && (
            <p role="alert" className="vcap-message vcap-error">
              {error?.message ?? "Could not load observations."}
              {payload?.query
                ? " The previous result remains displayed with its original measurement labels."
                : " Refresh to try again."}
            </p>
          )}
          {payload?.cache_note && <p className="vcap-message">{payload.cache_note}</p>}
          {payload?.warnings?.map((warning, i) => (
            <p className="vcap-message" key={i}>
              {warning}
            </p>
          ))}
          {payload?.query && (
            <div className="vcap-result-caption">
              <strong>Displayed measurement</strong>
              <span>{describe(payload.query)}</span>
              {latestPeriod && <span>Data through {latestPeriod}</span>}
            </div>
          )}
          {query.scope === "countries" &&
            query.source_ids.includes("oecd") &&
            !query.source_ids.includes("nsf_ncses_2020") &&
            query.start_year < 2007 &&
            query.frequency === "annual" &&
            query.metric === "investment" &&
            query.stage === "total" &&
            query.unit === "USD" &&
            sources.some(
              (source) =>
                source.source_id === "nsf_ncses_2020" &&
                source.scopes.includes("countries"),
            ) && (
              <div className="vcap-message">
                <p>
                  The selected OECD series does not provide the earlier historical years. An
                  additional published report offers 1999–2018 coverage for its reported
                  countries. Coverage varies by country; no unavailable value is implied.
                </p>
                <button
                  className="btn"
                  disabled={transition || importing || query.source_ids.length >= 64}
                  onClick={() =>
                    selectQuery({
                      ...query,
                      source_ids: [...query.source_ids, "nsf_ncses_2020"].sort(),
                      vintage: null,
                    })
                  }
                >
                  Add historical 1999–2018 source
                </button>
              </div>
            )}
          {!rows.length &&
            query.scope === "global" &&
            query.source_ids.every((id) =>
              ["kpmg_pitchbook", "crunchbase"].includes(id),
            ) && (
              <div className="vcap-message">
                <p>
                  This saved selection needs an owned or licensed import. Published global
                  report editions are also available with their own coverage and
                  definitions.
                </p>
                <button
                  className="btn"
                  disabled={transition || importing}
                  onClick={() =>
                    selectQuery({
                      ...defaultQuery("global"),
                      start_year: query.start_year,
                      end_year: query.end_year,
                    })
                  }
                >
                  Load published global data
                </button>
              </div>
            )}
          {payload?.query && (
            <CalendarViews
              key={identity(payload.query)}
              payload={payload}
              query={payload.query}
              view={view}
              onView={setView}
              chart={<VCAPChart rows={rows} query={payload.query} />}
            />
          )}
          {rows.length > 0 ? (
            <>
              <ObservationTable rows={rows} page={page} onPage={setPage} />
              <Comparison payload={payload!} />
            </>
          ) : (
            !transition && (
              <section className="vcap-empty">
                <h3>
                  {payload?.status === "input_error"
                    ? "Unsupported selection"
                    : "No matching observations"}
                </h3>
                <p>
                  {payload?.reason ?? "No observations are available for this selection."}
                </p>
                {payload?.next_actions?.map((action, i) => (
                  <p key={i}>{action}</p>
                ))}
              </section>
            )
          )}
          <SourceDetails sources={sources} selected={query.source_ids} />
          <details className="vcap-details">
            <summary>Release history and methodology</summary>
            <button
              className="btn"
              disabled={historyLoading}
              onClick={() => {
                void loadHistory();
              }}
            >
              {historyLoading ? "Loading history…" : "Refresh release history"}
            </button>
            <p className="vcap-muted">
              A release selector pins its owning source; other selected sources keep their
              latest release. Every import is a complete release, including its period
              coverage.
            </p>
            {snapshots.length ? (
              <ul className="vcap-history">
                {snapshots.slice(0, 200).map((snapshot) => (
                  <li key={snapshot.snapshot_id}>
                    <strong>{snapshot.source_name}</strong> · publication{" "}
                    {snapshot.published_at ?? "unknown"} · retrieved {snapshot.retrieved_at}{" "}
                    · {snapshot.observation_count} rows ·{" "}
                    <span title={snapshot.snapshot_id}>
                      {snapshot.snapshot_id.slice(0, 12)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No saved releases.</p>
            )}
            {snapshots.length > 200 && (
              <p>
                Showing the first 200 releases. The release selector lists all saved
                releases.
              </p>
            )}
            <p>
              {payload?.methodology ??
                "Each publisher retains its own measurement definitions. Missing values stay missing; no country-to-world sum, source splicing or annualization is performed."}
            </p>
          </details>
        </PaneBody>
        <PaneFooter>
          <span>{rows.length.toLocaleString("en-US")} observations</span>
          <span>Publication, measurement and retrieval dates are separate</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function ObservationTable({
  rows,
  page,
  onPage,
}: {
  rows: Observation[];
  page: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.ceil(rows.length / 100),
    current = Math.min(page, pages - 1);
  return (
    <section data-testid="vcap-observation-table">
      <div className="vcap-section-title">
        <h3>Exact observations</h3>
        <span>
          {rows.length.toLocaleString("en-US")} rows · page {current + 1} of {pages}
        </span>
        <div className="vcap-actions">
          <button
            className="btn"
            disabled={current === 0}
            onClick={() => onPage(current - 1)}
          >
            Previous rows
          </button>
          <button
            className="btn"
            disabled={current >= pages - 1}
            onClick={() => onPage(current + 1)}
          >
            Next rows
          </button>
        </div>
      </div>
      <div
        className="vcap-table-scroll"
        tabIndex={0}
        aria-label="Scrollable exact observation table"
      >
        <table>
          <caption className="vcap-sr-only">
            Exact source observations, including measurement periods, status, publication,
            retrieval and vintage
          </caption>
          <thead>
            <tr>
              {[
                "Period",
                "Source",
                "Geography",
                "Exact value / unit",
                "Status / coverage",
                "Published",
                "Retrieved",
                "Version",
              ].map((title) => (
                <th key={title} scope="col">
                  {title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(current * 100, (current + 1) * 100).map((row, i) => (
              <tr
                key={`${row.snapshot_id ?? row.source_id}-${row.geography}-${row.period}-${i}`}
              >
                <th
                  scope="row"
                  title={`${row.period_start ?? ""} to ${row.period_end ?? ""}`}
                >
                  {row.period}
                </th>
                <td>{row.source_name}</td>
                <td>{row.geography}</td>
                <td className="vcap-number">{exactValue(row)}</td>
                <td className="vcap-coverage">
                  {row.status}
                  {row.is_partial ? " · partial period" : ""}
                  {row.coverage_cutoff && (
                    <span>Coverage through {row.coverage_cutoff}</span>
                  )}
                  {row.coverage_note && <span>{row.coverage_note}</span>}
                </td>
                <td>
                  <span>{row.published_at ?? "Unknown"}</span>
                  {row.publication_id && (
                    <span>
                      {row.publication_id} · {row.publication_table}
                    </span>
                  )}
                  {row.underlying_access_date && (
                    <span>Underlying data accessed {row.underlying_access_date}</span>
                  )}
                </td>
                <td>{row.retrieved_at ?? "Unknown"}</td>
                <td>
                  <span title={row.snapshot_id}>
                    {row.snapshot_id?.slice(0, 12) ?? "Unknown"}
                  </span>
                  <span>{row.methodology_version}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
function SourceDetails({ sources, selected }: { sources: Source[]; selected: string[] }) {
  return (
    <section data-testid="vcap-sources" className="vcap-sources">
      <h3>Sources and access</h3>
      {!sources.length && (
        <p>
          No source catalogue was returned. Refresh the sources or import a documented local
          dataset.
        </p>
      )}
      {sources.map((source) => (
        <details key={source.source_id} open={selected.includes(source.source_id)}>
          <summary>
            {source.source_name}{" "}
            <span className="vcap-muted">
              {(source.access_status ?? source.status ?? "unknown").replaceAll("_", " ")} ·{" "}
              {(source.access_mode ?? "unknown").replaceAll("_", " ")}
            </span>
          </summary>
          <div className="vcap-source-body">
            <p>
              {source.reason ??
                source.access_notes ??
                "Consult the source's methodology and permitted access."}
            </p>
            {source.reason && source.access_notes && <p>{source.access_notes}</p>}
            <p className="vcap-muted">
              Lineage: {source.lineage ?? source.source_name}. Observed geographies:{" "}
              {source.available_geographies?.join(", ") || "none loaded"}.
            </p>
            {source.published_at && (
              <p>
                Published {source.published_at}.
                {source.underlying_access_date && (
                  <> Underlying data accessed {source.underlying_access_date}.</>
                )}
              </p>
            )}
            {source.validation_summary && (
              <p>
                Source record validation:{" "}
                {Object.entries(source.validation_summary)
                  .map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`)
                  .join("; ")}
                .
              </p>
            )}
            <div className="vcap-actions">
              {safeReference(source.source_url) && (
                <a
                  href={safeReference(source.source_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Research / methodology
                </a>
              )}
              {safeReference(source.terms_url) && (
                <a
                  href={safeReference(source.terms_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Source terms
                </a>
              )}
            </div>
            {source.access_status !== "available" && (
              <p className="vcap-muted">
                Next step:{" "}
                {source.access_mode === "optional_key"
                  ? "configure the optional source connector on this device, or import a classified owned/licensed release."
                  : "import a complete source release you own or are licensed to use, or choose an available measurement."}
              </p>
            )}
          </div>
        </details>
      ))}
    </section>
  );
}
function Comparison({ payload }: { payload: Payload }) {
  const comparison = payload.comparison;
  if (
    !comparison ||
    (!comparison.blocked_pairs.length && !comparison.comparable_pairs.length)
  )
    return null;
  const label = (id: string) => {
    const series = payload.series?.find((item) => item.id === id);
    return series ? `${series.source_name} / ${series.geography}` : id;
  };
  return (
    <details className="vcap-details">
      <summary>Comparison eligibility</summary>
      {comparison.blocked_pairs.slice(0, 100).map((pair, i) => (
        <p key={`blocked-${i}`}>
          <strong>
            {label(pair.left)} versus {label(pair.right)}: difference blocked.
          </strong>{" "}
          {pair.reasons.join(" ")}
        </p>
      ))}
      {comparison.comparable_pairs.slice(0, 100).map((pair, i) => {
        const difference = latestComparableDifference(payload, pair.left, pair.right);
        return (
          <p key={`eligible-${i}`}>
            <strong>
              {label(pair.left)} versus {label(pair.right)}: comparable.
            </strong>{" "}
            {pair.reason}
            {difference
              ? ` Latest common period ${difference.period}: right minus left ${difference.value} ${difference.unit}.`
              : " No shared numeric period is available."}
          </p>
        );
      })}
      {comparison.blocked_pairs.length + comparison.comparable_pairs.length > 100 && (
        <p>
          Eligibility details are limited to 100 pairs per category; JSON export includes
          every comparison.
        </p>
      )}
      <p className="vcap-muted">
        Independent publisher totals can be viewed side by side. Numeric differences are not
        calculated without compatible measurement definitions.
      </p>
    </details>
  );
}
