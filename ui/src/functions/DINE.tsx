/**
 * DINE — Restaurants (OpenStreetMap Nominatim lookup).
 *
 * Header: location + keyword inputs (applied on Enter / Apply) + status
 * + refresh. Body: honesty note (ratings/prices are NOT fabricated —
 * they render only when a ratings provider is connected) + a place-type
 * filter derived from the payload's own `type` tags + place cards (name,
 * type pill, distance, full OSM address, opening hours).
 *
 * Honesty: `provider_unavailable` / `empty` payloads carry the backend
 * reason and render as explicit empty states; rating/price fields stay
 * blank when the OSM payload has none instead of showing fake scores.
 */
import { useMemo, useState, type CSSProperties } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface DINERow {
  name?: string;
  display_name?: string;
  lat?: number;
  lon?: number;
  distance_km?: number | null;
  osm_type?: string;
  osm_id?: number;
  place_id?: number;
  category?: string;
  type?: string;
  opening_hours?: string | null;
  rating?: number | null;
  price?: string | null;
  source_mode?: string;
}

interface DINEData {
  status?: string;
  reason?: string;
  location?: string;
  query?: string;
  rows?: DINERow[];
  methodology?: string;
}

const DEFAULT_LOCATION = "New York";
const DEFAULT_QUERY = "restaurant";

const LIMIT_OPTIONS = [
  { value: 10, label: "10" },
  { value: 15, label: "15" },
  { value: 25, label: "25" },
] as const;
const LIMIT_IDS = LIMIT_OPTIONS.map((o) => o.value);

export function DINEPane({ code }: FunctionPaneProps) {
  // Draft vs applied inputs: useFunction refetches on param change, so a
  // keystroke-level binding would fire one OSM request per character.
  const [locationDraft, setLocationDraft] = useState(DEFAULT_LOCATION);
  const [queryDraft, setQueryDraft] = useState(DEFAULT_QUERY);
  const [applied, setApplied] = useState({
    location: DEFAULT_LOCATION,
    query: DEFAULT_QUERY,
  });
  const [limit, setLimit] = usePersistentOption<number>(
    "showme.dine.limit",
    LIMIT_IDS,
    10,
  );
  const [typeFilter, setTypeFilter] = useState<string>("all");

  const { state, data, error, refetch } = useFunction<DINEData>({
    code,
    params: { ...applied, limit },
  });

  const payload = data?.data;
  const rows: DINERow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";

  // Place-type filter choices come from the payload itself (never invented).
  const typeOptions = useMemo(() => {
    const types = Array.from(
      new Set(rows.map((r) => (r.type ?? "").trim()).filter(Boolean)),
    ).sort();
    return [
      { value: "all", label: "ALL" },
      ...types.slice(0, 5).map((t) => ({ value: t, label: t.toUpperCase() })),
    ];
  }, [rows]);

  const visible = useMemo(
    () =>
      typeFilter === "all"
        ? rows
        : rows.filter((r) => (r.type ?? "").trim() === typeFilter),
    [rows, typeFilter],
  );

  const applyInputs = () => {
    setApplied({
      location: locationDraft.trim() || DEFAULT_LOCATION,
      query: queryDraft.trim() || DEFAULT_QUERY,
    });
    setTypeFilter("all");
  };

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={72} />
        <Skeleton height={72} width="90%" />
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
    ) : status === "provider_unavailable" || status === "empty" ? (
      <Empty
        title={
          status === "provider_unavailable"
            ? "OpenStreetMap lookup failed"
            : "No restaurants matched"
        }
        body={
          payload?.reason ??
          "The place provider returned nothing for this search."
        }
        icon="∅"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : rows.length === 0 ? (
      <Empty
        title="No places returned"
        body="The provider returned no rows for this search."
        icon="∅"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <div role="status" style={noteStyle} aria-label="Data coverage note">
          Places and addresses from OpenStreetMap. Ratings and prices are NOT
          fabricated — they render only when a ratings provider is connected.
        </div>
        <section style={kpiGridStyle} aria-label="DINE KPI ribbon">
          <StatCard
            label="Places"
            value={String(visible.length)}
            caption={`${rows.length} RETURNED · ${typeOptions.length - 1} TYPES`}
            tone="neutral"
          />
          <StatCard
            label="Location"
            value={payload?.location ?? applied.location}
            caption={`QUERY "${payload?.query ?? applied.query}"`}
            tone="neutral"
          />
          <StatCard
            label="Provider"
            value="OSM Nominatim"
            caption={status.toUpperCase()}
            tone={status === "live" ? "positive" : "neutral"}
          />
        </section>
        {typeOptions.length > 1 ? (
          <SegmentedControl
            label="TYPE"
            value={typeFilter}
            options={typeOptions}
            onChange={setTypeFilter}
            title="Filter places by payload type"
          />
        ) : null}
        <ul style={listStyle} aria-label="Restaurant results">
          {visible.map((row, i) => (
            <li key={`${row.place_id ?? row.name ?? "place"}-${i}`} style={cardStyle}>
              <div style={cardHeadStyle}>
                <span style={nameStyle}>{row.name ?? "—"}</span>
                {row.type ? (
                  <Pill tone="accent" variant="soft" withDot={false}>
                    {row.type}
                  </Pill>
                ) : null}
              </div>
              <div style={addrStyle}>{row.display_name ?? "—"}</div>
              <div style={metaRowStyle}>
                <span style={metaStyle}>
                  distance {fmtDistance(row.distance_km)}
                </span>
                {row.opening_hours ? (
                  <span style={metaStyle}>hours {row.opening_hours}</span>
                ) : null}
                <span style={metaStyle}>
                  rating {typeof row.rating === "number" ? row.rating : "—"}
                </span>
                <span style={metaStyle}>
                  price {row.price ?? "—"}
                </span>
              </div>
            </li>
          ))}
        </ul>
        {visible.length === 0 ? (
          <Empty
            title={`No ${typeFilter} places in this result set`}
            body="The provider returned no places of the selected type."
            icon="∅"
          />
        ) : null}
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Restaurants"
          subtitle={`${visible.length} places · ${payload?.location ?? applied.location}`}
          trailing={
            <FunctionControlGroup>
              <input
                type="search"
                aria-label="Location"
                value={locationDraft}
                onChange={(e) => setLocationDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") applyInputs();
                }}
                placeholder="city / area"
                style={inputStyle}
              />
              <input
                type="search"
                aria-label="Search keyword"
                value={queryDraft}
                onChange={(e) => setQueryDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") applyInputs();
                }}
                placeholder="keyword"
                style={inputStyle}
              />
              <button
                type="button"
                className="btn"
                onClick={applyInputs}
                title="Apply location + keyword"
              >
                Apply
              </button>
              <SegmentedControl
                label="LIMIT"
                value={limit}
                options={LIMIT_OPTIONS}
                onChange={setLimit}
                title="Result limit"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh restaurant search"
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
          <StatusSection label="places" value={`${visible.length}/${rows.length}`} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="limit" value={limit} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function fmtDistance(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(2)} km`;
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noteStyle: CSSProperties = {
  border: "1px solid var(--border, var(--text-mute))",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  padding: "6px 8px",
  fontFamily: "JetBrains Mono, monospace",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 8,
};

const cardStyle: CSSProperties = {
  border: "1px solid var(--border, var(--text-mute))",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const cardHeadStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  justifyContent: "space-between",
};

const nameStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  color: "var(--text-primary)",
  fontSize: "var(--font-size-md)",
};

const addrStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  overflowWrap: "anywhere",
};

const metaRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 12,
};

const metaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-secondary)",
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
  width: 150,
};
