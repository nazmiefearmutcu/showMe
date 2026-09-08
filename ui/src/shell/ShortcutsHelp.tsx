/**
 * ShortcutsHelp — keyboard cheat sheet overlay.
 *
 * Triggered globally with `?` (UI-INT-10 P1). Wires into the global Escape
 * handler and is focus-trapped for screen-reader / keyboard parity (A11Y-03).
 *
 * U5 TRUTH PASS (Lane D, 2026-09-08): the overlay previously listed only
 * ⌘K / ? / ⌘B / ⌘\ / ⌘⇧\ / ⌘W and lied by omission. Every row below was
 * verified against the actual key handlers in source before being listed:
 *   - App.tsx keydown  → ⌘K, ⌘B, ⌘J, ⌘\, ⌘⇧\, ⌘W
 *   - Palette.tsx      → ↑/↓, Enter, Esc, ⌘1–9 (while the palette is open)
 *   - Workspace.tsx    → splitter arrows/Home/End resize, Esc cancels drag,
 *                        F6 / ⇧F6 / ⌘⇧] / ⌘⇧[ pane-focus cycling (U4)
 *   - ShortcutsHelp    → this overlay (`?`)
 * Deliberately NOT listed (no handler exists): sidebar `/` focus, ⌘G
 * symbol jump — those are survey proposals, not shipped shortcuts.
 *
 * New rows use `t(key, "English fallback")`: the i18n contract has zero
 * English-catalog fallback, so the literal second argument is the shipped
 * copy until the 12 locale catalogs add the keys.
 */
import { useEffect, useRef, useState } from "react";
import { t, useLocale } from "@/i18n";
import { useEscape, useFocusTrap } from "@/lib/a11y";

interface Group {
  title: string;
  rows: Array<{ keys: string; label: string }>;
}

function buildGroups(): Group[] {
  return [
    {
      title: t("shell.shortcuts.global"),
      rows: [
        { keys: "⌘K", label: t("shell.shortcuts.palette_open") },
        {
          keys: "⌘1–9",
          label: t(
            "shell.shortcuts.palette_jump",
            "Jump to Nth palette result (palette open)",
          ),
        },
        { keys: "⌘B", label: t("shell.shortcuts.toggle_sidebar") },
        {
          keys: "⌘J",
          label: t("shell.shortcuts.agent_pane", "Open AGENT pane"),
        },
        { keys: "?", label: t("shell.shortcuts.toggle_help") },
      ],
    },
    {
      title: t("shell.shortcuts.workspace"),
      rows: [
        { keys: "⌘\\", label: t("shell.shortcuts.split_h") },
        { keys: "⌘⇧\\", label: t("shell.shortcuts.split_v") },
        { keys: "⌘W", label: t("shell.shortcuts.close_pane") },
        {
          keys: "F6 / ⇧F6",
          label: t(
            "shell.shortcuts.cycle_pane_f6",
            "Cycle pane focus forward / back",
          ),
        },
        {
          keys: "⌘⇧] / ⌘⇧[",
          label: t(
            "shell.shortcuts.cycle_pane_brackets",
            "Cycle pane focus forward / back",
          ),
        },
      ],
    },
    {
      title: t("shell.shortcuts.splitters", "Panes & splitters"),
      rows: [
        {
          keys: "← ↑ ↓ →",
          label: t(
            "shell.shortcuts.splitter_arrows",
            "Resize focused splitter by 5%",
          ),
        },
        {
          keys: "Home / End",
          label: t(
            "shell.shortcuts.splitter_home_end",
            "Splitter to minimum / maximum",
          ),
        },
        {
          keys: "Esc",
          label: t(
            "shell.shortcuts.esc_cancel",
            "Cancel split drag · close overlay",
          ),
        },
      ],
    },
    {
      title: t("shell.shortcuts.palette_group", "Command palette"),
      rows: [
        {
          keys: "↑ / ↓",
          label: t("shell.shortcuts.palette_move", "Move selection"),
        },
        {
          keys: "Enter",
          label: t("shell.shortcuts.palette_choose", "Open selection"),
        },
        {
          keys: "Esc",
          label: t("shell.shortcuts.palette_close", "Close palette"),
        },
      ],
    },
  ];
}

export function ShortcutsHelp() {
  // UI-ROBUSTNESS F6: locale subscription (before the `open` early-return —
  // hooks must run unconditionally) so the cheat-sheet copy re-renders when
  // the user switches language while the overlay is open.
  useLocale();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      // Only react when the user is not typing into an input/textarea.
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      const isText =
        tag === "input" || tag === "textarea" || target?.isContentEditable === true;
      if (event.key === "?" && !isText) {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  useEscape(open, () => setOpen(false));
  useFocusTrap(ref, open);

  if (!open) return null;
  const groups = buildGroups();

  return (
    <div className="shortcuts-help__backdrop" onClick={() => setOpen(false)}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={t("shell.shortcuts.title")}
        onClick={(e) => e.stopPropagation()}
        className="shortcuts-help__panel"
      >
        <header className="shortcuts-help__header">
          <h2 className="shortcuts-help__title">{t("shell.shortcuts.title")}</h2>
          <button
            type="button"
            aria-label={t("common.close")}
            onClick={() => setOpen(false)}
            className="btn btn--ghost"
          >
            ✕
          </button>
        </header>
        {groups.map((group) => (
          <section key={group.title} className="shortcuts-help__group">
            <h3 className="shortcuts-help__group-title">{group.title}</h3>
            <dl className="shortcuts-help__dl">
              {group.rows.map((row) => (
                <div key={row.keys} className="shortcuts-help__row">
                  <dt>
                    <span className="kbd">{row.keys}</span>
                  </dt>
                  <dd className="shortcuts-help__dd">{row.label}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </div>
  );
}
