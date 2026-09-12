/**
 * PaneChrome — small top strip on every leaf with split / close / target.
 *
 * Sits *above* the function pane's own header (the design-system `Pane`
 * primitive). Round 16 promotes this into a draggable handle for relocating
 * a pane inside the tree.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import { LINK_GROUP_IDS as LINK_GROUPS, useWorkspace } from "@/lib/workspace";
import { useAppStore } from "@/lib/store";
import { t, useLocale } from "@/i18n";
import { useFocusTrap } from "@/lib/a11y";
import { usePaneContract } from "@/lib/pane-contract-store";
import { fetchManifests, useManifest } from "@/manifest/registry";
import {
  makePinnedItemForPane,
  pinItem,
  togglePinnedItem,
  usePinnedItems,
  writePinnedDragData,
} from "@/lib/pins";
import { useLiveQuote } from "@/lib/market-data";
import {
  addSymbol,
  ensureWatchlistLoaded,
  removeSymbol,
  useIsWatched,
} from "@/lib/watchlist";
import { navigate } from "@/lib/router";
import { PaneHealth } from "./PaneHealth";
import { formatPercent, formatPrice } from "@/lib/format";

interface PaneChromeProps {
  leafId: string;
  code: string;
  symbol?: string;
  linkGroup?: string;
}

interface PaneDragPreview {
  x: number;
  y: number;
  overPinned: boolean;
}

/**
 * Link-group hues. No dedicated tokens exist yet, so groups borrow the
 * existing semantic ladder (accent / accent-2 / warn / positive); the
 * unlinked state is deliberately neutral (text-mute) so "no group" never
 * reads as a color-coded group.
 */
const LINK_GROUP_HUES: Record<string, string> = {
  A: "var(--accent)",
  B: "var(--accent-2)",
  C: "var(--warn, #f6c350)",
  D: "var(--positive)",
};

function linkHueFor(group?: string): string {
  return (group && LINK_GROUP_HUES[group]) || "var(--text-mute)";
}

