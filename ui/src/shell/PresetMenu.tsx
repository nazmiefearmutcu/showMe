/**
 * PresetMenu — small dropdown over the titlebar for save / load / delete
 * named workspace layouts. Round 16 swaps the storage backend (localStorage
 * → Tauri filesystem) without touching this component.
 */
import { useEffect, useRef, useState } from "react";
import { listPresets, loadPreset, savePreset, deletePreset } from "@/lib/presets";
import { toast } from "@/lib/toast";

import type { PresetSummary } from "@/lib/presets";

export function PresetMenu() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [presets, setPresets] = useState<PresetSummary[]>([]);
  const ref = useRef<HTMLDivElement>(null);

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

  return (
    <div ref={ref} style={{ position: "relative" }} className="interactive">
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
          style={{
            position: "absolute",
            top: 28,
            right: 0,
            background: "var(--bg-elev-2)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--radius-md)",
            boxShadow: "var(--shadow-elev)",
            width: 280,
            zIndex: 1000,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              padding: "8px 10px",
              borderBottom: "1px solid var(--border-subtle)",
              display: "flex",
              gap: 6,
            }}
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Preset name"
              onKeyDown={(e) => e.key === "Enter" && onSave()}
              style={{
                flex: 1,
                background: "var(--bg-elev-3)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-primary)",
                font: "inherit",
                fontSize: 11,
                padding: "2px 6px",
                outline: "none",
              }}
            />
            <button
              type="button"
              onClick={onSave}
              disabled={!name.trim()}
              className="btn btn--accent"
              style={{ height: 22, fontSize: 10 }}
            >
              Save
            </button>
          </div>
          <div style={{ maxHeight: 280, overflowY: "auto" }}>
            {presets.length === 0 && (
              <div
                style={{
                  padding: 12,
                  color: "var(--text-mute)",
                  fontSize: 11,
                  textAlign: "center",
                }}
              >
                no presets yet
              </div>
            )}
            {presets.map((p) => (
              <div
                key={p.name}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto auto",
                  gap: 6,
                  padding: "6px 10px",
                  borderBottom: "1px solid var(--border-subtle)",
                  fontSize: 11,
                  alignItems: "center",
                }}
              >
                <button
                  type="button"
                  onClick={async () => {
                    if (await loadPreset(p.name))
                      toast.info("Layout loaded", p.name);
                    setOpen(false);
                  }}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--text-primary)",
                    fontFamily: "JetBrains Mono, monospace",
                    cursor: "default",
                    textAlign: "left",
                    padding: 0,
                  }}
                  title={`Saved ${p.savedAt}`}
                >
                  {p.name}
                </button>
                <span style={{ color: "var(--text-mute)", fontSize: 10 }}>
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
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--text-mute)",
                    fontSize: 10,
                    cursor: "default",
                    padding: 0,
                  }}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
