/**
 * Keychain-backed secret store wrapper.
 *
 * Tauri only — browser-mode raises a friendly toast when a write is
 * attempted. Designers can stub their own keys via env files for
 * `npm run dev`.
 */
import { invoke, isInTauri } from "./tauri";

export interface KeychainEntry {
  account: string;
  service: string;
}

export type SecretsBackend = "keychain" | "browser" | "unsupported";

/**
 * Returns which platform-specific store the running shell will use.
 * macOS Tauri → Keychain · other Tauri → unsupported · vite preview → browser.
 */
export async function secretsBackend(): Promise<SecretsBackend> {
  if (!isInTauri()) return "browser";
  try {
    const os = await import("@tauri-apps/plugin-os");
    const platform = await os.platform();
    return platform === "macos" ? "keychain" : "unsupported";
  } catch {
    return "unsupported";
  }
}

export async function listSecrets(): Promise<KeychainEntry[]> {
  if (!isInTauri()) return [];
  try {
    return await invoke<KeychainEntry[]>("keychain_list");
  } catch {
    return [];
  }
}

export async function setSecret(account: string, value: string): Promise<void> {
  if (!isInTauri()) {
    throw new Error("Keychain only available inside Tauri shell");
  }
  await invoke("keychain_set", { account, value });
}

export async function getSecret(account: string): Promise<string | null> {
  if (!isInTauri()) return null;
  try {
    return await invoke<string | null>("keychain_get", { account });
  } catch {
    return null;
  }
}

export async function deleteSecret(account: string): Promise<boolean> {
  if (!isInTauri()) return false;
  try {
    return await invoke<boolean>("keychain_delete", { account });
  } catch {
    return false;
  }
}
