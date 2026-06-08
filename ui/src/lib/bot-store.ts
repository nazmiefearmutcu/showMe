/**
 * Sub-system D UI store: bot CRUD + enable/disable + signal log.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface SignalEntry {
  bar_index: number;
  bar_time: string;
  kind: "entry" | "exit";
  price: number;
  action: "placed" | "shadow" | "skipped";
  order_id?: string | null;
  error?: string | null;
  timestamp?: string;
  /**
   * H13 honesty: provenance of the equity used to size a LIVE order.
   * "broker" = real broker.account() equity; "fallback_10k" = the
   * documented $10k floor when the broker exposed no usable equity.
   * undefined/null for shadow entries and pre-existing records.
   */
  equity_source?: string | null;
}

export interface BotRecord {
  id: string;
  strategy_id: string;
  credential_id: string;
  exchange_id: string;
  symbol: string;
  timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
  tick_interval_seconds: number;
  mode: "shadow" | "live";
  enabled: boolean;
  last_processed_event: SignalEntry | null;
  signal_log: SignalEntry[];
  created_at: string;
  updated_at: string;
}

export interface BotMeta {
  id: string;
  strategy_id: string;
  credential_id: string;
  exchange_id: string;
  symbol: string;
  timeframe: string;
  mode: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

const _BLANK_BOT = (): Omit<BotRecord, "id" | "created_at" | "updated_at" | "last_processed_event" | "signal_log" | "enabled" | "mode"> => ({
  strategy_id: "",
  credential_id: "",
  exchange_id: "",
  symbol: "",
  timeframe: "1h",
  tick_interval_seconds: 60,
});

interface BotStoreShape {
  bots: BotMeta[];
  draft: Partial<BotRecord> | null;
  draftIsNew: boolean;
  dirty: boolean;
  loading: boolean;
  saving: boolean;
  /** H-UI-2 — enable/disable in-flight flag so the buttons can disable. */
  toggling: boolean;
  error: string | null;
  /** Track AbortController for the in-flight openExisting (H-UI-11). */
  _openController?: AbortController | null;

