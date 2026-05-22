import {
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type MouseEvent,
  type MutableRefObject,
} from "react";
import { useAppStore } from "@/lib/store";
import type { FunctionEntry } from "@/lib/sidecar";
import { navigate, useRoute } from "@/lib/router";
import { listNativeCodes } from "@/functions/registry";
import { t } from "@/i18n";
import {
  PIN_DRAG_MIME,
  makePinnedItemForFunctionEntry,
  pinItem,
  readPinnedDragData,
  unpinItem,
  usePinnedItems,
  writePinnedDragData,
  type PinnedItem,
} from "@/lib/pins";

type PinDragSource = "source" | "pinned";

interface PinDragPreview {
  item: PinnedItem;
  source: PinDragSource;
  x: number;
  y: number;
  overPinned: boolean;
}

const CATEGORY_ORDER = [
  "portfolio",
  "equity",
  "trade",
  "macro",
  "bond",
  "fx",
  "commodity",
  "derivative",
  "news",
  "screen",
  "comm",
  "api",
  "chart",
  "misc",
];

interface SidebarShortcut {
  code: string;
  label: string;
  meta: string;
  href: string;
  path: string;
  ariaLabel?: string;
}

const WORKSPACE_ITEMS: SidebarShortcut[] = [
  { code: "HOME", label: "Overview", meta: "OVR", href: "#/", path: "/" },
  { code: "WATCH", label: "Watchlist", meta: "WTC", href: "#/fn/WATCH", path: "/fn/WATCH" },
  {
    code: "PORT",
    label: "Portfolio",
    meta: "POR",
    href: "#/fn/PORT",
    path: "/fn/PORT",
    ariaLabel: "Open holdings workspace",
  },
  { code: "WEI", label: "Macro Monitor", meta: "MAC", href: "#/fn/WEI", path: "/fn/WEI" },
  { code: "NI", label: "News Desk", meta: "NEW", href: "#/fn/NI", path: "/fn/NI" },
  { code: "SCAN", label: "All Functions", meta: "FN", href: "#/fn/SCAN", path: "/fn/SCAN" },
  { code: "MIS", label: "Multi Indicator Scan", meta: "MIS", href: "#/fn/MIS", path: "/fn/MIS" },
];

const RECENT_ITEMS: SidebarShortcut[] = [
  { code: "GEX", label: "Gamma Exposure", meta: "GEX", href: "#/fn/GEX", path: "/fn/GEX" },
  { code: "BTMM", label: "Yield Curve", meta: "BTM", href: "#/fn/BTMM", path: "/fn/BTMM" },
  { code: "WEI", label: "World Heatmap", meta: "MAP", href: "#/fn/WEI", path: "/fn/WEI" },
  {
    code: "OMON",
    label: "Option Monitor",
    meta: "OMO",
    href: "#/fn/OMON",
    path: "/fn/OMON",
  },
  { code: "EQS", label: "Equity Screener", meta: "EQS", href: "#/fn/EQS", path: "/fn/EQS" },
];

const TOOL_ITEMS: SidebarShortcut[] = [
  { code: "ALRT", label: "Alerts", meta: "ALR", href: "#/fn/ALRT", path: "/fn/ALRT" },
  {
    code: "INDX",
    label: "Indicator Index",
    meta: "IDX",
    href: "#/fn/INDX",
    path: "/fn/INDX",
    ariaLabel: "Open indicator depot",
  },
  {
    code: "STRA",
    label: "Strategy Editor",
    meta: "STR",
    href: "#/fn/STRA",
    path: "/fn/STRA",
    ariaLabel: "Open strategy editor",
  },
  {
    code: "BOT",
    label: "Bot Manager",
    meta: "BOT",
    href: "#/fn/BOT",
    path: "/fn/BOT",
    ariaLabel: "Open bot manager",
  },
  {
    code: "INSTANT",
    label: "Trade Ticket",
    meta: "TRD",
    href: "#/fn/INSTANT",
    path: "/fn/INSTANT",
  },
  { code: "TLDR", label: "Daily TL;DR", meta: "TLR", href: "#/fn/TLDR", path: "/fn/TLDR" },
  {
    code: "PREF",
    label: "Settings",
    meta: "SET",
    href: "#/preferences",
    path: "/preferences",
  },
];

