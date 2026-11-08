/**
 * NSE — News search (company name / keyword) over the Awareness full-text index.
 *
 * Nothing is fetched until a query is entered. Zero rows at the standard floor is
 * reported by the backend `hidden_note`; the floor is never lowered silently.
 */
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Pane, PaneBody, PaneEmpty, PaneHeader } from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { NewsFrame } from "./awareness/NewsFrame";
import { floorOption, hourOption } from "./awareness/format";
import type { NewsPayload, NewsRow } from "./awareness/news-types";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const REFRESH_MS = 60_000;
const HOUR_OPTIONS: readonly number[] = [168, 720, 2160];
const FLOOR_OPTIONS: readonly string[] = ["premium", "standard", "low"];

export function NSEPane({ code, symbol }: FunctionPaneProps) {
  const [hours, setHours] = usePersistentOption("aw.nse.hours", HOUR_OPTIONS, 720);
  const [floor, setFloor] = usePersistentOption("aw.nse.floor", FLOOR_OPTIONS, "standard");
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const pane = (symbol ?? "").trim().toUpperCase();

  const params = useMemo(() => {
    const p: Record<string, unknown> = { q, hours, min_quality: floor, limit: 50 };
    if (pane) p.symbol = pane;
    return p;
  }, [q, hours, floor, pane]);

  const { state, data, error, refetch } = useFunction<NewsPayload>({
    code,
    params,
    enabled: q.length > 0,
  });

  const tick = useVisibilityTick(REFRESH_MS);
  const refetchRef = useRef(refetch);
  useEffect(() => {
    refetchRef.current = refetch;
  });
  useEffect(() => {
    if (tick > 0 && q) refetchRef.current();
  }, [tick, q]);

  const rows: NewsRow[] = data?.data?.rows ?? [];
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setQ(draft.trim());
  };

  const toolbar = (
    <div className="aw-toolbar" role="toolbar" aria-label="News search filters">
      <div className="aw-toolbar__row">
        <form className="aw-field" onSubmit={onSubmit} role="search">
          <label className="aw-field__label" htmlFor={`${code}-q`}>
            Company or keyword
          </label>
          <input
            id={`${code}-q`}
            className="aw-input"
            placeholder="e.g. NVIDIA or chip export"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit" className="aw-btn">
            Search
          </button>
        </form>
        <span className="aw-toolbar__spacer" />
        <FunctionControlGroup>
          <LoadStatePill
            state={q ? state : "idle"}
            status={data?.data?.status ?? data?.status}
          />
          <RefreshButton
            loading={state === "loading"}
            onClick={refetch}
            disabled={!q}
            title="Refresh search"
          />
        </FunctionControlGroup>
      </div>
      <div className="aw-toolbar__row">
        <SegmentedControl
          label="Window"
          value={hours}
          options={HOUR_OPTIONS.map(hourOption)}
          onChange={setHours}
        />
        <SegmentedControl
          label="Quality floor"
          value={floor}
          options={FLOOR_OPTIONS.map(floorOption)}
          onChange={setFloor}
        />
      </div>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="News search"
          subtitle={q ? `"${q}"` : "Awareness full-text search"}
        />
        <PaneBody>
          {q ? (
            <NewsFrame
              code={code}
              symbol={pane || undefined}
              subject="news search"
              state={state}
              error={error}
              data={data}
              onRetry={refetch}
              toolbar={toolbar}
              emptyTitle="No stories match this search"
              emptyBody={`"${q}", window ${Math.round(hours / 24)}d, quality ${floor}.`}
              emptyAction={
                floor !== "low" ? (
                  <button type="button" className="aw-btn" onClick={() => setFloor("low")}>
                    Include low quality
                  </button>
                ) : undefined
              }
              ariaLabel={`News results for ${q}`}
              summary={`${rows.length} results for "${q}"`}
              onShowLow={() => setFloor("low")}
            />
          ) : (
            <>
              {toolbar}
              <PaneEmpty
                title="Search the news index"
                body="Enter a company name or keyword to search Awareness full text."
              />
            </>
          )}
        </PaneBody>
      </Pane>
    </div>
  );
}
