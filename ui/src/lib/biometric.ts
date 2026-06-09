/**
 * Biometric / Touch ID frontend bridge.
 *
 * Pairs the Tauri command surface with a 5-min reauth cache so a single
 * approval covers the obvious "place a few orders" flow without re-prompting
 * for every click. The Rust shell still has the final word — `requireAuth`
 * always re-asks once the cache window closes.
 */
import { invoke, isInTauri } from "./tauri";

export type BiometryKind = "none" | "touch_id" | "face_id";
export type BioVia =
  | "touch_id"
  | "face_id"
  | "password"
  | "stub"
  | "denied"
  | "unavailable";

export interface BiometricCapabilities {
  biometry_available: boolean;
  passcode_available: boolean;
  biometry_kind: BiometryKind;
}

export interface BiometricResult {
  allowed: boolean;
  reason: string;
  via: BioVia;
  capabilities: BiometricCapabilities;
}

const REAUTH_WINDOW_MS = 5 * 60 * 1000;
let lastApprovalTs = 0;

export async function capabilities(): Promise<BiometricCapabilities> {
  if (!isInTauri()) {
    return {
      biometry_available: false,
      passcode_available: false,
      biometry_kind: "none",
    };
  }
  try {
    return await invoke<BiometricCapabilities>("biometric_capabilities");
  } catch {
    return {
      biometry_available: false,
      passcode_available: false,
      biometry_kind: "none",
    };
  }
}

const UNAVAILABLE_CAPS: BiometricCapabilities = {
  biometry_available: false,
  passcode_available: false,
  biometry_kind: "none",
};

export async function requestBiometric(reason: string): Promise<BiometricResult> {
  // Security gate: fail CLOSED. Outside Tauri there is no LocalAuthentication
  // bridge, so deny rather than silently approve (mirrors `capabilities()`,
  // the Rust core's Ok(false) on non-macOS, and the bio_seed manifest contract:
  // allowed=false, via="unavailable", "not configured"). "BIO never silently
  // approves." Production is always in Tauri, so this only affects dev/browser.
  if (!isInTauri()) {
    return { allowed: false, reason, via: "unavailable", capabilities: UNAVAILABLE_CAPS };
  }
  try {
    return await invoke<BiometricResult>("request_biometric", { reason });
  } catch {
    // An errored OS call must DENY — never throw-through or approve.
    return { allowed: false, reason, via: "unavailable", capabilities: UNAVAILABLE_CAPS };
  }
}

/**
 * Run `action` only after the user authenticates (or the cached approval
 * is still warm). Returns whatever `action` returns; throws when the
 * user cancels.
 */
export async function requireAuth<T>(
  reason: string,
  action: () => Promise<T> | T,
): Promise<T> {
  const fresh = Date.now() - lastApprovalTs < REAUTH_WINDOW_MS;
  if (fresh) return action();
  const res = await requestBiometric(reason);
  if (!res.allowed) {
    throw new Error(`auth denied (${res.via})`);
  }
  lastApprovalTs = Date.now();
  return action();
}

export function clearAuthCache(): void {
  lastApprovalTs = 0;
}

export interface LiveTradeOptions {
  /** $ notional of the order; we only force re-prompt above this. */
  notional?: number;
  /** Hard floor — orders ≤ this dollar value never need biometric. */
  notionalThreshold?: number;
  /** Override the default reason string shown in the OS prompt. */
  reason?: string;
}

/**
 * Wrap an order-submission callback in a biometric gate.
 *
 * The 5-min reauth cache from `requireAuth` still applies — the prompt
 * only fires when the cache window is cold *and* the notional clears
 * the threshold (default $1 000 per Rapor 2 §6.7 madde 2).
 */
export async function gateLiveTrade<T>(
  opts: LiveTradeOptions,
  action: () => Promise<T> | T,
): Promise<T> {
  const threshold = opts.notionalThreshold ?? 1000;
  const notional = opts.notional ?? 0;
  const reason =
    opts.reason ??
    (notional
      ? `Live trade · $${notional.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
      : "Live trade");
  if (notional > 0 && notional < threshold) {
    return action();
  }
  return requireAuth(reason, action);
}
