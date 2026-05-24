/**
 * PaneChrome — small top strip on every leaf with split / close / target.
 *
 * Sits *above* the function pane's own header (the design-system `Pane`
 * primitive). Round 16 promotes this into a draggable handle for relocating
 * a pane inside the tree.
 */
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useWorkspace } from "@/lib/workspace";
import { useAppStore } from "@/lib/store";
import { t } from "@/i18n";
import { useFocusTrap } from "@/lib/a11y";
import {
  makePinnedItemForPane,
  pinItem,
  togglePinnedItem,
  usePinnedItems,
  writePinnedDragData,
} from "@/lib/pins";

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

const LINK_GROUPS = ["A", "B", "C", "D"] as const;

export function PaneChrome({ leafId, code, symbol, linkGroup }: PaneChromeProps) {
  const splitFocused = useWorkspace((s) => s.splitFocused);
  const closeFocused = useWorkspace((s) => s.closeFocused);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const setLeafLinkGroup = useWorkspace((s) => s.setLeafLinkGroup);
  const setFocused = useWorkspace((s) => s.setFocused);
  const tree = useWorkspace((s) => s.tree);
  const focusedId = useWorkspace((s) => s.focusedId);
  const isFocused = leafId === focusedId;
  const isOnlyLeaf = tree.kind === "leaf";
  const idx = useAppStore((s) => s.functionIndex);
  const pinnedItems = usePinnedItems();
  const [picker, setPicker] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dragPreview, setDragPreview] = useState<PaneDragPreview | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // A11Y: trap Tab inside the dropdown so screen-reader / keyboard users
  // can't escape into the underlying chrome. Escape handler already wired
  // on the parent action wrapper; this complements it. Restores focus to
  // the trigger on close.
  useFocusTrap(menuRef, menuOpen);
  const pinTarget = useMemo(
    () => makePinnedItemForPane(code, symbol, idx),
    [code, idx, symbol],
  );
  const currentIsPinned = pinnedItems.some((item) => item.id === pinTarget.id);
  const runMenuAction = (action: () => void) => {
    action();
    setMenuOpen(false);
  };
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
      <span className="pane-chrome__symbol">{symbol ?? "—"}</span>
      {isFocused && <span className="pane-chrome__focus">focus</span>}

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
          onClick={() => setMenuOpen((open) => !open)}
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
  const filtered = !query.trim()
    ? options.slice(0, 30)
    : options
        .filter(
          (o) =>
            o.code.toLowerCase().includes(query.toLowerCase()) ||
            o.name.toLowerCase().includes(query.toLowerCase()),
        )
        .slice(0, 30);
  return (
    <div className="picker-popup" onBlur={onDismiss}>
      <input
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter functions…"
        aria-label="Filter functions"
        onKeyDown={(e) => e.key === "Escape" && onDismiss()}
        className="picker-popup__input"
      />
      <div className="picker-popup__list">
        {filtered.map((o) => (
          <button
            key={o.code}
            type="button"
            onClick={() => onPick(o.code)}
            className={`picker-popup__row${o.code === current ? " picker-popup__row--active" : ""}`}
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
