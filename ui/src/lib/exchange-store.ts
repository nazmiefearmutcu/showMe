/**
 * Sub-system A: zustand store for the Connect-Exchange pane.
 *
 * - `catalog` lists available exchanges from `/api/exchange/catalog`.
 * - `credentials` lists saved connections (no secrets, server-side).
 * - Form input (api_key etc.) is kept in component-local state ONLY.
 *
 * All HTTP goes through `sidecarFetch` so the sidecar port + X-ShowMe-Token
 * are attached automatically. `sidecarFetch` throws on non-OK responses; each
 * action below translates that into a boolean / envelope shape suitable for
 * the CONN pane.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";
import { useBotsSupervisionStore } from "./bots-supervision-store";

/**
 * Shape returned by `GET /api/exchange/credentials/{id}/dependents` (Agent 2).
 * The endpoint may not be deployed yet — `dependentBots()` below has a
 * defensive fallback to compute the count client-side from `/api/bots`.
 *
 * `bots_unknown` set to true (QA-2026-05-23 fix) when BOTH the dedicated
 * endpoint AND the `/api/bots` fallback fail. The CONN delete modal must
 * surface a "could not check bot dependencies — proceed carefully?" hint
 * instead of the misleading "0 bot etkilenecek" message.
 */
export interface CredentialDependents {
  credential_id: string;
  bot_count: number;
  bot_ids: string[];
  bots_unknown?: boolean;
}

export interface CatalogEntry {
  id: string;
  display_name: string;
  aliases: string[];
  asset_classes: string[];
  regions: string[];
  adapter: string;
  requires: string[];
  optional: string[];
  capabilities: Record<string, boolean>;
  ccxt_id: string | null;
  notes: string;
}

export interface CredentialRecord {
  id: string;
  exchange_id: string;
  account_label: string;
  permissions: ("read" | "trade")[];
  created_at: string;
}

export interface CreateCredentialPayload {
  exchange_id: string;
  account_label: string;
  secrets: Record<string, string>;
  permissions: ("read" | "trade")[];
  skip_test?: boolean;
}

export interface CatalogFilter {
  query: string;
  assetClasses: string[];
  regions: string[];
}

interface ExchangeStoreShape {
  catalog: CatalogEntry[];
  credentials: CredentialRecord[];
  selectedExchangeId: string | null;
  catalogLoading: boolean;
  credentialsLoading: boolean;
  error: string | null;

  loadCatalog: () => Promise<void>;
  loadCredentials: () => Promise<void>;
  saveCredential: (payload: CreateCredentialPayload) => Promise<boolean>;
  deleteCredential: (credentialId: string, opts?: { force?: boolean }) => Promise<boolean>;
  testCredential: (credentialId: string) => Promise<{ ok: boolean; account?: unknown; error?: string }>;
  upgradeToTrade: (credentialId: string, accountLabel: string) => Promise<boolean>;
  /**
   * C9 (FIX_CONTRACT) — count bots that depend on this credential so the UI
   * can warn the user before delete cascades.  Prefers Agent 2's authoritative
   * endpoint; falls back to `/api/bots` client-side filter when the endpoint
   * is missing (e.g. older sidecar build).
   */
  dependentBots: (credentialId: string) => Promise<CredentialDependents>;

  setSelectedExchange: (id: string | null) => void;
  filterCatalog: (f: CatalogFilter) => CatalogEntry[];
}

