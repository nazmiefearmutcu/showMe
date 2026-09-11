/**
 * ISIN — Symbol Cross-Reference.
 *
 * Resolves an ISIN / CUSIP / SEDOL / ticker to OpenFIGI canonical
 * records (backend api/isin.py, keyless live provider). One input ->
 * a group of ranked match cards (FIGI, composite FIGI, share-class
 * FIGI, ticker, exchange, sector, security type). The last 5 lookups
 * persist in localStorage and re-run on click. The backend validates
 * ISIN check digits and detects the ID type — the pane never guesses.
 */
import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface ISINMatch {
  figi?: string | null;
  ticker?: string | null;
  name?: string | null;
  marketSector?: string | null;
  securityType?: string | null;
  securityType2?: string | null;
  exchCode?: string | null;
  compositeFIGI?: string | null;
  shareClassFIGI?: string | null;
}

interface ISINGroup {
  input?: string;
  id_type?: string;
  error?: string;
  matches?: ISINMatch[];
}

interface ISINRow {
  input?: string;
  id_type?: string;
  rank?: string;
  figi?: string | null;
  ticker?: string | null;
  name?: string | null;
  exchange?: string | null;
}

interface ISINData {
  status?: string;
  reason?: string;
  rows?: ISINRow[];
  match_groups?: ISINGroup[];
  next_actions?: string[];
}

const HISTORY_KEY = "showme.isin.history";
const HISTORY_MAX = 5;
const DEFAULT_INPUT = "US0378331005";

function readHistory(): string[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is string => typeof item === "string" && item.length > 0)
      .slice(0, HISTORY_MAX);
  } catch {
    return [];
  }
}

function writeHistory(values: string[]): string[] {
  const next = values.slice(0, HISTORY_MAX);
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable — history just does not persist */
  }
  return next;
}

