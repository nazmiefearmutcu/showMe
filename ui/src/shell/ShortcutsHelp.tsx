/**
 * ShortcutsHelp — keyboard cheat sheet overlay.
 *
 * Triggered globally with `?` (UI-INT-10 P1). Lists every documented
 * shortcut grouped by surface so users do not need to read the source to
 * discover them. Wires into the global Escape handler and is focus-trapped
 * for screen-reader / keyboard parity (A11Y-03).
 */
import { useEffect, useRef, useState } from "react";
import { t } from "@/i18n";
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
        { keys: "?", label: t("shell.shortcuts.toggle_help") },
        { keys: "⌘B", label: t("shell.shortcuts.toggle_sidebar") },
      ],
    },
    {
      title: t("shell.shortcuts.workspace"),
      rows: [
        { keys: "⌘\\", label: t("shell.shortcuts.split_h") },
        { keys: "⌘⇧\\", label: t("shell.shortcuts.split_v") },
        { keys: "⌘W", label: t("shell.shortcuts.close_pane") },
      ],
    },
  ];
}

export function ShortcutsHelp() {
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
