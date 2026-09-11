/**
 * PFA — Performance Attribution (specialized portfolio pane, wave-2 lane L8).
 *
 * Brinson-Hood-Beebower screen for `portfolio/pfa.py`: a headline active
 * return, the three effect totals, a signed per-sector effect ladder, and
 * the full signed sector table (weights, returns, allocation / selection /
 * interaction / total).
 *
 * The backend serves a small default SAMPLE when no weight/return maps are
 * passed, so the shared data-quality badge must stay visible — the pane never
 * drops or restyles it.
 */
import { useMemo, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "../function-controls";
import type { FunctionPaneProps } from "../registry-types";
import {
  asRecord,
  asRows,
  BarRow,
  DataQualityBadge,
  emptyCopy,
  fmtPct,
  MetricStrip,
  PaneGate,
  PortfolioEmpty,
  SectionHead,
  sortByField,
  str,
  toneClass,
  WarningStrip,
  type Row,
} from "./shared";

interface PfaPayload {
  status?: string;
  reason?: string;
  rows?: Row[];
  totals?: Row;
  summary?: Row;
  methodology?: string;
  [key: string]: unknown;
}

/**
 * G3: editable Brinson inputs. The backend (`portfolio/pfa.py`) already
 * accepts `port_weights / port_returns / bench_weights / bench_returns`; the
 * pane previously never sent them, so it was permanently the default sample.
 *
 * Fields are `Sector: value` pairs entered as PERCENTAGES (e.g. "Technology:
 * 45") and converted to fractions for the backend, which computes in
 * fractions (the pane formats with `fromFraction`).
 */
export interface PfaEditorFields {
  portWeights: string;
  portReturns: string;
  benchWeights: string;
  benchReturns: string;
}

export const EMPTY_PFA_FIELDS: PfaEditorFields = {
  portWeights: "",
  portReturns: "",
  benchWeights: "",
  benchReturns: "",
};

/**
 * Parse `Sector: value, Sector: value` (comma or newline separated) into a
 * `{sector: fraction}` map. Percent inputs are divided by 100; unparseable
 * fragments are skipped (never guessed). Returns `{}` for an empty input.
 */
export function parseSectorMap(raw: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of raw.split(/[,\n]+/)) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const [sector, value] = trimmed.split(":");
    if (!sector || value == null) continue;
    const pct = Number(value.trim());
    if (!Number.isFinite(pct)) continue;
    out[sector.trim()] = pct / 100;
  }
  return out;
}

/** All four maps are required — the backend silently falls back otherwise. */
function pfaParamsFor(fields: PfaEditorFields): Record<string, unknown> | undefined {
  const portWeights = parseSectorMap(fields.portWeights);
  const portReturns = parseSectorMap(fields.portReturns);
  const benchWeights = parseSectorMap(fields.benchWeights);
  const benchReturns = parseSectorMap(fields.benchReturns);
  if (
    Object.keys(portWeights).length === 0 ||
    Object.keys(portReturns).length === 0 ||
    Object.keys(benchWeights).length === 0 ||
    Object.keys(benchReturns).length === 0
  ) {
    return undefined;
  }
  return {
    port_weights: portWeights,
    port_returns: portReturns,
    bench_weights: benchWeights,
    bench_returns: benchReturns,
  };
}

const SECTOR_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "sector",
    header: "Sector",
    width: 148,
    render: (row) => str(row.sector) ?? "—",
  },
  {
    key: "port_weight",
    header: "Port Wt",
    width: 82,
    align: "right",
    numeric: true,
    render: (row) => <span className="portfolio-analytics-num">{fmtPct(row.port_weight, { fromFraction: true })}</span>,
  },
  {
    key: "bench_weight",
    header: "Bench Wt",
    width: 84,
    align: "right",
    numeric: true,
    render: (row) => <span className="portfolio-analytics-num">{fmtPct(row.bench_weight, { fromFraction: true })}</span>,
  },
  {
    key: "port_return",
    header: "Port Ret",
    width: 82,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.port_return === "number" ? row.port_return : null) ?? ""}`}>
        {fmtPct(row.port_return, { fromFraction: true, signed: true })}
      </span>
    ),
  },
  {
    key: "bench_return",
    header: "Bench Ret",
    width: 84,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.bench_return === "number" ? row.bench_return : null) ?? ""}`}>
        {fmtPct(row.bench_return, { fromFraction: true, signed: true })}
      </span>
    ),
  },
  {
    key: "allocation_effect",
    header: "Alloc",
    width: 78,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.allocation_effect === "number" ? row.allocation_effect : null) ?? ""}`}>
        {fmtPct(row.allocation_effect, { fromFraction: true, signed: true })}
      </span>
    ),
  },
  {
    key: "selection_effect",
    header: "Select",
    width: 78,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.selection_effect === "number" ? row.selection_effect : null) ?? ""}`}>
        {fmtPct(row.selection_effect, { fromFraction: true, signed: true })}
      </span>
    ),
  },
  {
    key: "interaction_effect",
    header: "Interact",
    width: 80,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.interaction_effect === "number" ? row.interaction_effect : null) ?? ""}`}>
        {fmtPct(row.interaction_effect, { fromFraction: true, signed: true })}
      </span>
    ),
  },
  {
    key: "total_effect",
    header: "Total",
    width: 82,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.total_effect === "number" ? row.total_effect : null) ?? ""}`}>
        {fmtPct(row.total_effect, { fromFraction: true, signed: true })}
      </span>
    ),
  },
];

