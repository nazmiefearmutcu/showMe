import { useEffect, useState } from "react";
import { useAppStore } from "@/lib/store";
import { invoke } from "@/lib/tauri";
import { navigate, useRoute } from "@/lib/router";
import {
  PRESET_LABELS,
  THEME_CHANGE_EVENT,
  readState,
  toggleTheme as toggleThemeLib,
  type ThemeState,
} from "@/lib/theme";
import { useWorkspace } from "@/lib/workspace";
import { loadBuiltinPreset } from "@/lib/builtinPresets";
import { OrbitMark, Pill, TopbarSegment } from "@/design-system";
import { t } from "@/i18n";
import { PresetMenu } from "./PresetMenu";
import { toast } from "@/lib/toast";

/**
 * QA-2026-05-23: top-nav links are no longer visual decoration. Each
 * dispatches a real navigation so the user gets the surface the label
 * promises.
 *   • Overview  → welcome dashboard (`/`)
 *   • Watchlist → WATCH pane
 *   • Portfolio → PORT pane
 *   • AAPL      → DES pane scoped to AAPL (preserves symbol-bound route)
 *   • Markets   → Markets Overview preset (DES + GP + WEI + TOP grid)
 *   • News      → TOP news pane
 *   • Functions → open the command palette
 *
 * `kind` discriminates between simple route nav, preset load, and palette
 * open so we can attach `aria-current="page"` only when relevant.
 */
type MarketNavKind = "route" | "preset" | "palette";
interface MarketNavLink {
  label: string;
  kind: MarketNavKind;
  /** Hash route (kind === "route"). */
  path?: string;
  /** Built-in preset id (kind === "preset"). */
  preset?: string;
  /** Codes that should highlight this nav as active. */
  activeCodes?: string[];
  /** Path prefix to match for "route" kind active state. */
  activePath?: string;
}
const MARKET_NAV: MarketNavLink[] = [
  { label: "Overview", kind: "route", path: "/", activePath: "/" },
  {
    label: "Watchlist",
    kind: "route",
    path: "/fn/WATCH",
    activeCodes: ["WATCH"],
  },
  {
    label: "Portfolio",
    kind: "route",
    path: "/fn/PORT",
    activeCodes: ["PORT"],
  },
  {
    label: "AAPL",
    kind: "route",
    path: "/symbol/AAPL/DES",
    activePath: "/symbol/AAPL/DES",
  },
  {
    label: "Markets",
    kind: "preset",
    preset: "markets-overview",
    activeCodes: ["MAP", "WEI"],
  },
  { label: "News", kind: "route", path: "/fn/NI", activeCodes: ["NI", "TOP", "CN"] },
  { label: "Functions", kind: "palette" },
];

const QUICK_CODES = ["OMON", "GEX", "FA", "BTMM"];

function isMarketNavActive(
  item: MarketNavLink,
  route: ReturnType<typeof useRoute>,
  activeCode: string,
): boolean {
  if (item.activeCodes && item.activeCodes.includes(activeCode.toUpperCase())) {
    return true;
  }
  if (item.activePath) {
    if (item.activePath === "/" && route.kind === "welcome") return true;
    if (
      item.activePath.startsWith("/symbol/") &&
      route.kind === "function" &&
      route.symbol &&
      `/symbol/${route.symbol}/${route.code}` === item.activePath
    ) {
      return true;
    }
  }
  return false;
}

