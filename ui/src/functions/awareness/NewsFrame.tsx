import type { ReactNode } from "react";
import type { FunctionCallResult } from "@/lib/functions";
import { PaneState } from "@/design-system";
import { AwarenessUnavailable } from "./AwarenessUnavailable";
import { ProviderHealthStrip } from "./ProviderHealthStrip";
import { StoryList } from "./StoryList";
import { newsMeta, type NewsPayload, type NewsRow } from "./news-types";
import { uniqueCount } from "./format";
import type { PaneStateKind } from "@/design-system/PaneState";

export interface NewsFrameProps {
  code: string;
  symbol?: string;
  /** Pane label used in the unavailable copy, e.g. "news". */
  subject: string;
  state: PaneStateKind;
  error?: unknown;
  data?: FunctionCallResult<NewsPayload>;
  nowMs?: number;
  onRetry?: () => void;
  /** Filters / controls rendered above the health strip (always visible). */
  toolbar: ReactNode;
  emptyTitle: string;
  /** Body of the empty state: should name the active filters and offer relaxers. */
  emptyBody: ReactNode;
  emptyAction?: ReactNode;
  ariaLabel: string;
  onFilter?: (kind: "country" | "topic", value: string) => void;
  renderLeading?: (row: NewsRow) => ReactNode;
  /** Footer summary text, e.g. "48 stories from 31 publishers in 24h". */
  summary: string;
  /** Switch the quality floor to show low-quality items that were hidden. */
  onShowLow?: () => void;
}

/**
 * Shared news pane body: state handling (§0.4), provider health strip, story list,
 * footer. Panes supply their own toolbar and empty-state copy.
 */
export function NewsFrame({
  code,
  symbol,
  subject,
  state,
  error,
  data,
  nowMs,
  onRetry,
  toolbar,
  emptyTitle,
  emptyBody,
  emptyAction,
  ariaLabel,
  onFilter,
  renderLeading,
  summary,
  onShowLow,
}: NewsFrameProps) {
  const payload = data?.data;
  const status = payload?.status ?? data?.status;
  const rows = payload?.rows ?? [];
  const meta = newsMeta(payload, data?.metadata);

  if (status === "provider_unavailable") {
    return (
      <div className="aw-frame">
        {toolbar}
        <AwarenessUnavailable
          reason={payload?.reason ?? data?.reason}
          onRetry={onRetry}
          subject={subject}
        />
      </div>
    );
  }

  const hasRows = rows.length > 0;
  const publishers = uniqueCount(rows.map((r) => r.publisher));

  return (
    <div className="aw-frame">
      {toolbar}
      <ProviderHealthStrip
        providers={meta.providers}
        feedHealth={meta.feed_health}
        generatedAt={meta.generated_at}
        nowMs={nowMs}
      />
      <PaneState
        state={state}
        error={error}
        empty={!hasRows}
        emptyTitle={emptyTitle}
        emptyBody={
          <>
            {emptyBody}
            {payload?.hidden_note ? (
              <span className="aw-empty-note">
                {" "}
                {payload.hidden_note}
                {onShowLow ? (
                  <>
                    {" "}
                    <button
                      type="button"
                      className="aw-link aw-linkbtn"
                      onClick={onShowLow}
                    >
                      Show low quality
                    </button>
                  </>
                ) : null}
              </span>
            ) : null}
          </>
        }
        emptyAction={emptyAction}
        onRetry={onRetry}
        loadingRows={6}
      >
        <StoryList
          rows={rows}
          code={code}
          symbol={symbol}
          nowMs={nowMs}
          onFilter={onFilter}
          renderLeading={renderLeading}
          ariaLabel={ariaLabel}
        />
      </PaneState>
      {hasRows ? (
        <footer className="aw-footer">
          <span>
            {summary}
            {publishers ? ` from ${publishers} publishers` : ""}
          </span>
          {payload?.hidden_note ? (
            // A fallback or floor note is shown whenever the backend sends one, with rows or
            // without (without rows it is also in the empty state). With onShowLow the note
            // is the labelled opt-in to reveal the hidden rows.
            onShowLow ? (
              <button type="button" className="aw-linkbtn aw-link" onClick={onShowLow}>
                {payload.hidden_note}
              </button>
            ) : (
              <span className="aw-footer__note" role="note">
                {payload.hidden_note}
              </span>
            )
          ) : null}
          <span className="aw-mono">awareness /v1/markets/news</span>
        </footer>
      ) : null}
    </div>
  );
}