export function ISINPane({ code, symbol }: FunctionPaneProps) {
  const [input, setInput] = useState(() => (symbol || "").trim() || DEFAULT_INPUT);
  const [lookup, setLookup] = useState(() => (symbol || "").trim() || DEFAULT_INPUT);
  const [history, setHistory] = useState<string[]>(readHistory);
  const { state, data, error, refetch } = useFunction<ISINData>({
    code,
    params: { ids: lookup },
    enabled: lookup.length > 0,
  });

  const payload = data?.data;
  const groups: ISINGroup[] = useMemo(
    () => payload?.match_groups ?? [],
    [payload],
  );
  const status = payload?.status ?? "—";

  // Persist the lookup once a result resolves OK (dedupe, most recent first).
  useEffect(() => {
    if (state !== "ok" || status !== "ok") return;
    const value = lookup.trim();
    if (!value) return;
    setHistory((prev) => {
      const next = [value, ...prev.filter((item) => item !== value)].slice(0, HISTORY_MAX);
      return writeHistory(next);
    });
  }, [state, status, lookup]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = input.trim();
    if (!next) return;
    setLookup(next);
  }

  function lookupFromHistory(value: string) {
    setInput(value);
    setLookup(value);
  }

  const matchCount = payload?.rows?.length ?? 0;

  const body = lookup.length === 0 ? (
    <Empty
      title="Identifier required"
      body="Enter a ticker such as AAPL or an ISIN such as US0378331005."
      icon="⌖"
    />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={72} />
      <Skeleton height={72} />
      <Skeleton height={72} width="80%" />
    </div>
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? "—"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : status === "provider_unavailable" ? (
    <Empty
      title="OpenFIGI unavailable"
      body={payload?.reason ?? "The OpenFIGI adapter is not configured."}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : groups.length === 0 || matchCount === 0 ? (
    <Empty
      title="No OpenFIGI matches"
      body={
        payload?.next_actions?.[0] ??
        "Try ID Type TICKER for common symbols such as AAPL, MSFT, or SPY."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {groups.map((group) => {
        const inputLabel = group.input ?? lookup;
        return (
          <section key={inputLabel} aria-label={`Cross-ID results for ${inputLabel}`}>
            <div style={groupHeaderStyle}>
              <span style={monoStrongStyle}>{inputLabel}</span>
              {group.id_type ? (
                <Pill tone="accent" variant="soft" withDot={false}>
                  {group.id_type}
                </Pill>
              ) : null}
              <span style={monoMutedStyle}>
                {group.error
                  ? `lookup failed: ${group.error}`
                  : `${group.matches?.length ?? 0} exchange-level match(es)`}
              </span>
            </div>
            <div style={cardGridStyle}>
              {(group.matches ?? []).map((match, idx) => (
                <div
                  key={`${inputLabel}-${match.figi ?? idx}`}
                  style={cardStyle}
                  aria-label={`Match ${idx + 1} for ${inputLabel}: ${match.ticker ?? "unknown"} on ${match.exchCode ?? "unknown exchange"}`}
                >
                  <div style={cardTopStyle}>
                    <span style={monoStrongStyle}>{match.ticker ?? "—"}</span>
                    <Pill tone="muted" variant="soft" withDot={false}>
                      #{idx + 1}
                    </Pill>
                  </div>
                  <div style={cardNameStyle}>{match.name ?? "—"}</div>
                  <dl style={dlStyle}>
                    <div style={dlRowStyle}>
                      <dt style={dtStyle}>FIGI</dt>
                      <dd style={ddStyle}>{match.figi ?? "—"}</dd>
                    </div>
                    <div style={dlRowStyle}>
                      <dt style={dtStyle}>Composite</dt>
                      <dd style={ddStyle}>{match.compositeFIGI ?? "—"}</dd>
                    </div>
                    <div style={dlRowStyle}>
                      <dt style={dtStyle}>Share class</dt>
                      <dd style={ddStyle}>{match.shareClassFIGI ?? "—"}</dd>
                    </div>
                    <div style={dlRowStyle}>
                      <dt style={dtStyle}>Exchange</dt>
                      <dd style={ddStyle}>{match.exchCode ?? "—"}</dd>
                    </div>
                    <div style={dlRowStyle}>
                      <dt style={dtStyle}>Sector</dt>
                      <dd style={ddStyle}>{match.marketSector ?? "—"}</dd>
                    </div>
                    <div style={dlRowStyle}>
                      <dt style={dtStyle}>Type</dt>
                      <dd style={ddStyle}>{match.securityType ?? "—"}</dd>
                    </div>
                  </dl>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Symbol Cross-Reference"
          subtitle={`OpenFIGI cross-ID · ${matchCount} match(es) · ${lookup}`}
          trailing={
            <FunctionControlGroup>
              <form onSubmit={submit} style={formStyle}>
                <input
                  type="search"
                  aria-label="Identifier to cross-reference"
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="ISIN / CUSIP / SEDOL / ticker"
                  style={inputStyle}
                />
                <button type="submit" className="btn" title="Run OpenFIGI lookup">
                  Look up
                </button>
              </form>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={lookup.length === 0}
                title="Re-run OpenFIGI lookup"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {body}
          {history.length > 0 ? (
            <div
              style={historyRowStyle}
              role="group"
              aria-label="Lookup history"
            >
              <span style={historyLabelStyle}>RECENT</span>
              {history.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="fn-segmented__opt"
                  onClick={() => lookupFromHistory(item)}
                  title={`Re-run lookup ${item}`}
                >
                  {item}
                </button>
              ))}
            </div>
          ) : null}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="matches" value={matchCount} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="input" value={lookup} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const formStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const inputStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
  height: 24,
  padding: "0 6px",
  width: 200,
};

const historyRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
  marginTop: 12,
};

const historyLabelStyle: CSSProperties = {
  padding: "0 5px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
  whiteSpace: "nowrap",
};

const groupHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginBottom: 8,
  flexWrap: "wrap",
};

const cardGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
  gap: 10,
};

const cardStyle: CSSProperties = {
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 10,
  display: "grid",
  gap: 6,
};

const cardTopStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const cardNameStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
};

const dlStyle: CSSProperties = {
  margin: 0,
  display: "grid",
  gap: 2,
};

const dlRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 8,
};

const dtStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-xs)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};

const ddStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
  fontSize: "var(--font-size-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  overflowWrap: "anywhere",
  textAlign: "right",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};
