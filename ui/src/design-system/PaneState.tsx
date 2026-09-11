/**
 * PaneState — the shared async-state body wrapper for function panes.
 *
 * Before this kit every pane hand-rolled the same branch:
 * `state === "loading" ? <SkeletonStack/> : state === "error" ? <Empty .../>
 * : rows.length === 0 ? <Empty .../> : <content/>` — six verified copies in
 * BQUANT / EVTS / PEOP / FLDS / SECF / MOSS alone.
 *
 * PaneState centralizes the branch (still fully controllable by the caller):
 *
 *   <PaneState
 *     state={state}
 *     error={error}
 *     empty={rows.length === 0}
 *     emptyTitle="No events"
 *     emptyBody={payload?.reason}
 *     onRetry={refetch}
 *   >
 *     ...content...
 *   </PaneState>
 *
 * Behavior:
 *  - `idle` / `loading` → a dense skeleton stack (`data-testid=pane-state-loading`)
 *  - `error`            → Empty with the error message + Retry (`pane-state-error`)
 *  - `empty`            → Empty with title/body + Retry (`pane-state-empty`)
 *  - `ok` / `refreshing`→ children; `refreshing` adds a small inline
 *    "updating…" status strip above the content and keeps stale data visible
 *    (`pane-state-refreshing`, `data-stale="true"`) — matching useFunction's
 *    refresh semantics where `data` stays on screen.
 *
 * The wrapper renders no extra visual chrome in the ok branch — children keep
 * full control of their own layout (grid gap classes etc.).
 */
import type { ReactNode } from "react";
import { Empty } from "./Empty";
import { Skeleton } from "./Skeleton";

export type PaneStateKind = "idle" | "loading" | "error" | "ok" | "refreshing";

export interface PaneStateProps {
  /** The `useFunction` state (or any compatible tagged state). */
  state: PaneStateKind;
  /** Error object / message shown in the error branch. */
  error?: unknown;
  /** True when the ok payload has no rows — renders the empty branch. */
  empty?: boolean;
  emptyTitle?: string;
  emptyBody?: ReactNode;
  emptyIcon?: ReactNode;
  /** Extra action rendered next to the default Retry button. */
  emptyAction?: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
  /** Skeleton row count for the loading branch (default 4). */
  loadingRows?: number;
  /** Inline label for the refreshing strip (default "updating…"). */
  refreshingLabel?: string;
  className?: string;
  /** Ok-branch content (unused by the loading/error/empty branches). */
  children?: ReactNode;
}

function errorMessage(error: unknown): string {
  if (error == null) return "The function call failed.";
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message || "The function call failed.";
  if (typeof error === "object" && "message" in error) {
    const msg = (error as { message?: unknown }).message;
    if (typeof msg === "string" && msg) return msg;
  }
  return "The function call failed.";
}

export function PaneLoading({
  rows = 4,
  className,
}: {
  rows?: number;
  className?: string;
}) {
  const slim = Math.max(1, rows - 1);
  return (
    <div
      data-testid="pane-state-loading"
      aria-busy="true"
      className={className ?? "u-grid-gap-8"}
    >
      <Skeleton height={56} />
      {Array.from({ length: slim }).map((_, i) => (
        <Skeleton key={i} height={20} width={i === slim - 1 ? "80%" : "100%"} />
      ))}
    </div>
  );
}

export function PaneError({
  message,
  onRetry,
  retryLabel = "Retry",
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div data-testid="pane-state-error">
      <Empty
        title="Function error"
        body={message}
        icon="!"
        action={
          onRetry ? (
            <button type="button" onClick={onRetry} className="btn">
              {retryLabel}
            </button>
          ) : undefined
        }
      />
    </div>
  );
}

export function PaneEmpty({
  title,
  body,
  icon,
  action,
  onRetry,
  retryLabel = "Retry",
}: {
  title: string;
  body?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div data-testid="pane-state-empty">
      <Empty
        title={title}
        body={body}
        icon={icon}
        action={
          action ??
          (onRetry ? (
            <button type="button" onClick={onRetry} className="btn">
              {retryLabel}
            </button>
          ) : undefined)
        }
      />
    </div>
  );
}

export function PaneState({
  state,
  error,
  empty = false,
  emptyTitle = "No data returned",
  emptyBody,
  emptyIcon,
  emptyAction,
  onRetry,
  retryLabel = "Retry",
  loadingRows = 4,
  refreshingLabel = "updating…",
  className,
  children,
}: PaneStateProps) {
  if (state === "loading" || state === "idle") {
    return <PaneLoading rows={loadingRows} className={className} />;
  }
  if (state === "error") {
    return <PaneError message={errorMessage(error)} onRetry={onRetry} retryLabel={retryLabel} />;
  }
  if (empty) {
    return (
      <PaneEmpty
        title={emptyTitle}
        body={emptyBody}
        icon={emptyIcon}
        action={emptyAction}
        onRetry={onRetry}
        retryLabel={retryLabel}
      />
    );
  }
  return (
    <div data-testid="pane-state-ok" className={className}>
      {state === "refreshing" ? (
        <div
          data-testid="pane-state-refreshing"
          data-stale="true"
          role="status"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            marginBottom: 8,
            padding: "2px 8px",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
            color: "var(--text-mute)",
            fontFamily: "var(--font-mono)",
            fontSize: "var(--font-size-xs)",
            letterSpacing: "var(--tracking-label)",
            textTransform: "uppercase",
          }}
        >
          <span aria-hidden="true">◌</span>
          {refreshingLabel}
        </div>
      ) : null}
      {children}
    </div>
  );
}
