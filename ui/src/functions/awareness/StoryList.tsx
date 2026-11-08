import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { StoryDrawer } from "./StoryDrawer";
import { StoryRow, openArticle } from "./StoryRow";
import type { NewsRow } from "./news-types";

export interface StoryListProps {
  rows: NewsRow[];
  /** Pane code (TOP, NI, CN, NSE, NALRT) used for story-detail calls. */
  code: string;
  symbol?: string;
  nowMs?: number;
  onFilter?: (kind: "country" | "topic", value: string) => void;
  /** Per-row extra node, e.g. NALRT severity. */
  renderLeading?: (row: NewsRow) => ReactNode;
  ariaLabel: string;
}

/**
 * Story-first flat list. Keyboard: j/k move row focus, o opens the focused row's article,
 * Enter (on a focused row) opens the story drawer, Esc closes the drawer.
 *
 * Row focus is looked up inside this list only, so j/k never move into another pane on
 * the same board. The open drawer is tracked by the row's id, so a refresh that reorders
 * the rows cannot switch the drawer to a different story.
 */
export function StoryList({
  rows,
  code,
  symbol,
  nowMs,
  onFilter,
  renderLeading,
  ariaLabel,
}: StoryListProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const drawerIndex = drawerId === null ? -1 : rows.findIndex((r) => r.id === drawerId);
  const drawerOpen = drawerIndex >= 0;

  const focusRow = (index: number) => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-row-index="${index}"]`);
    el?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (drawerOpen) return;
    const target = e.target as HTMLElement;
    const current = Number(
      target.closest("[data-row-index]")?.getAttribute("data-row-index"),
    );
    if (Number.isNaN(current)) return;
    if (e.key === "j") {
      e.preventDefault();
      focusRow(Math.min(rows.length - 1, current + 1));
    } else if (e.key === "k") {
      e.preventDefault();
      focusRow(Math.max(0, current - 1));
    } else if (e.key === "o") {
      openArticle(rows[current]?.url ?? rows[current]?.link);
    }
  };

  return (
    <div
      ref={listRef}
      role="feed"
      aria-label={ariaLabel}
      className="aw-list"
      onKeyDown={onKeyDown}
    >
      {rows.map((row, index) => (
        <StoryRow
          key={row.id}
          row={row}
          code={code}
          symbol={symbol}
          nowMs={nowMs}
          index={index}
          onFilter={onFilter}
          leading={renderLeading?.(row)}
          onOpenDrawer={() => setDrawerId(row.id)}
        />
      ))}
      {drawerOpen ? (
        <StoryDrawer
          row={rows[drawerIndex]}
          code={code}
          symbol={symbol}
          nowMs={nowMs}
          hasPrev={drawerIndex > 0}
          hasNext={drawerIndex < rows.length - 1}
          onPrev={() => setDrawerId(rows[Math.max(0, drawerIndex - 1)].id)}
          onNext={() => setDrawerId(rows[Math.min(rows.length - 1, drawerIndex + 1)].id)}
          onClose={() => {
            const idx = drawerIndex;
            setDrawerId(null);
            window.setTimeout(() => focusRow(idx), 0);
          }}
        />
      ) : null}
    </div>
  );
}
