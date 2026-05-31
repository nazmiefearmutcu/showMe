/**
 * Sub-system E UI store: list strategies, edit/save/preview.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface IndicatorRef {
  alias: string;
  id: string;
  params: Record<string, unknown>;
}

export interface Rule {
  kind: "crosses_above" | "crosses_below" | "greater_than" | "less_than" | "equals_approximately";
  left: string;
  right: string;
  tolerance?: number | null;
}

export interface Position {
  side: "long" | "short";
  sizing_kind: "fixed_quote" | "fixed_base" | "risk_pct";
  sizing_value: number;
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
}

export interface AssetFilter {
  exchanges?: string[] | null;
  symbols?: string[] | null;
  asset_classes?: string[] | null;
}

export interface StrategySpec {
  id: string;
  name: string;
  description: string;
  version: number;
  asset_filter: AssetFilter;
  timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
  indicators: IndicatorRef[];
  entry_rules: Rule[];
  entry_logic: "all" | "any";
  exit_rules: Rule[];
  exit_logic: "all" | "any";
  position: Position;
  created_at: string;
  updated_at: string;
}

export interface StrategyMeta {
  id: string;
  name: string;
  description: string;
  timeframe: string;
  created_at: string;
  updated_at: string;
}

export interface PreviewEvent {
  bar_index: number;
  bar_time: string;
  kind: "entry" | "exit";
  price: number;
  details: Record<string, unknown>;
}

export interface PreviewResult {
  strategy_id: string;
  symbol: string;
  timeframe: string;
  bars: number;
  events: PreviewEvent[];
  source: string;
}

const _BLANK_SPEC = (): Omit<StrategySpec, "id" | "created_at" | "updated_at"> => ({
  name: "",
  description: "",
  version: 1,
  asset_filter: {},
  timeframe: "1h",
  indicators: [],
  entry_rules: [],
  entry_logic: "all",
  exit_rules: [],
  exit_logic: "any",
  position: { side: "long", sizing_kind: "fixed_quote", sizing_value: 100 },
});

/** Shape returned by GET /api/strategies/{id}/dependents (Agent 2). */
export interface StrategyDependents {
  bot_count: number;
  bot_ids: string[];
}

interface StrategyStoreShape {
  strategies: StrategyMeta[];
  draft: Partial<StrategySpec> | null;
  draftIsNew: boolean;
  dirty: boolean;
  loading: boolean;
  /** H-UI-2 + LOW asimetri — flip during delete so UI can disable Sil. */
  removing: boolean;
  /**
   * Round 24 CRITICAL — flip during POST/PUT so the UI can disable Kaydet AND
   * the store can early-exit a concurrent `save()` call. Without this guard a
   * native double-click on Kaydet produced two POST /api/strategies → two
   * strategy rows with the same name + skewed timestamps.
   */
  saving: boolean;
  /** Round 24 — flip during POST /preview so STRA can disable Preview button. */
  previewing: boolean;
  error: string | null;
  lastPreview: PreviewResult | null;
  /** Track AbortController for the in-flight openExisting (H-UI-11). */
  _openController?: AbortController | null;

  loadList: () => Promise<void>;
  openNew: () => void;
  openExisting: (id: string) => Promise<void>;
  setDraftField: <K extends keyof StrategySpec>(k: K, v: StrategySpec[K]) => void;
  save: () => Promise<StrategySpec | null>;
  remove: (id: string, opts?: { force?: boolean; skipConfirm?: boolean }) => Promise<boolean>;
  preview: (id: string) => Promise<PreviewResult | null>;
}

