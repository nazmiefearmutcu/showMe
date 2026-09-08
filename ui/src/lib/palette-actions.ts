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
import { loadPreset, savePreset } from "./presets";
import { useAppStore } from "./store";
import { readState, setDensity, setPreset, toggleTheme, type Preset } from "./theme";
import { toast } from "./toast";
import { useWorkspace } from "./workspace";
import { safeReadLocal, safeWriteLocal } from "./safe-storage";

export type ActionGroup = "theme" | "layout" | "workspace" | "preferences";

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

  return actions;
}
