import { useState, type ReactNode } from "react";
import { relativeTimeLabel } from "@/lib/time";
import { useFunction } from "@/lib/useFunction";
import { useWorkspace } from "@/lib/workspace";
import { EntityChip } from "./EntityChip";
import { ImportanceMeter } from "./ImportanceMeter";
import { QualityPill } from "./QualityPill";
import { SentimentChip } from "./SentimentChip";
import { TierBadge } from "./TierBadge";
import { hhmmUtc } from "./format";
import type { NewsPayload, NewsRow, StoryItem } from "./news-types";

const ASSET_OR_PLACE = new Set(["equity", "crypto", "fx", "commodity", "index", "country"]);

const CONTENT_BADGES = new Set([
  "analysis",
  "opinion",
  "official",
  "press_release",
  "social",
]);

export interface StoryRowProps {
  row: NewsRow;
  /** Pane code used to fetch story detail on expand (TOP, NI, CN, NSE, NALRT). */
  code: string;
  symbol?: string;
  nowMs?: number;
  /** Open the story drawer for this row. */
  onOpenDrawer?: (row: NewsRow) => void;
  /** Add a filter from a country/topic chip. */
  onFilter?: (kind: "country" | "topic", value: string) => void;
  /** Extra meta node rendered before the sentiment chip (e.g. NALRT severity). */
  leading?: ReactNode;
  /** Pane-level row index used for keyboard focus. */
  index?: number;
}

export function openArticle(url: string | null | undefined) {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

export function StoryRow({
  row,
  code,
  symbol,
  nowMs,
  onOpenDrawer,
  onFilter,
  leading,
  index,
}: StoryRowProps) {
  const [expanded, setExpanded] = useState(false);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const url = row.url ?? row.link ?? null;
  const rel = relativeTimeLabel(row.published_at, nowMs) ?? "";
  const abs = hhmmUtc(row.published_at);
  const body = row.excerpt ?? row.summary ?? "";
  const extraSources = Math.max(0, (row.story_size ?? 1) - 1);
  const showBadge = row.content_type && CONTENT_BADGES.has(row.content_type);
  const showLang = row.language && row.language !== "en";
  const sentimentModel = row.sentiment_model ?? null;

  const story = useFunction<NewsPayload>({
    code,
    symbol,
    params: { story_id: row.story_id ?? "" },
    enabled: expanded && Boolean(row.story_id),
  });
  const detailItems: StoryItem[] = story.data?.data?.story?.items ?? [];

  const label = `${row.publisher}, ${rel} ago: ${row.title}`;

  // One chip per entity: tickers/assets and countries come from the salient `symbols` /
  // `countries` lists; `entities` only adds what those cannot show (central banks, people).
  const chipSymbols = Array.from(new Set(row.symbols));
  const chipCountries = Array.from(new Set(row.countries));
  const covered = new Set<string>([...chipSymbols, ...chipCountries]);
  const seenEntity = new Set<string>();
  const chipEntities = row.entities.filter((e) => {
    if (!e.id || covered.has(e.id) || ASSET_OR_PLACE.has(e.type ?? "")) return false;
    if (seenEntity.has(e.id)) return false;
    seenEntity.add(e.id);
    return true;
  });

  return (
    <article
      className="aw-row"
      aria-label={label}
      data-row-index={index}
      tabIndex={-1}
      onClick={(e) => {
        const target = e.target as HTMLElement;
        if (target.closest("button, a, input, select")) return;
        onOpenDrawer?.(row);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) onOpenDrawer?.(row);
      }}
    >
      <div className="aw-row__meta">
        <span className="aw-row__publisher">{row.publisher}</span>
        <TierBadge tier={row.publisher_tier} />
        {showBadge ? <span className="aw-row__badge">{row.content_type}</span> : null}
        {showLang ? <span className="aw-row__badge">{row.language}</span> : null}
        <span className="aw-row__time" title={`${abs} UTC`}>
          {rel ? `${rel} ago` : ""} <span className="aw-mono">{abs} UTC</span>
        </span>
        {row.is_paywalled ? (
          <span className="aw-row__lock" role="img" aria-label="Paywalled at source">
            {"\u{1F512}"}
          </span>
        ) : null}
        <span className="aw-row__spacer" />
        {leading}
        <ImportanceMeter importance={row.importance} />
        <SentimentChip
          score={row.sentiment_score}
          confidence={row.sentiment_confidence}
          model={sentimentModel}
          label={row.sentiment}
        />
        <QualityPill
          label={row.quality_label}
          score={row.quality_score}
          reasons={row.quality_reasons}
        />
        <button
          type="button"
          className="aw-row__open"
          aria-label={`Open article at ${row.publisher}`}
          title="Open article"
          disabled={!url}
          onClick={() => openArticle(url)}
        >
          {"\u2197"}
        </button>
      </div>
      <button
        type="button"
        className="aw-row__headline"
        title={row.title}
        onClick={() => openArticle(url)}
        disabled={!url}
      >
        {row.title}
      </button>
      {body ? <p className="aw-row__summary">{body}</p> : null}
      <div className="aw-row__chips">
        {chipSymbols.map((s) => (
          <EntityChip
            key={`sym-${s}`}
            kind="symbol"
            label={s}
            onClick={() => setFocusedTarget("DES", s)}
          />
        ))}
        {chipEntities.map((e) => (
          <EntityChip
            key={`ent-${e.type}-${e.id}`}
            kind="entity"
            label={e.name ?? e.id}
            title={`${e.type} ${e.id}`}
            onClick={
              e.type === "equity" && e.id ? () => setFocusedTarget("DES", e.id) : undefined
            }
          />
        ))}
        {chipCountries.map((c) => (
          <EntityChip
            key={`cty-${c}`}
            kind="country"
            label={c}
            onClick={onFilter ? () => onFilter("country", c) : undefined}
          />
        ))}
        {row.topics.map((t) => (
          <EntityChip
            key={`top-${t}`}
            kind="topic"
            label={t}
            onClick={onFilter ? () => onFilter("topic", t) : undefined}
          />
        ))}
        <span className="aw-row__spacer" />
        {extraSources > 0 ? (
          <button
            type="button"
            className="aw-row__more"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            +{extraSources} sources {expanded ? "\u25B4" : "\u25BE"}
          </button>
        ) : null}
      </div>
      {expanded ? (
        <div
          className="aw-corro"
          role="group"
          aria-label={`Other sources for ${row.title}`}
        >
          {story.state === "loading" || story.state === "idle" ? (
            <div className="aw-corro__loading">Loading sources</div>
          ) : story.state === "error" ? (
            <div className="aw-corro__loading">Could not load the other sources.</div>
          ) : detailItems.length === 0 ? (
            <div className="aw-corro__loading">
              No other sources returned for this story.
            </div>
          ) : (
            detailItems.map((it) => (
              <div key={it.id} className="aw-corro__row">
                <span className="aw-mono">{hhmmUtc(it.published_at)}</span>
                <TierBadge tier={it.publisher_tier} />
                <span className="aw-corro__pub">{it.publisher_name}</span>
                <span className="aw-corro__title" title={it.title}>
                  {it.title}
                </span>
                <button
                  type="button"
                  className="aw-row__open"
                  aria-label={`Open article at ${it.publisher_name}`}
                  disabled={!it.url}
                  onClick={() => openArticle(it.url)}
                >
                  {"\u2197"}
                </button>
              </div>
            ))
          )}
        </div>
      ) : null}
    </article>
  );
}
