/**
 * Built-in workspace presets — code-defined trees, no user-save needed.
 *
 * Round 25 ships **Markets Overview**: a 2×2 split (DES + GP on top,
 * WEI + TOP at the bottom) so the trader gets price + chart + global
 * indices + headlines on one screen as soon as the app boots.
 *
 * Future Rounds add more presets here (PORT-only blotter, scanner-
 * heavy mode, etc.). They render as one-click chips on the Welcome
 * screen and survive the application restart because they're code,
 * not state.
 */
import {
  leaf,
  loadWorkspace,
  split,
  type SerializedWorkspace,
  type WorkspaceNode,
} from "./workspace";

export interface BuiltinPreset {
  id: string;
  label: string;
  description: string;
  build: (symbol?: string) => WorkspaceNode;
}

function markersOverviewTree(symbol = "AAPL"): WorkspaceNode {
  return split(
    "v",
    [
      split("h", [leaf("DES", symbol), leaf("GP", symbol)]),
      split("h", [leaf("WEI"), leaf("TOP")]),
    ],
    [0.55, 0.45],
  );
}

function tradingDeskTree(symbol = "AAPL"): WorkspaceNode {
  return split(
    "h",
    [
      split("v", [leaf("DES", symbol), leaf("PORT")]),
      split("v", [leaf("GP", symbol), leaf("WATCH")]),
    ],
    [0.5, 0.5],
  );
}

function macroTree(): WorkspaceNode {
  return split(
    "v",
    [
      split("h", [leaf("WEI"), leaf("WCRS")]),
      split("h", [leaf("GLCO"), leaf("ECO")]),
    ],
  );
}

export const BUILTIN_PRESETS: BuiltinPreset[] = [
  {
    id: "markets-overview",
    label: "Markets Overview",
    description: "DES + chart on top, world indices + headlines below",
    build: markersOverviewTree,
  },
  {
    id: "trading-desk",
    label: "Trading Desk",
    description: "DES + portfolio + chart + watchlist (4-pane split)",
    build: tradingDeskTree,
  },
  {
    id: "macro",
    label: "Macro Watch",
    description: "WEI + WCRS + GLCO + ECO (cross-asset macro grid)",
    build: macroTree,
  },
];

export function loadBuiltinPreset(id: string, symbol?: string): boolean {
  const preset = BUILTIN_PRESETS.find((p) => p.id === id);
  if (!preset) return false;
  const tree = preset.build(symbol);
  const serialized: SerializedWorkspace = {
    tree,
    focusedId: "", // loadWorkspace remaps and falls back to firstLeafId
    savedAt: new Date().toISOString(),
  };
  loadWorkspace(serialized);
  return true;
}
