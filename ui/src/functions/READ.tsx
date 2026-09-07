/**
 * READ — Reading List.
 *
 * Personal queue over the backend's real SQLite saved-articles store
 * (articles are saved from CN / NI / NSE / TOP via a Save action). Header:
 * persisted status filter (`showme.read.status`) + row limit + status pills
 * + refresh. Body: queue KPI ribbon (in view / unread / in progress), an
 * honesty strip stating how the list is derived (payload-declared sqlite
 * store + cached-snapshot mode, never a live fetch), and the article cards —
 * status pill, headline, source, saved stamp, tags. The headline links out
 * ONLY from the payload's own absolute URL (rows without a link render
 * unlinked, never with an invented target).
 *
 * Honesty: an empty store is distinct from "no rows match the filters", and
 * both are distinct from a store read failure (`provider_unavailable`,
 * reason surfaced verbatim). No synthetic placeholder rows in any branch.
 */
import { useMemo, type CSSProperties } from "react";
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
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption, ROW_LIMITS, type RowLimit } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface READArticle {
  article_id?: string | null;
  saved_utc?: string | null;
  status?: string | null;
  title?: string | null;
  matched_symbol?: string | null;
  source?: string | null;
  tags?: string[];
  published_utc?: string | null;
  link?: string | null;
  read_utc?: string | null;
}

interface READPayload {
  status?: string;
  reason?: string;
  rows?: READArticle[];
  articles?: READArticle[];
  article_count?: number;
  unread_count?: number;
  in_progress_count?: number;
  summary?: string;
  methodology?: string;
  next_actions?: string[];
}

type READStatusFilter = "all" | "unread" | "in_progress" | "read" | "archived";

const STATUS_OPTIONS: { value: READStatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "unread", label: "Unread" },
  { value: "in_progress", label: "Reading" },
  { value: "read", label: "Read" },
  { value: "archived", label: "Archived" },
];

function statusTone(status?: string | null): "accent" | "warn" | "positive" | "muted" {
  switch ((status ?? "").toLowerCase()) {
    case "unread":
      return "accent";
    case "in_progress":
      return "warn";
    case "read":
      return "positive";
    default:
      return "muted";
  }
}

