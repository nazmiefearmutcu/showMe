/**
 * Universal security context — the desk's active security.
 *
 * Bloomberg-grade desks have ONE notion of "the security you are looking
 * at": every command, pane and titlebar readout resolves against it. This
 * module is that single source of truth.
 *
 * Producers:
 *   - `shell/Titlebar.tsx` derives the value from the focused workspace
 *     leaf (symbol → asset class via `lib/symbols.ts`) and pushes it here
 *     on every focus/symbol change.
 *   - Non-React callers (command line, palette verbs) use the imperative
 *     `setActiveSecurity()`.
 *
 * Semantics (frozen interface, see campaign CONTRACT.md):
 *   - `symbol`     — normalized ticker, e.g. "AAPL" / "BTCUSDT".
 *   - `label`      — human-readable display label for the security
 *                    (currently the asset-class label, e.g. "US Equity").
 *   - `assetClass` — canonical uppercase asset class from
 *                    `inferAssetClassName` (EQUITY / CRYPTO / FX / …).
 *
 * `active === null` means "no security in context" (e.g. a HOME pane) and
 * must render as a neutral placeholder — never as a fake security.
 */
import { create } from "zustand";

export interface ActiveSecurity {
  symbol: string;
  label: string;
  assetClass: string;
}

interface SecurityContextState {
  active: ActiveSecurity | null;
  setActive: (s: ActiveSecurity | null) => void;
}

/** Value-equality so pushing the same security twice doesn't re-render the desk. */
function sameSecurity(a: ActiveSecurity | null, b: ActiveSecurity | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return a.symbol === b.symbol && a.label === b.label && a.assetClass === b.assetClass;
}

const useSecurityContextStore = create<SecurityContextState>((set) => ({
  active: null,
  setActive: (next) => set((state) => (sameSecurity(state.active, next) ? state : { active: next })),
}));

/**
 * Hook: subscribe to the active security. Re-renders the caller whenever
 * the value meaningfully changes.
 */
export function useSecurityContext(): {
  active: ActiveSecurity | null;
  setActive: (s: ActiveSecurity | null) => void;
} {
  const active = useSecurityContextStore((s) => s.active);
  const setActive = useSecurityContextStore((s) => s.setActive);
  return { active, setActive };
}

/** Imperative setter for non-React callers (command line, palette verbs). */
export function setActiveSecurity(s: ActiveSecurity | null): void {
  useSecurityContextStore.getState().setActive(s);
}
