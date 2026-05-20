import { useEffect, useState } from "react";
import { useAppStore } from "@/lib/store";
import { invoke } from "@/lib/tauri";
import { navigate } from "@/lib/router";
import {
  PRESET_LABELS,
  THEME_CHANGE_EVENT,
  readState,
  toggleTheme as toggleThemeLib,
  type ThemeState,
} from "@/lib/theme";
import { useWorkspace } from "@/lib/workspace";
import { OrbitMark, Pill, TopbarSegment } from "@/design-system";
import { t } from "@/i18n";
import { PresetMenu } from "./PresetMenu";
import { toast } from "@/lib/toast";

const MARKET_NAV = [
  { label: "Overview", path: "/" },
  { label: "Watchlist", path: "/fn/WATCH" },
  { label: "Portfolio", path: "/fn/PORT" },
  { label: "AAPL", path: "/symbol/AAPL/DES" },
  { label: "Markets", path: "/fn/WEI" },
  { label: "News", path: "/fn/NI" },
  { label: "Functions", path: "/fn/SCAN" },
];

const QUICK_CODES = ["OMON", "GEX", "FA", "BTMM"];

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
  const [themeState, setThemeState] = useState<ThemeState>(() => readState());

  useEffect(() => {
    const syncTheme = () => setThemeState(readState());
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
          {MARKET_NAV.map((item) => (
            <button
              key={item.label}
              type="button"
              className="titlebar__market-nav-btn"
              onClick={() => navigate(item.path)}
            >
              {item.label}
            </button>
          ))}
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
          title="New window (⌘N)"
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