export function READPane({ code, symbol }: FunctionPaneProps) {
  const [statusFilter, setStatusFilter] = usePersistentOption<READStatusFilter>(
    "showme.read.status",
    STATUS_OPTIONS.map((o) => o.value),
    "all",
  );
  const [limit, setLimit] = usePersistentOption<RowLimit>(
    "showme.read.limit",
    ROW_LIMITS,
    50,
  );

  const { state, data, error, refetch } = useFunction<READPayload>({
    code,
    symbol: symbol || undefined,
    params: {
      limit,
      ...(statusFilter === "all" ? {} : { status: statusFilter }),
    },
  });

  const payload = data?.data as READPayload;
  const envelopeStatus = data?.status;
  const status = payload?.status ?? envelopeStatus ?? "—";
  // The backend's provider_unavailable payload still carries rows: [] —
  // branch on the payload status, never on the presence of the rows key.
  const isUnavailable = payload?.status === "provider_unavailable";
  const unavailableReason = payload?.reason ?? data?.reason;
  const rows = useMemo<READArticle[]>(() => {
    const list = payload?.rows ?? payload?.articles ?? [];
    return Array.isArray(list) ? list : [];
  }, [payload]);
  const nextActions = useMemo<string[]>(() => payload?.next_actions ?? [], [payload]);

  const articleCount = payload?.article_count ?? rows.length;
  const unreadCount = payload?.unread_count;
  const inProgressCount = payload?.in_progress_count;
  const summary = payload?.summary;
  const methodology = payload?.methodology;

  const metadata = data?.metadata;
  const storeTotal =
    typeof metadata?.store_total === "number" ? metadata.store_total : undefined;
  const persistence =
    typeof metadata?.persistence === "string" ? metadata.persistence : undefined;
  const dataMode =
    typeof metadata?.data_mode === "string" ? metadata.data_mode : undefined;

  const storeEmpty = rows.length === 0 && storeTotal === 0;

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={20} />
        <Skeleton height={48} />
        <Skeleton height={48} width="90%" />
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
    ) : isUnavailable ? (
      <Empty
        title="Reading list unavailable"
        body={
          unavailableReason ??
          "The saved-articles store could not be read — nothing is fabricated while the store is unreachable."
        }
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : storeEmpty ? (
      <Empty
        title="Reading list is empty"
        body="No articles have been saved yet. Save articles from CN / NI / NSE / TOP via their Save action to populate this queue — no placeholder rows are invented here."
        icon="≡"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : rows.length === 0 ? (
      <Empty
        title="No saved articles match the filters"
        body={`The store has ${storeTotal ?? "—"} article(s) in total but none match status "${statusFilter}" at limit ${limit}. Clear the filter or raise the row limit.`}
        icon="≡"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <section style={kpiGridStyle} aria-label="READ queue summary">
          <StatCard
            label="In view"
            value={String(articleCount)}
            caption={summary ? summary.toUpperCase() : "SAVED ARTICLES MATCHING FILTERS"}
            tone="neutral"
          />
          <StatCard
            label="Unread"
            value={unreadCount != null ? String(unreadCount) : "—"}
            caption="WAITING IN THE QUEUE"
            tone={(unreadCount ?? 0) > 0 ? "negative" : "neutral"}
          />
          <StatCard
            label="In progress"
            value={inProgressCount != null ? String(inProgressCount) : "—"}
            caption="MARKED READING"
            tone="neutral"
          />
          <StatCard
            label="Store total"
            value={storeTotal != null ? String(storeTotal) : "—"}
            caption="ALL SAVED ARTICLES (ANY FILTER)"
            tone="neutral"
          />
        </section>

        <section style={honestyStyle} aria-label="READ data derivation">
          <Pill tone="muted" variant="soft" withDot={false}>
            {persistence === "sqlite_reading_list_v1"
              ? "sqlite store"
              : (persistence ?? "store backend unreported")}
          </Pill>
          <Pill tone="muted" variant="soft" withDot={false}>
            {dataMode ? dataMode.replace(/_/g, " ") : "data mode unreported"}
          </Pill>
          <span style={honestyTextStyle}>
            Derived only from articles you saved via CN / NI / NSE / TOP — statuses
            are tracked server-side; READ never invents queue rows.
          </span>
          {methodology ? (
            <span style={honestyMetaStyle} title={methodology}>
              derivation details on hover
            </span>
          ) : null}
        </section>

        {nextActions.length > 0 && (
          <div style={hintStyle} aria-label="READ hints">
            {nextActions.join(" ")}
          </div>
        )}

        <ul style={listStyle} aria-label="Reading list articles">
          {rows.map((row, i) => (
            <ArticleCard key={`${row.article_id ?? row.title ?? "row"}-${i}`} row={row} />
          ))}
        </ul>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Reading List"
          subtitle={`${articleCount} in view${unreadCount != null ? ` · ${unreadCount} unread` : ""}${statusFilter !== "all" ? ` · filter ${statusFilter}` : ""}`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="STATUS"
                value={statusFilter}
                options={STATUS_OPTIONS}
                onChange={setStatusFilter}
                title="Filter by read state"
              />
              <SegmentedControl
                label="ROWS"
                value={limit}
                options={ROW_LIMITS}
                onChange={setLimit}
                title="Row limit"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-read the saved-articles store"
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
          <StatusSection label="in view" value={articleCount} />
          <StatusDivider />
          <StatusSection label="unread" value={unreadCount ?? "—"} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="last" value={limit} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * One saved article: the headline links out ONLY from the payload's own
 * absolute URL; rows without a link stay unlinked with an honest
 * "no link provided" note (NSE/BRIEF convention).
 */
function ArticleCard({ row }: { row: READArticle }) {
  const href =
    typeof row.link === "string" && /^https?:\/\//.test(row.link.trim())
      ? row.link.trim()
      : null;
  const title = row.title?.trim() || "Untitled saved article";
  return (
    <li style={rowStyle}>
      <Pill tone={statusTone(row.status)} variant="soft" withDot={false}>
        {row.status ?? "—"}
      </Pill>
      <div style={contentStyle}>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            style={linkStyle}
            title="Open back in source"
          >
            {title} ↗
          </a>
        ) : (
          <>
            <span style={unlinkedTitleStyle}>{title}</span>
            <span className="u-text-mute" style={noLinkStyle}>
              no link provided
            </span>
          </>
        )}
        <div style={metaStyle}>
          {[
            row.source ?? "—",
            row.matched_symbol ?? null,
            row.saved_utc ? `saved ${fmtStamp(row.saved_utc)}` : null,
            (row.tags ?? []).length > 0
              ? `tags: ${(row.tags ?? []).slice(0, 4).join(", ")}`
              : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </div>
    </li>
  );
}

/** UTC ISO string → "YYYY-MM-DD HH:MM UTC" (slicing keeps the payload value verbatim). */
function fmtStamp(iso: string): string {
  if (!iso) return "—";
  if (iso.length < 16) return iso;
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const honestyStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const honestyTextStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-mute)",
};

const honestyMetaStyle: CSSProperties = {
  fontSize: 10,
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
  textDecoration: "underline dotted",
  cursor: "help",
};

const hintStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-mute)",
  border: "1px dashed var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 8,
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: 10,
  padding: "8px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
};

const contentStyle: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gap: 2,
};

const linkStyle: CSSProperties = {
  color: "var(--accent)",
  fontWeight: 600,
  fontSize: 13,
  textDecoration: "none",
  overflowWrap: "anywhere",
};

const unlinkedTitleStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 600,
  fontSize: 13,
  overflowWrap: "anywhere",
};

const noLinkStyle: CSSProperties = { fontSize: 11, marginLeft: 6 };

const metaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
};
