/**
 * NI — News Index (topic presets) and CN — company news (symbol-bound), one pane.
 *
 * Both are Awareness-backed story lists (see awareness/StoryList). NI sends a `topic`
 * preset; CN requires the pane symbol and sends it as the instrument. Market/price
 * rows never appear here: CN is news only.
 */
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { Pane, PaneBody, PaneEmpty, PaneHeader } from "@/design-system";
import { useFunction, type UseFunctionResult } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { NewsFrame } from "./awareness/NewsFrame";
import { hourOption } from "./awareness/format";
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
export const TOPIC_PRESETS: readonly string[] = [
  "MACRO",
  "FED",
  "EARN",
  "CHIPS",
  "OIL",
  "BANKS",
  "TECH",
  "CRYPTO",
];
const NI_HOURS: readonly number[] = [24, 48, 168];
const CN_HOURS: readonly number[] = [24, 168, 720];

export function NIPane({ code, symbol }: FunctionPaneProps) {
  const isCN = code === "CN";
  const sym = (symbol ?? "").trim().toUpperCase();
  if (isCN && !sym) {
    return (
      <div className="u-pane-host">
        <Pane>
          <PaneHeader code={code} title="Company news" subtitle="Symbol required" />
          <PaneBody>
            <PaneEmpty
              title="Pick a symbol"
              body="Company news is symbol-bound. Select a ticker to see its stories."
            />
          </PaneBody>
        </Pane>
      </div>
    );
  }
  return isCN ? <CNBody code={code} symbol={sym} /> : <NIBody code={code} />;
}

function useRefreshTick(refetch: () => void) {
  const tick = useVisibilityTick(REFRESH_MS);
  const refetchRef = useRef(refetch);
  useEffect(() => {
    refetchRef.current = refetch;
  });
  useEffect(() => {
    if (tick > 0) refetchRef.current();
  }, [tick]);
}

function NIBody({ code }: { code: string }) {
  const [topic, setTopic] = usePersistentOption("aw.ni.topic", TOPIC_PRESETS, "MACRO");
  const [hours, setHours] = usePersistentOption("aw.ni.hours", NI_HOURS, 48);
  const params = useMemo(() => ({ topic, hours, limit: 50 }), [topic, hours]);
  const { state, data, error, refetch } = useFunction<NewsPayload>({ code, params });
  useRefreshTick(refetch);
  const rows: NewsRow[] = data?.data?.rows ?? [];

  return (
    <NewsPaneFrame
      code={code}
      title="News index"
      subtitle={`${topic} preset`}
      subject="news"
      state={state}
      error={error}
      data={data}
      refetch={refetch}
      emptyBody={`Topic ${topic}, window ${hours}h.`}
      summary={`${rows.length} stories · ${topic} · ${hours}h`}
      toolbarControls={
        <>
          <SegmentedControl
            label="Topic"
            value={topic}
            options={TOPIC_PRESETS}
            onChange={setTopic}
          />
          <SegmentedControl
            label="Window"
            value={hours}
            options={NI_HOURS.map(hourOption)}
            onChange={setHours}
          />
        </>
      }
      ariaLabel="News index stories"
    />
  );
}

function CNBody({ code, symbol }: { code: string; symbol: string }) {
  const [hours, setHours] = usePersistentOption("aw.cn.hours", CN_HOURS, 168);
  const params = useMemo(() => ({ hours, limit: 50 }), [hours]);
  const { state, data, error, refetch } = useFunction<NewsPayload>({
    code,
    symbol,
    params,
  });
  useRefreshTick(refetch);
  const rows: NewsRow[] = data?.data?.rows ?? [];

  return (
    <NewsPaneFrame
      code={code}
      symbol={symbol}
      title={`Company news — ${symbol}`}
      subtitle="Awareness news for the pane symbol"
      subject="company news"
      state={state}
      error={error}
      data={data}
      refetch={refetch}
      emptyBody={`No stories for ${symbol} in the last ${hours}h.`}
      summary={`${rows.length} stories for ${symbol} · ${hours}h`}
      toolbarControls={
        <SegmentedControl
          label="Window"
          value={hours}
          options={CN_HOURS.map(hourOption)}
          onChange={setHours}
        />
      }
      ariaLabel={`Company news for ${symbol}`}
    />
  );
}

interface NewsPaneFrameProps {
  code: string;
  symbol?: string;
  title: string;
  subtitle: string;
  subject: string;
  state: UseFunctionResult<NewsPayload>["state"];
  error: unknown;
  data: UseFunctionResult<NewsPayload>["data"];
  refetch: () => void;
  emptyBody: string;
  summary: string;
  toolbarControls: ReactNode;
  ariaLabel: string;
}

function NewsPaneFrame(p: NewsPaneFrameProps) {
  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={p.code}
          title={p.title}
          subtitle={p.subtitle}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill
                state={p.state}
                status={p.data?.data?.status ?? p.data?.status}
              />
              <RefreshButton
                loading={p.state === "loading"}
                onClick={p.refetch}
                title="Refresh news"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <NewsFrame
            code={p.code}
            symbol={p.symbol}
            subject={p.subject}
            state={p.state}
            error={p.error}
            data={p.data}
            onRetry={p.refetch}
            toolbar={
              <div className="aw-toolbar" role="toolbar" aria-label={`${p.code} filters`}>
                {p.toolbarControls}
              </div>
            }
            emptyTitle="No stories match these filters"
            emptyBody={p.emptyBody}
            ariaLabel={p.ariaLabel}
            summary={p.summary}
          />
        </PaneBody>
      </Pane>
    </div>
  );
}
