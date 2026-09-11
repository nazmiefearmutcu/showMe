/**
 * CDE — Custom Data Fields (user-defined formula fields).
 *
 * Full CRUD over the backend's local formula store (runtime/cde_fields.json):
 * list, add (name + ShowMe DSL formula), remove, and evaluate (run a stored
 * formula against a row JSON, boolean result). Every action is a committed
 * `op` object passed as function params — `useFunction` re-runs when the op
 * changes, and every mutation response echoes the full updated store, so the
 * grid always renders server truth. Examples that the backend injects when
 * the store is empty are labelled as examples, never as stored fields.
 */
import { useMemo, useState, type CSSProperties } from "react";
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
  StatCard,
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

interface CDERow {
  name?: string;
  formula?: string;
  operation?: string;
  evaluation?: boolean;
}

interface CDEEvaluation {
  name?: string;
  value?: boolean;
  formula?: string;
}

interface CDEData {
  status?: string;
  reason?: string;
  rows?: CDERow[];
  count?: number;
  actions?: string[];
  evaluation?: CDEEvaluation;
  next_actions?: string[];
}

/** One committed operation — passed verbatim as backend params. */
interface CDEOp {
  action: "list" | "add" | "remove" | "evaluate";
  name?: string;
  formula?: string;
  row?: Record<string, unknown>;
}

const LIST_OP: CDEOp = { action: "list" };

