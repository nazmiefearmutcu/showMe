import { useEffect, useMemo, useState } from "react";
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
import { findLeaf, useWorkspace } from "@/lib/workspace";
import { inferAssetClassName, normalizeSymbolInput } from "@/lib/symbols";
import {
  setActiveSecurity,
  useSecurityContext,
  type ActiveSecurity,
} from "@/lib/security-context";
import { describeSessionState, type SessionKind } from "@/lib/market-state";
import { loadBuiltinPreset } from "@/lib/builtinPresets";
import { formatTickAge, TAPE_LABEL, useTapeHealth } from "@/lib/tape-health";
import { OrbitMark, Pill, TopbarSegment } from "@/design-system";
import { CommandLine } from "./CommandLine";
import { t, useLocale } from "@/i18n";
import { PresetMenu } from "./PresetMenu";
import { toast } from "@/lib/toast";
// Mini-tape styles ride a JS import (same pattern as Workspace.tsx →
// workspace-ux.css); styles/index.css is left untouched.
import "@/styles/titlebar-tape.css";

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

/**
 * TitlebarTape — compact tape readout beside the quick-actions group
 * (UI-finish wave F, 2026-09-09). Same honest registry as the Statusbar
 * pill (lib/tape-health.ts): `LIVE · N · <age>` / `RECONNECTING` / `DOWN`,
 * labels + age format single-sourced via TAPE_LABEL / formatTickAge.
 *   - Hidden entirely at zero subscriptions — no tape, no claim.
 *   - Age only while LIVE: tape-health coalesces tick commits to ~1/s so
 *     the figure stays fresh; when nothing is live the commits stop and a
 *     frozen age would silently go stale, so non-live states show the
 *     state word alone.
 *   - Semantic color rides data-tape-state in styles/titlebar-tape.css and
 *     touches only the state word.
 */
