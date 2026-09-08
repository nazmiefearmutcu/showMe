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
 * Honesty: the backend feed only reports its own 12-language registry;
 * the switcher list is built from @/i18n `listLocales()` so it keeps
 * working when the sidecar is down (labels are enriched from the payload
 * when it answers). Coverage pills are computed with
 * `isLocaleComplete()` — only shell chrome is translated; function panes
 * hardcode English. Arabic additionally flips the document to RTL.
 */
import { useMemo, useState, type CSSProperties } from "react";
import {
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

export function LANGPane({ code }: FunctionPaneProps) {
  // The UI locale is the source of truth for what is rendered; the
  // applied value mirrors it into the backend LANG call.
  const activeLocale = useLocale();
  const [appliedLang, setAppliedLang] = useState<Locale>(() => locale());

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

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={20} />
        <Skeleton height={20} />
        <Skeleton height={20} width="80%" />
      </div>
    ) : state === "error" ? (
      <Empty
        title="Backend registry unavailable"
        body={
          error?.message ??
          "The LANG registry call failed. The switcher below still works — it drives the UI locale directly."
        }
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
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
        <ul style={listStyle} aria-label="Locale options">
          {locales.map((loc) => {
            const isActive = loc === activeLocale;
            const complete = isLocaleComplete(loc);
            return (
              <li key={loc}>
                <button
                  type="button"
                  className="btn"
                  aria-pressed={isActive}
                  onClick={() => applyLocale(loc)}
                  style={isActive ? rowActiveStyle : rowStyle}
                  title={`Switch UI language to ${labelByLang.get(loc) ?? loc}`}
                >
                  <span style={codeStyle}>{loc.toUpperCase()}</span>
                  <span style={labelStyle}>
                    {labelByLang.get(loc) ?? loc}
                  </span>
                  <span style={spacerStyle} />
                  <Pill
                    tone={isActive ? "accent" : complete ? "positive" : "muted"}
                    variant="soft"
                    withDot={false}
                  >
                    {isActive ? "active" : complete ? "shell complete" : "shell labels"}
                  </Pill>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Language Switch"
          subtitle={`${locales.length} locales · active ${activeLocale}`}
          trailing={
            <FunctionControlGroup>
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
  fontSize: 11,
  padding: "6px 8px",
  fontFamily: "JetBrains Mono, monospace",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 6,
  gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  textAlign: "left",
};

const rowActiveStyle: CSSProperties = {
  ...rowStyle,
  border: "1px solid var(--accent, var(--text-primary))",
};

const codeStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  color: "var(--text-primary)",
  fontSize: 11,
  minWidth: 28,
};

const labelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-secondary)",
  fontSize: 11,
};

const spacerStyle: CSSProperties = {
  flex: 1,
};
