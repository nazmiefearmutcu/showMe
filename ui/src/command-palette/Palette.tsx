import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";
import { navigate } from "@/lib/router";
import { t, useLocale } from "@/i18n";
import { fuzzyRank } from "@/lib/fuzzy";
import { listRecentCodes, recordRecentCode } from "@/lib/palette-recents";
import {
  listPaletteActions,
  listRecentActionIds,
  recordRecentActionId,
  type PaletteAction,
} from "@/lib/palette-actions";
import { listPaletteSymbolUniverse } from "@/lib/palette-symbols";
import { listPresets } from "@/lib/presets";
import { listRecentSymbols, pushRecentSymbol } from "@/lib/symbols";
import { findLeaf, firstLeafId, useWorkspace } from "@/lib/workspace";
import { useFocusTrap } from "@/lib/a11y";

/**
 * Palette v2 (campaign 2026-09-08, Lane B): the ⌘K surface now answers the
 * three things a desk user types — function codes, TICKERS, and verbs.
 * Entry kinds:
 *   fn     — function catalog (unchanged behaviour: hash navigation).
 *   symbol — a known ticker; Enter rebinds the focused pane to it via the
 *            `/symbol/<SYM>/<code>` route (HOME/PREF focused → DES fallback).
 *   action — a verb into an existing store: theme presets, layout
 *            save/load, splits, sidebar/density preferences.
 * Ranking stays recents-first + fuzzyRank; keyboard model and a11y roles
 * are unchanged (single combobox + listbox, ⌘1–9 jump, focus trap).
 */
interface PaletteEntryBase {
  id: string;
  code: string;
  name: string;
  category: string;
}

interface FnPaletteEntry extends PaletteEntryBase {
  kind: "fn";
  hash: string;
}

interface SymbolPaletteEntry extends PaletteEntryBase {
  kind: "symbol";
  symbol: string;
  targetCode: string;
}

interface ActionPaletteEntry extends PaletteEntryBase {
  kind: "action";
  tag: string;
  action: PaletteAction;
}

type PaletteEntry = FnPaletteEntry | SymbolPaletteEntry | ActionPaletteEntry;

const STATIC_ENTRIES: FnPaletteEntry[] = [
  {
    id: "system.preferences",
    code: "PREF",
    name: "Preferences",
    category: "system",
    hash: "/preferences",
    kind: "fn",
  },
  {
    id: "system.welcome",
    code: "HOME",
    name: "Welcome",
    category: "system",
    hash: "/",
    kind: "fn",
  },
];

/** Codes that are not symbol-bindable targets — fall back to DES. */
const NON_SYMBOL_TARGET_CODES = new Set(["HOME", "PREF", "AGENT"]);

const LISTBOX_ID = "showme-palette-listbox";
const INPUT_ID = "showme-palette-input";

/**
 * Row ids embed the entry id, and layout entries can carry user-authored
 * preset names ("layout.user.my desk v2") whose spaces/quotes would make an
 * invalid HTML id and break aria-activedescendant linkage. Percent-encode
 * for DOM use; the raw id stays the React key.
 */
const optionDomId = (entryId: string): string => `palette-opt-${encodeURIComponent(entryId)}`;

/**
 * Label for the palette's modifier key. The app-level shortcut handler
 * (App.tsx) accepts both `metaKey` and `ctrlKey`, but the on-screen hint
 * should name the key this platform's keyboard actually has: ⌘ on Apple
 * hardware, Ctrl everywhere else. The old hard-coded ⌘ lied on Windows/Linux.
 */
const MOD_KEY = /\b(Mac|iPhone|iPad|iPod)\b/.test(
  typeof navigator !== "undefined"
    ? navigator.platform || navigator.userAgent
    : "",
)
  ? "⌘"
  : "Ctrl";

interface PaletteRow {
  head?: string;
  entry: PaletteEntry;
}

