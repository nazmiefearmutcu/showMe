/**
 * GREEKS — Portfolio Greeks aggregator.
 *
 * The backend GREEKS function is fully params-driven (`positions` array,
 * no instrument), so the pane owns a persisted option book: a JSON editor
 * (`showme.greeks.book`) with a sample default, applied to the call on
 * demand. Parse errors render honestly and never reach the sidecar.
 *
 * Body: net summary cards (delta/gamma/vega/theta/rho in trader-readable
 * units), the per-position greeks table with an aggregate NET row, and a
 * prominent note whenever the backend had to substitute default vol/T
 * assumptions (`assumptions_used`).
 *
 * Honesty: the success payload carries no `status` field — errors arrive
 * as input_error / input_required / calc_error envelopes and are shown
 * verbatim; per-position failures (rows with `error`) are surfaced as
 * text, never as zero greeks.
 */
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { usePersistentString } from "./function-control-state";
import { formatNumber } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

const BOOK_KEY = "showme.greeks.book";

type PositionInput = Record<string, unknown>;

const DEFAULT_BOOK: PositionInput[] = [
  {
    symbol: "AAPL 240C",
    kind: "call",
    quantity: 10,
    contract_size: 100,
    spot: 250,
    strike: 240,
    vol: 0.28,
    T: 0.5,
    r: 0.04,
  },
  {
    symbol: "SPY 600P",
    kind: "put",
    quantity: -5,
    contract_size: 100,
    spot: 610,
    strike: 600,
    vol: 0.18,
    T: 0.25,
    r: 0.04,
  },
];

interface GreeksRow {
  label?: string;
  symbol?: string;
  kind?: string;
  strike?: number;
  quantity?: number;
  contract_size?: number;
  delta?: number;
  gamma?: number;
  vega?: number;
  theta?: number;
  rho?: number;
  error?: string;
  isAggregate?: boolean;
}

interface GreeksData {
  status?: string;
  reason?: string;
  positions?: GreeksRow[];
  totals?: { delta?: number; gamma?: number; vega?: number; theta?: number; rho?: number };
  n?: number;
  units?: Record<string, string>;
  assumptions_used?: string[];
  methodology?: string;
}

