/**
 * BRIEF — Daily briefing (watchlist + top stories).
 *
 * Global feed (not symbol-bound): the backend composes a briefing from the
 * live RSS/GDELT news ranks — it does NOT call an LLM and does NOT fabricate
 * prose. Body: per-section briefing groups (Watchlist / Top stories) where
 * each headline links out to its evidence article and carries a citation
 * line (source · feed · published · matched symbol). Articles whose payload
 * has no usable absolute URL render unlinked with an honest "no link
 * provided" note — the pane never invents a link target.
 *
 * Honesty: the generated-at stamp comes from the payload's as_of card;
 * provider outages arrive as status "provider_unavailable" and are surfaced
 * verbatim — the brief never renders a fake "all quiet today" summary.
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
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface BRIEFArticle {
  title?: string | null;
  link?: string | null;
  url?: string | null;
  summary?: string | null;
  published_at?: string | null;
  source?: string | null;
  feed?: string | null;
  matched_symbol?: string | null;
  section?: string | null;
  severity?: string | null;
}

interface BRIEFCard {
  key?: string | null;
  label?: string | null;
  value?: unknown;
}

interface BRIEFData {
  status?: string;
  articles?: BRIEFArticle[];
  rows?: BRIEFArticle[];
  watchlist?: string[];
  article_count?: number;
  cards?: BRIEFCard[];
  methodology?: string;
  reason?: string;
  next_actions?: string[];
}

type SectionFilter = "all" | "watchlist" | "top_stories";

const SECTION_OPTIONS: { value: SectionFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "watchlist", label: "Watchlist" },
  { value: "top_stories", label: "Top stories" },
];

const SECTION_LABELS: Record<string, string> = {
  watchlist: "Watchlist",
  top_stories: "Top stories",
};

export function BRIEFPane({ code }: FunctionPaneProps) {
  const [section, setSection] = usePersistentOption<SectionFilter>(
    "showme.brief.section",
    SECTION_OPTIONS.map((o) => o.value),
    "all",
  );

  const { state, data, error, refetch } = useFunction<BRIEFData>({ code });

  const payload = data?.data;
  const articles: BRIEFArticle[] = useMemo(
    () => payload?.articles ?? payload?.rows ?? [],
    [payload],
  );
  const status = payload?.status ?? "—";

  // Generated-at stamp from the payload's as_of card (fallback: envelope).
  const generatedAt = useMemo(() => {
    const card = (payload?.cards ?? []).find((c) => c.key === "as_of");
    const raw =
      typeof card?.value === "string" ? card.value : (data?.asOf ?? "");
    return fmtStamp(raw);
  }, [payload, data]);

  // Audit A3 BRIEF [OPP]: the payload's `cards` already carry the
  // authoritative counts; render them in a KPI ribbon, but ONLY when the
  // card is actually present (missing card → no tile, never a fake zero).
  const articleCountCard = useMemo(
    () => cardNumeric(payload?.cards, "article_count"),
    [payload],
  );
  const watchlistSizeCard = useMemo(
    () => cardNumeric(payload?.cards, "watchlist_size"),
    [payload],
  );
  const hasKpi = articleCountCard != null || watchlistSizeCard != null;

  const groups = useMemo(() => {
    const wanted =
      section === "all"
        ? ["watchlist", "top_stories"]
        : [section];
    return wanted
      .map((key) => ({
        key,
        label: SECTION_LABELS[key] ?? key,
        items: articles.filter((a) => (a.section ?? "") === key),
      }))
      // Sections the filter asks for but the payload has no rows for are
      // still listed — with an explicit "no articles" note — while groups
      // outside the current filter disappear entirely.
      .filter((g) => section !== "all" || g.items.length > 0);
  }, [articles, section]);

  const watchlist = payload?.watchlist ?? [];

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={20} />
      <Skeleton height={48} />
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
  ) : articles.length === 0 ? (
    <Empty
      title="No briefing returned"
      body={
        payload?.next_actions?.[0] ??
        payload?.reason ??
        "No live headlines were available — the brief never invents a quiet-day summary."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {hasKpi && (
        <section style={kpiGridStyle} aria-label="BRIEF KPI ribbon">
          {articleCountCard != null && (
            <StatCard
              label="Stories"
              value={String(articleCountCard)}
              caption="PAYLOAD CARD · ARTICLE_COUNT"
              tone="neutral"
            />
          )}
          {watchlistSizeCard != null && (
            <StatCard
              label="Watchlist"
              value={String(watchlistSizeCard)}
              caption="PAYLOAD CARD · WATCHLIST_SIZE"
              tone="neutral"
            />
          )}
        </section>
      )}
      {watchlist.length > 0 && (
        <span className="u-text-mute" style={watchlistStyle}>
          Watchlist: {watchlist.join(", ")}
        </span>
      )}
      {groups.map((g) => (
        <section key={g.key} aria-label={`Briefing — ${g.label}`}>
          <div style={sectionTitleStyle}>{g.label}</div>
          {g.items.length === 0 ? (
            <span className="u-text-mute" style={noRowsStyle}>
              No articles in this section.
            </span>
          ) : (
            <ul style={listStyle}>
              {g.items.map((a, i) => (
                <ArticleItem key={`${a.title ?? ""}-${i}`} article={a} />
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Daily Brief"
          subtitle={`${articles.length} stories · generated ${generatedAt}`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="SECTION"
                value={section}
                options={SECTION_OPTIONS}
                onChange={(next) => setSection(next as SectionFilter)}
                title="Section filter"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh briefing"
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
          <StatusSection label="stories" value={articles.length} />
          <StatusDivider />
          <StatusSection label="watchlist" value={watchlist.length || "—"} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="section" value={section} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * One cited headline: the title links out to the evidence article when the
 * payload carries an absolute URL (`link` first, legacy `url` fallback);
 * otherwise the headline stays unlinked with an honest note. The citation
 * line stays attached to its headline.
 */
