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
  deleteCredential: (credentialId: string) => Promise<boolean>;
  testCredential: (credentialId: string) => Promise<{ ok: boolean; account?: unknown; error?: string }>;
  upgradeToTrade: (credentialId: string, accountLabel: string) => Promise<boolean>;

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

  deleteCredential: async (credentialId) => {
    set({ error: null });
    try {
      await sidecarFetch<{ ok: boolean }>(
        `/api/exchange/credentials/${credentialId}`,
        { method: "DELETE" },
      );
      await get().loadCredentials();
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return false;
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
