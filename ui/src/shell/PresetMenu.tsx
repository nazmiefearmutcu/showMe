/**
 * PresetMenu — small dropdown over the titlebar for save / load / delete
 * named workspace layouts. Round 16 swaps the storage backend (localStorage
 * → Tauri filesystem) without touching this component.
 *
 * UI-finish wave F (2026-09-09): adds "Reset to default desk" — loads the
 * canonical `home` builtin preset (the pristine single-HOME cold-boot desk)
 * through the existing loadBuiltinPreset path. Destructive (discards the
 * live tree), so it confirms via the shared design-system ConfirmDialog —
 * the same non-blocking, focus-trapped pattern STRA/BOT use; the native
 * window.confirm() is banned project-wide.
 */
import { useEffect, useRef, useState } from "react";
import { listPresets, loadPreset, savePreset, deletePreset } from "@/lib/presets";
import { loadBuiltinPreset } from "@/lib/builtinPresets";
import { ConfirmDialog } from "@/design-system";
import { toast } from "@/lib/toast";
import { useEscape, useFocusTrap } from "@/lib/a11y";

import type { PresetSummary } from "@/lib/presets";

export function PresetMenu() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [presets, setPresets] = useState<PresetSummary[]>([]);
  const [confirmReset, setConfirmReset] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  const refresh = () => {
    listPresets().then(setPresets).catch(() => setPresets([]));
  };

  useEffect(() => {
    if (open) refresh();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  // A11Y — Esc closes the dropdown; Tab is trapped inside while open.
  // While the destructive-reset confirm is up, Esc belongs to the dialog
  // alone (it cancels the reset; the menu stays put).
  useEscape(open && !confirmReset, () => setOpen(false));
  useFocusTrap(popupRef, open && !confirmReset);

  const onSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await savePreset(trimmed);
      toast.success("Preset saved", trimmed);
      refresh();
      setName("");
    } catch (err) {
      toast.error("Save failed", String(err));
    }
  };

  const onResetConfirmed = () => {
    setConfirmReset(false);
    if (!loadBuiltinPreset("home")) {
      toast.error("Preset 'home' not available");
      return;
    }
    toast.info("Layout loaded", "Default Desk");
    setOpen(false);
  };

  return (
    <div ref={ref} className="u-position-relative interactive" >
      <button
        type="button"
        className="btn btn--ghost"
        onClick={() => setOpen((o) => !o)}
        title="Layout presets"
      >
        ⌘ Layout
      </button>
      {open && (
        <div
          ref={popupRef}
          className="preset-menu"
          role="dialog"
          aria-label="Layout presets"
          data-testid="preset-menu-popup"
        >
          <div className="preset-menu__head">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Preset name"
              onKeyDown={(e) => e.key === "Enter" && onSave()}
              className="preset-menu__input"
            />
            <button
              type="button"
              onClick={onSave}
              disabled={!name.trim()}
              className="btn btn--accent u-btn-mini"
            >
              Save
            </button>
          </div>
          <div className="preset-menu__list">
            {presets.length === 0 && (
              <div className="preset-menu__empty">no presets yet</div>
            )}
            {presets.map((p) => (
              <div key={p.name} className="preset-menu__row">
                <button
                  type="button"
                  onClick={async () => {
                    if (await loadPreset(p.name))
                      toast.info("Layout loaded", p.name);
                    setOpen(false);
                  }}
                  className="preset-menu__row-btn"
                  title={`Saved ${p.savedAt}`}
                >
                  {p.name}
                </button>
                <span className="u-text-mute u-text-10">
                  {p.savedAt.slice(0, 10)}
                </span>
                <button
                  type="button"
                  onClick={async () => {
                    if (await deletePreset(p.name)) {
                      toast.warn("Deleted", p.name);
                      refresh();
                    }
                  }}
                  title="Delete preset"
                  className="preset-menu__delete"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
          {/* Reset to the canonical default desk (single HOME leaf).
              Destructive — discards the live layout — hence the confirm.
              Inline token styles: the .preset-menu rules live in
              styles/index.css, which this lane does not touch. */}
          <div
            className="preset-menu__footer"
            style={{
              borderTop: "1px solid var(--border-subtle)",
              padding: "var(--space-3) var(--space-3)",
            }}
          >
            <button
              type="button"
              className="preset-menu__row-btn"
              data-testid="preset-menu-reset"
              onClick={() => setConfirmReset(true)}
              title="Discard the current layout and load the default desk"
              style={{ color: "var(--negative-hex)", cursor: "pointer", width: "100%" }}
            >
              Reset to default desk
            </button>
          </div>
        </div>
      )}
      <ConfirmDialog
        open={confirmReset}
        title="Reset to default desk?"
        body="The current layout will be discarded and replaced with the default single-pane desk. Saved presets are kept."
        confirmLabel="Reset"
        cancelLabel="Cancel"
        destructive
        onConfirm={onResetConfirmed}
        onCancel={() => setConfirmReset(false)}
      />
    </div>
  );
}
