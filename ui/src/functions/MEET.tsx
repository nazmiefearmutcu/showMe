/**
 * MEET — Meeting Briefing.
 *
 * Pre-meeting brief assembled by the backend from Notion / Granola / GDELT /
 * portfolio + the public people reference. Header: topic input (committed
 * on Enter / Brief) + status pill + refresh. Body: briefing-section chips
 * (filterable), participant / note / news / portfolio rows with honest
 * status pills, connector status strip, and the pre-meeting questions.
 * Missing connectors render as `not_configured` / `not_available` — the
 * pane never invents notes or headlines.
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
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface MEETRow {
  section?: string;
  name?: string;
  role?: string;
  company?: string;
  title?: string;
  status?: string;
  source?: string;
  source_url?: string;
  url?: string;
  published_at?: string;
  symbol?: string;
  quantity?: number;
  avg_cost?: number | null;
  currency?: string;
}

interface MEETSection {
  section?: string;
  status?: string;
  count?: number;
}

interface MEETData {
  topic?: string;
  status?: string;
  meeting_date?: string;
  company?: { name?: string; sector?: string; industry?: string; ceo?: string; symbol?: string } | null;
  agenda?: { item?: string; status?: string }[];
  rows?: MEETRow[];
  briefing_sections?: MEETSection[];
  connection_status?: { source?: string; status?: string }[];
  questions?: string[];
  portfolio_position?: { symbol?: string; quantity?: number; avg_cost?: number | null; currency?: string } | null;
  recent_news?: { title?: string; source?: string; url?: string }[];
  methodology?: string;
}

export function MEETPane({ code, symbol }: FunctionPaneProps) {
  const fallbackTopic = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const [draft, setDraft] = useState("");
  const [topic, setTopic] = useState("");
  const [sectionFilter, setSectionFilter] = useState<string>("all");

  const effectiveTopic = topic || fallbackTopic;
  const { state, data, error, refetch } = useFunction<MEETData>({
    code,
    symbol: fallbackTopic || undefined,
    params: { topic: effectiveTopic },
    enabled: !!effectiveTopic,
  });

  const payload = data?.data;
  const allRows = useMemo(() => payload?.rows ?? [], [payload]);
  const sections = useMemo(
    () => Array.from(new Set(allRows.map((r) => r.section ?? "other"))),
    [allRows],
  );
  const rows = useMemo(
    () =>
      sectionFilter === "all"
        ? allRows
        : allRows.filter((r) => (r.section ?? "other") === sectionFilter),
    [allRows, sectionFilter],
  );
  const status = payload?.status ?? "—";

  const commit = () => setTopic(draft.trim());

  const sectionChips: { value: string; label: string }[] = [
    { value: "all", label: "All" },
    ...sections.map((s) => ({ value: s, label: s.replace("_", " ") })),
  ];

  const sectionStatusTone = (s?: string): "positive" | "warn" | "muted" =>
    s === "ready" ? "positive" : s === "needs_data" ? "warn" : "muted";

  const rowBody =
    rows.length === 0 ? null : (
      <ul style={listStyle} aria-label="MEET briefing rows">
        {rows.map((r, i) => (
          <li key={`${r.section ?? "row"}-${i}`} style={rowStyle}>
            <Pill
              tone={
                r.section === "participant"
                  ? "accent"
                  : r.section === "news"
                    ? "positive"
                    : r.section === "portfolio"
                      ? "warn"
                      : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {(r.section ?? "row").replace("_", " ")}
            </Pill>
            <div style={contentStyle}>
              <div style={titleStyle}>
                {r.name ?? r.title ?? (r.symbol ? `${r.symbol} position` : "—")}
                {r.status ? (
                  <Pill
                    tone={sectionStatusTone(r.status)}
                    variant="soft"
                    withDot={false}
                  >
                    {r.status}
                  </Pill>
                ) : null}
              </div>
              <div style={metaStyle}>
                {[
                  r.role,
                  r.company,
                  r.source,
                  typeof r.quantity === "number" ? `qty ${r.quantity}` : "",
                  r.published_at ? String(r.published_at).slice(0, 10) : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
            {r.source_url || r.url ? (
              <a
                href={r.source_url ?? r.url}
                target="_blank"
                rel="noreferrer"
                style={linkStyle}
                aria-label={`Open source for ${r.name ?? r.title ?? "row"}`}
              >
                open ↗
              </a>
            ) : null}
          </li>
        ))}
      </ul>
    );

  const body = !effectiveTopic ? (
    <Empty title="Enter a meeting topic" body="Type a company, person, or theme to build the briefing." icon="⌕" />
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
  ) : allRows.length === 0 && (payload?.agenda?.length ?? 0) === 0 ? (
    <Empty
      title="No briefing returned"
      body="The meeting connector stack returned nothing for this topic — no notes or news are fabricated."
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="MEET summary">
        <StatCard
          label="Meeting date"
          value={payload?.meeting_date?.slice(0, 10) ?? "—"}
          caption={`TOPIC "${(payload?.topic ?? effectiveTopic).toUpperCase()}"`}
          tone="neutral"
        />
        <StatCard
          label="Participants"
          value={String(
            payload?.briefing_sections?.find((s) => s.section === "participants")?.count ??
              allRows.filter((r) => r.section === "participant").length,
          )}
          caption={payload?.company?.name ?? "—"}
          tone="neutral"
        />
        <StatCard
          label="Connectors ready"
          value={`${(payload?.connection_status ?? []).filter((c) => c.status === "configured" || c.status === "used").length}/${(payload?.connection_status ?? []).length}`}
          caption={(payload?.connection_status ?? [])
            .map((c) => `${c.source}:${c.status}`)
            .join(" · ") || "—"}
          tone={(payload?.connection_status ?? []).every((c) => c.status === "configured" || c.status === "used")
            ? "positive"
            : "neutral"}
        />
      </section>

      {(payload?.briefing_sections ?? []).length > 0 ? (
        <section style={chipsRowStyle} aria-label="Briefing sections">
          {payload?.briefing_sections?.map((s) => (
            <Pill
              key={s.section ?? "section"}
              tone={sectionStatusTone(s.status)}
              variant="soft"
              withDot={false}
            >
              {`${s.section ?? "section"} · ${s.status ?? "—"} (${s.count ?? 0})`}
            </Pill>
          ))}
        </section>
      ) : (payload?.agenda ?? []).length > 0 ? (
        <section aria-label="Agenda" style={agendaStyle}>
          {(payload?.agenda ?? []).map((a, i) => (
            <div key={`${a.item ?? "item"}-${i}`} style={rowStyle}>
              <Pill tone="accent" variant="soft" withDot={false}>
                agenda
              </Pill>
              <span style={titleStyle}>{a.item ?? "—"}</span>
            </div>
          ))}
        </section>
      ) : null}

      {sections.length > 1 ? (
        <section style={chipsRowStyle} aria-label="Row filter">
          {sectionChips.map((c) => (
            <button
              key={c.value}
              type="button"
              disabled={c.value === sectionFilter}
              onClick={() => setSectionFilter(c.value)}
              title={`Filter rows: ${c.label}`}
              className={`fn-segmented__opt${c.value === sectionFilter ? " fn-segmented__opt--active" : ""}`}
            >
              {c.label}
            </button>
          ))}
        </section>
      ) : null}

      {rowBody}

      {(payload?.questions ?? []).length > 0 ? (
        <section aria-label="Pre-meeting questions" style={questionsStyle}>
          <span style={stripLabelStyle}>ask at the meeting</span>
          <ul style={{ ...listStyle, gap: 4 }}>
            {payload?.questions?.map((q, i) => (
              <li key={`q-${i}`} style={questionStyle}>
                {q}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Meeting Briefing — ${effectiveTopic || ""}`}
          subtitle={`${effectiveTopic || "—"} · ${allRows.length} rows · ${payload?.meeting_date?.slice(0, 10) ?? "no date"}`}
          trailing={
            <FunctionControlGroup>
              <form
                className="fn-control-group"
                onSubmit={(e) => {
                  e.preventDefault();
                  commit();
                }}
              >
                <input
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="meeting topic…"
                  aria-label="Meeting topic"
                  style={inputStyle}
                />
                <button type="submit" className="btn" disabled={!draft.trim()} title="Build briefing">
                  Brief
                </button>
              </form>
              <LoadStatePill state={state} status={status === "—" ? null : status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveTopic}
                title="Rebuild briefing"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="rows" value={allRows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="topic" value={effectiveTopic || "—"} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const chipsRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 6,
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: 10,
  padding: "7px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
};

const contentStyle: CSSProperties = {
  minWidth: 0,
  flex: 1,
  display: "grid",
  gap: 2,
};

const titleStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--text-primary)",
  overflowWrap: "anywhere",
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const metaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
};

const stripLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
};

const questionsStyle: CSSProperties = {
  display: "grid",
  gap: 4,
};

const agendaStyle: CSSProperties = {
  display: "grid",
  gap: 6,
};

const questionStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--text-primary)",
};

const inputStyle: CSSProperties = {
  width: 160,
};

const linkStyle: CSSProperties = {
  color: "var(--accent)",
  textDecoration: "none",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};
