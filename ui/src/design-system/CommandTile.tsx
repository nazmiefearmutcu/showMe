/**
 * CommandTile — one tile of the "Command Deck" grid.
 *
 * Each tile pairs a function code (PORT/WATCH/CN…) with a tiny icon and a
 * short, present-tense description. Hover lift on `interactive` tiles
 * surfaces the keyboard hint slot.
 */

import { memo, type ReactNode } from "react";

function CommandTileImpl({
  code,
  description,
  icon,
  hint,
  onClick,
  active,
}: {
  code: string;
  description: string;
  icon?: ReactNode;
  hint?: string;
  onClick?: () => void;
  active?: boolean;
}) {
  const interactive = Boolean(onClick);

  return (
    <button
      type="button"
      onClick={onClick}
      className={
        `showme-command-tile ds-command-tile${interactive ? " showme-command-tile--interactive ds-command-tile--interactive" : ""}${active ? " ds-command-tile--active" : ""}`
      }
      aria-pressed={active}
    >
      <span aria-hidden className="ds-command-tile__icon">
        {icon ?? <DefaultGlyph />}
      </span>
      <span className="ds-command-tile__code">{code}</span>
      <span className="ds-command-tile__desc">{description}</span>
      {hint && <span className="ds-command-tile__hint">{hint}</span>}
    </button>
  );
}

export const CommandTile = memo(CommandTileImpl);

function DefaultGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1.5" y="2.5" width="11" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
      <line x1="1.5" y1="5.5" x2="12.5" y2="5.5" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}