const CONNECTIONS_ITEMS: SidebarShortcut[] = [
  {
    code: "CONN",
    label: "Connect Exchange",
    meta: "CON",
    href: "#/fn/CONN",
    path: "/fn/CONN",
    ariaLabel: "Open exchange connect pane",
  },
];

const QUICK_ITEMS: SidebarShortcut[] = [
  {
    code: "OMON",
    label: "Option Monitor",
    meta: "OMON",
    href: "#/fn/OMON",
    path: "/fn/OMON",
  },
  { code: "GEX", label: "Gamma Exposure", meta: "GEX", href: "#/fn/GEX", path: "/fn/GEX" },
  { code: "FA", label: "Financial Analysis", meta: "FA", href: "#/fn/FA", path: "/fn/FA" },
  { code: "DES", label: "Description", meta: "DES", href: "#/fn/DES", path: "/fn/DES" },
  {
    code: "BTMM",
    label: "Rates Environment",
    meta: "BTMM",
    href: "#/fn/BTMM",
    path: "/fn/BTMM",
  },
  { code: "MOST", label: "Most Active", meta: "MOST", href: "#/fn/MOST", path: "/fn/MOST" },
];

function groupByCategory(entries: FunctionEntry[]) {
  const map = new Map<string, FunctionEntry[]>();
  for (const e of entries) {
    if (!map.has(e.category)) map.set(e.category, []);
    map.get(e.category)!.push(e);
  }
  return [...map.entries()].sort(
    ([a], [b]) =>
      (CATEGORY_ORDER.indexOf(a) === -1 ? 99 : CATEGORY_ORDER.indexOf(a)) -
      (CATEGORY_ORDER.indexOf(b) === -1 ? 99 : CATEGORY_ORDER.indexOf(b)),
  );
}

