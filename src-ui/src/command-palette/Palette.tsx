import { useEffect, useMemo, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";
import { navigate } from "@/lib/router";
import { t } from "@/i18n";

interface PaletteEntry {
  id: string;
  code: string;
  name: string;
  category: string;
  hash: string;
}

const STATIC_ENTRIES: PaletteEntry[] = [
  {
    id: "system.preferences",
    code: "PREF",
    name: "Preferences",
    category: "system",
    hash: "/preferences",
  },
  {
    id: "system.welcome",
    code: "HOME",
    name: "Welcome",
    category: "system",
    hash: "/",
  },
];

export function CommandPalette() {
  const open = useAppStore((s) => s.paletteOpen);
  const togglePalette = useAppStore((s) => s.togglePalette);
  const items = useAppStore((s) => s.functionIndex);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const all: PaletteEntry[] = useMemo(
    () => [
      ...STATIC_ENTRIES,
      ...items.map((i) => ({
        id: `fn.${i.code}`,
        code: i.code,
        name: i.name,
        category: i.category,
        hash: `/fn/${i.code}`,
      })),
    ],
    [items],
  );

  const filtered = useMemo(() => {
    if (!query.trim()) return all.slice(0, 60);
    const needle = query.toLowerCase();
    return all
      .filter(
        (i) =>
          i.code.toLowerCase().includes(needle) ||
          i.name.toLowerCase().includes(needle) ||
          i.category.toLowerCase().includes(needle),
      )
      .slice(0, 60);
  }, [all, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") togglePalette(false);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        togglePalette();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [togglePalette]);

  if (!open) return null;

  const choose = (entry: PaletteEntry) => {
    navigate(entry.hash);
    togglePalette(false);
  };

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const sel = filtered[cursor];
      if (sel) choose(sel);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        zIndex: 9000,
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        paddingTop: "14vh",
        backdropFilter: "blur(6px)",
      }}
      onClick={() => togglePalette(false)}
    >
      <div
        className="surface"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onListKey}
        style={{
          width: "560px",
          maxHeight: "62vh",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          boxShadow: "var(--shadow-elev)",
        }}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("shell.palette.placeholder")}
          style={{
            background: "transparent",
            border: "none",
            color: "var(--text-primary)",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 14,
            padding: "16px 20px",
            outline: "none",
            borderBottom: "1px solid var(--border-subtle)",
          }}
        />
        <div style={{ overflowY: "auto", padding: "4px 0" }}>
          {filtered.length === 0 && (
            <div
              style={{
                padding: "24px 20px",
                color: "var(--text-mute)",
                fontSize: 12,
              }}
            >
              {t("shell.palette.empty")}
            </div>
          )}
          {filtered.map((it, i) => {
            const isCursor = i === cursor;
            return (
              <div
                key={it.id}
                role="option"
                aria-selected={isCursor}
                onMouseEnter={() => setCursor(i)}
                onClick={() => choose(it)}
                style={{
                  padding: "8px 20px",
                  display: "flex",
                  gap: 12,
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 12,
                  cursor: "default",
                  background: isCursor ? "var(--bg-elev-2)" : "transparent",
                  borderLeft: isCursor
                    ? "2px solid var(--accent)"
                    : "2px solid transparent",
                }}
              >
                <span
                  style={{
                    color: "var(--accent)",
                    width: 80,
                    fontWeight: 600,
                  }}
                >
                  {it.code}
                </span>
                <span style={{ color: "var(--text-primary)" }}>{it.name}</span>
                <span
                  style={{
                    marginLeft: "auto",
                    color: "var(--text-mute)",
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                  }}
                >
                  {it.category}
                </span>
              </div>
            );
          })}
        </div>
        <div
          style={{
            padding: "8px 16px",
            borderTop: "1px solid var(--border-subtle)",
            fontSize: 10,
            color: "var(--text-mute)",
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span>
            <span className="kbd">↑↓</span> {t("shell.palette.navigate")} ·{" "}
            <span className="kbd">↵</span> {t("shell.palette.open")}
          </span>
          <span>
            <span className="kbd">esc</span> {t("shell.palette.close")}
          </span>
        </div>
      </div>
    </div>
  );
}
