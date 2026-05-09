/**
 * PaneChrome — small top strip on every leaf with split / close / target.
 *
 * Sits *above* the function pane's own header (the design-system `Pane`
 * primitive). Round 16 promotes this into a draggable handle for relocating
 * a pane inside the tree.
 */
import { useState } from "react";
import { useWorkspace } from "@/lib/workspace";
import { useAppStore } from "@/lib/store";

interface Props {
  leafId: string;
  code: string;
  symbol?: string;
  linkGroup?: string;
}

const LINK_GROUPS = ["A", "B", "C", "D"] as const;

export function PaneChrome({ leafId, code, symbol, linkGroup }: Props) {
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
  const [picker, setPicker] = useState(false);
  const [linkPicker, setLinkPicker] = useState(false);

  return (
    <header
      onMouseDownCapture={() => setFocused(leafId)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 6px 4px 10px",
        borderBottom: "1px solid var(--border-subtle)",
        background: "var(--bg-elev-1)",
        height: 26,
        position: "relative",
      }}
    >
      <button
        type="button"
        onClick={() => setPicker((p) => !p)}
        title="Change pane target"
        style={{
          background: "transparent",
          border: "none",
          color: "var(--accent)",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          fontWeight: 700,
          padding: "0 4px",
          cursor: "default",
        }}
      >
        {code}
      </button>
      <span
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          color: "var(--text-secondary)",
        }}
      >
        {symbol ?? "—"}
      </span>
      {isFocused && (
        <span
          style={{
            marginLeft: 4,
            fontSize: 9,
            color: "var(--accent)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          focus
        </span>
      )}

      <div style={{ marginLeft: "auto", display: "flex", gap: 2, position: "relative" }}>
        <ChromeButton
          title={
            linkGroup
              ? `Linked · group ${linkGroup}`
              : "Link symbol with siblings"
          }
          onClick={() => setLinkPicker((p) => !p)}
          active={!!linkGroup}
        >
          {linkGroup ? `🔗${linkGroup}` : "🔗"}
        </ChromeButton>
        <ChromeButton
          title="Split right (⌘\\)"
          onClick={() => splitFocused("h")}
        >
          ▣
        </ChromeButton>
        <ChromeButton
          title="Split below (⌘⇧\\)"
          onClick={() => splitFocused("v")}
        >
          ☰
        </ChromeButton>
        <ChromeButton
          title="Close pane"
          onClick={() => {
            if (isOnlyLeaf) return;
            closeFocused();
          }}
          disabled={isOnlyLeaf}
        >
          ✕
        </ChromeButton>
        {linkPicker && (
          <div
            style={{
              position: "absolute",
              top: 22,
              right: 0,
              background: "var(--bg-elev-2)",
              border: "1px solid var(--border-strong)",
              borderRadius: "var(--radius-md)",
              boxShadow: "var(--shadow-elev)",
              padding: 6,
              display: "flex",
              gap: 4,
              zIndex: 1100,
            }}
          >
            {LINK_GROUPS.map((g) => (
              <button
                key={g}
                type="button"
                title={`Link group ${g}`}
                onClick={() => {
                  setLeafLinkGroup(leafId, linkGroup === g ? undefined : g);
                  setLinkPicker(false);
                }}
                style={{
                  width: 22,
                  height: 22,
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 11,
                  fontWeight: 700,
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  background:
                    linkGroup === g ? "var(--accent-soft)" : "var(--bg-elev-3)",
                  color: linkGroup === g ? "var(--accent)" : "var(--text-secondary)",
                  cursor: "default",
                }}
              >
                {g}
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                setLeafLinkGroup(leafId, undefined);
                setLinkPicker(false);
              }}
              title="Unlink"
              style={{
                width: 22,
                height: 22,
                fontSize: 11,
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                background: "var(--bg-elev-3)",
                color: "var(--text-mute)",
                cursor: "default",
              }}
            >
              ✕
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
    </header>
  );
}

function ChromeButton({
  children,
  onClick,
  title,
  disabled,
  active,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  disabled?: boolean;
  active?: boolean;
}) {
  const baseBg = active ? "var(--accent-soft)" : "transparent";
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      disabled={disabled}
      style={{
        width: 22,
        height: 18,
        background: baseBg,
        border: `1px solid ${active ? "var(--accent)" : "var(--border-subtle)"}`,
        borderRadius: "var(--radius-sm)",
        color: disabled
          ? "var(--text-mute)"
          : active
            ? "var(--accent)"
            : "var(--text-secondary)",
        fontSize: 10,
        cursor: "default",
        padding: 0,
        opacity: disabled ? 0.4 : 1,
        transition: "background var(--motion-fast)",
      }}
      onMouseEnter={(e) =>
        !disabled &&
        ((e.currentTarget as HTMLElement).style.background =
          active ? "var(--accent-soft)" : "var(--bg-elev-3)")
      }
      onMouseLeave={(e) =>
        ((e.currentTarget as HTMLElement).style.background = baseBg)
      }
    >
      {children}
    </button>
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
    <div
      style={{
        position: "absolute",
        top: 28,
        left: 8,
        background: "var(--bg-elev-2)",
        border: "1px solid var(--border-strong)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-elev)",
        zIndex: 1000,
        width: 320,
        maxHeight: 360,
        display: "flex",
        flexDirection: "column",
      }}
      onBlur={onDismiss}
    >
      <input
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter functions…"
        onKeyDown={(e) => e.key === "Escape" && onDismiss()}
        style={{
          background: "transparent",
          border: "none",
          color: "var(--text-primary)",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 12,
          padding: "8px 10px",
          outline: "none",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      />
      <div style={{ overflowY: "auto" }}>
        {filtered.map((o) => (
          <button
            key={o.code}
            type="button"
            onClick={() => onPick(o.code)}
            style={{
              display: "grid",
              gridTemplateColumns: "70px 1fr",
              gap: 8,
              padding: "6px 10px",
              width: "100%",
              background: o.code === current ? "var(--bg-elev-3)" : "transparent",
              border: "none",
              color: "var(--text-primary)",
              cursor: "default",
              textAlign: "left",
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 11,
            }}
          >
            <span style={{ color: "var(--accent)", fontWeight: 700 }}>
              {o.code}
            </span>
            <span>{o.name}</span>
          </button>
        ))}
        {!filtered.length && (
          <div
            style={{
              padding: 16,
              color: "var(--text-mute)",
              fontSize: 11,
              textAlign: "center",
            }}
          >
            no matches
          </div>
        )}
      </div>
    </div>
  );
}