export const useStrategyStore = create<StrategyStoreShape>((set, get) => ({
  strategies: [],
  draft: null,
  draftIsNew: false,
  dirty: false,
  loading: false,
  removing: false,
  saving: false,
  previewing: false,
  error: null,
  lastPreview: null,
  _openController: null,

  loadList: async () => {
    set({ loading: true, error: null });
    try {
      const body = await sidecarFetch<{ records: StrategyMeta[] }>("/api/strategies");
      set({ strategies: body.records, loading: false });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  },

  openNew: () => set({ draft: _BLANK_SPEC(), draftIsNew: true, dirty: false, lastPreview: null }),

  openExisting: async (id) => {
    // H-UI-11 — abort any prior in-flight request so we don't get a
    // last-response-wins race when the user rapidly clicks between
    // strategies in the left rail.
    const prev = get()._openController;
    if (prev) {
      try { prev.abort(); } catch { /* noop */ }
    }
    const controller = new AbortController();
    set({ loading: true, error: null, _openController: controller });
    try {
      const spec = await sidecarFetch<StrategySpec>(
        `/api/strategies/${id}`,
        { signal: controller.signal },
      );
      // Only commit if THIS request was not aborted by a successor.
      if (controller.signal.aborted) return;
      set({
        draft: spec,
        draftIsNew: false,
        dirty: false,
        loading: false,
        lastPreview: null,
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

  save: async () => {
    // Round 24 CRITICAL — concurrent-save guard. Native double-click on
    // Kaydet used to fire two POST /api/strategies before the button's
    // `disabled={saving}` re-rendered, producing duplicate strategy rows.
    // The early-exit here is the only line that's race-free; the UI
    // disable is decorative.
    if (get().saving) return null;
    const cur = get().draft;
    if (!cur) return null;
    set({ saving: true, loading: true, error: null });
    try {
      if (get().draftIsNew || !cur.id) {
        const saved = await sidecarFetch<StrategySpec>("/api/strategies", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cur),
        });
        set({ draft: saved, draftIsNew: false, dirty: false, loading: false, saving: false });
        await get().loadList();
        return saved;
      } else {
        const saved = await sidecarFetch<StrategySpec>(`/api/strategies/${cur.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cur),
        });
        set({ draft: saved, dirty: false, loading: false, saving: false });
        await get().loadList();
        return saved;
      }
    } catch (e) {
      set({ loading: false, saving: false, error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },

  remove: async (id, opts) => {
    const { force = false, skipConfirm = false } = opts ?? {};
    // Round 24 HIGH — already-removing guard. The 2nd rapid Sil click would
    // otherwise queue another window.confirm + DELETE pair.
    if (get().removing) return false;
    // C9 cascade delete — query Agent 2's dependents endpoint first; if it
    // is not yet deployed, fall back to the legacy single-DELETE path
    // (still safer than the old silent behavior because the user has
    // already confirmed the destructive intent at the pane level).
    set({ removing: true, error: null });
    let deps: StrategyDependents = { bot_count: 0, bot_ids: [] };
    try {
      deps = await sidecarFetch<StrategyDependents>(
        `/api/strategies/${id}/dependents`,
      );
    } catch {
      // Endpoint not yet deployed — proceed with legacy DELETE.
    }
    if (!skipConfirm && deps.bot_count > 0) {
      const ok = window.confirm(
        `Bu stratejiye ${deps.bot_count} bot bağlı. ` +
        `Bot'lar otomatik devre dışı bırakılacak. Devam mı?`,
      );
      if (!ok) {
        set({ removing: false });
        return false;
      }
    }
    const effectiveForce = force || deps.bot_count > 0;
    const url = effectiveForce
      ? `/api/strategies/${id}?force=true`
      : `/api/strategies/${id}`;
    try {
      await sidecarFetch(url, { method: "DELETE" });
      const draft = get().draft;
      if (draft && draft.id === id) {
        set({ draft: null, draftIsNew: false, dirty: false });
      }
      await get().loadList();
      set({ removing: false });
      return true;
    } catch (e) {
      set({
        removing: false,
        error: e instanceof Error ? e.message : String(e),
      });
      return false;
    }
  },

  preview: async (id) => {
    // Round 24 HIGH — preview is an expensive backend call (full bar
    // history + indicator compute). A double-click cost two engine runs
    // and made the UI spinner stick. Early-exit when one is already
    // running; the second click is idempotent.
    if (get().previewing) return null;
    set({ previewing: true });
    try {
      const result = await sidecarFetch<PreviewResult>(
        `/api/strategies/${id}/preview`, { method: "POST" },
      );
      set({ lastPreview: result, previewing: false });
      return result;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e), previewing: false });
      return null;
    }
  },
}));
