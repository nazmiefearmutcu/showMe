/**
 * BMC — Market Concepts Education.
 *
 * Local market-concepts curriculum (Bloomberg Market Concepts equivalent):
 * 13 lessons across 6 modules, each with a concrete learning objective,
 * worked market example, self-check quiz, and completion state. Header:
 * module filter chips (persisted under `showme.bmc.module`). Body: lesson
 * list + a reader panel for the selected lesson. Synth by design (curriculum
 * reference), and the pane says so — nothing pretends to be live data.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
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
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface BMCLesson {
  module?: string;
  lesson_no?: string;
  lesson?: string;
  objective?: string;
  example?: string;
  quiz?: string;
  progress?: string;
}

interface BMCData {
  status?: string;
  rows?: BMCLesson[];
  cards?: { label?: string; value?: unknown }[];
  methodology?: string;
}

const MODULE_IDS = ["all", "equities", "fixed income", "fx", "commodities", "macro", "alternatives"];

export function BMCPane({ code }: FunctionPaneProps) {
  const [moduleFilter, setModuleFilter] = usePersistentOption<string>(
    "showme.bmc.module",
    MODULE_IDS,
    "all",
  );
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const { state, data, error, refetch } = useFunction<BMCData>({
    code,
    params: {},
  });

  const payload = data?.data;
  const allRows = useMemo(() => payload?.rows ?? [], [payload]);
  const modules = useMemo(
    () => Array.from(new Set(allRows.map((r) => r.module ?? "").filter(Boolean))),
    [allRows],
  );
  const rows = useMemo(
    () =>
      moduleFilter === "all"
        ? allRows
        : allRows.filter((r) => (r.module ?? "").toLowerCase() === moduleFilter),
    [allRows, moduleFilter],
  );

  // Keep the reader anchored to a real lesson when the filter changes.
  useEffect(() => {
    if (rows.length === 0) {
      setSelectedKey(null);
      return;
    }
    if (!selectedKey || !rows.some((r) => lessonKey(r) === selectedKey)) {
      setSelectedKey(lessonKey(rows[0]));
    }
  }, [rows, selectedKey]);

  const selected = rows.find((r) => lessonKey(r) === selectedKey) ?? rows[0] ?? null;
  const status = payload?.status ?? "—";

  const chipOptions = [
    { value: "all", label: "All" },
    ...modules.map((m) => ({ value: m.toLowerCase(), label: m })),
  ];

  const body = state === "loading" || state === "idle" ? (
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
      title="No lessons for this module"
      body={`The curriculum returned no lessons matching "${moduleFilter}". Switch back to All modules.`}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="BMC summary">
        <StatCard
          label="Modules"
          value={String(modules.length)}
          caption="CURRICULUM REFERENCE (LOCAL, NOT LIVE)"
          tone="neutral"
        />
        <StatCard
          label="Lessons"
          value={String(rows.length)}
          caption={moduleFilter === "all" ? "ALL MODULES" : moduleFilter.toUpperCase()}
          tone="neutral"
        />
        <StatCard
          label="Completed"
          value={String(rows.filter((r) => r.progress === "completed").length)}
          caption={`OF ${rows.length} IN VIEW`}
          tone="neutral"
        />
      </section>

      <section style={chipsRowStyle} aria-label="Module filter">
        {chipOptions.map((c) => (
          <button
            key={c.value}
            type="button"
            disabled={c.value === moduleFilter}
            onClick={() => setModuleFilter(c.value)}
            title={`Filter module: ${c.label}`}
            className={`fn-segmented__opt${c.value === moduleFilter ? " fn-segmented__opt--active" : ""}`}
          >
            {c.label}
          </button>
        ))}
      </section>

      <div style={readerGridStyle}>
        <ul style={listStyle} aria-label="BMC lessons">
          {rows.map((lesson) => {
            const key = lessonKey(lesson);
            const active = selected?.lesson === lesson.lesson && selected?.module === lesson.module;
            return (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => setSelectedKey(key)}
                  title={`Open lesson: ${lesson.lesson ?? ""}`}
                  style={{
                    ...lessonBtnStyle,
                    ...(active ? lessonBtnActiveStyle : {}),
                  }}
                  aria-current={active ? "true" : undefined}
                >
                  <span style={lessonNoStyle}>{lesson.lesson_no ?? "·"}</span>
                  <span style={lessonTitleStyle}>{lesson.lesson ?? "—"}</span>
                  <Pill
                    tone={lesson.progress === "completed" ? "positive" : "muted"}
                    variant="soft"
                    withDot={false}
                  >
                    {lesson.progress ?? "not_started"}
                  </Pill>
                </button>
              </li>
            );
          })}
        </ul>

        {selected ? (
          <section style={readerStyle} aria-label="Lesson reader">
            <div style={readerHeadStyle}>
              <Pill tone="accent" variant="soft" withDot={false}>
                {selected.module ?? "module"}
              </Pill>
              <span style={readerTitleStyle}>{selected.lesson ?? "—"}</span>
            </div>
            <dl style={dlStyle}>
              <dt style={dtStyle}>Objective</dt>
              <dd style={ddStyle}>{selected.objective ?? "—"}</dd>
              <dt style={dtStyle}>Example</dt>
              <dd style={ddStyle}>{selected.example ?? "—"}</dd>
              <dt style={dtStyle}>Self-check</dt>
              <dd style={ddStyle}>{selected.quiz ?? "—"}</dd>
            </dl>
          </section>
        ) : null}
      </div>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Market Concepts Education"
          subtitle={`${rows.length} lessons · ${moduleFilter === "all" ? "all modules" : moduleFilter}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {modules.length} modules
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh curriculum"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="lessons" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="module" value={moduleFilter} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function lessonKey(r: BMCLesson): string {
  return `${r.module ?? ""}#${r.lesson_no ?? ""}`;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const chipsRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const readerGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(240px, 5fr) minmax(260px, 7fr)",
  gap: 10,
  alignItems: "start",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 4,
};

const lessonBtnStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  textAlign: "left",
  padding: "6px 8px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  background: "transparent",
  cursor: "pointer",
  color: "inherit",
};

const lessonBtnActiveStyle: CSSProperties = {
  borderColor: "var(--accent)",
};

const lessonNoStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 11,
  color: "var(--text-mute)",
  minWidth: 16,
};

const lessonTitleStyle: CSSProperties = {
  flex: 1,
  fontSize: 12,
  color: "var(--text-primary)",
  overflowWrap: "anywhere",
};

const readerStyle: CSSProperties = {
  display: "grid",
  gap: 10,
  padding: "10px 12px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
};

const readerHeadStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
};

const readerTitleStyle: CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: "var(--text-primary)",
};

const dlStyle: CSSProperties = {
  margin: 0,
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  gap: "6px 12px",
};

const dtStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
  textTransform: "uppercase",
  paddingTop: 2,
};

const ddStyle: CSSProperties = {
  margin: 0,
  fontSize: 12,
  color: "var(--text-primary)",
  overflowWrap: "anywhere",
};