export function PaneChrome({ leafId, code, symbol, linkGroup }: PaneChromeProps) {
  // UI-ROBUSTNESS F6: locale subscription so the t() menu items below
  // re-render when the user switches language.
  useLocale();
  const splitFocused = useWorkspace((s) => s.splitFocused);
  const closeFocused = useWorkspace((s) => s.closeFocused);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const setLeafLinkGroup = useWorkspace((s) => s.setLeafLinkGroup);
  const setAllLinkGroups = useWorkspace((s) => s.setAllLinkGroups);
  const setFocused = useWorkspace((s) => s.setFocused);
  const tree = useWorkspace((s) => s.tree);
  const focusedId = useWorkspace((s) => s.focusedId);
  const isFocused = leafId === focusedId;
  const isOnlyLeaf = tree.kind === "leaf";
  const idx = useAppStore((s) => s.functionIndex);
  const pinnedItems = usePinnedItems();
  const [picker, setPicker] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [linkMenuOpen, setLinkMenuOpen] = useState(false);
  const [dragPreview, setDragPreview] = useState<PaneDragPreview | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const linkMenuRef = useRef<HTMLDivElement>(null);
  // A11Y: trap Tab inside the dropdown so screen-reader / keyboard users
  // can't escape into the underlying chrome. Escape handler already wired
  // on the parent action wrapper; this complements it. Restores focus to
  // the trigger on close.
  useFocusTrap(menuRef, menuOpen);
  useFocusTrap(linkMenuRef, linkMenuOpen);
  const pinTarget = useMemo(
    () => makePinnedItemForPane(code, symbol, idx),
    [code, idx, symbol],
  );
  const currentIsPinned = pinnedItems.some((item) => item.id === pinTarget.id);
  const runMenuAction = (action: () => void) => {
    action();
    setMenuOpen(false);
  };
  const runLinkMenuAction = (action: () => void) => {
    action();
    setLinkMenuOpen(false);
  };
  // Link-all target: keep the current pane's group when it has one, else
  // default to A (the menu item shows the resolved target next to the label).
  const linkAllTarget = linkGroup ?? LINK_GROUPS[0];
  const linkHue = linkHueFor(linkGroup);
  // REL-04 P11 — track any in-flight drag listeners so an unmount mid-drag
  // can detach them. Without this, dragging a pane chrome while another
  // pane closes (which removes this PaneChrome from the tree) used to
  // strand both `mousemove` and `mouseup` listeners on `window` forever.
  const dragCleanupRef = useRef<(() => void) | null>(null);
  useEffect(() => {
    return () => {
      dragCleanupRef.current?.();
      dragCleanupRef.current = null;
    };
  }, []);
  const beginPanePinDrag = (event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0 || isInteractiveTarget(event.target)) return;
    // Tear down any prior drag listeners before installing a new pair.
    dragCleanupRef.current?.();
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;
    let cancelled = false;
    const onMouseMove = (moveEvent: globalThis.MouseEvent) => {
      if (cancelled) return;
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 8) {
        moved = true;
      }
      if (!moved) return;
      setDragPreview({
        x: moveEvent.clientX,
        y: moveEvent.clientY,
        overPinned: isPointInsidePinnedDropZone(moveEvent.clientX, moveEvent.clientY),
      });
    };
    const cleanup = () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("keydown", onKeyDown);
      setDragPreview(null);
      dragCleanupRef.current = null;
    };
    const onMouseUp = (upEvent: globalThis.MouseEvent) => {
      cleanup();
      if (cancelled || !moved) return;
      if (isPointInsidePinnedDropZone(upEvent.clientX, upEvent.clientY)) {
        pinItem(pinTarget);
      }
    };
    // HIGH #15 (UI-Shell-Bundle UB) — Escape during drag cancels the
    // pin/drop intent and tears down listeners immediately. Without
    // this, accidentally starting a drag (mouse-down + minor jitter)
    // and trying to back out by hitting Esc left the ghost preview
    // hanging on screen until the next mouse-up.
    const onKeyDown = (keyEvent: KeyboardEvent) => {
      if (keyEvent.key === "Escape") {
        cancelled = true;
        cleanup();
      }
    };
    window.addEventListener("mousemove", onMouseMove);
    // Note: no `{ once: true }` here — we own the removeEventListener call
    // inside `cleanup`, which is symmetric with the unmount safety net.
    window.addEventListener("mouseup", onMouseUp);
    window.addEventListener("keydown", onKeyDown);
    dragCleanupRef.current = cleanup;
  };

  return (
    <header
      draggable={false}
      onDragStart={(e) => writePinnedDragData(e.dataTransfer, pinTarget)}
      onMouseDownCapture={(e) => {
        setFocused(leafId);
        beginPanePinDrag(e);
      }}
      className="pane-chrome"
      title={`${pinTarget.label} - drag to Pinned`}
    >
      <button
        type="button"
        onClick={() => setPicker((p) => !p)}
        title={`Change pane target (currently ${code})`}
        aria-label={`Change pane target, currently ${code}`}
        aria-haspopup="dialog"
        aria-expanded={picker}
        className="pane-chrome__code-btn"
      >
        {code}
      </button>
      <span className="pane-chrome__symbol">
        {symbol ?? "—"}
        {symbol && <LiveQuoteChip symbol={symbol} />}
      </span>
      {symbol && (
        <>
          <WatchToggle symbol={symbol} />
          <SetAlertAction symbol={symbol} />
        </>
      )}
      <PaneHealth leafId={leafId} />
      {isFocused && <span className="pane-chrome__focus">focus</span>}

      {/* Always-visible link-group badge (H2 fix). Link membership used to
          live only inside the ⋯ menu, so a linked desk was invisible. The
          badge shows the group letter (or a neutral dash when unlinked) and
          opens its own small menu with per-pane + desk-wide actions. */}
      <div
        className="pane-chrome__link-wrap"
        style={{ position: "relative", display: "inline-flex" }}
        onBlur={(e) => {
          const next = e.relatedTarget;
          if (next instanceof Node && e.currentTarget.contains(next)) return;
          setLinkMenuOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setLinkMenuOpen(false);
        }}
      >
        <button
          type="button"
          data-testid="pane-chrome-link-badge"
          data-link-group={linkGroup ?? ""}
          aria-label={
            linkGroup
              ? `Symbol link group ${linkGroup}. Change or clear the link group`
              : "Not linked to a symbol group. Change link group"
          }
          aria-haspopup="menu"
          aria-expanded={linkMenuOpen}
          title={
            linkGroup
              ? `Symbol link group ${linkGroup} — all linked panes follow one symbol`
              : "No symbol link — this pane changes independently"
          }
          className="interactive pane-chrome__link-badge"
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            minWidth: 14,
            height: 14,
            padding: "0 3px",
            marginLeft: "var(--space-2)",
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            fontWeight: 700,
            lineHeight: 1,
            textTransform: "uppercase",
            color: linkHue,
            border: `1px solid ${linkHue}`,
            borderRadius: 3,
            background: linkGroup
              ? `color-mix(in srgb, ${linkHue} 14%, transparent)`
              : "transparent",
            cursor: "pointer",
          } as CSSProperties}
          onClick={() => {
            setMenuOpen(false);
            setLinkMenuOpen((open) => !open);
          }}
        >
          {linkGroup ?? "–"}
        </button>
        {linkMenuOpen && (
          <div
            ref={linkMenuRef}
            className="pane-chrome__menu"
            role="menu"
            aria-label="Symbol link group"
            data-testid="pane-chrome-link-menu"
            style={{ right: "auto", left: 0 }}
          >
            <div className="pane-chrome__menu-label">Symbol link</div>
            <div className="pane-chrome__menu-grid" role="group" aria-label="Assign link group">
              {LINK_GROUPS.map((group) => (
                <button
                  key={group}
                  type="button"
                  data-link-choice={group}
                  className={`pane-chrome__menu-mini${linkGroup === group ? " pane-chrome__menu-mini--active" : ""}`}
                  onClick={() =>
                    runLinkMenuAction(() =>
                      setLeafLinkGroup(leafId, linkGroup === group ? undefined : group),
                    )
                  }
                >
                  {group}
                </button>
              ))}
            </div>
            <button
              type="button"
              role="menuitem"
              data-testid="pane-chrome-link-unlink"
              className="pane-chrome__menu-item"
              onClick={() => runLinkMenuAction(() => setLeafLinkGroup(leafId, undefined))}
            >
              <span>Unlink</span>
            </button>
            <button
              type="button"
              role="menuitem"
              data-testid="pane-chrome-link-all"
              className="pane-chrome__menu-item"
              title={`Assign group ${linkAllTarget} to every pane`}
              onClick={() => runLinkMenuAction(() => setAllLinkGroups(linkAllTarget))}
            >
              <span>Link all panes</span>
              <kbd>{linkAllTarget}</kbd>
            </button>
            <button
              type="button"
              role="menuitem"
              data-testid="pane-chrome-link-clear"
              className="pane-chrome__menu-item"
              onClick={() => runLinkMenuAction(() => setAllLinkGroups(undefined))}
            >
              <span>Clear all links</span>
            </button>
          </div>
        )}
      </div>

      <div
        className="pane-chrome__actions"
        onBlur={(e) => {
          const next = e.relatedTarget;
          if (next instanceof Node && e.currentTarget.contains(next)) return;
          setMenuOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setMenuOpen(false);
        }}
      >
        <button
          type="button"
          aria-label="Pane actions"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          title="Pane actions"
          className={`pane-chrome__menu-button${currentIsPinned ? " pane-chrome__menu-button--pinned" : ""}`}
          onClick={() => {
            setLinkMenuOpen(false);
            setMenuOpen((open) => !open);
          }}
        >
          <span aria-hidden>...</span>
        </button>
        {menuOpen && (
          <div
            ref={menuRef}
            className="pane-chrome__menu"
            role="menu"
            aria-label="Pane actions"
            data-testid="pane-chrome-menu"
          >
            <button
              type="button"
              role="menuitem"
              className={`pane-chrome__menu-item${currentIsPinned ? " pane-chrome__menu-item--active" : ""}`}
              onClick={() => runMenuAction(() => togglePinnedItem(pinTarget))}
            >
              <span>{currentIsPinned ? "Unpin" : "Pin"}</span>
              <kbd>{pinTarget.meta}</kbd>
            </button>
            <div className="pane-chrome__menu-label">Symbol link</div>
            <div className="pane-chrome__menu-grid" role="group" aria-label="Symbol link groups">
              {LINK_GROUPS.map((group) => (
                <button
                  key={group}
                  type="button"
                  className={`pane-chrome__menu-mini${linkGroup === group ? " pane-chrome__menu-mini--active" : ""}`}
                  onClick={() =>
                    runMenuAction(() =>
                      setLeafLinkGroup(leafId, linkGroup === group ? undefined : group),
                    )
                  }
                >
                  {group}
                </button>
              ))}
              <button
                type="button"
                className="pane-chrome__menu-mini"
                onClick={() => runMenuAction(() => setLeafLinkGroup(leafId, undefined))}
              >
                Off
              </button>
            </div>
            <button
              type="button"
              role="menuitem"
              className="pane-chrome__menu-item"
              onClick={() => runMenuAction(() => splitFocused("h"))}
            >
              <span>{t("shell.titlebar.split_right")}</span>
              <kbd>cmd\</kbd>
            </button>
            <button
              type="button"
              role="menuitem"
              className="pane-chrome__menu-item"
              onClick={() => runMenuAction(() => splitFocused("v"))}
            >
              <span>{t("shell.titlebar.split_bottom")}</span>
              <kbd>cmd shift\</kbd>
            </button>
            <button
              type="button"
              role="menuitem"
              className="pane-chrome__menu-item pane-chrome__menu-item--danger"
              disabled={isOnlyLeaf}
              onClick={() =>
                runMenuAction(() => {
                  if (!isOnlyLeaf) closeFocused();
                })
              }
            >
              <span>{t("shell.titlebar.close_pane")}</span>
              <kbd>cmd W</kbd>
            </button>
          </div>
        )}
      </div>

      {picker && (
        <Picker
          current={code}
          options={[
            { code: "HOME", name: "Welcome" },
            { code: "PREF", name: "Preferences" },
            { code: "AGENT", name: "Symbol Agent" },
            ...idx,
          ]}
          onPick={(c, s) => {
            setFocusedTarget(c, s ?? symbol);
            setPicker(false);
          }}
          onDismiss={() => setPicker(false)}
        />
      )}
      <ContractInline code={code} symbol={symbol} />
      {dragPreview && (
        <div
          className={`pin-drag-ghost${dragPreview.overPinned ? " pin-drag-ghost--over-pin" : ""}`}
          style={{ left: dragPreview.x + 12, top: dragPreview.y + 10 }}
          aria-hidden
        >
          <span className="pin-drag-ghost__dot" />
          <strong>{pinTarget.label}</strong>
          <span>{pinTarget.meta}</span>
        </div>
      )}
    </header>
  );
}