export function CDEPane({ code }: FunctionPaneProps) {
  const [op, setOp] = useState<CDEOp>(LIST_OP);

  // Add-form drafts.
  const [addName, setAddName] = useState("");
  const [addFormula, setAddFormula] = useState("");
  // Evaluate-form drafts.
  const [evalName, setEvalName] = useState("");
  const [evalRowJson, setEvalRowJson] = useState("{}");
  const [clientError, setClientError] = useState<string | null>(null);

  const { state, data, error, refetch } = useFunction<CDEData>({
    code,
    params: op as unknown as Record<string, unknown>,
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";
  const storedCount = payload?.count ?? 0;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const isExampleRows = storedCount === 0;
  const evaluation = payload?.evaluation ?? null;

  function submitAdd() {
    const name = addName.trim();
    const formula = addFormula.trim();
    if (!name || !formula) {
      setClientError("Name and formula are both required to add a field.");
      return;
    }
    setClientError(null);
    setOp({ action: "add", name, formula });
  }

  function submitEvaluate() {
    const name = evalName.trim();
    let row: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(evalRowJson || "{}");
      if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
        setClientError("Row JSON must be an object, e.g. {\"pe\": 18}.");
        return;
      }
      row = parsed as Record<string, unknown>;
    } catch {
      setClientError("Row JSON is not valid JSON.");
      return;
    }
    if (!name) {
      setClientError("Field name is required to evaluate.");
      return;
    }
    setClientError(null);
    setOp({ action: "evaluate", name, row });
  }

  function removeField(name: string) {
    setClientError(null);
    setOp({ action: "remove", name });
  }

  const COLS: DataGridColumn<CDERow>[] = useMemo(
    () => [
      {
        key: "name",
        header: "Name",
        width: 170,
        render: (r) => (
          <span style={monoStrongStyle}>{r.name ?? "—"}</span>
        ),
      },
      {
        key: "formula",
        header: "Formula",
        render: (r) => (
          <span style={monoPrimaryStyle}>{r.formula ?? "—"}</span>
        ),
      },
      {
        key: "operation",
        header: "Kind",
        width: 120,
        render: (r) => (
          <Pill
            tone={r.operation === "example" ? "muted" : "accent"}
            variant="soft"
            withDot={false}
          >
            {r.operation === "example" ? "example" : "stored"}
          </Pill>
        ),
      },
      {
        key: "actions",
        header: "",
        width: 90,
        render: (r) => {
          if (r.operation !== "custom_field" || !r.name) return null;
          const name: string = r.name;
          return (
            <button
              type="button"
              className="btn"
              title={`Remove stored field ${name}`}
              onClick={() => removeField(name)}
            >
              Remove
            </button>
          );
        },
      },
    ],
    // removeField/setOp are stable useState setters; the grid columns only
    // depend on the remove callback identity, which never changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const lastAction =
    op.action === "list"
      ? "list"
      : `${op.action} ${op.name ?? ""}`.trim();

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
  ) : (
    <div className="u-grid-gap-14">
      <section style={formGridStyle} aria-label="CDE actions">
        <form
          style={formCardStyle}
          onSubmit={(e) => {
            e.preventDefault();
            submitAdd();
          }}
          aria-label="CDE add form"
        >
          <span style={sectionTitleStyle}>Add field</span>
          <label style={fieldRowStyle}>
            <span style={fieldLabelStyle}>NAME</span>
            <input
              type="text"
              aria-label="New field name"
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              placeholder="cheap_quality"
              style={textInputStyle}
            />
          </label>
          <label style={fieldRowStyle}>
            <span style={fieldLabelStyle}>FORMULA (SHOWME DSL)</span>
            <input
              type="text"
              aria-label="New field formula"
              value={addFormula}
              onChange={(e) => setAddFormula(e.target.value)}
              placeholder="pe < 25 AND beta < 1.2"
              style={textInputStyle}
            />
          </label>
          <button type="submit" className="btn btn--accent" title="Store the field">
            Add field
          </button>
        </form>
        <form
          style={formCardStyle}
          onSubmit={(e) => {
            e.preventDefault();
            submitEvaluate();
          }}
          aria-label="CDE evaluate form"
        >
          <span style={sectionTitleStyle}>Evaluate field</span>
          <label style={fieldRowStyle}>
            <span style={fieldLabelStyle}>FIELD NAME</span>
            <input
              type="text"
              aria-label="Evaluate field name"
              value={evalName}
              onChange={(e) => setEvalName(e.target.value)}
              placeholder="cheap_quality"
              style={textInputStyle}
            />
          </label>
          <label style={fieldRowStyle}>
            <span style={fieldLabelStyle}>ROW JSON</span>
            <input
              type="text"
              aria-label="Evaluate row JSON"
              value={evalRowJson}
              onChange={(e) => setEvalRowJson(e.target.value)}
              placeholder='{"pe": 18, "beta": 1.1}'
              style={textInputStyle}
            />
          </label>
          <button type="submit" className="btn" title="Run the stored formula against the row">
            Evaluate
          </button>
        </form>
      </section>

      {clientError ? (
        <div role="note" style={errorNoteStyle} aria-label="CDE client error">
          {clientError}
        </div>
      ) : null}
      {status === "input_error" || status === "calc_error" ? (
        <div role="note" style={errorNoteStyle} aria-label="CDE backend error">
          <strong>{status}.</strong> {payload?.reason ?? "—"}
        </div>
      ) : null}
      {isExampleRows && rows.length > 0 ? (
        <div role="note" style={noteStyle} aria-label="CDE examples notice">
          No stored fields yet — the rows below are bundled examples. Add a
          field above to create your own.
        </div>
      ) : null}
      {evaluation ? (
        <section style={evalCardStyle} aria-label="CDE evaluation result">
          <span style={sectionTitleStyle}>Evaluation</span>
          <div style={evalRowsStyle}>
            <span style={monoPrimaryStyle}>{evaluation.name ?? "—"}</span>
            <span style={monoMutedStyle}>{evaluation.formula ?? "—"}</span>
            <Pill
              tone={evaluation.value ? "positive" : "negative"}
              variant="soft"
              withDot={false}
            >
              {evaluation.value ? "TRUE" : "FALSE"}
            </Pill>
          </div>
        </section>
      ) : null}
      <section style={kpiGridStyle} aria-label="CDE store summary">
        <StatCard
          label="Stored fields"
          value={String(storedCount)}
          caption="RUNTIME cde_fields.json"
          tone="neutral"
        />
        <StatCard
          label="Actions"
          value={String(payload?.actions?.length ?? 4)}
          caption={(payload?.actions ?? ["list", "add", "remove", "evaluate"]).join(" · ").toUpperCase()}
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.name ?? "f"}-${i}`}
        density="compact"
        ariaLabel="CDE stored fields"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Custom Data Fields"
          subtitle={`local formula store · ${storedCount} stored`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                local store
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-run current CDE action"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "local_cde_store"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="stored" value={storedCount} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="action" value={lastAction} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── styles ────────────────────────────────────────────────────────── */

const formGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 12,
  alignItems: "start",
};

const formCardStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: 12,
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
};

const sectionTitleStyle: CSSProperties = {
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const fieldRowStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 3,
};

const fieldLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
};

const textInputStyle: CSSProperties = {
  background: "var(--surface-1)",
  border: "1px solid var(--border-row)",
  borderRadius: 3,
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  height: 24,
  padding: "0 6px",
  width: "100%",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const evalCardStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: 10,
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
};

const evalRowsStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 10,
  alignItems: "center",
};

const noteStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-mute)",
};

const errorNoteStyle: CSSProperties = {
  border: "1px solid var(--negative, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
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

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
