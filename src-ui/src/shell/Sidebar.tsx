import { useMemo, useState } from "react";
import { useAppStore } from "@/lib/store";
import type { FunctionEntry } from "@/lib/sidecar";
import { navigate } from "@/lib/router";
import { listNativeCodes } from "@/functions/registry";

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
  const [query, setQuery] = useState("");
  const [peekOpen, setPeekOpen] = useState(false);
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
            <span>FN</span>
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
  onHide,
  onPin,
  onClose,
}: SidebarPanelProps) {
  return (
    <aside className={`sidebar sidebar--${variant}`}>
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 2,
          padding: "10px 12px 8px",
          background: "linear-gradient(180deg, rgba(7,8,10,0.98), rgba(7,8,10,0.88))",
          borderBottom: "1px solid var(--border-subtle)",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          letterSpacing: "0.04em",
          color: "var(--text-secondary)",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr auto",
            alignItems: "center",
            gap: 8,
          }}
        >
          <div>
            FUNCTIONS
            <span style={{ marginLeft: 8, color: "var(--text-mute)" }}>
              {filteredCount}/{total}
            </span>
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            {variant === "popup" && (
              <button
                type="button"
                className="sidebar-toggle-button"
                onClick={onPin}
                title="Dock functions panel"
              >
                &gt;
              </button>
            )}
            <button
              type="button"
              className="sidebar-toggle-button"
              onClick={variant === "docked" ? onHide : onClose}
              title={variant === "docked" ? "Hide functions panel" : "Close preview"}
            >
              {variant === "docked" ? "<" : "x"}
            </button>
          </div>
        </div>
        <div
          style={{
            marginTop: 8,
            display: "flex",
            alignItems: "center",
            gap: 6,
            border: "1px solid var(--border-subtle)",
            background: "rgba(255,255,255,0.035)",
            borderRadius: "var(--radius-sm)",
            padding: "0 8px",
            height: 26,
          }}
        >
          <span style={{ color: "var(--accent)" }}>/</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="code, name, category"
            style={{
              width: "100%",
              background: "transparent",
              border: "none",
              color: "var(--text-primary)",
              font: "inherit",
              fontSize: 11,
            }}
            />
        </div>
        <button
          type="button"
          className="btn btn--accent"
          onClick={() => navigate("/fn/AGENT")}
          style={{
            marginTop: 8,
            width: "100%",
            height: 26,
            padding: "0 10px",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 11,
          }}
        >
          AGENT
        </button>
      </div>

      {total === 0 && (
        <div
          style={{
            padding: "0 14px",
            color: "var(--text-mute)",
            fontSize: 11,
          }}
        >
          (waiting for sidecar…)
        </div>
      )}

      {grouped.map(([cat, items]) => (
        <section key={cat} style={{ padding: "6px 0 12px" }}>
          <div
            style={{
              padding: "0 14px",
              fontSize: 10,
              letterSpacing: "0.08em",
              color: "var(--accent)",
              textTransform: "uppercase",
              marginBottom: 4,
            }}
          >
            {cat}
            <span style={{ float: "right", color: "var(--text-mute)" }}>
              {items.length}
            </span>
          </div>
          {items.map((it) => (
            <button
              type="button"
              key={it.code}
              onClick={() => navigate(`/fn/${it.code}`)}
              className="sidebar-function"
              style={{
                width: "100%",
                background: "transparent",
                border: "none",
                textAlign: "left",
                padding: "4px 12px",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 11,
                color: "var(--text-secondary)",
                cursor: "default",
                display: "grid",
                gridTemplateColumns: "minmax(44px, auto) 1fr auto",
                gap: 8,
                alignItems: "center",
              }}
              title={it.name}
            >
              <strong style={{ color: "var(--text-primary)" }}>{it.code}</strong>
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {it.name}
              </span>
              {nativeCodes.has(it.code) && (
                <span style={{ color: "var(--positive)", fontSize: 9 }}>N</span>
              )}
            </button>
          ))}
        </section>
      ))}
    </aside>
  );
}