/**
 * LiveQuoteChip — live price + directional delta inside the pane header
 * (campaign 2026-09-08, Lane B / U2). Subscribes via the existing
 * `useLiveQuote` hook so the header breathes with the tape instead of
 * showing a static symbol string.
 *
 * Honesty contract: with no price (WS down, snapshot missing) the chip
 * renders NOTHING — the plain bound symbol above stays the truth. No fake
 * price, no optimistic fill-in. A price that can no longer be trusted
 * (freshness past the stale window, transport offline/error) stays visible
 * but dims under `--stale`, and the tooltip names the transport state
 * instead of claiming liveness. Isolated as a child component so only this
 * chip re-renders per tick, never the whole PaneChrome (UA-CRITICAL-06).
 */
function LiveQuoteChip({ symbol }: { symbol: string }) {
  const quote = useLiveQuote(symbol);
  if (quote.price == null) return null;
  const notLive =
    quote.stale || quote.transportState === "offline" || quote.transportState === "error";
  const changePct = quote.changePct;
  const up = changePct != null && changePct >= 0;
  return (
    <span
      className={`pane-chrome__quote${notLive ? " pane-chrome__quote--stale" : ""}`}
      data-testid="pane-chrome-quote"
      data-transport={quote.transportState}
      data-stale={notLive || undefined}
      title={`Quote · transport ${quote.transportState}${notLive ? " · price may be stale" : ""}`}
    >
      <span className="pane-chrome__quote-price">{formatPrice(quote.price)}</span>
      {changePct != null && (
        <span
          className={`pane-chrome__quote-delta pane-chrome__quote-delta--${up ? "up" : "down"}`}
        >
          <span aria-hidden>{up ? "▲" : "▼"}</span>
          <span className="u-sr-only">{up ? "up" : "down"}</span>
          {formatPercent(changePct, { signed: true })}
        </span>
      )}
    </span>
  );
}

