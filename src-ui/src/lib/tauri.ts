/**
 * Tauri façade — keeps the rest of the UI free from `@tauri-apps/api` knowledge.
 *
 * In a regular browser tab (`vite preview`), every method falls back to a
 * sensible no-op so the UI is still inspectable for design work.
 */
import type { Event } from "@tauri-apps/api/event";

const isTauri =
  typeof window !== "undefined" &&
  (
    // @ts-expect-error injected by Tauri runtime
    typeof window.__TAURI_INTERNALS__ !== "undefined" ||
    // @ts-expect-error injected by Tauri runtime
    typeof window.__TAURI__ !== "undefined" ||
    window.location.protocol === "tauri:"
  );

type Listener<T> = (event: Event<T>) => void;

export async function invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauri) {
    // Browser-mode stubs for design preview.
    if (cmd === "sidecar_status")
      return { status: "stub", restarts: 0, last_error: null } as unknown as T;
    if (cmd === "sidecar_port") return { port: null } as unknown as T;
    if (cmd === "install_to_applications")
      return {
        ok: false,
        source: "",
        target: "/Applications/showMe.app",
        already_installed: false,
      } as unknown as T;
    return null as unknown as T;
  }
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

export async function listen<T = unknown>(
  event: string,
  cb: Listener<T>,
): Promise<() => void> {
  if (!isTauri) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen<T>(event, cb);
}

export async function emit(event: string, payload?: unknown): Promise<void> {
  if (!isTauri) return;
  const { emit } = await import("@tauri-apps/api/event");
  return emit(event, payload);
}

export const isInTauri = (): boolean => isTauri;