export function Titlebar() {
  const status = useAppStore((s) => s.sidecarStatus);
  const port = useAppStore((s) => s.sidecarPort);
  // UI-INT-02 (extras): pull live count from store; backend may pass through
  // a `health.function_count` field but we already mirror that into
  // `functionIndex.length` via App.refreshFunctionIndex.
  const total = useAppStore((s) => s.functionIndex.length);
  const togglePalette = useAppStore((s) => s.togglePalette);
  const sidebarVisible = useAppStore((s) => s.sidebarVisible);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const splitFocused = useWorkspace((s) => s.splitFocused);
  const closeFocused = useWorkspace((s) => s.closeFocused);
  const tree = useWorkspace((s) => s.tree);
  const isOnlyLeaf = tree.kind === "leaf";
  const route = useRoute();
  const activeCode =
    route.kind === "function" ? route.code : route.kind === "welcome" ? "HOME" : "PREF";
  const [themeState, setThemeState] = useState<ThemeState>(() => readState());

  useEffect(() => {
    // HIGH #14 (UI-Shell-Bundle UB) — three listeners (focus, storage,
    // THEME_CHANGE_EVENT) used to all funnel into `setThemeState` which
    // re-rendered the entire titlebar even when the underlying theme
    // hadn't changed at all (focus-back from another window is the worst
    // offender — it fires on every alt-tab). Dedupe by remembering the
    // last applied (preset, mode) tuple and bailing if it matches.
    let lastKey: string | null = null;
    const syncTheme = () => {
      const next = readState();
      // Theme key combines preset + density + custom hex slots so a
      // genuine in-place edit still re-renders. The focus-back / cross-
      // tab storage events that don't change *any* of these are dropped
      // before reaching `setThemeState`.
      const key = JSON.stringify({
        p: next.preset,
        d: next.density,
        c: next.custom,
      });
      if (key === lastKey) return;
      lastKey = key;
      setThemeState(next);
    };
    syncTheme();
    window.addEventListener(THEME_CHANGE_EVENT, syncTheme);
    window.addEventListener("storage", syncTheme);
    window.addEventListener("focus", syncTheme);
    return () => {
      window.removeEventListener(THEME_CHANGE_EVENT, syncTheme);
      window.removeEventListener("storage", syncTheme);
      window.removeEventListener("focus", syncTheme);
    };
  }, []);

  const flipTheme = () => {
    // UX-09 P2: toggle between the user's last-used dark and light preset
    // instead of clobbering to midnight/papyrus.
    toggleThemeLib();
    setThemeState(readState());
  };

  const newWindow = async () => {
    const label = `w-${Date.now().toString(36)}`;
    try {
      await invoke("open_window", { label, title: "showMe", url: "/" });
    } catch (err) {
      toast.error("New window failed", String(err));
    }
  };

  const tone =
    status === "healthy"
      ? "positive"
      : status === "stub"
        ? "muted"
        : status === "booting"
          ? "warn"
          : "negative";

  return (
    <header className="titlebar" aria-label={t("app.name")}>
      {/* A11Y-05: visually-hidden h1 anchors the document outline. */}
      <h1 className="u-sr-only">showMe — Market Cockpit</h1>
      <TopbarSegment>
        <button
          type="button"
          className="interactive titlebar__home-btn"
          onClick={() => navigate("/")}
          title={t("app.name")}
          aria-label={`${t("app.name")} home`}
        >
          <OrbitMark size={18} />
          <strong className="titlebar__home-strong">{t("app.name")}</strong>
        </button>
      </TopbarSegment>

      <TopbarSegment caption="ShowMe 0.01" withDivider>
        <nav className="interactive titlebar__market-nav" aria-label="Market workspaces">
          {MARKET_NAV.map((item) => {
            const isActive = isMarketNavActive(item, route, activeCode);
            const handleClick = () => {
              switch (item.kind) {
                case "route":
                  if (item.path) navigate(item.path);
                  break;
                case "preset":
                  if (item.preset && !loadBuiltinPreset(item.preset)) {
                    toast.error(`Preset '${item.preset}' not available`);
                  }
                  break;
                case "palette":
                  togglePalette(true);
                  break;
              }
            };
            return (
              <button
                key={item.label}
                type="button"
                className={`titlebar__market-nav-btn${isActive ? " titlebar__market-nav-btn--active" : ""}`}
                aria-current={isActive ? "page" : undefined}
                onClick={handleClick}
              >
                {item.label}
              </button>
            );
          })}
        </nav>
      </TopbarSegment>

      <TopbarSegment withDivider>
        <button
          type="button"
          className="interactive titlebar__command-strip"
          onClick={() => togglePalette()}
          title="Command palette"
          aria-label="Open command palette"
        >
          <span className="titlebar__ticker-chip">AAPL</span>
          <strong>US Equity</strong>
          <span>Type a function - OMON - GEX - DES - MENU - / to focus</span>
        </button>
        <div className="interactive titlebar__quick-actions" aria-label="Quick functions">
          {QUICK_CODES.map((code) => (
            <button
              key={code}
              type="button"
              className="titlebar__quick-action"
              onClick={() => navigate(`/fn/${code}`)}
            >
              {code}
            </button>
          ))}
        </div>
      </TopbarSegment>

      <TopbarSegment caption="cockpit" withDivider>
        <div className="interactive titlebar__btn-group">
          <button
            type="button"
            className={`btn btn--ghost ${sidebarVisible ? "titlebar__home-btn--accent-sidebar" : ""}`}
            title="Toggle functions panel (⌘B)"
            aria-label={t("shell.sidebar.toggle")}
            aria-pressed={sidebarVisible}
            onClick={() => toggleSidebar()}
          >
            Fn
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            title="Split right (⌘\\)"
            aria-label={t("shell.titlebar.split_right")}
            onClick={() => splitFocused("h")}
          >
            Split R
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            title="Split below (⌘⇧\\)"
            aria-label={t("shell.titlebar.split_bottom")}
            onClick={() => splitFocused("v")}
          >
            Split B
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            title={
              isOnlyLeaf
                ? "Close pane (only leaf — disabled)"
                : t("shell.titlebar.close_pane_hint")
            }
            aria-label={t("shell.titlebar.close_pane")}
            aria-disabled={isOnlyLeaf}
            disabled={isOnlyLeaf}
            onClick={() => {
              if (isOnlyLeaf) return;
              closeFocused();
            }}
          >
            {t("shell.titlebar.close_pane")}
          </button>
        </div>
      </TopbarSegment>

      <div className="interactive titlebar__filler" />

      <TopbarSegment>
        <button
          type="button"
          className="btn btn--ghost interactive titlebar__palette-btn"
          onClick={() => togglePalette()}
          title="Command palette"
          aria-label="Open command palette"
        >
          <span className="kbd">⌘K</span>
        </button>
        <PresetMenu />
      </TopbarSegment>

      <TopbarSegment withDivider>
        <Pill tone={tone} variant="soft">
          {status}
        </Pill>
        {port && (
          <span className="titlebar__pill-row-extra" aria-label={`sidecar port ${port}`}>
            :{port}
          </span>
        )}
        {total > 0 && (
          <span
            className="titlebar__pill-row-extra--tracking"
            aria-label={`${total} functions registered`}
          >
            {total} FN
          </span>
        )}
        {/* UI-INT-06 P2: MK pill now has a tooltip + aria-label so users
            (and screen readers) know it tracks the market session. */}
        <span
          aria-label={t("shell.titlebar.market_pill_hint")}
          title={t("shell.titlebar.market_pill_hint")}
          className="titlebar__market-pill"
        >
          {t("shell.titlebar.market_pill")}
        </span>
      </TopbarSegment>

      <TopbarSegment withDivider>
        <button
          type="button"
          className="btn btn--ghost interactive"
          onClick={newWindow}
          title={t("shell.titlebar.new_window")}
          aria-label={t("shell.titlebar.new_window")}
        >
          New
        </button>
        <button
          type="button"
          className="btn btn--ghost interactive"
          onClick={flipTheme}
          title={`${t("shell.theme.toggle")} (${PRESET_LABELS[themeState.preset]})`}
          aria-label={`${t("shell.theme.toggle")} (currently ${PRESET_LABELS[themeState.preset]})`}
        >
          {PRESET_LABELS[themeState.preset]}
        </button>
        <button
          type="button"
          className="btn btn--ghost interactive"
          onClick={() => navigate("/preferences")}
          title={t("shell.preferences")}
          aria-label={t("shell.preferences")}
        >
          Prefs
        </button>
        <button
          type="button"
          className="btn btn--ghost interactive"
          onClick={() => invoke("open_data_folder")}
          title="Reveal data folder"
          aria-label="Reveal data folder"
        >
          Data
        </button>
      </TopbarSegment>
    </header>
  );
}
