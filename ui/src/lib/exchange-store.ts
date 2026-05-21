/**
 * Sub-system A: zustand store for the Connect-Exchange pane.
 *
 * - `catalog` lists available exchanges from `/api/exchange/catalog`.
 * - `credentials` lists saved connections (no secrets, server-side).
 * - Form input (api_key etc.) is kept in component-local state ONLY.
 */
import { create } from "zustand";

const TOKEN_HEADER = "X-ShowMe-Token";

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  // SHOWME_AUTH_TOKEN is injected at sidecar handshake time, exposed
  // via `window.__SHOWME_TOKEN__` (existing pattern — see lib/sidecar.ts).
  const tok =
    typeof window !== "undefined"
      ? ((window as unknown as { __SHOWME_TOKEN__?: string }).__SHOWME_TOKEN__ ?? "")
      : "";
  const h: Record<string, string> = { "Content-Type": "application/json", ...extra };
  if (tok) h[TOKEN_HEADER] = tok;
  return h;
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
      const r = await fetch("/api/exchange/catalog", { headers: authHeaders() });
      if (!r.ok) throw new Error(`catalog failed: ${r.status}`);
      const body = (await r.json()) as CatalogEntry[];
      set({ catalog: body, catalogLoading: false });
    } catch (e) {
      set({ catalogLoading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  loadCredentials: async () => {
    set({ credentialsLoading: true, error: null });
    try {
      const r = await fetch("/api/exchange/credentials", { headers: authHeaders() });
      if (!r.ok) throw new Error(`credentials failed: ${r.status}`);
      const body = (await r.json()) as { records: CredentialRecord[] };
      set({ credentials: body.records, credentialsLoading: false });
    } catch (e) {
      set({ credentialsLoading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  saveCredential: async (payload) => {
    try {
      const r = await fetch("/api/exchange/credentials", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const body = (await r.json().catch(() => ({ detail: r.statusText }))) as { detail?: string };
        set({ error: body.detail ?? `save failed: ${r.status}` });
        return false;
      }
      await get().loadCredentials();
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return false;
    }
  },

  deleteCredential: async (credentialId) => {
    const r = await fetch(`/api/exchange/credentials/${credentialId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!r.ok) return false;
    await get().loadCredentials();
    return true;
  },

  testCredential: async (credentialId) => {
    const r = await fetch(`/api/exchange/credentials/${credentialId}/test`, {
      method: "POST",
      headers: authHeaders(),
    });
    return (await r.json()) as { ok: boolean; account?: unknown; error?: string };
  },

  upgradeToTrade: async (credentialId, accountLabel) => {
    const r = await fetch(`/api/exchange/credentials/${credentialId}`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify({
        permissions: ["read", "trade"],
        confirm_account_label: accountLabel,
      }),
    });
    if (!r.ok) return false;
    await get().loadCredentials();
    return true;
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
