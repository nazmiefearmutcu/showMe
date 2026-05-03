import { useEffect } from "react";
import { Titlebar } from "./shell/Titlebar";
import { Sidebar } from "./shell/Sidebar";
import { Statusbar } from "./shell/Statusbar";
import { Workspace } from "./shell/Workspace";
import { CommandPalette } from "./command-palette/Palette";
import { ToastHost } from "./shell/ToastHost";
import { Empty } from "./design-system";
import { useAppStore } from "./lib/store";
import {
  bootstrapSidecarPort,
  fetchHealth,
  fetchFunctionIndex,
  onSidecarPort,
} from "./lib/sidecar";
import { listen } from "./lib/tauri";
import { applyAppearancePrefs } from "./lib/theme";
import { setLocale, locale } from "./i18n";
import { useRoute, navigate, parseRoute, type Route } from "./lib/router";
import { toast } from "./lib/toast";
import { useWorkspace } from "./lib/workspace";
import { normalizeSymbolInput } from "./lib/symbols";
import { mergeNativeFunctionIndex } from "./functions/registry";
import { STATIC_FUNCTION_INDEX } from "./functions/static-index";
import { restoreWorkspace, startWorkspaceAutosave } from "./lib/workspace-persist";

function staticFunctionIndex() {
  return mergeNativeFunctionIndex(STATIC_FUNCTION_INDEX);
}

async function refreshFunctionIndex() {
  try {
    const idx = await fetchFunctionIndex();
    useAppStore.getState().setFunctionIndex(mergeNativeFunctionIndex(idx));
  } catch (err) {
    console.warn("function-index fetch failed", err);
    useAppStore.getState().setFunctionIndex(staticFunctionIndex());
  }
}

const BACKEND_INDEX_READY_THRESHOLD = 20;

async function refreshHealth(): Promise<boolean> {
  try {
    const h = await fetchHealth();
    const root = h.engine?.engine_root ?? null;
    useAppStore.getState().setEngineRoot(root);
    useAppStore.getState().setSidecarStatus(h.ok ? "healthy" : "crashed");
    return h.ok;
  } catch {
    const state = useAppStore.getState();
    if (state.sidecarPort && state.functionIndex.length > 0) return true;
    state.setSidecarStatus(state.sidecarPort ? "crashed" : "booting");
    return false;
  }
}

function routeToTarget(route: Route): { code: string; symbol?: string } | null {
  switch (route.kind) {
    case "welcome":
      return { code: "HOME" };
    case "preferences":
    case "settings":
      return { code: "PREF" };
    case "function":
      return {
        code: route.code,
        symbol: normalizeSymbolInput(route.symbol) || undefined,
      };
    case "not-found":
      return null;
  }
}

function RouteSync() {
  const route = useRoute();
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  useEffect(() => {
    const target = routeToTarget(route);
    if (target) setFocusedTarget(target.code, target.symbol);
  }, [route, setFocusedTarget]);
  if (route.kind === "not-found") {
    return (
      <div style={{ padding: 32 }}>
        <Empty
          title="Route not found"
          body={
            <span>
              <code>#/{route.raw}</code> doesn't match any registered surface.
            </span>
          }
          action={
            <button
              type="button"
              onClick={() => navigate("/")}
              style={{
                background: "var(--bg-elev-2)",
                color: "var(--text-primary)",
                border: "1px solid var(--border-strong)",
                borderRadius: "var(--radius-md)",
                padding: "6px 12px",
                fontSize: 11,
                cursor: "default",
              }}
            >
              Back to welcome
            </button>
          }
        />
      </div>
    );
  }
  return <Workspace />;
}

export default function App() {
  const togglePalette = useAppStore((s) => s.togglePalette);
  const sidebarVisible = useAppStore((s) => s.sidebarVisible);
  const splitFocused = useWorkspace((s) => s.splitFocused);
  const closeFocused = useWorkspace((s) => s.closeFocused);

  // Boot-time invariants: theme + locale before first paint.
  useEffect(() => {
    applyAppearancePrefs();
    setLocale(locale());
  }, []);

  // Workspace tree restore + autosave (per-window, persists across restarts).
  useEffect(() => {
    let dispose: (() => void) | undefined;
    restoreWorkspace().finally(() => {
      const target = routeToTarget(parseRoute(window.location.hash || "#/"));
      if (target) {
        useWorkspace.getState().setFocusedTarget(target.code, target.symbol);
      }
      dispose = startWorkspaceAutosave();
    });
    return () => dispose?.();
  }, []);

  // Keyboard shortcuts: ⌘\ split-h, ⌘⇧\ split-v, ⌘W close pane.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key === "\\") {
        e.preventDefault();
        splitFocused(e.shiftKey ? "v" : "h");
      } else if (e.key.toLowerCase() === "b") {
        e.preventDefault();
        useAppStore.getState().toggleSidebar();
      } else if (e.key.toLowerCase() === "w") {
        // Allow native close-window when no split exists.
        const tree = useWorkspace.getState().tree;
        if (tree.kind !== "leaf") {
          e.preventDefault();
          closeFocused();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [splitFocused, closeFocused]);

  useEffect(() => {
    let unmount = false;
    const unsubscribe: Array<() => void> = [];

    const boot = async () => {
      useAppStore.getState().setFunctionIndex(staticFunctionIndex());
      await bootstrapSidecarPort();
      if (unmount) return;
      await refreshHealth();
      void refreshFunctionIndex();

      const offPort = onSidecarPort(() => {
        refreshHealth();
        refreshFunctionIndex();
      });
      unsubscribe.push(offPort);

      const warmupRetry = window.setInterval(() => {
        const state = useAppStore.getState();
        if (state.functionIndex.length > BACKEND_INDEX_READY_THRESHOLD && state.engineRoot) {
          window.clearInterval(warmupRetry);
          return;
        }
        if (state.sidecarPort) {
          refreshHealth();
          refreshFunctionIndex();
        }
      }, 2_000);
      unsubscribe.push(() => window.clearInterval(warmupRetry));

      const offStatus = await listen<{
        status: "booting" | "healthy" | "crashed" | "stopped";
      }>("sidecar:status", (e) => {
        const status = e.payload?.status;
        if (!status) return;
        if (status === "healthy" || status === "booting") {
          useAppStore.getState().setSidecarStatus(status);
          if (status === "healthy") refreshHealth();
          return;
        }
        refreshHealth().then((ok) => {
          if (!ok && status === "crashed") toast.error("Sidecar crashed", "Restarting…");
        });
      });
      unsubscribe.push(offStatus);

      const offReload = await listen("function-index:reload", () => {
        refreshFunctionIndex();
        toast.info("Function index reloaded");
      });
      unsubscribe.push(offReload);

      const offPalette = await listen("palette:toggle", () => togglePalette());
      unsubscribe.push(offPalette);

      const offNav = await listen<string>("nav:open", (e) => {
        if (typeof e.payload === "string") navigate(e.payload);
      });
      unsubscribe.push(offNav);

      const offFatal = await listen<string>("sidecar:fatal", (e) => {
        toast.error("Sidecar fatal", String(e.payload));
      });
      unsubscribe.push(offFatal);
    };
    boot();

    return () => {
      unmount = true;
      unsubscribe.forEach((u) => u());
    };
  }, [togglePalette]);

  return (
    <div className="app-shell">
      <Titlebar />
      <div className={`workspace ${sidebarVisible ? "" : "workspace--sidebar-hidden"}`}>
        <Sidebar />
        <RouteSync />
      </div>
      <Statusbar />
      <CommandPalette />
      <ToastHost />
    </div>
  );
}
