import { useEffect, useMemo, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";
import { navigate } from "@/lib/router";
import { t } from "@/i18n";
import { fuzzyRank } from "@/lib/fuzzy";
import { listRecentCodes, recordRecentCode } from "@/lib/palette-recents";
import { useFocusTrap } from "@/lib/a11y";

interface PaletteEntry {
  id: string;
  code: string;
  name: string;
  category: string;
  hash: string;
}

const STATIC_ENTRIES: PaletteEntry[] = [
  {
    id: "system.preferences",
    code: "PREF",
    name: "Preferences",
    category: "system",
    hash: "/preferences",
  },
  {
    id: "system.welcome",
    code: "HOME",
    name: "Welcome",
    category: "system",
    hash: "/",
  },
];

const LISTBOX_ID = "showme-palette-listbox";
const INPUT_ID = "showme-palette-input";

export function CommandPalette() {
  const open = useAppStore((s) => s.paletteOpen);
  const togglePalette = useAppStore((s) => s.togglePalette);
  const items = useAppStore((s) => s.functionIndex);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const recents = useMemo(() => listRecentCodes(), [open]);

  const all: PaletteEntry[] = useMemo(
    () => [
      ...STATIC_ENTRIES,
      ...items.map((i) => ({
        id: `fn.${i.code}`,
        code: i.code,
        name: i.name,
        category: i.category,
        hash: `/fn/${i.code}`,
      })),
    ],
    [items],
  );

  const filtered = useMemo(() => {
    if (!query.trim()) {
      // Recents first when palette opens with no query.
      const recentSet = new Set(recents.map((c) => c.toUpperCase()));
      const recentEntries = recents
        .map((code) => all.find((e) => e.code.toUpperCase() === code.toUpperCase()))
        .filter((e): e is PaletteEntry => Boolean(e));
      const others = all.filter((e) => !recentSet.has(e.code.toUpperCase()));
      return [...recentEntries, ...others].slice(0, 60);
    }
    return fuzzyRank(all, query, recents, 60);
  }, [all, query, recents]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        e.preventDefault();
        togglePalette(false);
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        togglePalette();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, togglePalette]);

  // A11Y-03 P1: trap Tab inside the dialog while it's open and restore focus
  // on close. focus-trap handles backdrop clicks safely too.
  useFocusTrap(dialogRef, open);

  if (!open) return null;

  const choose = (entry: PaletteEntry) => {
    recordRecentCode(entry.code);
    navigate(entry.hash);
    togglePalette(false);
  };

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const sel = filtered[cursor];
      if (sel) choose(sel);
    } else if ((e.metaKey || e.ctrlKey) && /^[1-9]$/.test(e.key)) {
      // UI-INT-10 P2: ⌘1..⌘9 jump straight to the Nth result.
      const idx = Number(e.key) - 1;
      const target = filtered[idx];
      if (target) {
        e.preventDefault();
        choose(target);
      }
    }
  };

  const showingRecents = !query.trim() && recents.length > 0;

  return (
    <div
      className="palette__backdrop"
      onClick={() => togglePalette(false)}
    >
      <div
        ref={dialogRef}
        className="surface palette__panel"
        role="dialog"
        aria-modal="true"
        aria-label={t("shell.palette.aria_label")}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onListKey}
      >
        <input
          ref={inputRef}
          id={INPUT_ID}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("shell.palette.placeholder")}
          aria-label={t("shell.palette.aria_label")}
          aria-autocomplete="list"
          aria-controls={LISTBOX_ID}
          aria-activedescendant={
            filtered[cursor] ? `palette-opt-${filtered[cursor].code}` : undefined
          }
          role="combobox"
          aria-expanded
          autoComplete="off"
          spellCheck={false}
          className="palette__input"
        />
        <div
          id={LISTBOX_ID}
          role="listbox"
          aria-label={t("shell.palette.aria_label")}
          className="palette__listbox"
        >
          {filtered.length === 0 && (
            <div className="palette__empty">{t("shell.palette.empty")}</div>
          )}
          {showingRecents && (
            <div className="palette__section-head">{t("shell.palette.recents")}</div>
          )}
          {filtered.map((it, i) => {
            const isCursor = i === cursor;
            const recencyHint = i < 9 && (
              <span aria-hidden className="palette__recency-hint">⌘{i + 1}</span>
            );
            return (
              <a
                key={it.id}
                id={`palette-opt-${it.code}`}
                role="option"
                aria-selected={isCursor}
                href={`#${it.hash}`}
                onMouseEnter={() => setCursor(i)}
                onClick={(e) => {
                  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                  e.preventDefault();
                  choose(it);
                }}
                className={`palette__option${isCursor ? " palette__option--cursor" : ""}`}
              >
                <span className="palette__option-code">{it.code}</span>
                <span className="palette__option-name">{it.name}</span>
                <span className="palette__option-meta">
                  {it.category}
                  {recencyHint}
                </span>
              </a>
            );
          })}
        </div>
        <div className="palette__footer">
          <span>
            <span className="kbd">↑↓</span> {t("shell.palette.navigate")} ·{" "}
            <span className="kbd">↵</span> {t("shell.palette.open")} ·{" "}
            <span className="kbd">⌘N</span> jump
          </span>
          <span>
            <span className="kbd">esc</span> {t("shell.palette.close")}
          </span>
        </div>
      </div>
    </div>
  );
}