  loadList: () => Promise<void>;
  openNew: () => void;
  openExisting: (id: string) => Promise<void>;
  setDraftField: <K extends keyof BotRecord>(k: K, v: BotRecord[K]) => void;
  save: (confirmLabel?: string) => Promise<BotRecord | null>;
  remove: (id: string) => Promise<boolean>;
  enable: (id: string, confirmLabel?: string) => Promise<BotRecord | null>;
  disable: (id: string) => Promise<BotRecord | null>;
}

// HIGH FIX (audit S7): loadList cascade had no AbortController, so a burst of
// saves/removes that each chained `await loadList()` would race — the last
// write usually won but the order was not deterministic, so the user could
// briefly see an "old row count" right after a delete. Single-flight guard:
// abort old request, queue at most one trailing reload.
let _loadListCtl: AbortController | null = null;
let _loadListPending = false;

export const useBotStore = create<BotStoreShape>((set, get) => ({
  bots: [],
  draft: null,
  draftIsNew: false,
  dirty: false,
  loading: false,
  saving: false,
  toggling: false,
  error: null,
  _openController: null,

  loadList: async () => {
    if (_loadListCtl) {
      _loadListCtl.abort();
      _loadListPending = true;
    }
    const ctl = new AbortController();
    _loadListCtl = ctl;
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<{ records: BotMeta[] }>("/api/bots", {
        signal: ctl.signal,
      });
      if (ctl.signal.aborted) return;
      set({ bots: body.records, loading: false });
    } catch (e) {
      if (ctl.signal.aborted) return;
      if (e instanceof Error && e.name === "AbortError") return;
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      if (_loadListCtl === ctl) _loadListCtl = null;
      if (_loadListPending && _loadListCtl == null) {
        _loadListPending = false;
        void get().loadList();
      }
    }
  },

  openNew: () => set({
    draft: { ..._BLANK_BOT(), mode: "shadow", enabled: false, signal_log: [], last_processed_event: null },
    draftIsNew: true, dirty: false,
  }),

  openExisting: async (id) => {
    // H-UI-11 — abort prior request so the last-response-wins race
    // between rapid sidebar clicks cannot show stale draft.
    const prev = get()._openController;
    if (prev) {
      try { prev.abort(); } catch { /* noop */ }
    }
    const controller = new AbortController();
    set({ loading: true, error: null, _openController: controller });
    try {
      const rec = await sidecarFetch<BotRecord>(
        `/api/bots/${id}`,
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      set({
        draft: rec,
        draftIsNew: false,
        dirty: false,
        loading: false,
        _openController: null,
      });
    } catch (e) {
      if (controller.signal.aborted) return;
      set({
        loading: false,
        error: e instanceof Error ? e.message : String(e),
        _openController: null,
      });
    }
  },

  setDraftField: (k, v) => {
    const cur = get().draft;
    if (!cur) return;
    set({ draft: { ...cur, [k]: v }, dirty: true });
  },

  save: async (confirmLabel?: string) => {
    const cur = get().draft;
    if (!cur) return null;
    // B-C4 — concurrent-save guard. Rapid double-click → second call no-ops.
    if (get().saving) return null;
    set({ saving: true, loading: true, error: null });
    try {
      if (get().draftIsNew || !cur.id) {
        // H-14 — strip runtime-state fields the backend manages.
        const { signal_log: _sl, last_processed_event: _lpe, ...payload } =
          cur as Partial<BotRecord>;
        void _sl; void _lpe;
        const saved = await sidecarFetch<BotRecord>("/api/bots", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        set({ draft: saved, draftIsNew: false, dirty: false, saving: false, loading: false });
        await get().loadList();
        return saved;
      } else {
        // H-14 — strip signal_log + last_processed_event from PUT body so the
        // runner-owned state isn't clobbered by a stale UI snapshot.
        const { signal_log: _sl, last_processed_event: _lpe, ...payload } =
          cur as Partial<BotRecord>;
        void _sl; void _lpe;
        // B-C3 — shadow→live mode change requires confirm_account_label per
        // backend live-gate. Caller passes the user-typed label.
        const body: Record<string, unknown> = { ...payload };
        if (confirmLabel !== undefined) {
          body.confirm_account_label = confirmLabel;
        }
        const saved = await sidecarFetch<BotRecord>(`/api/bots/${cur.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        set({ draft: saved, dirty: false, saving: false, loading: false });
        await get().loadList();
        return saved;
      }
    } catch (e) {
      set({ saving: false, loading: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },

  remove: async (id) => {
    // H-2 + H-3 — clear stale error AND surface loading state so the UI
    // can disable the Sil button mid-flight.
    set({ loading: true, error: null });
    try {
      await sidecarFetch(`/api/bots/${id}`, { method: "DELETE" });
      const draft = get().draft;
      if (draft && draft.id === id) {
        set({ draft: null, draftIsNew: false, dirty: false });
      }
      await get().loadList();
      set({ loading: false });
      return true;
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
      return false;
    }
  },

  enable: async (id, confirmLabel) => {
    // H-UI-2 — surface in-flight state so the BOT.tsx button disables and
    // rapid double-clicks cannot multi-POST.
    if (get().toggling) return null;
    set({ toggling: true, error: null });
    try {
      const rec = await sidecarFetch<BotRecord>(`/api/bots/${id}/enable`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(confirmLabel !== undefined ? { confirm_account_label: confirmLabel } : {}),
      });
      const draft = get().draft;
      if (draft && draft.id === id) set({ draft: rec });
      await get().loadList();
      set({ toggling: false });
      return rec;
    } catch (e) {
      set({ toggling: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },

  disable: async (id) => {
    if (get().toggling) return null;
    set({ toggling: true, error: null });
    try {
      const rec = await sidecarFetch<BotRecord>(`/api/bots/${id}/disable`, { method: "POST" });
      const draft = get().draft;
      if (draft && draft.id === id) set({ draft: rec });
      await get().loadList();
      set({ toggling: false });
      return rec;
    } catch (e) {
      set({ toggling: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },
}));
