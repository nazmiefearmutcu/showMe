/**
 * Palette v2 action registry — verbs for the ⌘K command line.
 *
 * Campaign 2026-09-08 (Lane B, U1): the palette listed 142 functions but was
 * blind to what a desk user types most — verbs. This registry composes
 * one-line actions into stores/APIs that already exist (theme presets,
 * layout presets, workspace splits, sidebar/density preferences). Each run()
 * is a one-liner into an existing store; nothing here introduces new state.
 *
 * Action recents use their OWN localStorage stack (separate from
 * lib/palette-recents.ts, whose stack feeds the Sidebar "Recent" group and
 * therefore must only ever contain function codes).
 */
import { BUILTIN_PRESETS, loadBuiltinPreset } from "./builtinPresets";
import { useBotStore } from "./bot-store";
import { isKaosRecord } from "./kaos-venues";
import { startKaosBot } from "./first-run";
import { loadPreset, savePreset } from "./presets";
import { useAppStore } from "./store";
import { readState, setDensity, setPreset, toggleTheme, type Preset } from "./theme";
import { toast } from "./toast";
import { findLeaf, firstLeafId, useWorkspace } from "./workspace";
import { safeReadLocal, safeWriteLocal } from "./safe-storage";
import { navigate } from "./router";
import { recordRecentCode } from "./palette-recents";
import { pushRecentSymbol } from "./symbols";
import { fuzzyRankDetailed } from "./fuzzy";
import type { ParsedCommand } from "./command-parse";

export type ActionGroup = "theme" | "layout" | "workspace" | "bot" | "preferences";

export interface PaletteAction {
  /** Stable unique id — doubles as the fuzzy/recents key ("theme.midnight"). */
  id: string;
  /** Short uppercase chip shown in the palette's code column. */
  tag: string;
  /** Primary searchable label, e.g. "Switch theme to Midnight". */
  name: string;
  group: ActionGroup;
  run: () => void;
}

const THEME_PRESETS: Exclude<Preset, "custom">[] = [
  "midnight",
  "matrix",
  "iced",
  "amber",
  "papyrus",
  "neon",
];

const ACTION_RECENTS_KEY = "showme.palette.action-recents";
const ACTION_RECENTS_MAX = 5;

export function listRecentActionIds(): string[] {
  return safeReadLocal<string[]>(ACTION_RECENTS_KEY, [], {
    label: "Recent palette actions",
    validate: (v): v is string[] => Array.isArray(v),
  }).filter((s) => typeof s === "string");
}

export function recordRecentActionId(id: string): void {
  const current = listRecentActionIds().filter((existing) => existing !== id);
  safeWriteLocal(
    ACTION_RECENTS_KEY,
    [id, ...current].slice(0, ACTION_RECENTS_MAX),
    { label: "Recent palette actions" },
  );
}