/**
 * WatchToggle — "+ watch" membership toggle next to the symbol chip
 * (campaign 2026-09-11 double / lane B1). One-point adoption for every
 * symbol-bound pane: adds/removes the bound symbol in the shared watchlist
 * store and reflects membership changes made anywhere else in the app
 * (`useIsWatched` subscribes to the store's publish channel). Inline SVG
 * glyph (no emoji); filled + accent when watched, outline + mute otherwise.
 */
function WatchToggle({ symbol }: { symbol: string }) {
  const watched = useIsWatched(symbol);
  // Hydrate the store once per session; other surfaces read it too, so this
  // is a shared, cached read rather than a per-pane fetch.
  useEffect(() => {
    void ensureWatchlistLoaded();
  }, []);
  const label = watched
    ? `Remove ${symbol} from watchlist`
    : `Add ${symbol} to watchlist`;
  return (
    <button
      type="button"
      data-testid="pane-chrome-watch"
      aria-pressed={watched}
      aria-label={label}
      title={label}
      className="pane-chrome__watch"
      onClick={() => {
        void (watched ? removeSymbol(symbol) : addSymbol(symbol));
      }}
      style={{
        ...symbolActionStyle,
        color: watched ? "var(--accent)" : "var(--text-mute)",
        borderColor: watched ? "var(--accent)" : "transparent",
        background: watched
          ? "color-mix(in srgb, var(--accent) 14%, transparent)"
          : "transparent",
      }}
    >
      <svg width="10" height="10" viewBox="0 0 24 24" aria-hidden focusable="false">
        <path
          d="M12 3.6l2.6 5.27 5.82.85-4.21 4.1.99 5.79L12 16.87l-5.2 2.74.99-5.79-4.21-4.1 5.82-.85L12 3.6z"
          fill={watched ? "currentColor" : "none"}
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}

/**
 * SetAlertAction — hands the bound symbol to the existing ALRT pane via the
 * hash router (`#/symbol/<sym>/ALRT`); ALRT's own seeded form does the rest.
 * Navigation only — no modal, no duplicated alert UI.
 */
function SetAlertAction({ symbol }: { symbol: string }) {
  const label = `Set an alert for ${symbol}`;
  return (
    <button
      type="button"
      data-testid="pane-chrome-alert"
      aria-label={label}
      title={label}
      className="pane-chrome__alert"
      onClick={() => navigate(`/symbol/${symbol}/ALRT`)}
      style={{
        ...symbolActionStyle,
        color: "var(--text-mute)",
        borderColor: "transparent",
        background: "transparent",
      }}
    >
      <svg width="10" height="10" viewBox="0 0 24 24" aria-hidden focusable="false">
        <path
          d="M12 3a5.5 5.5 0 0 0-5.5 5.5v3.1L5 15h14l-1.5-3.4V8.5A5.5 5.5 0 0 0 12 3z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <path
          d="M10 17.6a2 2 0 0 0 4 0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
}

/** Shared compact geometry for the two symbol actions — same 14px band as
 * the link badge so the chrome row height stays untouched. */
const symbolActionStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 16,
  height: 14,
  padding: "0 2px",
  marginLeft: "var(--space-2)",
  border: "1px solid transparent",
  borderRadius: 3,
  background: "transparent",
  cursor: "pointer",
  lineHeight: 1,
};

const MODE_TONE: Record<string, string> = {
  live_official: "positive",
  live_exchange: "positive",
  delayed_reference: "neutral",
  modeled: "warn",
  cached_snapshot: "neutral",
  provider_unavailable: "negative",
  not_configured: "muted",
};

const MODE_LABEL: Record<string, string> = {
  live_official: "LIVE · OFFICIAL",
  live_exchange: "LIVE · EXCHANGE",
  delayed_reference: "DELAYED",
  modeled: "MODELED",
  cached_snapshot: "CACHED",
  provider_unavailable: "PROVIDER DOWN",
  not_configured: "NOT CONFIGURED",
};

/**
 * ContractInline — compact inline contract surface that sits INSIDE the
 * existing PaneChrome header row (not as a separate band) so an empty
 * pane body never leaves the badge floating in dead space. Three signals:
 *
 *   • mode pill (data_mode) — only renders when useFunction or
 *     sidecarFetch has landed a snapshot for this leaf
 *   • src tag — first provider name when available
 *   • man dot — tiny manifest indicator, hover shows category + primary
 *     + N inputs from the FunctionManifest registry
 *
 * Designed to add ~120px of horizontal real estate to PaneChrome rather
 * than introducing a new visual row.
 */
function ContractInline({ code, symbol }: { code: string; symbol?: string }) {
  const snap = usePaneContract(code, symbol);
  const manifest = useManifest(code);

  // Trigger a one-shot manifest fetch the first time PaneChrome mounts;
  // the registry deduplicates further calls.
  useEffect(() => {
    if (!manifest) void fetchManifests().catch(() => undefined);
  }, [manifest]);

  if (!snap && !manifest) return null;
  const mode = snap?.dataMode;
  const tone = (mode && MODE_TONE[mode]) || "muted";
  const modeLabel = mode ? MODE_LABEL[mode] || mode.toUpperCase() : null;
  const firstSource = snap?.sources?.[0];
  const sourceMore = (snap?.sources?.length ?? 0) - 1;
  const warningCount = snap?.warnings?.length ?? 0;
  const manifestTitle = manifest
    ? `Manifest: ${manifest.category} · primary ${manifest.provider_chain.primary} · ${manifest.inputs.length} inputs`
    : undefined;
  const snapshotTitle = snap
    ? `Data mode: ${mode ?? "—"}\nSources: ${snap.sources?.join(", ") ?? "—"}\nAs of: ${snap.asOf ?? "—"}\nLatency: ${snap.latencyMs ?? "—"} ms\nWarnings: ${snap.warnings?.length ?? 0}\nNext actions: ${snap.nextActions?.join(", ") ?? "—"}`
    : undefined;
  return (
    <span
      className="pane-chrome__contract-inline"
      data-testid="pane-chrome-contract"
      data-data-mode={mode ?? ""}
      role="status"
      aria-label="Pane manifest and data mode"
    >
      {manifest && (
        <span
          className="pane-chrome__manifest-dot"
          title={manifestTitle}
          data-testid="pane-chrome-manifest"
          aria-label={manifestTitle}
        >
          M
        </span>
      )}
      {modeLabel && (
        <span
          className={`pane-chrome__mode pane-chrome__mode--${tone}`}
          title={snapshotTitle}
          data-testid="pane-chrome-mode"
        >
          {modeLabel}
        </span>
      )}
      {firstSource && (
        <span
          className="pane-chrome__sources"
          title={snapshotTitle}
          data-testid="pane-chrome-sources"
        >
          {firstSource}{sourceMore > 0 ? `+${sourceMore}` : ""}
        </span>
      )}
      {warningCount > 0 && (
        <span
          className="pane-chrome__warnings"
          title={snap?.warnings?.join("\n")}
          data-testid="pane-chrome-warnings"
        >
          ⚠{warningCount}
        </span>
      )}
    </span>
  );
}


function isInteractiveTarget(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    Boolean(target.closest("button, input, textarea, select, a, [role='menu']"))
  );
}

