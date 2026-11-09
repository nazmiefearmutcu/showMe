import { useEffect, useRef, type KeyboardEvent } from "react";
import { relativeTimeLabel } from "@/lib/time";
import { useFunction } from "@/lib/useFunction";
import { EntityChip } from "./EntityChip";
import { ImportanceMeter } from "./ImportanceMeter";
import { SentimentChip } from "./SentimentChip";
import { TierBadge } from "./TierBadge";
import { hhmmUtc, parseQualityReason, prettyToken } from "./format";
import { QualityTag, qualityText } from "./QualityPill";
import { openArticle, safeArticleUrl } from "./StoryRow";
import type { NewsPayload, NewsRow } from "./news-types";

export interface StoryDrawerProps {
  row: NewsRow;
  code: string;
  symbol?: string;
  nowMs?: number;
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
}

const FOCUSABLE =
  'button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

function signedPoints(points: number | null): string {
  if (points === null) return "";
  if (points > 0) return `+${points}`;
  if (points < 0) return `−${Math.abs(points)}`;
  return "0";
}

/** Right-anchored story drawer. Focus is trapped while open; Esc closes. */
export function StoryDrawer({
  row,
  code,
  symbol,
  nowMs,
  hasPrev,
  hasNext,
  onPrev,
  onNext,
  onClose,
}: StoryDrawerProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  // Keyed by the row id (the lead item); see StoryRow for why a story hash is not used.
  const story = useFunction<NewsPayload>({
    code,
    symbol,
    params: { story_id: row.id },
    enabled: Boolean(row.story_id),
  });
  const detail = story.data?.data?.story ?? null;
  const items = detail?.items ?? [];
  const sorted = [...items].sort((a, b) => a.published_at.localeCompare(b.published_at));
  const firstSeen = detail?.first_seen_at ?? row.first_seen_at ?? row.published_at;
  const url = safeArticleUrl(row.url) ?? safeArticleUrl(row.link);

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLElement>("button")?.focus();
  }, [row.id]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !dialogRef.current) return;
    const nodes = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="aw-drawer-backdrop" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Story"
        className="aw-drawer"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <header className="aw-drawer__head">
          <span className="aw-drawer__title">Story</span>
          <span className="aw-mono aw-drawer__meta">
            {row.story_size} sources, first seen {hhmmUtc(firstSeen)} UTC
          </span>
          <span className="aw-row__spacer" />
          <button
            type="button"
            className="aw-icon-btn"
            aria-label="Previous story"
            disabled={!hasPrev}
            onClick={onPrev}
          >
            {"‹"}
          </button>
          <button
            type="button"
            className="aw-icon-btn"
            aria-label="Next story"
            disabled={!hasNext}
            onClick={onNext}
          >
            {"›"}
          </button>
          <button
            type="button"
            className="aw-icon-btn"
            aria-label="Close story"
            onClick={onClose}
          >
            {"×"}
          </button>
        </header>

        <section className="aw-drawer__section" aria-label="Lead item">
          <div className="aw-row__meta">
            <span className="aw-row__publisher">{row.publisher}</span>
            <TierBadge tier={row.publisher_tier} />
            <span className="aw-badge">Lead</span>
            <span className="aw-mono">
              {hhmmUtc(row.published_at)} UTC
              {relativeTimeLabel(row.published_at, nowMs)
                ? ` · ${relativeTimeLabel(row.published_at, nowMs)} ago`
                : ""}
            </span>
          </div>
          <h3 className="aw-drawer__headline">{row.title}</h3>
          {(row.excerpt ?? row.summary) ? (
            <p className="aw-drawer__excerpt">
              {(row.excerpt ?? row.summary ?? "").slice(0, 400)}
            </p>
          ) : null}
          <div className="aw-drawer__actions">
            <button
              type="button"
              className="aw-btn aw-btn--accent"
              disabled={!url}
              onClick={() => openArticle(url)}
            >
              Open at {row.publisher}
            </button>
            <button
              type="button"
              className="aw-btn"
              disabled={!url}
              onClick={() => {
                if (url && typeof navigator !== "undefined")
                  void navigator.clipboard?.writeText(url).catch(() => undefined);
              }}
            >
              Copy link
            </button>
            <SentimentChip
              score={row.sentiment_score}
              confidence={row.sentiment_confidence}
              model={row.sentiment_model}
              label={row.sentiment}
            />
            <ImportanceMeter importance={row.importance} />
          </div>
        </section>

        <section className="aw-drawer__section" aria-label="Quality reasons">
          <h4 className="aw-drawer__h">
            Why this is {qualityText(row.quality_label).toLowerCase()}{" "}
            <span className="aw-mono">{row.quality_score}/100</span>
          </h4>
          {row.quality_reasons.length === 0 ? (
            <p className="aw-drawer__empty">No reasons supplied by Awareness.</p>
          ) : (
            <table className="aw-why__table">
              <tbody>
                {row.quality_reasons.map((raw) => {
                  const r = parseQualityReason(raw);
                  return (
                    <tr key={raw}>
                      <td>{r.label}</td>
                      <td className="aw-why__pts">{signedPoints(r.points)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>

        <section className="aw-drawer__section" aria-label="Entities">
          <h4 className="aw-drawer__h">Entities and entity sentiment</h4>
          {row.entities.length === 0 ? (
            <p className="aw-drawer__empty">No entities linked.</p>
          ) : (
            <div className="aw-ent-grid">
              {row.entities.map((e) => {
                const es = row.entity_sentiment?.[e.id];
                return (
                  <div key={`${e.type}-${e.id}`} className="aw-ent-grid__row">
                    <span className="aw-mono aw-muted">{e.type}</span>
                    <EntityChip kind="entity" label={e.name ?? e.id} title={e.id} />
                    <span className="aw-mono aw-muted">
                      {e.confidence != null ? e.confidence.toFixed(2) : ""}
                    </span>
                    {es ? (
                      <SentimentChip
                        score={es.score}
                        confidence={es.confidence}
                        model={es.model}
                        label={es.label}
                      />
                    ) : (
                      <span />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section
          className="aw-drawer__section aw-drawer__section--grow"
          aria-label="All sources"
        >
          <h4 className="aw-drawer__h">All sources, oldest first</h4>
          {!row.story_id ? (
            <div className="aw-corro__loading">No story group for this item.</div>
          ) : story.state === "loading" || story.state === "idle" ? (
            <div className="aw-corro__loading">Loading sources</div>
          ) : story.state === "error" ? (
            <div className="aw-corro__loading">
              Could not load the sources for this story.
            </div>
          ) : sorted.length === 0 ? (
            <div className="aw-corro__loading">
              No other sources returned for this story.
            </div>
          ) : (
            sorted.map((it) => {
              const itemUrl = safeArticleUrl(it.url);
              return (
                <div key={it.id} className="aw-corro__row">
                  <span className="aw-mono">{hhmmUtc(it.published_at)}</span>
                  <TierBadge tier={it.publisher_tier} />
                  <span className="aw-corro__pub">
                    {it.publisher_name}
                    {it.id === row.id ? " (lead)" : ""}
                  </span>
                  <span className="aw-corro__title" title={it.title}>
                    {it.title}
                  </span>
                  <QualityTag label={it.quality_label} />
                  <button
                    type="button"
                    className="aw-row__open"
                    aria-label={`Open article at ${it.publisher_name}`}
                    disabled={!itemUrl}
                    onClick={() => openArticle(itemUrl)}
                  >
                    {"↗"}
                  </button>
                </div>
              );
            })
          )}
        </section>

        <footer className="aw-drawer__foot">
          {row.topics.map((t) => (
            <span key={t} className="aw-chip aw-chip--topic">
              {prettyToken(t)}
            </span>
          ))}
          <span className="aw-mono aw-muted">{row.story_id ?? "no story id"}</span>
        </footer>
      </div>
    </div>
  );
}