function parseBook(json: string): { positions?: PositionInput[]; error?: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch (e) {
    return { error: `Invalid JSON: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (!Array.isArray(parsed)) {
    return { error: "Book JSON must be an array of position objects." };
  }
  return { positions: parsed as PositionInput[] };
}

export function GreeksPane({ code }: FunctionPaneProps) {
  const [draft, setDraft] = usePersistentString(
    BOOK_KEY, JSON.stringify(DEFAULT_BOOK, null, 2),
  );
  const [book, setBook] = useState<PositionInput[]>(() => {
    if (draft.trim() === "") return DEFAULT_BOOK;
    const parsed = parseBook(draft);
    return parsed.positions ?? DEFAULT_BOOK;
  });
  const [parseError, setParseError] = useState<string | null>(null);


  const applyBook = () => {
    const parsed = parseBook(draft);
    if (parsed.error) {
      setParseError(parsed.error);
      return;
    }
    setParseError(null);
    setBook(parsed.positions ?? []);
  };

  const { state, data, error, refetch } = useFunction<GreeksData>({
    code,
    params: { positions: book },
  });

  const payload = data?.data;
  // The success envelope has no `status` — derive ok from the presence of
  // aggregate totals.
  const status = payload?.status ?? (payload?.totals ? "ok" : "—");
  const isLive = state === "ok" && status === "ok";
  const totals = payload?.totals;

  const rows: GreeksRow[] = useMemo(() => {
    const perPosition = payload?.positions ?? [];
    const aggregate: GreeksRow = {
      label: "NET — book",
      isAggregate: true,
      ...(totals ?? {}),
    };
    return [...perPosition, aggregate];
  }, [payload, totals]);

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={180} />
    </div>
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? "—"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : status === "input_required" ? (
    <Empty
      title="Empty option book"
      body={`${payload?.reason ?? "No option positions supplied."} Edit the book JSON below and apply.`}
      icon="∅"
    />
  ) : status === "input_error" || status === "calc_error" || !totals ? (
    <Empty
      title="Greeks unavailable"
      body={payload?.reason ?? "The aggregation did not return totals."}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {(payload?.assumptions_used?.length ?? 0) > 0 && (
        <div style={noteStyle} role="note">
          <Pill tone="warn" variant="soft">
            synthetic
          </Pill>
          <span>
            Missing inputs were defaulted by the engine —{" "}
            {payload?.assumptions_used?.join("; ")}
          </span>
        </div>
      )}
      <section style={kpiGridStyle} aria-label="Net portfolio greeks cards">
        <NetCard label="Net delta" value={totals?.delta} unit={payload?.units?.delta} />
        <NetCard label="Net gamma" value={totals?.gamma} unit={payload?.units?.gamma} />
        <NetCard label="Net vega" value={totals?.vega} unit={payload?.units?.vega} />
        <NetCard label="Net theta" value={totals?.theta} unit={payload?.units?.theta} tone="negative" />
        <NetCard label="Net rho" value={totals?.rho} unit={payload?.units?.rho} />
      </section>
      <BookTable rows={rows} n={payload?.n} />
      <BookEditor
        draft={draft}
        parseError={parseError}
        onDraftChange={setDraft}
        onApply={applyBook}
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Portfolio Greeks"
          subtitle="Black-Scholes greeks summed across the option book"
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "ok" : status}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Recompute portfolio greeks"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="source" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="positions" value={String(payload?.n ?? book.length)} tone="accent" />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── net summary card ──────────────────────────────────────────────── */

function NetCard({
  label,
  value,
  unit,
  tone = "neutral",
}: {
  label: string;
  value?: number;
  unit?: string;
  tone?: "neutral" | "negative";
}) {
  return (
    <StatCard
      label={label}
      value={fmtNum(value)}
      caption={unit ?? "trader-readable units"}
      tone={tone === "negative" && typeof value === "number" && value < 0 ? "negative" : "neutral"}
    />
  );
}

/* ── per-position table + aggregate row ────────────────────────────── */

function BookTable({ rows, n }: { rows: GreeksRow[]; n?: number }) {
  const COLS: DataGridColumn<GreeksRow>[] = useMemo(
    () => [
      {
        key: "label",
        header: "Position",
        width: 150,
        render: (row) => (
          <span style={row.isAggregate ? aggPrimaryStyle : monoPrimaryStyle}>
            {row.error ? "—" : row.label ?? row.symbol ?? "—"}
          </span>
        ),
      },
      {
        key: "kind",
        header: "Kind",
        width: 70,
        render: (row) => (
          <span style={monoMutedStyle}>{row.error ? "—" : row.kind ?? "—"}</span>
        ),
      },
      {
        key: "strike",
        header: "Strike",
        numeric: true,
        width: 84,
        render: (row) => (
          <span style={monoMutedStyle}>{row.error ? "—" : fmtNum(row.strike)}</span>
        ),
      },
      {
        key: "quantity",
        header: "Qty × size",
        numeric: true,
        width: 100,
        render: (row) => (
          <span style={monoMutedStyle}>
            {row.error || row.isAggregate ? "—" : `${fmtNum(row.quantity)} × ${row.contract_size ?? "—"}`}
          </span>
        ),
      },
      {
        key: "delta",
        header: "Delta",
        numeric: true,
        width: 104,
        render: (row) => <GreekCell row={row} field="delta" />,
      },
      {
        key: "gamma",
        header: "Gamma",
        numeric: true,
        width: 96,
        render: (row) => <GreekCell row={row} field="gamma" />,
      },
      {
        key: "theta",
        header: "Theta/day",
        numeric: true,
        width: 104,
        render: (row) => <GreekCell row={row} field="theta" />,
      },
      {
        key: "vega",
        header: "Vega/1% vol",
        numeric: true,
        width: 110,
        render: (row) => <GreekCell row={row} field="vega" />,
      },
      {
        key: "rho",
        header: "Rho/1bp",
        numeric: true,
        width: 96,
        render: (row) => <GreekCell row={row} field="rho" />,
      },
    ],
    [],
  );
  return (
    <section aria-label="Per-position greeks table">
      <SectionTitle>
        Per-position greeks{typeof n === "number" ? ` — ${n} position${n === 1 ? "" : "s"}` : ""}
      </SectionTitle>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(row, i) => `${row.label ?? row.symbol ?? "row"}-${i}`}
        density="compact"
        ariaLabel="Option book greeks with aggregate row"
      />
    </section>
  );
}

function GreekCell({ row, field }: { row: GreeksRow; field: keyof GreeksRow }) {
  if (row.error) {
    return (
      <span style={errorStyle} title={row.error}>
        error
      </span>
    );
  }
  const value = row[field];
  return (
    <span style={row.isAggregate ? aggStrongStyle : monoStrongStyle}>{fmtNum(value as number)}</span>
  );
}

/* ── persisted JSON book editor ────────────────────────────────────── */

function BookEditor({
  draft,
  parseError,
  onDraftChange,
  onApply,
}: {
  draft: string;
  parseError: string | null;
  onDraftChange: (next: string) => void;
  onApply: () => void;
}) {
  return (
    <section aria-label="Option book JSON editor">
      <SectionTitle>Option book (JSON) — persisted locally</SectionTitle>
      <textarea
        aria-label="Option book JSON"
        value={draft}
        onChange={(e) => onDraftChange(e.target.value)}
        rows={7}
        spellCheck={false}
        style={textareaStyle}
      />
      <div style={editorRowStyle}>
        <span style={editorHintStyle}>
          fields: symbol, kind (call|put), quantity, contract_size, spot, strike, vol, T (years), r
        </span>
        <button type="button" className="btn" onClick={onApply}>
          Apply book
        </button>
      </div>
      {parseError && (
        <div style={noteStyle} role="alert">
          <span>{parseError} — the last valid book is still in use.</span>
        </div>
      )}
    </section>
  );
}

/* ── formatting + styles ───────────────────────────────────────────── */

function fmtNum(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return formatNumber(n, 2);
}

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: "var(--font-size-2xs)",
        letterSpacing: "0.08em",
        color: "var(--text-mute)",
        marginBottom: 6,
        textTransform: "uppercase",
      }}
    >
      {children}
    </div>
  );
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
};

const noteStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 10px",
  border: "1px solid var(--warn-soft)",
  borderRadius: 4,
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-md)",
};

const textareaStyle: CSSProperties = {
  width: "100%",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  fontVariantNumeric: "tabular-nums",
  padding: "6px 8px",
  border: "1px solid var(--border-row)",
  borderRadius: 4,
  background: "var(--surface-1)",
  color: "var(--text-primary)",
  resize: "vertical",
};

const editorRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  marginTop: 6,
};

const editorHintStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const aggStrongStyle: CSSProperties = {
  ...monoStrongStyle,
  color: "var(--accent)",
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const aggPrimaryStyle: CSSProperties = {
  ...monoPrimaryStyle,
  color: "var(--accent)",
  fontWeight: 700,
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const errorStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--negative)",
  fontSize: "var(--font-size-sm)",
};