function ArticleItem({ article }: { article: BRIEFArticle }) {
  const raw = [article.link, article.url].find(
    (c): c is string => typeof c === "string" && /^https?:\/\//.test(c.trim()),
  );
  const href = raw ? raw.trim() : null;
  const title = article.title?.trim() || "Untitled headline";
  const severity = (article.severity ?? "").toLowerCase();
  return (
    <li style={itemStyle}>
      <div style={titleRowStyle}>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            style={linkStyle}
          >
            {title}
          </a>
        ) : (
          <>
            <span style={unlinkedTitleStyle}>{title}</span>
            <span className="u-text-mute" style={noLinkStyle}>
              no link provided
            </span>
          </>
        )}
        {severity === "medium" && (
          <Pill tone="warn" variant="soft" withDot={false}>
            medium
          </Pill>
        )}
        {severity === "high" && (
          <Pill tone="negative" variant="soft" withDot={false}>
            high
          </Pill>
        )}
      </div>
      <div className="u-text-mute" style={citationStyle}>
        {[
          article.source ?? "—",
          article.feed ?? "—",
          fmtStamp(article.published_at ?? ""),
          article.matched_symbol ?? "—",
        ].join(" · ")}
      </div>
      {article.summary ? (
        <p className="u-text-mute" style={summaryStyle}>
          {article.summary}
        </p>
      ) : null}
    </li>
  );
}

/**
 * Read a numeric card value by key. Returns null when the card is missing or
 * carries a non-finite value — the caller must not render a fabricated 0.
 */
function cardNumeric(cards: BRIEFCard[] | undefined, key: string): number | null {
  const card = (cards ?? []).find((c) => c.key === key);
  const value = card?.value;
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * "2026-09-05T09:25:00+00:00" → "2026-09-05 09:25 UTC". The backend stamps
 * UTC ISO strings; slicing (not Date parsing) keeps the exact payload value
 * on screen with no timezone re-interpretation. Blank input → "—".
 */
function fmtStamp(iso: string): string {
  if (!iso) return "—";
  if (iso.length < 16) return iso;
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

const watchlistStyle: CSSProperties = { fontSize: "var(--font-size-md)" };
const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};
const sectionTitleStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  fontWeight: 600,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  marginBottom: 6,
};
const noRowsStyle: CSSProperties = { fontSize: "var(--font-size-md)" };
const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 12,
};
const itemStyle: CSSProperties = {
  borderBottom: "1px solid var(--border)",
  paddingBottom: 10,
};
const titleRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 8,
  flexWrap: "wrap",
};
const linkStyle: CSSProperties = {
  color: "var(--accent)",
  fontWeight: 600,
  fontSize: "var(--font-size-lg)",
  textDecoration: "none",
};
const unlinkedTitleStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 600,
  fontSize: "var(--font-size-lg)",
};
const noLinkStyle: CSSProperties = { fontSize: "var(--font-size-sm)" };
const citationStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  marginTop: 2,
  fontFamily: "JetBrains Mono, monospace",
};
const summaryStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  margin: "4px 0 0",
  maxWidth: 860,
};