export function CommandPalette() {
  // UI-ROBUSTNESS F6: locale subscription (before the `open` early-return —
  // hooks must run unconditionally) so placeholder/footer/section copy
  // re-renders when the user switches language.
  useLocale();
  const open = useAppStore((s) => s.paletteOpen);
  const togglePalette = useAppStore((s) => s.togglePalette);
  const items = useAppStore((s) => s.functionIndex);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // HIGH #11 (UI-Shell-Bundle UB) — the legacy `useMemo(..., [open])` re-
  // read localStorage every time the palette opened. Replace with a
  // useState seeded from localStorage once + a `storage` event listener
  // for cross-tab updates. We still refresh the snapshot when the
  // palette opens so a navigation that happened while the palette was
  // closed shows up immediately.
  const [recents, setRecents] = useState<string[]>(() => listRecentCodes());
  const [recentSymbols, setRecentSymbols] = useState<string[]>(() =>
    listRecentSymbols(),
  );
  const [recentActionIds, setRecentActionIds] = useState<string[]>(() =>
    listRecentActionIds(),
  );
  const [userPresetNames, setUserPresetNames] = useState<string[]>([]);
  useEffect(() => {
    if (!open) return;
    setRecents(listRecentCodes());
    setRecentSymbols(listRecentSymbols());
    setRecentActionIds(listRecentActionIds());
    // User-saved layout presets live behind an async backend (Tauri FS or
    // localStorage); fetch them on open so "Load layout: <name>" rows exist.
    let cancelled = false;
    listPresets()
      .then((presets) => {
        if (!cancelled) setUserPresetNames(presets.map((p) => p.name));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open]);
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key && e.key.startsWith("showme.palette.recents.")) {
        setRecents(listRecentCodes());
      }
    };
    if (typeof window !== "undefined") {
      window.addEventListener("storage", onStorage);
      return () => window.removeEventListener("storage", onStorage);
    }
    return undefined;
  }, []);

  // Which pane will a symbol entry rebind? Read the focused leaf at open
  // time (non-reactive is fine — the palette is a modal; the desk can't
  // change under it). HOME/PREF/AGENT leaves fall back to DES.
  const symbolTargetCode = useMemo(() => {
    if (!open) return "DES";
    try {
      const { tree, focusedId } = useWorkspace.getState();
      const leaf = findLeaf(tree, focusedId) ?? (tree.kind === "leaf" ? tree : findLeaf(tree, firstLeafId(tree)));
      const code = (leaf?.code ?? "DES").toUpperCase();
      return NON_SYMBOL_TARGET_CODES.has(code) ? "DES" : code;
    } catch {
      return "DES";
    }
  }, [open]);

  const actions = useMemo(() => listPaletteActions(userPresetNames), [userPresetNames]);

  const all: PaletteEntry[] = useMemo(
    () => [
      ...STATIC_ENTRIES,
      ...items.map((i) => ({
        id: `fn.${i.code}`,
        code: i.code,
        name: i.name,
        category: i.category,
        hash: `/fn/${i.code}`,
        kind: "fn" as const,
      })),
      ...listPaletteSymbolUniverse().map((sym) => ({
        id: `sym.${sym}`,
        code: sym,
        name: `Open ${sym} in focused pane (${symbolTargetCode})`,
        category: "symbol",
        kind: "symbol" as const,
        symbol: sym,
        targetCode: symbolTargetCode,
      })),
      ...actions.map((action) => ({
        id: `act.${action.id}`,
        code: action.id,
        name: action.name,
        category: "action",
        kind: "action" as const,
        tag: action.tag,
        action,
      })),
    ],
    [items, actions, symbolTargetCode],
  );

  const rows: PaletteRow[] = useMemo(() => {
    if (!query.trim()) {
      // Recents first when palette opens with no query. Sections: recent
      // functions, recent symbols, recent actions, then the function
      // catalog. The static symbol catalog stays out of the empty view —
      // 500 rows of noise is the opposite of a command line.
      const recentSet = new Set(recents.map((c) => c.toUpperCase()));
      const fnEntries: FnPaletteEntry[] = all.filter(
        (e): e is FnPaletteEntry => e.kind === "fn",
      );
      const recentEntries = recents
        .map((code) =>
          fnEntries.find((e) => e.code.toUpperCase() === code.toUpperCase()),
        )
        .filter((e): e is FnPaletteEntry => Boolean(e));
      const recentSymbolEntries = recentSymbols
        .map((sym) =>
          all.find(
            (e): e is SymbolPaletteEntry =>
              e.kind === "symbol" && e.symbol.toUpperCase() === sym.toUpperCase(),
          ),
        )
        .filter((e): e is SymbolPaletteEntry => Boolean(e));
      const recentActionEntries = recentActionIds
        .map((id) =>
          all.find(
            (e): e is ActionPaletteEntry =>
              e.kind === "action" && e.action.id === id,
          ),
        )
        .filter((e): e is ActionPaletteEntry => Boolean(e));
      const others = fnEntries.filter(
        (e) => !recentSet.has(e.code.toUpperCase()),
      );
      const rowsOut: PaletteRow[] = [];
      for (const entry of [
        ...recentEntries,
        ...recentSymbolEntries,
        ...recentActionEntries,
        ...others,
      ].slice(0, 60)) {
        let head: string | undefined;
        if (!query.trim()) {
          const index = rowsOut.length;
          if (index === recentEntries.length && recentSymbolEntries.length > 0) {
            head = "Recent symbols";
          } else if (
            index === recentEntries.length + recentSymbolEntries.length &&
            recentActionEntries.length > 0
          ) {
            head = "Recent actions";
          } else if (index === 0 && recentEntries.length > 0) {
            head = t("shell.palette.recents");
          }
        }
        rowsOut.push({ head, entry });
      }
      return rowsOut;
    }
    // Ranked mixed search: recency boost applies to fn codes, tickers, and
    // action ids alike (fuzzyRank matches on the entry's code field).
    const recentsAll = [...recents, ...recentSymbols, ...recentActionIds];
    return fuzzyRank(all, query, recentsAll, 60).map((entry) => ({ entry }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, query, recents, recentSymbols, recentActionIds]);

  const filtered = useMemo(() => rows.map((r) => r.entry), [rows]);

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
    // QA-2026-05-23: only handle Escape here. Cmd/Ctrl+K is now bound at
    // the App level so there is a single source of truth, eliminating the
    // collision where the menu-accel `palette:toggle` event and this
    // keydown handler both fired and double-toggled the palette.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        e.preventDefault();
        togglePalette(false);
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
    if (entry.kind === "fn") recordRecentCode(entry.code);
    if (entry.kind === "symbol") pushRecentSymbol(entry.symbol);
    if (entry.kind === "action") recordRecentActionId(entry.action.id);
    if (entry.kind === "fn") navigate(entry.hash);
    if (entry.kind === "symbol") navigate(`/symbol/${entry.symbol}/${entry.targetCode}`);
    togglePalette(false);
    if (entry.kind === "action") entry.action.run();
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
            filtered[cursor] ? optionDomId(filtered[cursor].id) : undefined
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
          {showingRecents && rows[0]?.head && (
            <div className="palette__section-head">{rows[0].head}</div>
          )}
          {rows.map((row, i) => {
            const it = row.entry;
            const isCursor = i === cursor;
            // Section heads for the symbol/action recents blocks (the first
            // recents head renders above the list via `showingRecents`).
            const sectionHead =
              row.head && !(i === 0 && showingRecents) ? row.head : null;
            const recencyHint = i < 9 && (
              <span aria-hidden className="palette__recency-hint">{MOD_KEY}{i + 1}</span>
            );
            return (
              <Fragment key={it.id}>
                {sectionHead && (
                  <div className="palette__section-head palette__section-head--sub">
                    {sectionHead}
                  </div>
                )}
                <a
                  id={optionDomId(it.id)}
                  role="option"
                  aria-selected={isCursor}
                  href={it.kind === "fn" ? `#${it.hash}` : undefined}
                  onMouseEnter={() => setCursor(i)}
                  onClick={(e) => {
                    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                    e.preventDefault();
                    choose(it);
                  }}
                  className={`palette__option palette__option--${it.kind}${isCursor ? " palette__option--cursor" : ""}`}
                >
                  <span className="palette__option-code">
                    {it.kind === "action" ? it.tag : it.code}
                  </span>
                  <span className="palette__option-name">{it.name}</span>
                  <span className="palette__option-meta">
                    {it.category}
                    {recencyHint}
                  </span>
                </a>
              </Fragment>
            );
          })}
        </div>
        <div className="palette__footer">
          <span>
            <span className="kbd">↑↓</span> {t("shell.palette.navigate")} ·{" "}
            <span className="kbd">↵</span> {t("shell.palette.open")} ·{" "}
            <span className="kbd">{MOD_KEY}1-9</span> {t("shell.palette.jump")}
          </span>
          <span className="palette__footer-hint">
            Try a ticker (AAPL) or an action (theme, layout, split)
          </span>
          <span>
            <span className="kbd">esc</span> {t("shell.palette.close")}
          </span>
        </div>
      </div>
    </div>
  );
}
