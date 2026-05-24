import { useEffect, useState } from "react";
import { Titlebar } from "./shell/Titlebar";
import { Sidebar } from "./shell/Sidebar";
import { Statusbar } from "./shell/Statusbar";
import { Workspace } from "./shell/Workspace";
import { CommandPalette } from "./command-palette/Palette";
import { ToastHost } from "./shell/ToastHost";
import { ShortcutsHelp } from "./shell/ShortcutsHelp";
import { IntroSplash } from "./shell/IntroSplash";
import { ThemeTransitionOverlay } from "./shell/ThemeTransitionOverlay";
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
import { refreshAutoTimezone } from "./lib/timezone";
import { setLocale, locale } from "./i18n";
import { useRoute, navigate, parseRoute, type Route } from "./lib/router";
import { toast } from "./lib/toast";
import { useWorkspace } from "./lib/workspace";
import { normalizeSymbolInput } from "./lib/symbols";
import { mergeNativeFunctionIndex } from "./functions/registry";
import { STATIC_FUNCTION_INDEX } from "./functions/static-index";
import { restoreWorkspace, startWorkspaceAutosave } from "./lib/workspace-persist";
import { recordRecentCode } from "./lib/palette-recents";

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

// HIGH #6 (UI-Shell-Bundle UB) cmd+K race — replace the 50 ms timestamp
// window with a structural lock keyed on the *post-toggle* paletteOpen
// value. Tauri menu accelerator can still emit `palette:toggle` 100 ms
// after the keyboard shortcut on a slow machine; the old window quietly
// double-flipped the palette closed in that case. The new lock:
//
//   1. Keyboard handler reads the post-toggle paletteOpen and stamps
//      `expectedNext` plus a generation id.
//   2. The `palette:toggle` Tauri listener checks: if the current store
//      value already matches `expectedNext` AND we haven't bumped the
//      generation past the one we recorded, swallow the event.
//   3. Any genuine subsequent press bumps the generation, so the
//      structural lock self-clears without a wall-clock window.
let paletteSyncGen = 0;
let paletteExpectedAfterShortcut: boolean | null = null;
let paletteShortcutGen = 0;

function recordPaletteShortcutFire(nextOpen: boolean): void {
  paletteSyncGen += 1;
  paletteShortcutGen = paletteSyncGen;
  paletteExpectedAfterShortcut = nextOpen;
}

function shouldSuppressPaletteEvent(currentOpen: boolean): boolean {
  if (paletteExpectedAfterShortcut === null) return false;
  if (paletteSyncGen !== paletteShortcutGen) return false;
  if (currentOpen !== paletteExpectedAfterShortcut) return false;
  // Consume the lock on a successful suppression so a genuine re-press
  // immediately after isn't accidentally eaten.
  paletteExpectedAfterShortcut = null;
  return true;
}

// HIGH #5 (UI-Shell-Bundle UB) — single source of truth for "the user is
// typing in an editable surface". `cmd+W` / `cmd+B` / `cmd+K` used to
// fire even when the focus was inside an `<input>` inside the palette,
// a strategy editor textbox, or a contenteditable rich-text island
// (XSEN search, BDA prompt). Reaches the activeElement first because
// `e.target` may be the wrapping form, not the editable child.
//
// Exported for regression testing — see App.shortcuts-input-guard.test.tsx.
export function isEditableTarget(e: KeyboardEvent): boolean {
  const candidates: (Element | null | undefined)[] = [
    e.target as Element | null,
    typeof document !== "undefined" ? document.activeElement : null,
  ];
  for (const node of candidates) {
    if (!node || !(node instanceof Element)) continue;
    if (node.closest('input,textarea,select,[contenteditable="true"],[contenteditable=""]')) {
      return true;
    }
  }
  return false;
}

async function refreshHealth(): Promise<boolean> {
  try {
    const h = await fetchHealth();
    const root = h.engine?.engine_root ?? null;
    useAppStore.getState().setEngineRoot(root);
    useAppStore.getState().setSidecarStatus(h.ok ? "healthy" : "crashed");
    return h.ok;
  } catch {
    const state = useAppStore.getState();
    if (state.sidecarPort && state.functionIndex.length > 0) {
      state.setSidecarStatus("crashed");
      return true;
    }
    state.setSidecarStatus(state.sidecarPort ? "crashed" : "booting");
    return false;
  }
}