export const useExchangeStore = create<ExchangeStoreShape>((set, get) => ({
  catalog: [],
  credentials: [],
  selectedExchangeId: null,
  catalogLoading: false,
  credentialsLoading: false,
  error: null,

  loadCatalog: async () => {
    set({ catalogLoading: true, error: null });
    try {
      const body = await sidecarFetch<CatalogEntry[]>("/api/exchange/catalog");
      set({ catalog: body, catalogLoading: false });
    } catch (e) {
      set({ catalogLoading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  loadCredentials: async () => {
    set({ credentialsLoading: true, error: null });
    try {
      const body = await sidecarFetch<{ records: CredentialRecord[] }>("/api/exchange/credentials");
      set({ credentials: body.records, credentialsLoading: false });
    } catch (e) {
      set({ credentialsLoading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  saveCredential: async (payload) => {
    set({ error: null });
    try {
      await sidecarFetch<CredentialRecord>("/api/exchange/credentials", {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
      });
      await get().loadCredentials();
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return false;
    }
  },

  deleteCredential: async (credentialId, opts) => {
    set({ error: null });
    // C9 (FIX_CONTRACT) — cascade-aware delete.  When force=true, append the
    // query param so Agent 2's backend will disable dependent bots instead of
    // 409'ing.  Older sidecar builds without the query param simply ignore it.
    const qs = opts?.force ? "?force=true" : "";
    try {
      await sidecarFetch<{ ok: boolean }>(
        `/api/exchange/credentials/${credentialId}${qs}`,
        { method: "DELETE" },
      );
      await get().loadCredentials();
      // Cross-store invalidation — bots referencing this credential may now
      // be disabled (cascade) or stale-permission; refresh the supervisor so
      // the badge / mode pills reflect the new state immediately.
      // QA-2026-05-23: log failures instead of swallowing them so the caller
      // can decide whether to surface a "bot list may be stale" hint.
      try {
        await useBotsSupervisionStore.getState().loadAll();
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn(
          "[exchange-store] supervision invalidation failed after delete:",
          err,
        );
        // Preserve the delete success but mark the supervisor as stale.
        set({ error: "bots_supervision_stale" });
      }
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return false;
    }
  },

  dependentBots: async (credentialId) => {
    // Prefer Agent 2's dedicated endpoint.  Falls back to /api/bots if the
    // sidecar build is old (or returns 404). QA-2026-05-23: when BOTH paths
    // fail we now return `bots_unknown=true` so the CONN delete confirm copy
    // can warn the user instead of falsely claiming "0 bot etkilenecek".
    let dedicatedErr: unknown = null;
    try {
      const body = await sidecarFetch<CredentialDependents>(
        `/api/exchange/credentials/${credentialId}/dependents`,
      );
      if (body && typeof body.bot_count === "number") {
        return {
          credential_id: credentialId,
          bot_count: body.bot_count,
          bot_ids: Array.isArray(body.bot_ids) ? body.bot_ids : [],
        };
      }
    } catch (err) {
      dedicatedErr = err;
    }
    try {
      const fallback = await sidecarFetch<{ records: Array<{ id: string; credential_id: string }> }>(
        "/api/bots",
      );
      const records = Array.isArray(fallback?.records) ? fallback.records : [];
      const matches = records.filter((b) => b.credential_id === credentialId);
      return {
        credential_id: credentialId,
        bot_count: matches.length,
        bot_ids: matches.map((b) => b.id),
      };
    } catch (fallbackErr) {
      // eslint-disable-next-line no-console
      console.warn(
        "[exchange-store] dependentBots failed for both endpoints:",
        { credentialId, dedicatedErr, fallbackErr },
      );
      return {
        credential_id: credentialId,
        bot_count: 0,
        bot_ids: [],
        bots_unknown: true,
      };
    }
  },

  testCredential: async (credentialId) => {
    try {
      return await sidecarFetch<{ ok: boolean; account?: unknown; error?: string }>(
        `/api/exchange/credentials/${credentialId}/test`,
        { method: "POST" },
      );
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  },

  upgradeToTrade: async (credentialId, accountLabel) => {
    set({ error: null });
    try {
      await sidecarFetch<CredentialRecord>(
        `/api/exchange/credentials/${credentialId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            permissions: ["read", "trade"],
            confirm_account_label: accountLabel,
          }),
          headers: { "Content-Type": "application/json" },
        },
      );
      await get().loadCredentials();
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return false;
    }
  },

  setSelectedExchange: (id) => set({ selectedExchangeId: id }),

  filterCatalog: ({ query, assetClasses, regions }) => {
    const q = query.trim().toLowerCase();
    return get().catalog.filter((e) => {
      if (q) {
        const hit =
          e.id.toLowerCase().includes(q) ||
          e.display_name.toLowerCase().includes(q) ||
          e.aliases.some((a) => a.toLowerCase().includes(q));
        if (!hit) return false;
      }
      if (assetClasses.length && !assetClasses.some((c) => e.asset_classes.includes(c))) {
        return false;
      }
      if (regions.length && !regions.some((r) => e.regions.includes(r))) {
        return false;
      }
      return true;
    });
  },
}));
