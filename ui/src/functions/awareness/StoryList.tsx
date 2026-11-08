import { useState, type KeyboardEvent, type ReactNode } from "react";
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
  const [drawerIndex, setDrawerIndex] = useState<number | null>(null);

  const focusRow = (index: number) => {
    const el = document.querySelector<HTMLElement>(`[data-row-index="${index}"]`);
    el?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (drawerIndex !== null) return;
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
    <div role="feed" aria-label={ariaLabel} className="aw-list" onKeyDown={onKeyDown}>
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
          onOpenDrawer={() => setDrawerIndex(index)}
        />
      ))}
      {drawerIndex !== null && rows[drawerIndex] ? (
        <StoryDrawer
          row={rows[drawerIndex]}
          code={code}
          symbol={symbol}
          nowMs={nowMs}
          hasPrev={drawerIndex > 0}
          hasNext={drawerIndex < rows.length - 1}
          onPrev={() => setDrawerIndex((i) => (i === null ? i : Math.max(0, i - 1)))}
          onNext={() =>
            setDrawerIndex((i) => (i === null ? i : Math.min(rows.length - 1, i + 1)))
          }
          onClose={() => {
            const idx = drawerIndex;
            setDrawerIndex(null);
            window.setTimeout(() => focusRow(idx), 0);
          }}
        />
      ) : null}
    </div>
  );
}
