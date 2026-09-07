/**
 * APPL — Industry Taxonomy (classification chain + reference peers).
 *
 * Header: SYNTHETIC/LIVE honesty pill + TABLE view segmented control (all
 * levels / crosswalk rows only) + status pill + refresh. Body: a prominent
 * "Synthetic / reference data" banner whenever the payload is the bundled
 * taxonomy model (status "reference_taxonomy" — the survey probe confirmed
 * the sidecar serves this even with live=true), the GICS classification
 * chain as a breadcrumb (sector → industry group → industry → sub-industry,
 * falling back to provider sector/industry fields when no crosswalk exists),
 * the reference sector peer list, and a dense level/classification/source
 * table.
 *
 * Data honesty: in a reference-taxonomy payload even rows stamped
 * "live_yfinance" are bundled template labels, so the pane re-stamps every
 * non-ok payload's source pills as "reference_taxonomy_model" instead of
 * echoing a live label it cannot verify. Peer chips are labelled reference
 * sector peers, never a verified comparables set.
 */
import { useMemo, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
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
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface APPLRow {
  level?: string;
  classification?: string | null;
  raw_code?: string | null;
  source_mode?: string;
}

interface APPLPeer {
  symbol?: string;
  peer_set?: string;
}

interface APPLData {
  status?: string;
  sector?: string | null;
  industry?: string | null;
  exchange?: string | null;
  exchange_name?: string | null;
  rows?: APPLRow[];
  peers?: APPLPeer[];
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

type ViewFilter = "all" | "crosswalk";

// Honesty re-stamp: a reference-taxonomy payload's "live_yfinance" row
// labels are bundled template values, not verified provider fields.
function sourceLabelFor(r: APPLRow, synthetic: boolean): string {
  const mode = r.source_mode ?? "";
  if (!synthetic || mode.includes("reference")) return mode || "—";
  return "reference_taxonomy_model";
}

const VIEW_OPTIONS = [
  { value: "all", label: "ALL LEVELS" },
  { value: "crosswalk", label: "CROSSWALK" },
] as const satisfies readonly { value: ViewFilter; label: string }[];
const VIEW_IDS = VIEW_OPTIONS.map((o) => o.value);

const CHAIN_LEVELS = [
  "GICS sector",
  "GICS industry group",
  "GICS industry",
  "GICS sub-industry",
] as const;

function isCrosswalkRow(level: string | null | undefined): boolean {
  const l = String(level ?? "");
  return (
    l.startsWith("GICS") || l === "NAICS" || l === "ICB"
  );
}

export function APPLPane({ code, symbol }: FunctionPaneProps) {
  const [viewFilter, setViewFilter] = usePersistentOption<ViewFilter>(
    "showme.appl.view",
    VIEW_IDS,
    "all",
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<APPLData>({
    code,
    symbol: effectiveSymbol,
    params: { live: true },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: APPLRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const isSynthetic = state === "ok" && status !== "ok";

  const chain = useMemo(
    () =>
      CHAIN_LEVELS.map((level) => ({
        level,
        value: rows.find((r) => r.level === level)?.classification ?? null,
      })),
    [rows],
  );
  const hasCrosswalk = chain.some((c) => c.value != null);
  const displayChain = useMemo(() => {
    if (hasCrosswalk) return chain;
    const provider = rows.filter((r) =>
      String(r.level ?? "").startsWith("Provider"),
    );
    return provider.length
      ? provider.map((r) => ({
          level: String(r.level ?? ""),
          value: r.classification ?? null,
        }))
      : [];
  }, [chain, hasCrosswalk, rows]);

  const peers = useMemo(() => payload?.peers ?? [], [payload]);

  const filtered = useMemo(
    () =>
      viewFilter === "all"
        ? rows
        : rows.filter((r) => isCrosswalkRow(r.level)),
    [rows, viewFilter],
  );

  const COLS: DataGridColumn<APPLRow>[] = useMemo(
    () => [
      {
        key: "level",
        header: "Level",
        width: 220,
        render: (r) => (
          <span style={monoPrimaryStyle}>{r.level ?? "—"}</span>
        ),
      },
      {
        key: "classification",
        header: "Classification",
        width: 420,
        render: (r) => (
          <span style={monoStrongStyle}>{r.classification ?? "—"}</span>
        ),
      },
      {
        key: "source",
        header: "Source",
        width: 260,
        render: (r) => {
          const label = sourceLabelFor(r, isSynthetic);
          return label === "—" ? (
            <span className="u-text-mute">—</span>
          ) : (
            <Pill
              tone={label.includes("reference") ? "warn" : "muted"}
              variant="soft"
              withDot={false}
            >
              {label}
            </Pill>
          );
        },
      },
    ],
    [isSynthetic],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="APPL needs an equity / ETF ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
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
  ) : rows.length === 0 ? (
    <Empty
      title="Taxonomy unavailable"
      body="No taxonomy rows were returned for this symbol; APPL will not guess a classification."
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : filtered.length === 0 ? (
    <Empty
      title="No crosswalk rows in this payload"
      body="The reference model carries no GICS/NAICS/ICB crosswalk for this symbol; switch the TABLE control to ALL LEVELS."
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {isSynthetic ? (
        <div
          role="status"
          aria-label="Synthetic taxonomy notice"
          style={referenceBannerStyle}
        >
          <Pill tone="warn" variant="soft">
            Synthetic / reference data
          </Pill>
          <span style={referenceNoteStyle}>
            This payload is the bundled taxonomy model (status
            {" "}{status}), NOT a live provider classification. A probe
            confirmed the sidecar serves reference_taxonomy even with
            live=true; treat every row below as static labels.
          </span>
        </div>
      ) : null}
      {displayChain.length ? (
        <section aria-label="APPL classification chain" style={crumbCardStyle}>
          <span style={crumbLabelStyle}>CLASSIFICATION CHAIN</span>
          <nav aria-label="GICS breadcrumb" style={crumbRowStyle}>
            {displayChain.map((c, i) => (
              <span key={`${c.level}-${i}`} style={crumbItemWrapStyle}>
                {i > 0 ? (
                  <span aria-hidden="true" style={crumbSepStyle}>
                    →
                  </span>
                ) : null}
                <span style={crumbItemStyle}>
                  <span style={crumbItemLabelStyle}>{c.level}</span>
                  <span style={crumbItemValueStyle}>
                    {c.value ?? "—"}
                  </span>
                </span>
              </span>
            ))}
          </nav>
          {!hasCrosswalk ? (
            <span style={crumbFallbackNoteStyle}>
              No GICS crosswalk for this symbol — showing provider
              sector/industry fields only.
            </span>
          ) : null}
        </section>
      ) : null}
      <section aria-label="APPL reference peers" style={crumbCardStyle}>
        <span style={crumbLabelStyle}>REFERENCE SECTOR PEERS</span>
        {peers.length ? (
          <>
            <div style={peerRowStyle}>
              {peers.map((p, i) => (
                <Pill key={`${p.symbol ?? "peer"}-${i}`} tone="muted" variant="soft" withDot={false}>
                  {p.symbol ?? "—"}
                </Pill>
              ))}
            </div>
            <span style={crumbFallbackNoteStyle}>
              {`Labelled ${
                [...new Set(peers.map((p) => p.peer_set ?? "reference_peer"))].join(", ")
              } rows — not a verified comparables set.`}
            </span>
          </>
        ) : (
          <span style={crumbFallbackNoteStyle}>
            No peer list in this taxonomy payload — the reference model does
            not enumerate peers for this symbol.
          </span>
        )}
      </section>
      <DataGrid
        columns={COLS}
        rows={filtered}
        rowKey={(r, i) => `${r.level ?? ""}-${i}`}
        density="compact"
        ariaLabel="APPL taxonomy table"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Industry Taxonomy — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${filtered.length} of ${rows.length} levels`}
          trailing={
            <FunctionControlGroup>
              {state === "ok" && rows.length ? (
                <Pill
                  tone={isSynthetic ? "warn" : "accent"}
                  variant="soft"
                  withDot={false}
                >
                  {isSynthetic ? "SYNTHETIC" : "LIVE"}
                </Pill>
              ) : null}
              <SegmentedControl
                label="TABLE"
                value={viewFilter}
                options={VIEW_OPTIONS}
                onChange={setViewFilter}
                title="Taxonomy table view filter"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh industry taxonomy"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="rows" value={`${filtered.length}/${rows.length}`} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="view" value={viewFilter} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const referenceBannerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "8px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--warn-soft)",
  background: "var(--warn-soft)",
};

const referenceNoteStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.45,
};

const crumbCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 8,
  padding: "10px 12px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--surface-2)",
};

const crumbLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.08em",
  color: "var(--text-mute)",
};

const crumbRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 8,
};

const crumbItemWrapStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
};

const crumbSepStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const crumbItemStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
};

const crumbItemLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
};

const crumbItemValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-primary)",
};

const crumbFallbackNoteStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.45,
};

const peerRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};
