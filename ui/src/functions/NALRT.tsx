/**
 * NALRT — News alerts: high-importance Awareness stories in a short window.
 *
 * Severity is supplied per row by the backend (`critical` when importance >= 85,
 * otherwise `high`). Nothing is generated client-side.
 */
import { useEffect, useMemo, useRef } from "react";
import { Pane, PaneBody, PaneHeader } from "@/design-system";
import { useFunction } from "@/lib/useFunction";
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
const THRESHOLDS: readonly number[] = [50, 70, 85];
const WINDOWS: readonly number[] = [6, 24];

const THRESHOLD_LABEL: Record<number, string> = {
  50: "50+",
  70: "70+",
  85: "85+ critical",
};

export function NALRTPane({ code }: FunctionPaneProps) {
  const [minImportance, setMinImportance] = usePersistentOption(
    "aw.nalrt.min",
    THRESHOLDS,
    70,
  );
  const [hours, setHours] = usePersistentOption("aw.nalrt.hours", WINDOWS, 6);
  const params = useMemo(
    () => ({ hours, min_importance: minImportance, limit: 50 }),
    [hours, minImportance],
  );
  const { state, data, error, refetch } = useFunction<NewsPayload>({ code, params });

  const tick = useVisibilityTick(REFRESH_MS);
  const refetchRef = useRef(refetch);
  useEffect(() => {
    refetchRef.current = refetch;
  });
  useEffect(() => {
    if (tick > 0) refetchRef.current();
  }, [tick]);

  const rows: NewsRow[] = data?.data?.rows ?? [];
  const critical = rows.filter((r) => r.severity === "critical").length;

  const toolbar = (
    <div className="aw-toolbar" role="toolbar" aria-label="News alert filters">
      <div className="aw-toolbar__row">
        <SegmentedControl
          label="Importance"
          value={minImportance}
          options={THRESHOLDS.map((v) => ({ value: v, label: THRESHOLD_LABEL[v] }))}
          onChange={setMinImportance}
        />
        <SegmentedControl
          label="Window"
          value={hours}
          options={WINDOWS.map(hourOption)}
          onChange={setHours}
        />
        <span className="aw-toolbar__spacer" />
        <FunctionControlGroup>
          <LoadStatePill state={state} status={data?.data?.status ?? data?.status} />
          <RefreshButton
            loading={state === "loading"}
            onClick={refetch}
            title="Refresh alerts"
          />
        </FunctionControlGroup>
      </div>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="News alerts"
          subtitle={`Importance ${THRESHOLD_LABEL[minImportance]}, last ${hours}h`}
        />
        <PaneBody>
          <NewsFrame
            code={code}
            subject="news alerts"
            state={state}
            error={error}
            data={data}
            onRetry={refetch}
            toolbar={toolbar}
            emptyTitle="No alerts in this window"
            emptyBody={`No stories with importance ${THRESHOLD_LABEL[minImportance]} in the last ${hours}h.`}
            emptyAction={
              <div className="aw-relaxers">
                {minImportance > 50 ? (
                  <button
                    type="button"
                    className="aw-btn"
                    onClick={() => setMinImportance(50)}
                  >
                    Lower to importance 50+
                  </button>
                ) : null}
                {hours < 24 ? (
                  <button type="button" className="aw-btn" onClick={() => setHours(24)}>
                    Widen to 24h
                  </button>
                ) : null}
              </div>
            }
            ariaLabel="News alerts"
            renderLeading={(row) => <SeverityPill severity={row.severity} />}
            summary={`${rows.length} alerts, ${critical} critical, last ${hours}h`}
          />
        </PaneBody>
      </Pane>
    </div>
  );
}

function SeverityPill({ severity }: { severity?: "critical" | "high" }) {
  if (!severity) return null;
  return (
    <span
      className={`aw-sev aw-sev--${severity}`}
      title={severity === "critical" ? "Importance 85 or higher" : "Importance below 85"}
    >
      {severity.toUpperCase()}
    </span>
  );
}