export function PerformanceAttributionPane({ code }: FunctionPaneProps) {
  const [editorOpen, setEditorOpen] = useState(false);
  const [fields, setFields] = useState<PfaEditorFields>(EMPTY_PFA_FIELDS);
  const [applied, setApplied] = useState<PfaEditorFields | null>(null);
  // Params stay `undefined` until the user applies a COMPLETE editor, so the
  // untouched pane keeps the backend's labelled default SAMPLE unchanged.
  const params = useMemo(() => (applied ? pfaParamsFor(applied) : undefined), [applied]);
  const canApply = useMemo(() => pfaParamsFor(fields) !== undefined, [fields]);
  const { state, data, error, refetch } = useFunction<PfaPayload>({ code, params });
  const payload = data?.data;
  const rows = useMemo(() => sortByField(asRows(payload?.rows), "total_effect"), [payload]);
  const totals = useMemo(() => asRecord(payload?.totals), [payload]);
  const summary = useMemo(() => asRecord(payload?.summary), [payload]);
  const warnings = data?.warnings ?? [];
  const status = str(payload?.status) ?? data?.status ?? "ok";
  const isEmpty = !payload || rows.length === 0;

  const effects = useMemo(
    () =>
      [
        { label: "Allocation", value: totals?.allocation },
        { label: "Selection", value: totals?.selection },
        { label: "Interaction", value: totals?.interaction },
      ].map((entry) => ({
        label: entry.label,
        value: typeof entry.value === "number" && Number.isFinite(entry.value) ? entry.value : null,
      })),
    [totals],
  );

  const effectMax = useMemo(
    () => Math.max(...effects.map((entry) => Math.abs(entry.value ?? 0)), 1e-9),
    [effects],
  );
  const sectorMax = useMemo(
    () => Math.max(...rows.map((row) => Math.abs(typeof row.total_effect === "number" ? row.total_effect : 0)), 1e-9),
    [rows],
  );

  const activeReturn = typeof totals?.active_return === "number" ? totals.active_return : null;
  const badge = (
    <DataQualityBadge
      payload={payload as Row | undefined}
      metadata={data?.metadata}
      sources={data?.sources}
    />
  );
  const empty = emptyCopy(payload as Row | undefined);

  const body = (
    <PaneGate state={state} error={error} refetch={refetch}>
      {isEmpty ? (
        <PortfolioEmpty badge={badge} title={empty.title} body={empty.body} />
      ) : (
        <div className="portfolio-analytics-view">
          {badge}
          <section className="portfolio-analytics-summary">
            <div className="portfolio-analytics-summary__hero">
              <span className="portfolio-analytics-label">Active return</span>
              <strong className={toneClass(activeReturn)}>
                {fmtPct(activeReturn, { fromFraction: true, signed: true })}
              </strong>
              <span>
                portfolio {fmtPct(totals?.portfolio_return, { fromFraction: true, signed: true })} vs benchmark{" "}
                {fmtPct(totals?.benchmark_return, { fromFraction: true, signed: true })}
              </span>
            </div>
            <MetricStrip
              metrics={[
                {
                  key: "portfolio_return",
                  label: "Portfolio Return",
                  value: fmtPct(totals?.portfolio_return, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof totals?.portfolio_return === "number" ? totals.portfolio_return : null),
                },
                {
                  key: "benchmark_return",
                  label: "Benchmark Return",
                  value: fmtPct(totals?.benchmark_return, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof totals?.benchmark_return === "number" ? totals.benchmark_return : null),
                },
                {
                  key: "allocation",
                  label: "Allocation",
                  value: fmtPct(totals?.allocation, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof totals?.allocation === "number" ? totals.allocation : null),
                },
                {
                  key: "selection",
                  label: "Selection",
                  value: fmtPct(totals?.selection, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof totals?.selection === "number" ? totals.selection : null),
                },
                {
                  key: "interaction",
                  label: "Interaction",
                  value: fmtPct(totals?.interaction, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof totals?.interaction === "number" ? totals.interaction : null),
                },
                {
                  key: "sectors",
                  label: "Sectors",
                  value: String(typeof summary?.sectors === "number" ? summary.sectors : rows.length),
                },
              ]}
            />
          </section>

          <WarningStrip warnings={warnings} />

          <div className="portfolio-analytics-grid">
            <section className="portfolio-table-panel">
              <SectionHead title="Sector attribution" meta={`${rows.length} sector(s) · sorted by |total effect|`} />
              <DataGrid
                columns={SECTOR_COLUMNS}
                rows={rows}
                rowKey={(row, idx) => `${String(row.sector ?? idx)}-${idx}`}
                density="compact"
                ariaLabel="PFA Brinson attribution by sector"
              />
            </section>

            <aside className="portfolio-analytics-rail">
              <section className="portfolio-visual-panel">
                <SectionHead title="Effect totals" meta="active return decomposition" />
                <div className="portfolio-ladder u-mt-4">
                  {effects.map((entry) => (
                    <BarRow
                      key={entry.label}
                      label={entry.label}
                      value={entry.value ?? 0}
                      max={effectMax}
                      text={fmtPct(entry.value, { fromFraction: true, signed: true })}
                      title={`${entry.label} effect vs total benchmark return`}
                    />
                  ))}
                </div>
              </section>

              <section className="portfolio-visual-panel">
                <SectionHead title="Sector effect" meta="|total| descending" />
                <div className="portfolio-ladder u-mt-4">
                  {rows.slice(0, 8).map((row) => {
                    const value = typeof row.total_effect === "number" ? row.total_effect : 0;
                    return (
                      <BarRow
                        key={`${String(row.sector)}-bar`}
                        label={str(row.sector) ?? "—"}
                        value={value}
                        max={sectorMax}
                        text={fmtPct(value, { fromFraction: true, signed: true })}
                      />
                    );
                  })}
                </div>
              </section>

              {payload?.methodology ? (
                <section className="portfolio-method-panel">
                  <h3>Method</h3>
                  <p>{payload.methodology}</p>
                </section>
              ) : null}
            </aside>
          </div>
        </div>
      )}
    </PaneGate>
  );

  return (
    <div className="portfolio-analytics-host">
      <Pane>
        <PaneHeader
          code={code.toUpperCase()}
          title="Performance Attribution"
          subtitle="Allocation, selection, and interaction effects"
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                busy={state === "refreshing" || state === "loading"}
                onClick={refetch}
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody className="portfolio-analytics-body">
          <PfaEditor
            open={editorOpen}
            onToggle={() => setEditorOpen((v) => !v)}
            fields={fields}
            onChange={(next) => setFields(next)}
            canApply={canApply}
            applied={applied !== null}
            onApply={() => setApplied({ ...fields })}
            onReset={() => {
              setFields(EMPTY_PFA_FIELDS);
              setApplied(null);
            }}
          />
          {body}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
          <span>sectors · {rows.length}</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * G3: compact editor over the backend's existing `port_weights /
 * port_returns / bench_weights / bench_returns` params. Apply is disabled
 * until all four maps parse — the backend silently serves the sample when
 * any map is missing, so a partial send would look like "my data is wrong".
 */
function PfaEditor({
  open,
  onToggle,
  fields,
  onChange,
  canApply,
  applied,
  onApply,
  onReset,
}: {
  open: boolean;
  onToggle: () => void;
  fields: PfaEditorFields;
  onChange: (next: PfaEditorFields) => void;
  canApply: boolean;
  applied: boolean;
  onApply: () => void;
  onReset: () => void;
}) {
  const fid = (name: string) => `pfa-${name}`;
  const input = (
    key: keyof PfaEditorFields,
    label: string,
    placeholder: string,
  ) => (
    <label
      className="portfolio-control-field portfolio-control-field--wide"
      htmlFor={fid(key)}
      key={key}
    >
      <span>{label}</span>
      <input
        id={fid(key)}
        value={fields[key]}
        spellCheck={false}
        onChange={(e) => onChange({ ...fields, [key]: e.target.value })}
        placeholder={placeholder}
      />
    </label>
  );
  return (
    <section className="portfolio-method-panel" data-testid="pfa-editor">
      <header className="port-section-head">
        <div>
          <h3>Custom weights &amp; returns</h3>
          <span>
            {applied
              ? "custom inputs applied"
              : "optional — the backend sample runs until applied"}
          </span>
        </div>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onToggle}
          aria-expanded={open}
          data-testid="pfa-editor-toggle"
        >
          {open ? "Hide editor" : "Edit weights"}
        </button>
      </header>
      {open ? (
        <div className="u-flex-col u-gap-5 u-mt-4">
          {input("portWeights", "Port weights", "Technology: 45, Financials: 20")}
          {input("portReturns", "Port returns", "Technology: 18, Financials: 5")}
          {input("benchWeights", "Bench weights", "Technology: 30, Financials: 18")}
          {input("benchReturns", "Bench returns", "Technology: 12, Financials: 4")}
          <div className="u-flex u-gap-8">
            <button
              type="button"
              className="btn btn--accent"
              disabled={!canApply}
              onClick={onApply}
              data-testid="pfa-editor-apply"
              title={
                canApply
                  ? "Send these weights/returns and re-run the attribution"
                  : "All four maps are required (Sector: percent pairs)"
              }
            >
              Apply
            </button>
            <button
              type="button"
              className="btn"
              onClick={onReset}
              data-testid="pfa-editor-reset"
            >
              Reset to sample
            </button>
          </div>
          <span className="u-text-secondary">
            Enter percentages as “Sector: value” pairs; the backend falls back to
            the sample when any of the four maps is missing.
          </span>
        </div>
      ) : null}
    </section>
  );
}

export default PerformanceAttributionPane;
