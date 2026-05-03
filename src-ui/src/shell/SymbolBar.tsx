import { useEffect, useState } from "react";
import {
  listRecentSymbols,
  normalizeSymbolInput,
  pushRecentSymbol,
  removeRecentSymbol,
} from "@/lib/symbols";
import { navigate } from "@/lib/router";
import { Pill } from "@/design-system";

interface SymbolBarProps {
  code: string;
  symbol?: string;
}

export function SymbolBar({ code, symbol }: SymbolBarProps) {
  const [draft, setDraft] = useState(
    () => normalizeSymbolInput(symbol) || listRecentSymbols()[0] || "AAPL",
  );
  const [recent, setRecent] = useState<string[]>(() => listRecentSymbols());

  useEffect(() => {
    const normalized = normalizeSymbolInput(symbol);
    if (normalized) {
      setDraft(normalized);
      return;
    }
    setDraft((current) => current || listRecentSymbols()[0] || "AAPL");
  }, [symbol]);
  useEffect(() => {
    if (symbol) pushRecentSymbol(symbol);
    setRecent(listRecentSymbols());
  }, [symbol]);

  const submit = (sym: string) => {
    const next = normalizeSymbolInput(sym);
    if (!next) return;
    pushRecentSymbol(next);
    navigate(`/symbol/${next}/${code}`);
    setRecent(listRecentSymbols());
  };

  const removeSymbol = (sym: string) => {
    const next = normalizeSymbolInput(sym);
    removeRecentSymbol(next);
    setRecent(listRecentSymbols());
    if (next === normalizeSymbolInput(symbol)) {
      setDraft("");
      navigate(`/fn/${code}`);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 14px",
        borderBottom: "1px solid var(--border-subtle)",
        background: "var(--bg-elev-2)",
        minWidth: 0,
      }}
    >
      <span
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--text-mute)",
        }}
      >
        Symbol
      </span>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
        }}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          background: "var(--bg-elev-3)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          padding: "0 8px",
          height: 24,
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="AAPL"
          style={{
            background: "transparent",
            border: "none",
            outline: "none",
            color: "var(--text-primary)",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 12,
            width: 120,
            textTransform: "uppercase",
          }}
        />
        <button
          type="submit"
          onClick={() => submit(draft)}
          style={{
            background: "var(--accent)",
            color: "#000",
            border: "none",
            borderRadius: "var(--radius-sm)",
            fontSize: 10,
            padding: "2px 6px",
            cursor: "default",
            fontWeight: 700,
          }}
        >
          GO
        </button>
      </form>

      <div
        style={{
          display: "flex",
          gap: 4,
          marginLeft: 12,
          minWidth: 0,
          flex: "1 1 auto",
          flexWrap: "wrap",
        }}
      >
        {recent.slice(0, 6).map((s) => (
          <span
            key={s}
            style={{
              display: "inline-flex",
              alignItems: "center",
              background:
                s === symbol ? "var(--accent-soft)" : "var(--bg-elev-3)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              overflow: "hidden",
            }}
          >
            <button
              type="button"
              onClick={() => submit(s)}
              style={{
                background: "transparent",
                border: "none",
                color: s === symbol ? "var(--accent)" : "var(--text-secondary)",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 11,
                padding: "2px 7px",
                cursor: "default",
                height: 22,
              }}
              title={`Open ${s}/${code}`}
            >
              {s}
            </button>
            <button
              type="button"
              aria-label={`Remove ${s}`}
              onClick={(e) => {
                e.stopPropagation();
                removeSymbol(s);
              }}
              style={{
                background: "transparent",
                border: "none",
                borderLeft: "1px solid var(--border-subtle)",
                color: "var(--text-mute)",
                cursor: "default",
                fontSize: 12,
                height: 22,
                lineHeight: "20px",
                padding: "0 6px",
              }}
              title={`Remove ${s}`}
            >
              x
            </button>
          </span>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Pill tone="accent" withDot={false}>
          {code}
        </Pill>
      </div>
    </div>
  );
}