function TitlebarTape() {
  const health = useTapeHealth();
  // R3 M-2: unlike the Statusbar there is no 1 Hz heartbeat here, and the
  // tape-health throttle coalesces tick-only commits — so during a silent
  // stall while still "live" (half-open socket) a computed age would freeze
  // at a young value and lie. A 1 Hz re-render while an age is on screen
  // keeps the figure counting up honestly (Statusbar parity).
  const [, setClockTick] = useState(0);
  useEffect(() => {
    if (!(health.state === "live" && health.lastTickAt != null)) return;
    const id = setInterval(() => setClockTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [health.state, health.lastTickAt]);
  if (health.totalSymbols === 0) return null;
  const stateLabel = TAPE_LABEL[health.state];
  // Vocabulary per state: `LIVE · N · <age>` / `RECONNECTING` / `DOWN`.
  // Age only while LIVE — tape-health coalesces tick commits to ~1/s so the
  // figure stays fresh; when nothing is live the commits stop and a frozen
  // age would silently go stale, so other states stay word-only.
  const ageMs =
    health.state === "live" && health.lastTickAt != null
      ? Math.max(0, Date.now() - health.lastTickAt)
      : null;
  const ageLabel = ageMs == null ? null : formatTickAge(ageMs);
  const streaming = health.state === "live" ? health.liveSymbols : 0;
  const hint = `Market data tape: ${stateLabel}${health.state === "live" ? ` — ${streaming} of ${health.totalSymbols} subscribed symbols streaming` : ""}${ageLabel == null ? "" : `, freshest tick ${ageLabel} ago`}`;
  return (
    <span
      className="titlebar-tape"
      data-tape-state={health.state}
      data-testid="titlebar-tape"
      title={hint}
      aria-label={hint}
    >
      <span className="titlebar-tape__state">{stateLabel}</span>
      {health.state === "live" && (
        <span className="titlebar-tape__value">· {health.totalSymbols}</span>
      )}
      {ageLabel && <span className="titlebar-tape__value">· {ageLabel}</span>}
    </span>
  );
}

/**
 * Asset-class display labels for the titlebar security chip. These are data
 * labels (not chrome copy): the chip reads "<ticker> · US Equity".
 */
const ASSET_CLASS_LABELS: Record<string, string> = {
  EQUITY: "US Equity",
  ETF: "ETF",
  INDEX: "Index",
  CRYPTO: "Crypto",
  FX: "FX",
  COMMODITY: "Commodity",
  BOND: "Bond",
};

/**
 * Map a security's canonical asset class to the session vocabulary.
 * Equities/ETFs/indices/bonds trade on the NYSE calendar; commodities ride
 * the CME futures clock (approximated by `describeSessionState`).
 */
function sessionKindForAssetClass(assetClass: string): SessionKind {
  switch (assetClass) {
    case "CRYPTO":
      return "crypto";
    case "FX":
      return "fx";
    case "COMMODITY":
      return "futures";
    default:
      return "equity";
  }
}

/**
 * Market session pill — bound to the ACTIVE security's asset class instead
 * of the old static "MK" string (M1). A 60 s tick keeps the label honest as
 * sessions open/close; the pill itself is the only thing that re-renders.
 */
function MarketSessionPill({ kind }: { kind: SessionKind }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);
  const session = describeSessionState(kind);
  const hint = `${session.venue} session: ${session.label}`;
  return (
    <span
      className="titlebar__market-pill"
      data-testid="titlebar-market-pill"
      data-session-state={session.state}
      data-session-kind={kind}
      aria-label={hint}
      title={hint}
    >
      {session.label}
    </span>
  );
}

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
  // UI-ROBUSTNESS F6: subscribe to locale changes so every t() label below
  // re-renders when the user switches language in Preferences.
  useLocale();
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
  // H2 fix: the titlebar security chip follows the FOCUSED pane live.
  // Derive ticker + asset class from the focused workspace leaf, push the
  // value into the desk-wide security context (single source of truth for
  // other lanes), and fall back to an imperatively-set context when the
  // focused pane has no symbol of its own.
  const focusedLeaf = useWorkspace((s) => findLeaf(s.tree, s.focusedId));
  const focusedSymbol = normalizeSymbolInput(focusedLeaf?.symbol) || null;
  const derivedSecurity = useMemo<ActiveSecurity | null>(() => {
    if (!focusedSymbol) return null;
    const assetClass = inferAssetClassName(focusedSymbol);
    return {
      symbol: focusedSymbol,
      label: ASSET_CLASS_LABELS[assetClass] ?? assetClass,
      assetClass,
    };
  }, [focusedSymbol]);
  useEffect(() => {
    setActiveSecurity(derivedSecurity);
  }, [derivedSecurity]);
  const { active: contextSecurity } = useSecurityContext();
  const security = derivedSecurity ?? contextSecurity;
  const sessionKind = sessionKindForAssetClass(security?.assetClass ?? "EQUITY");
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
      <TopbarSegment className="titlebar__seg-home">
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

      <TopbarSegment className="titlebar__seg-nav" caption="ShowMe 0.01" withDivider>
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

      <TopbarSegment className="titlebar__seg-command" withDivider>
        <button
          type="button"
          className="interactive titlebar__command-strip"
          data-testid="titlebar-security-chip"
          onClick={() => togglePalette()}
          title="Command palette"
          aria-label="Open command palette"
        >
          <span className="titlebar__ticker-chip" data-testid="titlebar-security-symbol">
            {security?.symbol ?? "—"}
          </span>
          <strong data-testid="titlebar-security-class">{security?.label ?? "—"}</strong>
          <span>{t("shell.palette.placeholder")} · / command · e.g. MSFT GP</span>
        </button>
        <CommandLine />
        {/* role="group" makes the pre-existing aria-label actually exposed
            to assistive tech (a plain div ignores aria-label). */}
        <div className="interactive titlebar__quick-actions" role="group" aria-label="Quick functions">
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
        <TitlebarTape />
      </TopbarSegment>

      <TopbarSegment className="titlebar__seg-cockpit" caption="cockpit" withDivider>
        <div className="interactive titlebar__btn-group" role="group" aria-label="Pane actions">
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
            {t("shell.titlebar.split_right")}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            title="Split below (⌘⇧\\)"
            aria-label={t("shell.titlebar.split_bottom")}
            onClick={() => splitFocused("v")}
          >
            {t("shell.titlebar.split_bottom")}
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

      <TopbarSegment className="titlebar__seg-palette">
        <button
          type="button"
          className="btn btn--ghost interactive titlebar__palette-btn"
          onClick={() => togglePalette()}
          title="Command palette"
          aria-label="Open command palette"
        >
          <span className="kbd">⌘K</span>
        </button>
        {/* Always-visible Settings entry point: the utility segment (which
            also links /preferences) hides on narrow windows, and the owner
            could not find settings anywhere (2026-09-16). */}
        <button
          type="button"
          className="btn btn--ghost interactive titlebar__settings-btn"
          data-testid="titlebar-settings"
          onClick={() => navigate("/preferences")}
          title={t("shell.preferences")}
          aria-label={t("shell.preferences")}
        >
          <span className="kbd">⚙</span>
        </button>
        <PresetMenu />
      </TopbarSegment>

      <TopbarSegment className="titlebar__seg-status" withDivider>
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
        {/* M1 fix: the session pill is bound to the ACTIVE security's venue
            (NYSE calendar / 24-7 crypto / 24-5 FX / CME-approx futures),
            never a static "MK" string. */}
        <MarketSessionPill kind={sessionKind} />
      </TopbarSegment>

      <TopbarSegment className="titlebar__seg-utility" withDivider>
        <button
          type="button"
          className="btn btn--ghost interactive"
          onClick={newWindow}
          title={t("shell.titlebar.new_window")}
          aria-label={t("shell.titlebar.new_window")}
        >
          {t("shell.titlebar.new_window")}
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
          {t("shell.preferences")}
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
