/**
 * CommandLine — the persistent, non-modal Bloomberg-style command input
 * (campaign 2026-09-11, Lane L2).
 *
 * Grammar + execution live in `lib/command-parse.ts` /
 * `lib/palette-actions.ts`; this component owns only the interaction:
 *
 *   - `/` focuses the input from anywhere (installed globally by
 *     `useCommandLineHotkey`, which the App root calls once). Editable
 *     targets and open modals are respected.
 *   - Escape blurs.
 *   - Enter parses + executes (`MSFT GP`, `GP`, `MSFT`, `theme`, `<GO>`).
 *   - ArrowDown/ArrowUp move the suggestion selection while the dropdown
 *     is open; with no suggestions they step session command history.
 *   - Suggestions: the pinned security-function row, fuzzy function codes
 *     (`useAppStore.functionIndex`), and symbol matches from
 *     `lib/palette-symbols.ts`. Each row executes on Enter.
 *
 * The component reads stores on demand (`getState`) and stays droppable
 * into the titlebar without props.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useAppStore } from "@/lib/store";
import { isTextTarget } from "@/lib/pane-focus-cycle";
import {
  makeCommandPredicates,
  parseCommandInput,
  type ParsedCommand,
} from "@/lib/command-parse";
import {
  getCommandHistory,
  pushCommandHistory,
  stepCommandHistory,
} from "@/lib/command-history";
import { listPaletteSymbolUniverse } from "@/lib/palette-symbols";
import {
  executeParsedCommand,
  findPaletteActionForVerb,
  focusedTargetCode,
  openFunctionTarget,
  runPaletteActionByVerb,
} from "@/lib/palette-actions";
import { fuzzyRankDetailed } from "@/lib/fuzzy";

const MAX_SUGGESTIONS = 10;
const MAX_CODE_SUGGESTIONS = 6;
const MAX_SYMBOL_SUGGESTIONS = 4;

/** Module-level registry so `focusCommandLine()` works without refs. */
let registeredInput: HTMLInputElement | null = null;

/**
 * Focus + select the command line input. No-op when the component is not
 * mounted (tests, splash). Exported for the hotkey hook and for future
 * menu items / palette actions.
 */
export function focusCommandLine(): void {
  const el = registeredInput;
  if (!el) return;
  el.focus();
  try {
    el.select();
  } catch {
    // Detached inputs can throw on select() in jsdom — focusing is enough.
  }
}

/**
 * Install the global `/` keydown that focuses the command line. Mount once
 * (App root). Editable targets (inputs / textareas / contenteditable) and
 * open modal surfaces (palette, shortcuts) keep their own keyboard.
 */
