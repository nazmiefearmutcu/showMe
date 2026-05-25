/**
 * Manifest registry — the UI's mirror of the backend's process-wide
 * `ManifestRegistry`. A single instance is shared across the app and a
 * Zustand store backs the React subscription so any component (or
 * `useManifest(code)`) re-renders when manifests load.
 *
 * Design choice: the imperative `ManifestStore` class is the source of
 * truth (matches the Python registry's surface 1:1); the Zustand store
 * mirrors it so React stays out of the contract. Tests and non-React
 * callers can poke the class directly without dragging Zustand in.
 */
import { useEffect, useState } from "react";
import { create } from "zustand";

import { type FunctionManifest } from "./types";

// ---------------------------------------------------------------------------
// Imperative store (class) — mirrors backend.manifest.ManifestRegistry.
// ---------------------------------------------------------------------------

type Listener = () => void;

export class ManifestStore {
  private readonly _byCode = new Map<string, FunctionManifest>();
  private readonly _listeners = new Set<Listener>();

  set(code: string, manifest: FunctionManifest): void {
    this._byCode.set(code, manifest);
    this._emit();
  }

  get(code: string): FunctionManifest | null {
    return this._byCode.get(code) ?? null;
  }

  all(): FunctionManifest[] {
    return Array.from(this._byCode.values());
  }

  codes(): string[] {
    return Array.from(this._byCode.keys());
  }

  clear(): void {
    if (this._byCode.size === 0) return;
    this._byCode.clear();
    this._emit();
  }

  /** Replace the entire registry atomically — one notification at the end. */
  replaceAll(manifests: Iterable<FunctionManifest>): void {
    this._byCode.clear();
    for (const m of manifests) {
      this._byCode.set(m.code, m);
    }
    this._emit();
  }

  /** Subscribe to mutations. Returns an unsubscribe handle. */
  subscribe(fn: Listener): () => void {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  private _emit(): void {
    for (const fn of this._listeners) {
      try {
        fn();
      } catch (err) {
        // A buggy listener must not interrupt the rest of the fan-out.
        // eslint-disable-next-line no-console
        console.warn("ManifestStore listener threw", err);
      }
    }
  }
}

/** Module-level singleton — matches backend's `REGISTRY`. */
export const manifestStore = new ManifestStore();

// ---------------------------------------------------------------------------
// React surface — Zustand store wraps the class so components re-render.
// ---------------------------------------------------------------------------

interface ManifestZustandState {
  /** Bumps every time `manifestStore` mutates. */
  version: number;
  loading: boolean;
  error: string | null;
  setLoading: (v: boolean) => void;
  setError: (e: string | null) => void;
}

export const useManifestStore = create<ManifestZustandState>((set) => ({
  version: 0,
  loading: false,
  error: null,
  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e }),
}));

// Bridge: bump `version` whenever the imperative store changes.
manifestStore.subscribe(() => {
  useManifestStore.setState((s) => ({ version: s.version + 1 }));
});

// ---------------------------------------------------------------------------
// HTTP loader — talks to `/api/manifest` (top-level list, see backend route).
// ---------------------------------------------------------------------------

/**
 * Fetch every manifest from the backend and populate the singleton store.
 *
 * @param baseUrl Optional explicit base URL. When omitted we fall back to
 *  same-origin (`/api/manifest`) so this works under vite preview AND under
 *  the Tauri shell once a sidecar port is published. Callers that want to
 *  go through the project's `sidecarFetch` can wire `baseUrl` to the value
 *  of `sidecarBaseUrl()`.
 */
export async function fetchManifests(baseUrl?: string): Promise<void> {
  const setLoading = useManifestStore.getState().setLoading;
  const setError = useManifestStore.getState().setError;
  setLoading(true);
  setError(null);
  try {
    // 2026-05-25 fix: route through sidecarFetch so Tauri renderer gets the
    // correct sidecar base URL + X-ShowMe-Token header. The bare `fetch()`
    // path 404'd under `tauri://localhost` and silently swallowed the manifest.
    let payload: unknown;
    if (baseUrl) {
      const res = await fetch(`${baseUrl}/api/manifest`);
      if (!res.ok) {
        throw new Error(`/api/manifest → ${res.status} ${res.statusText}`);
      }
      payload = await res.json();
    } else {
      const { sidecarFetch } = await import("@/lib/sidecar");
      payload = await sidecarFetch<unknown>("/api/manifest");
    }
    if (!Array.isArray(payload)) {
      throw new Error("/api/manifest did not return a top-level array");
    }
    manifestStore.replaceAll(payload as FunctionManifest[]);
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
    throw err;
  } finally {
    setLoading(false);
  }
}

// ---------------------------------------------------------------------------
// React hook — single-manifest subscription.
// ---------------------------------------------------------------------------

/**
 * Subscribe a component to one manifest by code. Re-renders when the
 * registry changes (load / clear / replace). Returns `null` until the
 * registry has the requested code.
 */
export function useManifest(code: string): FunctionManifest | null {
  // We track the version externally and dereference the imperative store
  // on every render. This stays correct under React 18 strict-mode double
  // invocations because the class is the single source of truth.
  const version = useManifestStore((s) => s.version);
  const [snapshot, setSnapshot] = useState<FunctionManifest | null>(() =>
    manifestStore.get(code),
  );
  useEffect(() => {
    // Re-sync whenever the code or version changes.
    setSnapshot(manifestStore.get(code));
  }, [code, version]);
  return snapshot;
}
