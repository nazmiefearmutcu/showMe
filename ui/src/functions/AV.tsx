/**
 * AV — Audio / Video Archive.
 *
 * Keyless playable archive: per-symbol SEC EDGAR filing rows (8-K / 10-Q /
 * 10-K / proxy) when a symbol is in scope, or the global finance-podcast RSS
 * archive otherwise. Header: scope control + committed query filter
 * (persisted under `showme.av.*`). Body: archive list — title, date,
 * duration, media-type chip and an open link taken ONLY from payload URLs.
 * Provider outages / empty filters render the backend's honest reason —
 * no placeholder rows.
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
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface AVItem {
  event_date?: string;
  filing_date?: string;
  published?: string;
  title?: string;
  media_type?: string;
  duration_seconds?: number | null;
  duration?: string;
  play_url?: string;
  url?: string;
  source_url?: string;
  source?: string;
  feed?: string;
  form?: string;
  symbol?: string;
  has_transcript?: boolean;
  summary?: string;
}

interface AVCards {
  total_items?: number;
  items_with_transcript?: number;
  latest_event_date?: string | null;
  data_mode?: string;
}

interface AVData {
  status?: string;
  reason?: string;
  rows?: AVItem[];
  items?: AVItem[];
  query?: string;
  symbol?: string;
  feed_count?: number;
  count?: number;
  cards?: AVCards;
  next_actions?: string[];
  methodology?: string;
}

type ScopeValue = "symbol" | "global";
const SCOPE_OPTIONS = [
  { value: "symbol" as ScopeValue, label: "symbol" },
  { value: "global" as ScopeValue, label: "global" },
] as const;
const SCOPE_IDS = SCOPE_OPTIONS.map((o) => o.value);

export function AVPane({ code, symbol }: FunctionPaneProps) {
  const [scope, setScope] = usePersistentOption<ScopeValue>(
    "showme.av.scope",
    SCOPE_IDS,
    "symbol",
  );
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");

  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<AVData>({
    code,
    symbol: scope === "symbol" ? effectiveSymbol : undefined,
    params: { symbol: scope === "symbol" ? effectiveSymbol : "", query },
    enabled: scope === "global" || !!effectiveSymbol,
  });

  const payload = data?.data;
  const items = useMemo(() => payload?.rows ?? payload?.items ?? [], [payload]);
  const cards = payload?.cards;
  const status = payload?.status ?? "—";
  const unavailable = status === "provider_unavailable";

  const commit = () => setQuery(draft.trim());

  const body = scope === "symbol" && !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="Switch scope to global for the podcast archive, or pick an equity ticker." icon="⌖" />
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
  ) : unavailable ? (
    <Empty
      title="Media archive unavailable"
      body={payload?.reason ?? "The media / filings providers are unreachable — no placeholder rows are shown."}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : items.length === 0 ? (
    <Empty
      title="No archive entries"
      body={payload?.reason ?? "The archive returned no entries for these filters."}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="AV archive summary">
        <StatCard
          label="Archive items"
          value={String(cards?.total_items ?? items.length)}
          caption={scope === "symbol" ? `SEC EDGAR · ${effectiveSymbol}` : `${payload?.feed_count ?? 0} RSS FEEDS`}
          tone="neutral"
        />
        <StatCard
          label="With transcript / document"
          value={String(cards?.items_with_transcript ?? items.filter((i) => i.has_transcript).length)}
          caption="PRIMARY DOC OR TRANSCRIPT ATTACHED"
          tone="neutral"
        />
        <StatCard
          label="Latest event"
          value={(cards?.latest_event_date ?? "—").slice(0, 10)}
          caption={`DATA MODE ${cards?.data_mode ?? "—"}`}
          tone="neutral"
        />
      </section>
      <ul style={listStyle} aria-label="AV archive items">
        {items.map((item, i) => {
          const link = item.play_url ?? item.url;
          return (
            <li key={`${link ?? item.title ?? "item"}-${i}`} style={rowStyle}>
              <Pill tone="accent" variant="soft" withDot={false}>
                {item.media_type ?? "media"}
              </Pill>
              <div style={contentStyle}>
                <div style={titleStyle}>{item.title ?? "—"}</div>
                <div style={metaStyle}>
                  {[
                    item.source ?? item.feed,
                    fmtDate(item.event_date ?? item.published ?? item.filing_date),
                    fmtDuration(item),
                    item.form ? `form ${item.form}` : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </div>
              {link ? (
                <a
                  href={link}
                  target="_blank"
                  rel="noreferrer"
                  style={linkStyle}
                  aria-label={`Open ${item.title ?? "archive item"}`}
                >
                  open ↗
                </a>
              ) : null}
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
          title={`Audio / Video Archive — ${scope === "symbol" ? effectiveSymbol || "" : "global"}`}
          subtitle={`${items.length} items · ${scope === "symbol" ? "SEC EDGAR archive" : "podcast RSS archive"}${query ? ` · query "${query}"` : ""}`}
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
                  placeholder="filter media…"
                  aria-label="Archive query filter"
                  style={inputStyle}
                />
                <button type="submit" className="btn" disabled={!draft.trim()} title="Apply media filter">
                  Filter
                </button>
              </form>
              <SegmentedControl
                label="SCOPE"
                value={scope}
                options={SCOPE_OPTIONS}
                onChange={setScope}
                title="Archive scope"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={scope === "symbol" && !effectiveSymbol}
                title="Refresh media archive"
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
          <StatusSection label="items" value={items.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="scope" value={scope} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function fmtDate(v: string | undefined): string {
  const s = String(v ?? "").trim();
  return s ? s.slice(0, 10) : "";
}

function fmtDuration(item: AVItem): string {
  const secs = item.duration_seconds;
  if (typeof secs === "number" && Number.isFinite(secs) && secs > 0) {
    const m = Math.floor(secs / 60);
    const s = Math.round(secs % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  const raw = item.duration;
  return raw ? String(raw) : "";
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
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
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
  overflowWrap: "anywhere",
};

const metaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const inputStyle: CSSProperties = {
  width: 150,
};

const linkStyle: CSSProperties = {
  color: "var(--accent)",
  textDecoration: "none",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
};
