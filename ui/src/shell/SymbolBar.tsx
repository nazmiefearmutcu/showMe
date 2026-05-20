import { useEffect, useState } from "react";
import {
  listRecentSymbols,
  normalizeSymbolInput,
  pushRecentSymbol,
  removeRecentSymbol,
} from "@/lib/symbols";
import { resolveSymbolInput } from "@/lib/symbol-resolver";
import { navigate } from "@/lib/router";
import { Pill } from "@/design-system";

interface SymbolBarProps {
  code: string;
  symbol?: string;
}

const MARKET_SYMBOL_OPTIONS = [
  "AAPL",
  "MSFT",
  "NVDA",
  "TSLA",
  "SPY",
  "QQQ",
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "ethereum",
  "solana",
  "pepe",
  "dogwifhat",
  "flock",
  "EURUSD",
  "GBPUSD=X",
  "GC=F",
  "CL=F",
  "US10Y",
];

export function SymbolBar({ code, symbol }: SymbolBarProps) {
  const [draft, setDraft] = useState(
    () => normalizeSymbolInput(symbol) || listRecentSymbols()[0] || "AAPL",
  );
  const [recent, setRecent] = useState<string[]>(() => listRecentSymbols());
  const suggestions = Array.from(
    new Set([
      normalizeSymbolInput(symbol),
      ...recent,
      ...MARKET_SYMBOL_OPTIONS,
    ].filter(Boolean)),
  ).slice(0, 24);

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

  const submit = async (sym: string) => {
    const next = await resolveSymbolInput(sym);
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
    <div className="symbol-bar-host">
      <span className="symbol-bar-host__label">Symbol</span>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit(draft);
        }}
        className="symbol-bar-host__form"
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="AAPL"
          list={`symbol-bar-options-${code}`}
          className="symbol-bar-host__input"
        />
        <datalist id={`symbol-bar-options-${code}`}>
          {suggestions.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
        <button type="submit" className="symbol-bar-host__go">GO</button>
      </form>

      <div className="symbol-bar-host__recents">
        {recent.slice(0, 6).map((s) => (
          <span
            key={s}
            className={`symbol-bar-chip${s === symbol ? " symbol-bar-chip--active" : ""}`}
          >
            <button
              type="button"
              onClick={() => void submit(s)}
              className={`symbol-bar-chip__btn${s === symbol ? " symbol-bar-chip__btn--active" : ""}`}
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
              className="symbol-bar-chip__remove"
              title={`Remove ${s}`}
            >
              x
            </button>
          </span>
        ))}
      </div>

      <div className="u-inline-flex u-items-center u-gap-6">
        <Pill tone="accent" withDot={false}>
          {code}
        </Pill>
      </div>
    </div>
  );
}