function stampName(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `desk-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

/**
 * Build the action list. User-saved layout preset names are injected by the
 * caller (the palette fetches them async on open — listPresets is async,
 * the registry itself stays synchronous).
 */
export function listPaletteActions(userPresetNames: string[] = []): PaletteAction[] {
  const actions: PaletteAction[] = [];

  for (const preset of THEME_PRESETS) {
    const label = preset.charAt(0).toUpperCase() + preset.slice(1);
    actions.push({
      id: `theme.${preset}`,
      tag: "THEME",
      name: `Switch theme to ${label}`,
      group: "theme",
      run: () => {
        setPreset(preset);
      },
    });
  }
  actions.push({
    id: "theme.toggle-dark-light",
    tag: "THEME",
    name: "Toggle dark / light theme",
    group: "theme",
    run: () => {
      toggleTheme();
    },
  });

  for (const preset of BUILTIN_PRESETS) {
    actions.push({
      id: `layout.builtin.${preset.id}`,
      tag: "LAYOUT",
      name: `Load layout: ${preset.label}`,
      group: "layout",
      run: () => {
        if (loadBuiltinPreset(preset.id)) {
          toast.success(`Layout loaded: ${preset.label}`, preset.description);
        } else {
          toast.error(`Preset '${preset.id}' not available`);
        }
      },
    });
  }

  for (const name of userPresetNames) {
    actions.push({
      id: `layout.user.${name}`,
      tag: "LAYOUT",
      name: `Load layout: ${name}`,
      group: "layout",
      run: () => {
        void loadPreset(name).then((ok) => {
          if (ok) toast.success(`Layout loaded: ${name}`);
          else toast.error(`Preset '${name}' could not be loaded`);
        });
      },
    });
  }

  actions.push({
    id: "layout.save-current",
    tag: "LAYOUT",
    name: "Save current layout as preset",
    group: "layout",
    run: () => {
      const name = stampName();
      void savePreset(name)
        .then(() => toast.success(`Layout saved as ${name}`, "Rename it any time from ⌘ Layout"))
        .catch((err: unknown) => toast.error("Layout save failed", String(err)));
    },
  });

  actions.push({
    id: "workspace.split-right",
    tag: "PANE",
    name: "Split focused pane right",
    group: "workspace",
    run: () => {
      useWorkspace.getState().splitFocused("h");
    },
  });
  actions.push({
    id: "workspace.split-below",
    tag: "PANE",
    name: "Split focused pane below",
    group: "workspace",
    run: () => {
      useWorkspace.getState().splitFocused("v");
    },
  });
  actions.push({
    id: "workspace.close-pane",
    tag: "PANE",
    name: "Close focused pane",
    group: "workspace",
    run: () => {
      useWorkspace.getState().closeFocused();
    },
  });

  actions.push({
    id: "bot.start-kaos",
    tag: "KAOS",
    name: "Start KAOS bot",
    group: "bot",
    run: () => {
      // Same flow as the first-run card: reopens the saved KAOS Multibot,
      // or opens a new preseeded draft (engine "kaos", crypto + NASDAQ
      // venues, shadow). Never enables or flips modes programmatically.
      void startKaosBot()
        .then((outcome) => {
          toast.success(
            outcome === "opened-existing"
              ? "KAOS Multibot opened"
              : "New KAOS Multibot draft",
            "Scans crypto + NASDAQ. Shadow mode until you enable live.",
          );
        })
        .catch((err: unknown) => toast.error("KAOS bot failed to open", String(err)));
    },
  });
  actions.push({
    id: "bot.open-kaos",
    tag: "KAOS",
    name: "Open KAOS bot",
    group: "bot",
    run: () => {
      const store = useBotStore.getState();
      void store
        .loadList()
        .then(() => {
          const { bots, openExisting } = useBotStore.getState();
          const existing = bots.find((b) => isKaosRecord(b));
          if (existing) {
            void openExisting(existing.id);
          } else {
            toast.error(
              "No KAOS bot saved yet",
              "Run 'Start KAOS bot' to create the KAOS Multibot draft.",
            );
          }
          useWorkspace.getState().setFocusedTarget("BOT");
        })
        .catch((err: unknown) => toast.error("KAOS bot failed to open", String(err)));
    },
  });

  actions.push({
    id: "prefs.toggle-sidebar",
    tag: "PREF",
    name: "Toggle functions sidebar",
    group: "preferences",
    run: () => {
      useAppStore.getState().toggleSidebar();
    },
  });
  actions.push({
    id: "prefs.toggle-density",
    tag: "PREF",
    name: "Toggle compact / comfortable density",
    group: "preferences",
    run: () => {
      setDensity(readState().density === "compact" ? "comfortable" : "compact");
    },
  });
  actions.push({
    id: "prefs.shortcuts-help",
    tag: "PREF",
    name: "Shortcuts help",
    group: "preferences",
    run: () => {
      // Same overlay the `?` key toggles — one store flag, one truth.
      useAppStore.getState().showShortcuts();
    },
  });

  return actions;
}

/* ── L2 command execution (campaign 2026-09-11) ──────────────────────────
 *
 * Shared execution path for the titlebar CommandLine and anything else that
 * parses `ParsedCommand`. The palette keeps its own recents semantics
 * (function codes and symbols have separate stacks); these helpers are the
 * canonical "open a function code with an optional symbol" navigation.
 */

/** Codes that are not symbol-bindable targets — fall back to DES. */
export const NON_SYMBOL_TARGET_CODES = new Set(["HOME", "PREF", "AGENT"]);

/**
 * The code a symbol submission should bind to: the focused leaf's code, or
 * DES when the focused leaf is HOME/PREF/AGENT (or headless). Mirrors the
 * palette's `symbolTargetCode` computation (Palette.tsx).
 */
export function focusedTargetCode(): string {
  try {
    const { tree, focusedId } = useWorkspace.getState();
    const leaf =
      findLeaf(tree, focusedId) ??
      (tree.kind === "leaf" ? tree : findLeaf(tree, firstLeafId(tree)));
    const code = (leaf?.code ?? "DES").toUpperCase();
    return NON_SYMBOL_TARGET_CODES.has(code) ? "DES" : code;
  } catch {
    return "DES";
  }
}

/**
 * Pure navigation: `/symbol/<SYM>/<CODE>` when a symbol is supplied,
 * `/fn/<CODE>` otherwise. No recents are recorded here — callers decide.
 */
export function navigateToFunction(code: string, symbol?: string): void {
  const upper = code.toUpperCase();
  if (symbol) {
    navigate(`/symbol/${symbol}/${upper}`);
  } else {
    navigate(`/fn/${upper}`);
  }
}

/**
 * Canonical "open with recents" path for the command line: records the
 * function code (and the symbol, when present) then navigates.
 */
export function openFunctionTarget(code: string, symbol?: string): void {
  const upper = code.toUpperCase();
  recordRecentCode(upper);
  if (symbol) pushRecentSymbol(symbol);
  navigateToFunction(upper, symbol);
}

/**
 * Resolve a lowercase verb token to the best registered action. Fuzzy
 * scoring runs over the action registry (`listPaletteActions`); a floor of
 * 400 (substring-level match) keeps a stray word from firing something
 * unrelated. Returns null when nothing crosses the floor.
 */
export function findPaletteActionForVerb(verb: string): PaletteAction | null {
  const actions = listPaletteActions();
  if (actions.length === 0) return null;
  const targets = actions.map((action) => ({
    code: action.id,
    name: action.name,
    category: action.group,
    action,
  }));
  const top = fuzzyRankDetailed(targets, verb, [], 1)[0];
  if (!top || top.score < 400) return null;
  return top.item.action;
}

/** Run the best action for a verb token. Records the action recents stack. */
export function runPaletteActionByVerb(verb: string): boolean {
  const action = findPaletteActionForVerb(verb);
  if (!action) return false;
  recordRecentActionId(action.id);
  action.run();
  return true;
}

/**
 * Execute a parsed command. Returns true when the command was handled
 * (navigated or ran an action); false for `empty` / `unknown` / a verb with
 * no registered action — the caller decides whether that is an error state.
 */
export function executeParsedCommand(parsed: ParsedCommand): boolean {
  switch (parsed.kind) {
    case "empty":
      return false;
    case "unknown":
      return false;
    case "function":
      openFunctionTarget(parsed.code);
      return true;
    case "security":
      // A bare security binds to the focused pane's function (palette
      // symbol-row parity), falling back to DES for HOME/PREF/AGENT.
      openFunctionTarget(focusedTargetCode(), parsed.symbol);
      return true;
    case "security-function":
      openFunctionTarget(parsed.code, parsed.symbol);
      return true;
    case "verb":
      return runPaletteActionByVerb(parsed.verb);
  }
}