function routeToTarget(route: Route): { code: string; symbol?: string } | null {
  switch (route.kind) {
    case "welcome":
      // S10 dashboard-restore: HOME is safely native (`Workspace.tsx`
      // renders `<Welcome />` for HOME — never the design-export
      // cockpit), so the welcome route can once again focus a HOME
      // leaf. This is the dashboard surface the user expects at `#/`.
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

// HIGH #7 (UI-Shell-Bundle UB) — `recordRecentCode` dedupe.
//
// ReactStrictMode double-invokes effects in dev so the same hashchange
// fires `recordRecentCode("DES")` twice within ~1 ms. The palette stack
// would then count DES twice and push something genuinely older off the
// end. Guard with a (timestamp, code) tuple — anything within 100 ms of
// the previous fire for the same code is treated as the dev double-tap
// and dropped.
let lastRecordedCode: string | null = null;
let lastRecordedAt = 0;

function recordRouteRecentCode(code: string): void {
  const now = Date.now();
  if (lastRecordedCode === code && now - lastRecordedAt < 100) return;
  lastRecordedCode = code;
  lastRecordedAt = now;
  recordRecentCode(code);
}

function RouteSync() {
  const route = useRoute();
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  useEffect(() => {
    const target = routeToTarget(route);
    if (target) {
      setFocusedTarget(target.code, target.symbol);
      // QA-2026-05-23: record every navigated function code so the
      // sidebar "Recent" group reflects the user's real history.
      // HIGH #7: dedupe via timestamp guard above so React's
      // double-invoke in StrictMode doesn't fake-pad the stack.
      if (target.code && target.code !== "HOME" && target.code !== "PREF") {
        recordRouteRecentCode(target.code);
      }
    }
  }, [route, setFocusedTarget]);
  if (route.kind === "not-found") {
    return (
      <div className="welcome-route-empty">
        <Empty
          title="Route not found"
          body={
            <span>
              <code>#/{route.raw}</code> doesn't match any registered surface.
            </span>
          }
          action={
            <button type="button" onClick={() => navigate("/")}>
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
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [backendIndexReady, setBackendIndexReady] = useState(false);
  const [introDone, setIntroDone] = useState(false);
  const sidecarStatus = useAppStore((s) => s.sidecarStatus);
  const functionCount = useAppStore((s) => s.functionIndex.length);
  const splitFocused = useWorkspace((s) => s.splitFocused);
  const closeFocused = useWorkspace((s) => s.closeFocused);

  // Boot-time invariants: theme + locale before first paint.
  useEffect(() => {
    applyAppearancePrefs();
    setLocale(locale());
    // When the user has timezone in auto-mode, re-poll the OS each time the
    // app re-gains focus. Handles the "laptop crossed a timezone border
    // and woke from sleep" case without forcing a manual restart.
    refreshAutoTimezone();
    const onVisible = () => {
      if (document.visibilityState === "visible") refreshAutoTimezone();
    };
    window.addEventListener("focus", refreshAutoTimezone);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", refreshAutoTimezone);
      document.removeEventListener("visibilitychange", onVisible);
    };
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
      setWorkspaceReady(true);
    });
    return () => dispose?.();
  }, []);

  // Keyboard shortcuts (single source of truth — QA-2026-05-23):
  //   ⌘K        open command palette  (was racing with Palette.tsx's own
  //                                    keydown + Tauri menu accel → fixed)
  //   ⌘B        toggle sidebar
  //   ⌘J        open AGENT pane
  //   ⌘\        split horizontal
  //   ⌘⇧\       split vertical
  //   ⌘W        close pane
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      // HIGH #5: never intercept these shortcuts while the user is
      // typing into a text input / textarea / contenteditable. cmd+W in
      // an OrderTicket textbox previously closed the user's pane mid-
      // edit; cmd+B inside the strategy editor toggled the sidebar
      // away from the workspace they were watching.
      if (isEditableTarget(e)) return;
      const key = e.key.toLowerCase();
      if (e.key === "\\") {
        e.preventDefault();
        splitFocused(e.shiftKey ? "v" : "h");
      } else if (key === "b") {
        e.preventDefault();
        useAppStore.getState().toggleSidebar();
      } else if (key === "k") {
        // HIGH #6: structural lock keyed on the post-toggle paletteOpen
        // value (see `recordPaletteShortcutFire` above). Removes the
        // 50 ms timing window that intermittently double-flipped the
        // palette on slow machines.
        e.preventDefault();
        const willOpen = !useAppStore.getState().paletteOpen;
        recordPaletteShortcutFire(willOpen);
        togglePalette();
      } else if (key === "j") {
        e.preventDefault();
        navigate("/fn/AGENT");
      } else if (key === "w") {
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
  }, [splitFocused, closeFocused, togglePalette]);

  useEffect(() => {
    let unmount = false;
    const unsubscribe: Array<() => void> = [];
    const markBackendReadyIfLoaded = () => {
      if (unmount) return;
      const state = useAppStore.getState();
      if (
        state.sidecarStatus === "healthy" &&
        state.engineRoot &&
        state.functionIndex.length > BACKEND_INDEX_READY_THRESHOLD
      ) {
        setBackendIndexReady(true);
      }
    };

    const boot = async () => {
      setBackendIndexReady(false);
      useAppStore.getState().setFunctionIndex(staticFunctionIndex());
      await bootstrapSidecarPort();
      if (unmount) return;
      await refreshHealth();
      await refreshFunctionIndex();
      if (unmount) return;
      markBackendReadyIfLoaded();

      const offPort = onSidecarPort(() => {
        refreshHealth()
          .then(() => refreshFunctionIndex())
          .then(markBackendReadyIfLoaded);
      });
      unsubscribe.push(offPort);

      const warmupRetry = window.setInterval(() => {
        const state = useAppStore.getState();
        if (
          state.functionIndex.length > BACKEND_INDEX_READY_THRESHOLD &&
          state.engineRoot
        ) {
          window.clearInterval(warmupRetry);
          return;
        }
        if (state.sidecarPort) {
          refreshHealth()
            .then(() => refreshFunctionIndex())
            .then(markBackendReadyIfLoaded);
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
          if (status === "healthy") {
            refreshHealth()
              .then(() => refreshFunctionIndex())
              .then(markBackendReadyIfLoaded);
          }
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

      const offPalette = await listen("palette:toggle", () => {
        // HIGH #6: the keyboard handler may have just fired the toggle
        // and recorded the post-toggle expected value. If the Tauri
        // menu accelerator follows up in the same logical action,
        // swallow it so the palette doesn't bounce closed.
        const isOpen = useAppStore.getState().paletteOpen;
        if (shouldSuppressPaletteEvent(isOpen)) return;
        togglePalette();
      });
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

  const shellFallbackReady =
    functionCount > BACKEND_INDEX_READY_THRESHOLD &&
    (sidecarStatus === "crashed" ||
      sidecarStatus === "stopped" ||
      sidecarStatus === "stub");
  const dashboardReady = workspaceReady && (backendIndexReady || shellFallbackReady);

  return (
    <>
      <div className="app-shell" aria-hidden={!introDone}>
        <Titlebar />
        <div className={`workspace ${sidebarVisible ? "" : "workspace--sidebar-hidden"}`}>
          <Sidebar />
          {/* A11Y landmark: wrap the routed surface in a <main> so screen
              readers can jump straight to it. Preferences/Welcome/AGENT
              already paint their own inner <main>; that's fine — the
              outer landmark just ensures *something* exists for the route
              the user lands on. */}
          <main id="main" className="workspace__main">
            <RouteSync />
          </main>
        </div>
        <Statusbar />
        <CommandPalette />
        <ShortcutsHelp />
        <ToastHost />
      </div>
      {!introDone ? (
        <IntroSplash ready={dashboardReady} onDone={() => setIntroDone(true)} />
      ) : null}
      <ThemeTransitionOverlay />
    </>
  );
}