function isPointInsidePinnedDropZone(clientX: number, clientY: number): boolean {
  const zone = document.querySelector<HTMLElement>('[aria-label="Pinned drop zone"]');
  if (!zone) return false;
  const rect = zone.getBoundingClientRect();
  return (
    clientX >= rect.left &&
    clientX <= rect.right &&
    clientY >= rect.top &&
    clientY <= rect.bottom
  );
}

interface PickerEntry {
  code: string;
  name: string;
}

function Picker({
  options,
  current,
  onPick,
  onDismiss,
}: {
  options: PickerEntry[];
  current: string;
  onPick: (code: string, symbol?: string) => void;
  onDismiss: () => void;
}) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const filtered = !query.trim()
    ? options.slice(0, 30)
    : options
        .filter(
          (o) =>
            o.code.toLowerCase().includes(query.toLowerCase()) ||
            o.name.toLowerCase().includes(query.toLowerCase()),
        )
        .slice(0, 30);
  // Reset the keyboard cursor whenever the filter changes so Enter always
  // picks a row the user can actually see highlighted.
  useEffect(() => {
    setCursor(0);
  }, [query]);
  const pickAt = (index: number) => {
    const row = filtered[index];
    if (row) onPick(row.code);
  };
  return (
    // Same containment pattern as the actions menu above: a blur to a node
    // OUTSIDE the popup dismisses it. A bare `onBlur={onDismiss}` fired when
    // the mousedown moved focus to a row — unmounting the list before the
    // row's click ever fired, so mouse selection was dead.
    <div
      className="picker-popup"
      onBlur={(e) => {
        const next = e.relatedTarget;
        if (next instanceof Node && e.currentTarget.contains(next)) return;
        onDismiss();
      }}
    >
      <input
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter functions…"
        aria-label="Filter functions"
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            onDismiss();
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            setCursor((c) => Math.min(c + 1, filtered.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setCursor((c) => Math.max(c - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            pickAt(cursor);
          }
        }}
        role="combobox"
        aria-expanded
        aria-controls="pane-chrome-picker-listbox"
        aria-activedescendant={
          filtered[cursor] ? `pane-chrome-picker-opt-${filtered[cursor].code}` : undefined
        }
        className="picker-popup__input"
      />
      <div
        id="pane-chrome-picker-listbox"
        role="listbox"
        className="picker-popup__list"
      >
        {filtered.map((o, i) => (
          <button
            key={o.code}
            type="button"
            onClick={() => onPick(o.code)}
            // Keep focus on the input: no blur fires mid-click, so the popup
            // survives until onPick/onDismiss runs (Safari never focuses
            // buttons on mousedown, which defeated the blur handler alone).
            onMouseDown={(e) => e.preventDefault()}
            id={`pane-chrome-picker-opt-${o.code}`}
            role="option"
            aria-selected={i === cursor}
            className={`picker-popup__row${o.code === current ? " picker-popup__row--active" : ""}${i === cursor ? " picker-popup__row--cursor" : ""}`}
          >
            <span className="picker-popup__row-code">{o.code}</span>
            <span>{o.name}</span>
          </button>
        ))}
        {!filtered.length && (
          <div className="picker-popup__empty">no matches</div>
        )}
      </div>
    </div>
  );
}
