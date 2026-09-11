/**
 * LANG — Language Switch (terminal locale options).
 *
 * Surfaces the terminal's 12 supported locales and APPLIES the choice
 * through the UI's real i18n mechanism (`setLocale` from @/i18n —
 * persists to localStorage, updates <html lang/dir>, fires
 * LOCALE_CHANGE_EVENT so every `useLocale()` subscriber re-renders). The
 * same choice is sent to the backend LANG function, which persists
 * runtime/lang.txt for sidecar-side consumers.
 *
 * L7 upgrade: the locale grid is a real DataGrid (sortable locale / label /
 * coverage / active columns, keyboard cell navigation, roving tabindex)
 * with a client-side filter box. Row click applies the locale; the whole
 * switcher still works when the sidecar is down because the list is built
 * from @/i18n `listLocales()`.
 *
 * Honesty: coverage pills are computed with `isLocaleComplete()` — only
 * shell chrome is translated; function panes hardcode English. Arabic
 * additionally flips the document to RTL. The sidecar-persisted value is
 * shown separately and never conflated with the active UI locale.
 */
import { useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { PaneState } from "@/design-system/PaneState";
import { useFunction } from "@/lib/useFunction";
import {
  isLocaleComplete,
  listLocales,
  locale,
  setLocale,
  useLocale,
  type Locale,
} from "@/i18n";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface LANGRow {
  lang?: string;
  label?: string;
  selected?: boolean;
  coverage?: string;
  requires_reload?: boolean;
}

interface LANGData {
  status?: string;
  lang?: string;
  rows?: LANGRow[];
  methodology?: string;
}

interface LangViewRow {
  loc: Locale;
  label: string;
  complete: boolean;
  active: boolean;
}

export function LANGPane({ code }: FunctionPaneProps) {
  // The UI locale is the source of truth for what is rendered; the
  // applied value mirrors it into the backend LANG call.
  const activeLocale = useLocale();
  const [appliedLang, setAppliedLang] = useState<Locale>(() => locale());
  const [search, setSearch] = useState("");

  const { state, data, error, refetch } = useFunction<LANGData>({
    code,
    params: { lang: appliedLang },
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";

  // Backend rows only enrich labels; the switcher works without them.
  const labelByLang = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of payload?.rows ?? []) {
      if (row.lang && row.label) map.set(row.lang, row.label);
    }
    return map;
  }, [payload]);

  const persistedLang = payload?.lang ?? null;

  const applyLocale = (loc: Locale) => {
    setLocale(loc);
    setAppliedLang(loc);
  };

  const locales = useMemo(() => listLocales(), []);

  const viewRows: LangViewRow[] = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return locales
      .map((loc) => ({
        loc,
        label: labelByLang.get(loc) ?? loc,
        complete: isLocaleComplete(loc),
        active: loc === activeLocale,
      }))
      .filter(
        (row) =>
          !needle ||
          row.loc.toLowerCase().includes(needle) ||
          row.label.toLowerCase().includes(needle),
      );
  }, [locales, labelByLang, activeLocale, search]);

  const COLS: DataGridColumn<LangViewRow>[] = useMemo(
    () => [
      {
        key: "loc",
        header: "Locale",
        width: 90,
        sortable: true,
        sortValue: (r) => r.loc,
        render: (r) => (
          <span
            style={codeStyle}
            title={`Switch UI language to ${r.label}`}
          >
            {r.loc.toUpperCase()}
          </span>
        ),
      },
      {
        key: "label",
        header: "Label",
        sortable: true,
        sortValue: (r) => r.label,
        render: (r) => <span style={labelStyle}>{r.label}</span>,
      },
      {
        key: "complete",
        header: "Coverage",
        width: 150,
        sortable: true,
        sortValue: (r) => (r.complete ? 1 : 0),
        render: (r) => (
          <Pill
            tone={r.active ? "accent" : r.complete ? "positive" : "muted"}
            variant="soft"
            withDot={false}
          >
            {r.complete ? "shell complete" : "shell labels"}
          </Pill>
        ),
      },
      {
        key: "active",
        header: "Active",
        width: 96,
        sortable: true,
        sortValue: (r) => (r.active ? 1 : 0),
        render: (r) =>
          r.active ? (
            <Pill tone="accent" variant="soft" withDot={false}>
              active
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const body = (
    <PaneState
      state={state}
      error={error}
      empty={viewRows.length === 0}
      emptyTitle={`No locales match "${search}"`}
      emptyBody="Clear the filter to see all 12 terminal locales."
      emptyAction={
        search ? (
          <button type="button" className="btn" onClick={() => setSearch("")}>
            Clear filter
          </button>
        ) : undefined
      }
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        <div role="status" style={noteStyle} aria-label="Translation coverage note">
          Only shell chrome is translated; function panes hardcode English.
          Arabic flips the document to RTL. The choice persists in the UI and
          is mirrored to the sidecar's runtime/lang.txt.
        </div>
        <section style={kpiGridStyle} aria-label="LANG KPI ribbon">
          <StatCard
            label="Active locale"
            value={activeLocale.toUpperCase()}
            caption={isLocaleComplete(activeLocale) ? "SHELL COMPLETE" : "SHELL LABELS ONLY"}
            tone="positive"
          />
          <StatCard
            label="Locales"
            value={String(locales.length)}
            caption={`${locales.filter((l) => isLocaleComplete(l)).length} SHELL-COMPLETE`}
            tone="neutral"
          />
          <StatCard
            label="Sidecar persisted"
            value={(persistedLang ?? "—").toUpperCase()}
            caption="runtime/lang.txt"
            tone="neutral"
          />
        </section>
        <DataGrid
          columns={COLS}
          rows={viewRows}
          rowKey={(r) => r.loc}
          density="compact"
          ariaLabel="Locale options"
          keyboardNavigable
          defaultSortKey="loc"
          defaultSortDir="ascending"
          onRowClick={(row) => applyLocale(row.loc)}
        />
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Language Switch"
          subtitle={`${viewRows.length}/${locales.length} locales · active ${activeLocale}`}
          trailing={
            <FunctionControlGroup>
              <input
                type="search"
                aria-label="Filter locales"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="filter locales"
                title="Filter locales"
                style={searchStyle}
              />
              <Pill tone="muted" variant="soft" withDot={false}>
                {activeLocale.toUpperCase()}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh language registry"
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
          <StatusSection label="locales" value={locales.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="active" value={activeLocale} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noteStyle: CSSProperties = {
  border: "1px solid var(--border, var(--text-mute))",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  padding: "6px 8px",
  fontFamily: "JetBrains Mono, monospace",
};

const searchStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
  height: 24,
  padding: "0 6px",
  width: 140,
};

const codeStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  color: "var(--text-primary)",
  fontSize: "var(--font-size-sm)",
  cursor: "pointer",
};

const labelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
};