export function useCommandLineHotkey(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
      const { paletteOpen, shortcutsOpen } = useAppStore.getState();
      if (paletteOpen || shortcutsOpen) return;
      // Modal guard (R1-F8): confirmation dialogs own the keyboard while open —
      // focusing the command line behind the scrim would hijack their keys.
      if (document.querySelector('[role="dialog"][aria-modal="true"], [role="alertdialog"]')) {
        return;
      }
      if (isTextTarget(e)) return;
      e.preventDefault();
      focusCommandLine();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

interface CommandSuggestion {
  id: string;
  code: string;
  label: string;
  meta: string;
  /** Canonical command text recorded in session history. */
  history: string;
  run: () => void;
}

/**
 * Symbol suggestions for a multi-word command: exact matches for every
 * token, then prefix completions for the token being typed.
 */
function matchSymbolSuggestions(
  universe: readonly string[],
  query: string,
  exclude: ReadonlySet<string>,
): string[] {
  const words = query.split(/\s+/).filter(Boolean);
  const known = new Set(universe);
  const out: string[] = [];
  for (const word of words) {
    if (out.length >= MAX_SYMBOL_SUGGESTIONS) break;
    const upper = word.toUpperCase();
    if (!upper) continue;
    if (known.has(upper) && !exclude.has(upper) && !out.includes(upper)) {
      out.push(upper);
    }
  }
  const tail = words[words.length - 1]?.toUpperCase() ?? "";
  if (tail.length >= 2) {
    for (const symbol of universe) {
      if (out.length >= MAX_SYMBOL_SUGGESTIONS) break;
      if (!symbol.startsWith(tail)) continue;
      if (exclude.has(symbol) || out.includes(symbol)) continue;
      out.push(symbol);
    }
  }
  return out;
}

function optionDomId(suggestion: CommandSuggestion): string {
  // ids can carry dots/uppercase — percent-encode for DOM/ARIA safety.
  return `cmdline-opt-${encodeURIComponent(suggestion.id)}`;
}

export function CommandLine() {
  const items = useAppStore((s) => s.functionIndex);
  const [input, setInput] = useState("");
  const [cursor, setCursor] = useState(0);
  const [menuVisible, setMenuVisible] = useState(false);
  const [menuAnchor, setMenuAnchor] = useState<{ top: number; left: number; width: number } | null>(
    null,
  );
  const inputRef = useRef<HTMLInputElement | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const draftRef = useRef("");
  // Symbol universe is expensive-ish to normalize (~500 rows); memoized and
  // re-derived when `rememberSymbols()` bumps the version (the recents stack
  // grows after each executed command, so the universe can gain entries).
  const [symbolsVersion, setSymbolsVersion] = useState(0);
  const symbols = useMemo(() => {
    // `symbolsVersion` is an intentional invalidation key (bumped after each
    // executed command so recents can enter the universe) — not read otherwise.
    void symbolsVersion;
    return listPaletteSymbolUniverse();
  }, [symbolsVersion]);

  const predicates = useMemo(() => {
    const codes = new Set(items.map((entry) => entry.code.toUpperCase()));
    return makeCommandPredicates({ codes, symbols });
  }, [items, symbols]);

  const parsed: ParsedCommand = useMemo(
    () => parseCommandInput(input, predicates),
    [input, predicates],
  );

  const suggestions = useMemo<CommandSuggestion[]>(() => {
    const text = input.trim();
    if (!text) return [];
    const out: CommandSuggestion[] = [];
    const excluded = new Set<string>();
    if (parsed.kind === "security-function") {
      out.push({
        id: `cmd.${parsed.symbol}.${parsed.code}`,
        code: parsed.code,
        label: `Open ${parsed.code} with ${parsed.symbol}`,
        meta: parsed.go ? "GO" : "Command",
        history: `${parsed.symbol} ${parsed.code}${parsed.go ? " <GO>" : ""}`,
        run: () => openFunctionTarget(parsed.code, parsed.symbol),
      });
      excluded.add(parsed.code);
    }
    const codeTargets = items.map((entry) => ({
      code: entry.code,
      name: entry.name,
      category: entry.category,
      entry,
    }));
    for (const hit of fuzzyRankDetailed(codeTargets, text, [], MAX_CODE_SUGGESTIONS)) {
      const code = hit.item.code.toUpperCase();
      if (out.some((s) => s.id === `fn.${code}`)) continue;
      out.push({
        id: `fn.${code}`,
        code,
        label: hit.item.name,
        meta: hit.item.category,
        history: code,
        run: () => openFunctionTarget(code),
      });
    }
    const symbolHits = matchSymbolSuggestions(symbols, text, excluded);
    for (const symbol of symbolHits) {
      out.push({
        id: `sym.${symbol}`,
        code: symbol,
        label: `Open ${symbol} in focused pane`,
        meta: "Symbol",
        history: `${symbol} ${focusedTargetCode()}`,
        run: () => openFunctionTarget(focusedTargetCode(), symbol),
      });
    }
    return out.slice(0, MAX_SUGGESTIONS);
  }, [input, parsed, items, symbols]);

  const menuOpen = menuVisible && input.trim() !== "";

  // The titlebar clips overflow (verified in a real browser: the dropdown was
  // invisible behind `overflow: hidden`), so the suggestion menu renders
  // through a portal to <body> with fixed coordinates anchored to the input.
  useEffect(() => {
    if (!menuOpen) return;
    const update = () => {
      const rect = formRef.current?.getBoundingClientRect();
      if (!rect) return;
      // jsdom reports a zero rect; real browsers report the input's box.
      // The 340px floor keeps the menu usable in both.
      const width = Math.max(340, rect.width);
      const left = Math.min(rect.left, Math.max(8, window.innerWidth - width - 8));
      setMenuAnchor({ top: rect.bottom + 4, left, width });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [menuOpen]);

  useEffect(() => {
    setCursor(0);
  }, [input]);

  const rememberSymbols = () => {
    setSymbolsVersion((v) => v + 1);
  };

  const submit = (raw: string) => {
    const text = raw.trim();
    if (!text) return;
    pushCommandHistory(text);
    const parsedCommand = parseCommandInput(text, predicates);
    let handled = executeParsedCommand(parsedCommand);
    if (!handled && parsedCommand.kind === "unknown" && !text.includes(" ")) {
      // Palette records action ids ("theme.midnight") into the shared session
      // history; replaying one here hits no code/symbol/verb (the dot is not a
      // valid verb token), so give the action registry a chance before
      // reporting "no match" (R1-F9).
      handled = runPaletteActionByVerb(text.toLowerCase());
    }
    if (!handled) {
      // Keep the input so the user can fix the command; the empty-state
      // hint explains the grammar.
      setMenuVisible(true);
      return;
    }
    setInput("");
    draftRef.current = "";
    setCursor(0);
    setMenuVisible(false);
    rememberSymbols();
  };

  const runSuggestion = (suggestion: CommandSuggestion) => {
    pushCommandHistory(suggestion.history);
    suggestion.run();
    setInput("");
    draftRef.current = "";
    setCursor(0);
    setMenuVisible(false);
    rememberSymbols();
  };

  const historyStep = (dir: -1 | 1) => {
    const history = getCommandHistory();
    if (dir === -1 && !history.includes(input)) draftRef.current = input;
    const next = stepCommandHistory(input || null, dir);
    setInput(next === null ? draftRef.current : next);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (suggestions.length > 0) {
        setCursor((c) => Math.min(c + 1, suggestions.length - 1));
      } else {
        historyStep(1);
      }
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (suggestions.length > 0) {
        setCursor((c) => Math.max(c - 1, 0));
      } else {
        historyStep(-1);
      }
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      // R1-F1: a typed verb that resolves to a registered action must win over
      // a coincidental fuzzy suggestion ("split" must not open DVD). Only fall
      // through to suggestions when the verb is not actionable.
      const verbHandled =
        parsed.kind === "verb" && findPaletteActionForVerb(parsed.verb) != null;
      if (!verbHandled && suggestions.length > 0 && suggestions[cursor]) {
        runSuggestion(suggestions[cursor]);
      } else {
        submit(input);
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      setMenuVisible(false);
      inputRef.current?.blur();
    }
  };

  return (
    <div className="cmdline interactive">
      <form
        ref={formRef}
        className="cmdline__form"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          submit(input);
        }}
      >
        <span aria-hidden="true" className="cmdline__prompt">
          {"\u203a"}
        </span>
        <input
          ref={(el) => {
            inputRef.current = el;
            registeredInput = el;
          }}
          id="showme-cmdline-input"
          className="cmdline__input"
          role="combobox"
          aria-expanded={menuOpen}
          aria-controls={menuOpen ? "showme-cmdline-listbox" : undefined}
          aria-activedescendant={
            menuOpen && suggestions[cursor] ? optionDomId(suggestions[cursor]) : undefined
          }
          aria-autocomplete="list"
          aria-label="Command line"
          placeholder="Type a command — e.g. MSFT GP"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setMenuVisible(true);
          }}
          onFocus={() => setMenuVisible(true)}
          onBlur={() => setMenuVisible(false)}
          onKeyDown={onKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        <span aria-hidden="true" className="cmdline__hint">
          {"<GO>"}
        </span>
        <button
          type="submit"
          className="cmdline__go"
          aria-label="Run command (GO)"
          title="Run command (GO)"
        >
          GO
        </button>
      </form>
      {menuOpen &&
        menuAnchor &&
        createPortal(
          <div
            id="showme-cmdline-listbox"
            role="listbox"
            aria-label="Command suggestions"
            className="cmdline__menu"
            style={{
              position: "fixed",
              top: menuAnchor.top,
              left: menuAnchor.left,
              width: menuAnchor.width,
              minWidth: 340,
            }}
            onMouseDown={(e) => e.preventDefault()}
          >
            {suggestions.length === 0 ? (
              <div className="cmdline__empty">
                No match — try MSFT GP, a code like GP, or a verb like theme
              </div>
            ) : (
              suggestions.map((suggestion, index) => (
                <div
                  key={suggestion.id}
                  id={optionDomId(suggestion)}
                  role="option"
                  aria-selected={index === cursor}
                  className={`cmdline__option${index === cursor ? " cmdline__option--cursor" : ""}`}
                  onMouseEnter={() => setCursor(index)}
                  onMouseDown={() => runSuggestion(suggestion)}
                >
                  <span className="cmdline__option-code">{suggestion.code}</span>
                  <span className="cmdline__option-label">{suggestion.label}</span>
                  <span className="cmdline__option-meta">{suggestion.meta}</span>
                </div>
              ))
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
