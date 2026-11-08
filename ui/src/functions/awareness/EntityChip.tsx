import { prettyToken } from "./format";

export type EntityChipKind = "entity" | "country" | "topic" | "symbol";

export interface EntityChipProps {
  kind: EntityChipKind;
  label: string;
  onClick?: () => void;
  title?: string;
}

/**
 * Chip for entities, countries, topics and symbols. Entities/symbols are interactive
 * text (accent-2 on dark, accent on papyrus via awareness.css); topics and countries are
 * secondary text. Non-interactive chips render a span.
 */
export function EntityChip({ kind, label, onClick, title }: EntityChipProps) {
  const text = kind === "topic" ? prettyToken(label) : label;
  const cls = `aw-chip aw-chip--${kind}`;
  if (onClick) {
    return (
      <button
        type="button"
        className={cls}
        onClick={onClick}
        title={title ?? text}
        aria-label={`${kind} ${text}`}
      >
        {text}
      </button>
    );
  }
  return (
    <span className={cls} title={title ?? text}>
      {text}
    </span>
  );
}