export function Sidebar() {
  const index = useAppStore((s) => s.functionIndex);
  const sidebarVisible = useAppStore((s) => s.sidebarVisible);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const pinnedItems = usePinnedItems();
  const [query, setQuery] = useState("");
  const [peekOpen, setPeekOpen] = useState(false);
  const route = useRoute();
  const activeCode =
    route.kind === "function" ? route.code : route.kind === "welcome" ? "HOME" : "PREF";
  const activePath = routeToPath(route);
  const nativeCodes = useMemo(() => new Set(listNativeCodes()), []);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return index;
    return index.filter((entry) =>
      `${entry.code} ${entry.name} ${entry.category} ${entry.description}`
        .toLowerCase()
        .includes(q),
    );
  }, [index, query]);
  const grouped = useMemo(() => groupByCategory(filtered), [filtered]);
  const total = index.length;

  return (
    <div className={`sidebar-slot ${sidebarVisible ? "" : "sidebar-slot--hidden"}`}>
      {sidebarVisible ? (
        <SidebarPanel
          variant="docked"
          query={query}
          setQuery={setQuery}
          total={total}
          filteredCount={filtered.length}
          grouped={grouped}
          nativeCodes={nativeCodes}
          activeCode={activeCode}
          activePath={activePath}
          pinnedItems={pinnedItems}
          onHide={() => {
            setPeekOpen(false);
            toggleSidebar(false);
          }}
        />
      ) : (
        <>
          <button
            type="button"
            className="sidebar-edge-hitbox"
            onMouseEnter={() => setPeekOpen(true)}
            onClick={() => setPeekOpen(true)}
            aria-label="Show functions preview"
          >
            <span>Functions</span>
          </button>
          {peekOpen && (
            <div
              className="sidebar-popover sidebar-popover--open"
              onMouseEnter={() => setPeekOpen(true)}
              onMouseLeave={() => setPeekOpen(false)}
            >
              <SidebarPanel
                variant="popup"
                query={query}
                setQuery={setQuery}
                total={total}
                filteredCount={filtered.length}
                grouped={grouped}
                nativeCodes={nativeCodes}
                activeCode={activeCode}
                activePath={activePath}
                pinnedItems={pinnedItems}
                onPin={() => {
                  setPeekOpen(false);
                  toggleSidebar(true);
                }}
                onClose={() => setPeekOpen(false)}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface SidebarPanelProps {
  variant: "docked" | "popup";
  query: string;
  setQuery: (value: string) => void;
  total: number;
  filteredCount: number;
  grouped: Array<[string, FunctionEntry[]]>;
  nativeCodes: Set<string>;
  activeCode: string;
  activePath: string;
  pinnedItems: PinnedItem[];
  onHide?: () => void;
  onPin?: () => void;
  onClose?: () => void;
}

function SidebarPanel({
  variant,
  query,
  setQuery,
  total,
  filteredCount,
  grouped,
  nativeCodes,
  activeCode,
  activePath,
  pinnedItems,
  onHide,
  onPin,
  onClose,
}: SidebarPanelProps) {
  const pinnedDropZoneRef = useRef<HTMLElement | null>(null);
  const suppressNextClickRef = useRef(false);
  const [dragPreview, setDragPreview] = useState<PinDragPreview | null>(null);
  const shouldSuppressClick = () => suppressNextClickRef.current;
  const pinnedIds = useMemo(
    () => new Set(pinnedItems.map((item) => item.id)),
    [pinnedItems],
  );
  const hiddenSourceId = dragPreview?.source === "source" ? dragPreview.item.id : null;
  const hiddenPinnedId = dragPreview?.source === "pinned" ? dragPreview.item.id : null;
  const visiblePinnedItems = useMemo(
    () => pinnedItems.filter((item) => item.id !== hiddenPinnedId),
    [hiddenPinnedId, pinnedItems],
  );
  const visibleWorkspaceItems = useMemo(
    () => filterShortcutItems(WORKSPACE_ITEMS, pinnedIds, hiddenSourceId),
    [hiddenSourceId, pinnedIds],
  );
  const visibleRecentItems = useMemo(
    () => filterShortcutItems(RECENT_ITEMS, pinnedIds, hiddenSourceId),
    [hiddenSourceId, pinnedIds],
  );
  const visibleToolItems = useMemo(
    () => filterShortcutItems(TOOL_ITEMS, pinnedIds, hiddenSourceId),
    [hiddenSourceId, pinnedIds],
  );
  const visibleQuickItems = useMemo(
    () => filterShortcutItems(QUICK_ITEMS, pinnedIds, hiddenSourceId),
    [hiddenSourceId, pinnedIds],
  );
  const visibleConnectionsItems = useMemo(
    () => filterShortcutItems(CONNECTIONS_ITEMS, pinnedIds, hiddenSourceId),
    [hiddenSourceId, pinnedIds],
  );
  const visibleGrouped = useMemo(
    () =>
      grouped
        .map(([cat, items]) => {
          const visible = items.filter((it) => {
            const pin = makePinnedItemForFunctionEntry(it);
            return pin.id !== hiddenSourceId && !pinnedIds.has(pin.id);
          });
          return [cat, visible] as [string, FunctionEntry[]];
        })
        .filter(([, items]) => items.length > 0),
    [grouped, hiddenSourceId, pinnedIds],
  );
  const finishPinDrag = (
    item: PinnedItem,
    source: PinDragSource,
    clientX: number,
    clientY: number,
  ) => {
    suppressNextClickRef.current = true;
    window.setTimeout(() => {
      suppressNextClickRef.current = false;
    }, 0);
    if (isPointInsideSection(pinnedDropZoneRef.current, clientX, clientY)) {
      pinItem(item);
      return;
    }
    if (source === "pinned") unpinItem(item.id);
  };
  const beginMousePinDrag = (
    event: MouseEvent<HTMLElement>,
    item: PinnedItem,
    source: PinDragSource,
  ) => {
    if (event.button !== 0) return;
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;
    const onMouseMove = (moveEvent: globalThis.MouseEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 8) {
        moved = true;
      }
      if (!moved) return;
      setDragPreview({
        item,
        source,
        x: moveEvent.clientX,
        y: moveEvent.clientY,
        overPinned: isPointInsideSection(
          pinnedDropZoneRef.current,
          moveEvent.clientX,
          moveEvent.clientY,
        ),
      });
    };
    const onMouseUp = (upEvent: globalThis.MouseEvent) => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      setDragPreview(null);
      if (!moved) return;
      finishPinDrag(item, source, upEvent.clientX, upEvent.clientY);
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp, { once: true });
  };

  return (
    <aside
      className={`sidebar sidebar--${variant}`}
      aria-label={t("shell.sidebar.search_label")}
    >
      <h2 className="u-sr-only">Functions</h2>
      <div className="sidebar__header">
        <div className="sidebar__header-row">
          <div className="u-whitespace-nowrap">
            FN
            <span
              className="sidebar__count"
              aria-live="polite"
              aria-label={
                filteredCount === total
                  ? t("shell.sidebar.total_count", { count: total })
                  : t("shell.sidebar.filtered_count", { count: filteredCount, total })
              }
            >
              {filteredCount} / {total}
            </span>
          </div>
          <div className="sidebar__toggle-group">
            {variant === "popup" && (
              <button
                type="button"
                className="sidebar-toggle-button"
                onClick={onPin}
                title={t("shell.sidebar.dock")}
                aria-label={t("shell.sidebar.dock")}
              >
                <span aria-hidden>&gt;</span>
              </button>
            )}
            <button
              type="button"
              className="sidebar-toggle-button"
              onClick={variant === "docked" ? onHide : onClose}
              title={
                variant === "docked"
                  ? t("shell.sidebar.hide")
                  : t("shell.sidebar.close_preview")
              }
              aria-label={
                variant === "docked"
                  ? t("shell.sidebar.hide")
                  : t("shell.sidebar.close_preview")
              }
            >
              <span aria-hidden>{variant === "docked" ? "<" : "x"}</span>
            </button>
          </div>
        </div>
        <div className="sidebar__search-host">
          <span aria-hidden className="sidebar__search-slash">
            /
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="code, name, category"
            aria-label={t("shell.sidebar.search_label")}
            className="sidebar__search-input"
          />
        </div>
        <a
          href="#/fn/AGENT"
          className="btn btn--accent sidebar__agent-btn"
          onClick={(e) => {
            // Keep middle-click + cmd-click + drag-to-tab semantics; only
            // intercept primary-click without modifiers (A11Y-08).
            if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            e.preventDefault();
            navigate("/fn/AGENT");
          }}
        >
          <span className="sidebar__agent-label">
            <span className="sidebar__agent-label-icon">✦</span>
            AGENT
          </span>
          <span className="kbd sidebar__agent-kbd">⌘J</span>
        </a>
      </div>

      {!query.trim() && (
        <div className="sidebar-shortcuts">
          <SidebarShortcutGroup
            title="Pinned"
            count={visiblePinnedItems.length}
            items={visiblePinnedItems}
            activePath={activePath}
            droppable
            visualDropActive={Boolean(dragPreview?.overPinned)}
            dropZoneRef={pinnedDropZoneRef}
            onDropItem={pinItem}
            onRemove={(item) => unpinItem(item.id)}
            onMousePinDragStart={beginMousePinDrag}
            shouldSuppressClick={shouldSuppressClick}
          />
          <SidebarShortcutGroup
            title="Workspaces"
            count={visibleWorkspaceItems.length}
            items={visibleWorkspaceItems}
            activePath={activePath}
            onMousePinDragStart={beginMousePinDrag}
            shouldSuppressClick={shouldSuppressClick}
          />
          <SidebarShortcutGroup
            title="Recent"
            count={visibleRecentItems.length}
            items={visibleRecentItems}
            activePath={activePath}
            onMousePinDragStart={beginMousePinDrag}
            shouldSuppressClick={shouldSuppressClick}
          />
          <SidebarShortcutGroup
            title="Tools"
            count={visibleToolItems.length}
            items={visibleToolItems}
            activePath={activePath}
            onMousePinDragStart={beginMousePinDrag}
            shouldSuppressClick={shouldSuppressClick}
          />
          <SidebarShortcutGroup
            title="Connections"
            count={visibleConnectionsItems.length}
            items={visibleConnectionsItems}
            activePath={activePath}
            onMousePinDragStart={beginMousePinDrag}
            shouldSuppressClick={shouldSuppressClick}
          />
          <SidebarShortcutGroup
            title="Quick Functions"
            count={visibleQuickItems.length}
            items={visibleQuickItems}
            activePath={activePath}
            onMousePinDragStart={beginMousePinDrag}
            shouldSuppressClick={shouldSuppressClick}
          />
        </div>
      )}

      {total === 0 && <div className="sidebar__empty">(waiting for sidecar…)</div>}

      {visibleGrouped.map(([cat, items]) => (
        <section key={cat} className="sidebar__group" aria-label={cat}>
          <h3 className="sidebar__group-head">
            {cat}
            <span className="sidebar__group-count">{items.length}</span>
          </h3>
          {items.map((it) => {
            const isActive = activeCode === it.code;
            const href = `#/fn/${it.code}`;
            const draggablePin = makePinnedItemForFunctionEntry(it);
            return (
              <a
                key={it.code}
                href={href}
                draggable={false}
                onDragStart={(e) => writePinnedDragData(e.dataTransfer, draggablePin)}
                onMouseDown={(e) => beginMousePinDrag(e, draggablePin, "source")}
                onClick={(e) => {
                  if (shouldSuppressClick()) {
                    e.preventDefault();
                    return;
                  }
                  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
                    return;
                  e.preventDefault();
                  navigate(`/fn/${it.code}`);
                }}
                className={`sidebar-function sidebar-function-link ${isActive ? "sidebar-function-link--active" : ""}`}
                aria-current={isActive ? "page" : undefined}
                title={`${it.name} - drag to Pinned`}
              >
                <strong>{it.code}</strong>
                <span className="sidebar-function-link__name">{it.name}</span>
                {nativeCodes.has(it.code) && (
                  <span className="sidebar-function-link__native">N</span>
                )}
              </a>
            );
          })}
        </section>
      ))}
      {dragPreview && <PinDragGhost drag={dragPreview} />}
    </aside>
  );
}

function SidebarShortcutGroup({
  title,
  count,
  items,
  activePath,
  droppable,
  visualDropActive,
  dropZoneRef,
  onDropItem,
  onRemove,
  onMousePinDragStart,
  shouldSuppressClick,
}: {
  title: string;
  count: number;
  items: Array<SidebarShortcut | PinnedItem>;
  activePath: string;
  droppable?: boolean;
  visualDropActive?: boolean;
  dropZoneRef?: MutableRefObject<HTMLElement | null>;
  onDropItem?: (item: PinnedItem) => void;
  onRemove?: (item: PinnedItem) => void;
  onMousePinDragStart?: (
    event: MouseEvent<HTMLElement>,
    item: PinnedItem,
    source: PinDragSource,
  ) => void;
  shouldSuppressClick?: () => boolean;
}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const setSectionRef = (node: HTMLElement | null) => {
    sectionRef.current = node;
    if (dropZoneRef) dropZoneRef.current = node;
  };

  const handleDrop = (event: DragEvent<HTMLElement>) => {
    if (!droppable || !onDropItem) return;
    const item = readPinnedDragData(event.dataTransfer);
    if (!item) return;
    event.preventDefault();
    onDropItem(item);
    setDropActive(false);
  };

  const handleDragOver = (event: DragEvent<HTMLElement>) => {
    if (!droppable || !hasPinDragPayload(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDropActive(true);
  };

  return (
    <section
      ref={setSectionRef}
      className={`sidebar-shortcut-group${dropActive || visualDropActive ? " sidebar-shortcut-group--drop-active" : ""}`}
      aria-label={droppable ? `${title} drop zone` : title}
      onDragOver={handleDragOver}
      onDragLeave={() => setDropActive(false)}
      onDrop={handleDrop}
    >
      <h3 className="sidebar__group-head">
        {title}
        <span className="sidebar__group-count">{count}</span>
      </h3>
      {droppable && items.length === 0 && (
        <div className="sidebar-shortcut-group__drop-hint">Drop here to pin</div>
      )}
      {items.map((item) => {
        const isActive = activePath === item.path;
        const draggablePin = "id" in item ? item : shortcutToPinnedItem(item);
        return (
          <div
            key={`${title}-${item.code}-${item.path}`}
            className={`sidebar-shortcut-row${isActive ? " sidebar-shortcut-row--active" : ""}${onRemove ? "" : " sidebar-shortcut-row--plain"}`}
          >
            <a
              href={item.href}
              draggable={false}
              className="sidebar-shortcut"
              aria-label={"ariaLabel" in item ? item.ariaLabel : undefined}
              aria-current={isActive ? "page" : undefined}
              onDragStart={(e) => writePinnedDragData(e.dataTransfer, draggablePin)}
              onMouseDown={(e) =>
                onMousePinDragStart?.(
                  e,
                  draggablePin,
                  "id" in item ? "pinned" : "source",
                )
              }
              onDragEnd={(e) => {
                if (!onRemove || !("id" in item)) return;
                if (isPointInsideSection(sectionRef.current, e.clientX, e.clientY)) return;
                onRemove(item);
              }}
              onClick={(e) => {
                if (shouldSuppressClick?.()) {
                  e.preventDefault();
                  return;
                }
                if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
                  return;
                e.preventDefault();
                // S10 dashboard-restore: Overview navigates to the
                // welcome route (`#/`), which `RouteSync` resolves to a
                // HOME leaf that `Workspace.tsx` renders via the native
                // `<Welcome />` dashboard. Markets Overview is a
                // separate preset reachable through the preset menu /
                // command palette — never auto-loaded from the
                // dashboard click.
                navigate(item.path);
              }}
            >
              <span className="sidebar-shortcut__dot" aria-hidden />
              <strong>{item.label}</strong>
              <span>{item.meta}</span>
            </a>
            {onRemove && "id" in item && (
              <button
                type="button"
                className="sidebar-shortcut__remove"
                aria-label={`Unpin ${item.label}`}
                title={`Unpin ${item.label}`}
                onClick={() => onRemove(item)}
              >
                <span aria-hidden>x</span>
              </button>
            )}
          </div>
        );
      })}
    </section>
  );
}

function PinDragGhost({ drag }: { drag: PinDragPreview }) {
  return (
    <div
      className={`pin-drag-ghost${drag.overPinned ? " pin-drag-ghost--over-pin" : ""}`}
      style={{ left: drag.x + 12, top: drag.y + 10 }}
      aria-hidden
    >
      <span className="pin-drag-ghost__dot" />
      <strong>{drag.item.label}</strong>
      <span>{drag.item.meta}</span>
    </div>
  );
}

function routeToPath(route: ReturnType<typeof useRoute>): string {
  if (route.kind === "welcome") return "/";
  if (route.kind === "preferences" || route.kind === "settings") return "/preferences";
  if (route.kind === "function") {
    return route.symbol ? `/symbol/${route.symbol}/${route.code}` : `/fn/${route.code}`;
  }
  return "/";
}

function shortcutToPinnedItem(item: SidebarShortcut): PinnedItem {
  const kind = item.path === "/" || item.path.startsWith("/preferences")
    ? "workspace"
    : item.path.startsWith("/symbol/")
      ? "symbol"
      : "function";
  return {
    id: kind === "workspace" ? `workspace:${item.code}` : `${kind}:${item.code}`,
    kind,
    code: item.code,
    label: item.label,
    meta: item.meta,
    path: item.path,
    href: item.href,
  };
}

function filterShortcutItems(
  items: SidebarShortcut[],
  pinnedIds: Set<string>,
  hiddenSourceId: string | null,
): SidebarShortcut[] {
  return items.filter((item) => {
    const pin = shortcutToPinnedItem(item);
    return pin.id !== hiddenSourceId && !pinnedIds.has(pin.id);
  });
}

function hasPinDragPayload(event: DragEvent<HTMLElement>): boolean {
  return Array.from(event.dataTransfer.types).includes(PIN_DRAG_MIME);
}

function isPointInsideSection(
  section: HTMLElement | null,
  clientX: number,
  clientY: number,
): boolean {
  if (!section) return true;
  const rect = section.getBoundingClientRect();
  return (
    clientX >= rect.left &&
    clientX <= rect.right &&
    clientY >= rect.top &&
    clientY <= rect.bottom
  );
}
