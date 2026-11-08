/**
 * TOP — Awareness-backed news feed (story-first list).
 *
 * Source of truth is the awareness-markets service via the TOP function. Rows are
 * story leads (`story=true` collapse happens server-side); "+N sources" expands the
 * story's publishers and the drawer shows the full story. No sample data, no
 * fallback feeds: awareness down renders the unavailable state.
 *
 * TOP never shows low-quality news: the quality floor offers premium or standard only.
 *
 * Params sent: hours, limit, min_quality, topics, asset_classes, countries, q.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Pane, PaneBody, PaneHeader } from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { NewsFrame } from "./awareness/NewsFrame";
import { floorOption, hourOption } from "./awareness/format";
import type { NewsPayload, NewsRow } from "./awareness/news-types";
import {
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
  FunctionControlGroup,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const REFRESH_MS = 60_000;
const HOUR_OPTIONS: readonly number[] = [6, 24, 72, 168];
// Premium or standard only. Low-quality news is never shown on TOP (the backend clamps a low request).
const FLOOR_OPTIONS: readonly string[] = ["premium", "standard"];
// Asset-class tags exactly as the awareness taxonomy and the TOP seed spell them.
const ASSET_OPTIONS: readonly string[] = [
  "all",
  "equities",
  "indices",
  "fx",
  "rates",
  "credit",
  "commodities",
  "crypto",
  "macro",
];
const ASSET_LABEL: Record<string, string> = {
  all: "All",
  equities: "Equities",
  indices: "Indices",
  fx: "FX",
  rates: "Rates",
  credit: "Credit",
  commodities: "Commodities",
  crypto: "Crypto",
  macro: "Macro",
};
const FLOOR_LABEL: Record<string, string> = {
  premium: "Premium",
  standard: "Standard and above",
};

export function TOPPane({ code }: FunctionPaneProps) {
  const [hours, setHours] = usePersistentOption("aw.top.hours", HOUR_OPTIONS, 24);
  const [floor, setFloor] = usePersistentOption("aw.top.floor", FLOOR_OPTIONS, "standard");
  const [assetClass, setAssetClass] = usePersistentOption(
    "aw.top.asset",
    ASSET_OPTIONS,
    "all",
  );
  const [topic, setTopic] = useState("");
  const [country, setCountry] = useState("");
  const [qDraft, setQDraft] = useState("");
  const [q, setQ] = useState("");

  const params = useMemo(() => {
    const p: Record<string, unknown> = { hours, limit: 50, min_quality: floor };
    if (topic) p.topics = topic;
    if (assetClass !== "all") p.asset_classes = assetClass;
    if (country) p.countries = country;
    if (q) p.q = q;
    return p;
  }, [hours, floor, assetClass, topic, country, q]);

  const { state, data, error, refetch } = useFunction<NewsPayload>({ code, params });

  // Refresh every 60 s while visible. The tick is a trigger only and never enters params.
  const tick = useVisibilityTick(REFRESH_MS);
  const refetchRef = useRef(refetch);
  useEffect(() => {
    refetchRef.current = refetch;
  });
  useEffect(() => {
    if (tick > 0) refetchRef.current();
  }, [tick]);

  const rows = useMemo<NewsRow[]>(() => data?.data?.rows ?? [], [data]);
  const topics = useMemo(() => {
    const set = new Set<string>();
    for (const r of rows) for (const t of r.topics) set.add(t);
    if (topic) set.add(topic);
    return Array.from(set).sort();
  }, [rows, topic]);

  const clearFilters = () => {
    setTopic("");
    setCountry("");
    setAssetClass("all");
    setQ("");
    setQDraft("");
  };

  const toolbar = (
    <div className="aw-toolbar" role="toolbar" aria-label="TOP news filters">
      <div className="aw-toolbar__row">
        <label className="aw-field">
          <span className="aw-field__label">Topic</span>
          <select
            className="aw-select"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            aria-label="Topic"
          >
            <option value="">All topics</option>
            {topics.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
        <form
          className="aw-field"
          onSubmit={(e) => {
            e.preventDefault();
            setQ(qDraft.trim());
          }}
        >
          <label className="aw-field__label" htmlFor={`${code}-q`}>
            Search
          </label>
          <input
            id={`${code}-q`}
            className="aw-input"
            placeholder="Search headlines"
            value={qDraft}
            onChange={(e) => setQDraft(e.target.value)}
            onBlur={() => setQ(qDraft.trim())}
          />
        </form>
        {country ? (
          <button
            type="button"
            className="aw-chip aw-chip--filter"
            aria-label={`Remove country filter ${country}`}
            onClick={() => setCountry("")}
          >
            Country {country} {"×"}
          </button>
        ) : null}
        <span className="aw-toolbar__spacer" />
        <FunctionControlGroup>
          <LoadStatePill state={state} status={data?.data?.status ?? data?.status} />
          <RefreshButton
            loading={state === "loading"}
            onClick={refetch}
            title="Refresh news"
          />
        </FunctionControlGroup>
      </div>
      <div className="aw-toolbar__row">
        <SegmentedControl
          label="Asset class"
          value={assetClass}
          options={ASSET_OPTIONS.map((v) => ({ value: v, label: ASSET_LABEL[v] ?? v }))}
          onChange={setAssetClass}
        />
        <SegmentedControl
          label="Quality floor"
          value={floor}
          options={FLOOR_OPTIONS.map(floorOption)}
          onChange={setFloor}
        />
        <SegmentedControl
          label="Window"
          value={hours}
          options={HOUR_OPTIONS.map(hourOption)}
          onChange={setHours}
        />
      </div>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader code={code} title="Top news" subtitle="Awareness news, story-first" />
        <PaneBody>
          <NewsFrame
            code={code}
            subject="news"
            state={state}
            error={error}
            data={data}
            onRetry={refetch}
            toolbar={toolbar}
            emptyTitle="No stories match these filters"
            emptyBody={
              <>
                Window {hours}h, quality {FLOOR_LABEL[floor] ?? floor}
                {topic ? `, topic ${topic.replace(/_/g, " ")}` : ""}
                {assetClass !== "all" ? `, asset class ${assetClass}` : ""}
                {country ? `, country ${country}` : ""}
                {q ? `, search "${q}"` : ""}.
              </>
            }
            emptyAction={
              <div className="aw-relaxers">
                {hours < 168 ? (
                  <button type="button" className="aw-btn" onClick={() => setHours(168)}>
                    Widen to 7d
                  </button>
                ) : null}
                <button
                  type="button"
                  className="aw-btn aw-btn--ghost"
                  onClick={clearFilters}
                >
                  Clear filters
                </button>
              </div>
            }
            ariaLabel="Top news stories"
            onFilter={(kind, value) => {
              if (kind === "topic") setTopic(value);
              if (kind === "country") setCountry(value);
            }}
            summary={`${rows.length} stories in ${hours}h, quality ${FLOOR_LABEL[floor] ?? floor}`}
          />
        </PaneBody>
      </Pane>
    </div>
  );
}
