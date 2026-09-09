/**
 * First-run detection (upgrade U9, 2026-09-08).
 *
 * A truly fresh boot lands on a single empty HOME leaf with an empty
 * watchlist. Instead of leaving the desk bare, Welcome offers a one-time,
 * dismissible desk-setup card that loads one of the EXISTING builtin
 * presets (`lib/builtinPresets.ts`) and/or seeds a starter watchlist via
 * the EXISTING `addSymbol` queue (`lib/watchlist.ts`).
 *
 * Contract:
 *   - "First run" = the dismiss flag was never stored AND the live
 *     workspace tree is still the pristine single-HOME default. The tree
 *     check keeps the card away from users whose workspace restored from
 *     disk (they already have a desk) even if localStorage was cleared.
 *   - ANY card action (preset, seed, or Skip) attempts to store the flag.
 *     Write-failure degradation (real behavior, R1-L): `markFirstRunDone`
 *     swallows quota / private-mode write errors, so a PERSISTENTLY broken
 *     localStorage means the card can re-offer on the next boot (it stays
 *     dismissible every time). Within a session it never nag-loops: the
 *     read side treats storage-broken reads as "answered", and the card's
 *     own `answered` component state removes it immediately on any action.
 *   - The workspace persistence schema is NOT touched: presets build
 *     normal trees and the flag lives in its own localStorage key,
 *     following the existing `showme.*` convention
 *     (`showme.sidecarPort`, `showme.locale.v1`, …).
 */
import { addSymbol, type WatchlistRow } from "./watchlist";
import type { WorkspaceNode } from "./workspace";
import { useWorkspace } from "./workspace";
import { useBotStore } from "./bot-store";
import { isKaosRecord } from "./kaos-venues";

export const FIRST_RUN_DONE_KEY = "showme.firstrun.done";

/**
 * Starter deck for the one-click "seed watchlist" action. Liquid, routable
 * symbols only — equities via the quote route, crypto in canonical
 * no-slash Binance form (slash form 404s on /api/quote/).
 */
export const STARTER_WATCHLIST_SYMBOLS: readonly string[] = [
  "AAPL",
  "MSFT",
  "NVDA",
  "SPY",
  "QQQ",
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
];

/** True when the user has already answered the first-run card (or storage is unavailable). */
export function isFirstRunDone(): boolean {
  try {
    if (typeof localStorage === "undefined") return true;
    return localStorage.getItem(FIRST_RUN_DONE_KEY) === "1";
  } catch {
    // Private mode / quota errors: treat as answered so we never nag-loop.
    return true;
  }
}

/** Record that the first-run card was answered. Idempotent, best-effort. */
export function markFirstRunDone(): void {
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(FIRST_RUN_DONE_KEY, "1");
    }
  } catch {
    /* ignore — the card simply re-offers next boot, still dismissible */
  }
}

/** Pure check: the tree is still the untouched cold-boot single HOME leaf. */
export function isPristineHomeWorkspace(tree: WorkspaceNode): boolean {
  return tree.kind === "leaf" && tree.code === "HOME";
}

/**
 * Seed the starter watchlist through the existing serialized `addSymbol`
 * queue (dedupes against existing rows). Returns the resulting rows so the
 * caller can update in-component state without a second disk read.
 */
export async function seedStarterWatchlist(): Promise<WatchlistRow[]> {
  let rows: WatchlistRow[] = [];
  for (const symbol of STARTER_WATCHLIST_SYMBOLS) {
    rows = await addSymbol(symbol);
  }
  return rows;
}

/**
 * KAOS Multibot first-run action (frozen contract §D). Opens the saved
 * KAOS bot when one exists, otherwise opens a NEW draft preseeded by the
 * bot store's KAOS defaults (engine "kaos", crypto + NASDAQ venues, shadow
 * mode) — through the EXISTING bot-store create flow only. Never enables
 * or flips modes programmatically; saving/enabling stays a user action in
 * the BOT pane.
 *
 * Navigates the focused workspace leaf to the BOT pane in both branches.
 * A sidecar failure degrades honestly: the list comes back empty and the
 * user still lands on a KAOS draft they can complete once the sidecar is
 * up.
 */
export type KaosStartOutcome = "opened-existing" | "new-draft";

export async function startKaosBot(): Promise<KaosStartOutcome> {
  const store = useBotStore.getState();
  // Refresh the list first so an already-saved KAOS Multibot is reopened
  // instead of duplicated as a second draft.
  await store.loadList();
  const { bots, openExisting, openNew } = useBotStore.getState();
  // R2 L-3 fix: isKaosRecord is the real predicate (engine/name/spec-id) —
  // the old `strategy_id === KAOS_BOT_NAME` arm compared an id to a display
  // name and could never match a saved record.
  const existing = bots.find((b) => isKaosRecord(b));
  if (existing) {
    await openExisting(existing.id);
    useWorkspace.getState().setFocusedTarget("BOT");
    return "opened-existing";
  }
  openNew();
  useWorkspace.getState().setFocusedTarget("BOT");
  return "new-draft";
}
