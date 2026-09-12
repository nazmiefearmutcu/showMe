/**
 * CACT — Corporate Actions (dividends / splits / 8-K timeline).
 *
 * Header: TYPE filter chips (all / dividends / splits / 8-K & filings) +
 * WINDOW segmented control (all / past / upcoming) + status pill + refresh.
 * Body: KPI ribbon (actions in view, dividends, splits, latest action date)
 * + a dense actions table — date, type pill, amount/value and notes (unit,
 * accession no., document, provider reason), symbol-bound.
 *
 * Data honesty: provider_unavailable payloads render an explicit empty state
 * carrying the backend reason; an empty upcoming window says so outright
 * instead of implying forecasted actions (providers here report history).
 */
import { useMemo, type CSSProperties } from "react";
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
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface CACTRow {
  symbol?: string;
  action_type?: string;
  event_date?: string | null;
  value?: number | string | null;
  unit?: string;
  source_mode?: string;
  accession?: string;
  document?: string;
  reason?: string;
}

interface CACTData {
  status?: string;
  reason?: string;
  rows?: CACTRow[];
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

type TypeFilter = "all" | "dividend" | "split" | "filings";
type WindowFilter = "all" | "past" | "upcoming";

const TYPE_OPTIONS = [
  { value: "all", label: "ALL" },
  { value: "dividend", label: "DIV" },
  { value: "split", label: "SPLIT" },
  { value: "filings", label: "8-K" },
] as const satisfies readonly { value: TypeFilter; label: string }[];
const TYPE_IDS = TYPE_OPTIONS.map((o) => o.value);

const WINDOW_OPTIONS = [
  { value: "all", label: "ALL" },
  { value: "past", label: "PAST" },
  { value: "upcoming", label: "UPCOMING" },
] as const satisfies readonly { value: WindowFilter; label: string }[];
const WINDOW_IDS = WINDOW_OPTIONS.map((o) => o.value);

function classifyAction(
  actionType: string | undefined,
): Exclude<TypeFilter, "all"> {
  const t = (actionType ?? "").toLowerCase();
  if (t.startsWith("dividend")) return "dividend";
  if (t.startsWith("split")) return "split";
  return "filings";
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function isUpcoming(row: CACTRow, today: string): boolean | null {
  const d = (row.event_date ?? "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}/.test(d)) return null;
  return d > today;
}

export function CACTPane({ code, symbol }: FunctionPaneProps) {
  const [typeFilter, setTypeFilter] = usePersistentOption<TypeFilter>(
    "showme.cact.type",
    TYPE_IDS,
    "all",
  );
  const [windowFilter, setWindowFilter] = usePersistentOption<WindowFilter>(
    "showme.cact.when",
    WINDOW_IDS,
    "all",
  );
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<CACTData>({
    code,
    symbol: effectiveSymbol,
    params: {},
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: CACTRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const providerDown = state === "ok" && status === "provider_unavailable";

  const today = todayISO();
  const filtered = useMemo(
    () =>
      rows.filter((r) => {
        if (typeFilter !== "all" && classifyAction(r.action_type) !== typeFilter) {
          return false;
        }
        if (windowFilter !== "all") {
          const upcoming = isUpcoming(r, today);
          if (upcoming === null) return false;
          if (windowFilter === "upcoming" && !upcoming) return false;
          if (windowFilter === "past" && upcoming) return false;
        }
        return true;
      }),
    [rows, typeFilter, windowFilter, today],
  );

  const counts = useMemo(
    () => ({
      dividends: rows.filter((r) => classifyAction(r.action_type) === "dividend").length,
      splits: rows.filter((r) => classifyAction(r.action_type) === "split").length,
      latest: rows
        .map((r) => (r.event_date ?? "").slice(0, 10))
        .filter((d) => /^\d{4}-\d{2}-\d{2}/.test(d))
        .sort()
        .at(-1) ?? "—",
    }),
    [rows],
  );

  const COLS: DataGridColumn<CACTRow>[] = useMemo(
    () => [
      {
        key: "event_date",
        header: "Date",
        width: 124,
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {(r.event_date ?? "—").slice(0, 10)}
          </span>
        ),
      },
      {
        key: "action_type",
        header: "Type",
        width: 148,
        render: (r) => {
          const kind = classifyAction(r.action_type);
          return (
            <Pill
              tone={
                r.action_type === "provider_unavailable"
                  ? "warn"
                  : kind === "dividend"
                    ? "accent"
                    : kind === "split"
                      ? "positive"
                      : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {r.action_type ?? "—"}
            </Pill>
          );
        },
      },
      {
        key: "value",
        header: "Amount / value",
        numeric: true,
        width: 150,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtValue(r.value)}</span>
        ),
      },
      {
        key: "notes",
        header: "Notes",
        width: 320,
        render: (r) => (
          <span style={notesStyle}>{buildNotes(r)}</span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 200,
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={
                (r.source_mode ?? "").includes("unavailable") ? "warn" : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {r.source_mode}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="CACT needs an equity / ETF ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
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
  ) : providerDown || rows.length === 0 ? (
    <Empty
      title="No corporate actions returned"
      body={
        rows[0]?.reason ??
        payload?.reason ??
        "No dividend, split, or dated 8-K corporate-action rows were returned."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : filtered.length === 0 ? (
    <Empty
      title={
        windowFilter === "upcoming"
          ? "No upcoming actions in provider data"
          : "No actions match the current filters"
      }
      body={
        windowFilter === "upcoming"
          ? "Dividend/split feeds here report history; providers in this payload carry no dated future actions."
          : "Widen the TYPE or WINDOW filters to see more of the timeline."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="CACT KPI ribbon">
        <StatCard
          label="Actions in view"
          value={String(filtered.length)}
          caption={`${rows.length} TOTAL RETURNED`}
          tone="neutral"
        />
        <StatCard
          label="Dividends"
          value={String(counts.dividends)}
          caption="CASH / SHARE ROWS"
          tone="neutral"
        />
        <StatCard
          label="Splits"
          value={String(counts.splits)}
          caption="RATIO ROWS"
          tone="neutral"
        />
        <StatCard
          label="Latest action"
          value={counts.latest}
          caption={`WINDOW ${windowFilter.toUpperCase()}`}
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={filtered}
        rowKey={(r, i) => `${r.action_type ?? ""}-${r.event_date ?? ""}-${i}`}
        density="compact"
        ariaLabel="CACT corporate actions table"
        // Lane B4: latest action first — the corporate-action timeline is
        // read newest-first; null dates sink to the bottom.
        defaultSortKey="event_date"
        defaultSortDir="descending"
        keyboardNavigable
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Corporate Actions — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${filtered.length} of ${rows.length} actions`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="TYPE"
                value={typeFilter}
                options={TYPE_OPTIONS}
                onChange={setTypeFilter}
                title="Action type filter"
              />
              <SegmentedControl
                label="WINDOW"
                value={windowFilter}
                options={WINDOW_OPTIONS}
                onChange={setWindowFilter}
                title="Past vs upcoming"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh corporate actions"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="rows" value={`${filtered.length}/${rows.length}`} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="type" value={typeFilter} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function fmtValue(v: number | string | null | undefined): string {
  if (v == null || v === "") return "—";
  if (typeof v === "string") return v;
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

function buildNotes(r: CACTRow): string {
  const parts: string[] = [];
  if (r.unit) parts.push(r.unit);
  if (r.accession) parts.push(`acc ${r.accession}`);
  if (r.document) parts.push(r.document);
  if (r.reason) parts.push(r.reason);
  return parts.join(" · ") || "—";
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const notesStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-xs)",
};
