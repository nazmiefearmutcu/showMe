/**
 * GRAB — Screenshot → Email (honest capture-plan form).
 *
 * The backend GRAB function NEVER sends anything: it returns a two-step
 * capture plan (local capture = ready, email = draft_only / not_configured)
 * and refuses to auto-transmit. The pane mirrors that contract honestly:
 * a real form (target + recipient) whose submit calls the backend function,
 * a plan view of the returned steps, and a standing notice that nothing is
 * emailed automatically — transmission requires a separately confirmed mail
 * integration. Provider warnings are surfaced verbatim.
 *
 * `runFunction` is invoked imperatively (not `useFunction`) so the pane
 * never auto-fires on mount; the default state is idle.
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  Empty,
  Field,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import {
  runFunction,
  FunctionCallError,
  type FunctionCallResult,
} from "@/lib/functions";
import { useAppStore } from "@/lib/store";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface GRABStepRow {
  step?: string;
  target?: string;
  status?: string;
  output?: string;
  transmits_data?: boolean;
}

interface GRABData {
  status?: string;
  target?: string;
  recipient?: string | null;
  rows?: GRABStepRow[];
  cards?: GRABCard[];
  next_actions?: string[];
}

interface GRABCard {
  label?: string;
  value?: string;
}

export function GRABPane({ code }: FunctionPaneProps) {
  const sidecarPort = useAppStore((s) => s.sidecarPort);
  const sidecarReady = sidecarPort != null;

  const [target, setTarget] = useState("current_pane");
  const [recipient, setRecipient] = useState("");

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<FunctionCallResult<GRABData> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function prepare() {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    try {
      const res = await runFunction<GRABData>(code, {
        params: {
          target: target.trim() || "current_pane",
          recipient: recipient.trim(),
        },
        signal: controller.signal,
      });
      setResult(res);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(
        err instanceof FunctionCallError
          ? `${err.status}: ${err.body}`
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      if (!controller.signal.aborted) {
        setRunning(false);
      }
    }
  }

  const payload = result?.data;
  const status = payload?.status ?? "—";
  const state: "idle" | "loading" | "ok" | "error" = running
    ? "loading"
    : error
      ? "error"
      : result
        ? "ok"
        : "idle";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Screenshot Email"
          subtitle={
            payload?.recipient
              ? `plan for ${payload.recipient} · nothing sent`
              : "capture plan · nothing sent"
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="warn" variant="soft" withDot={false}>
                draft only
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={running}
                onClick={() => void prepare()}
                disabled={!sidecarReady}
                title="Re-prepare capture plan"
                label="Re-prepare"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div style={twoColLayout}>
            <form
              style={formCardStyle}
              aria-label="GRAB capture form"
              onSubmit={(e) => {
                e.preventDefault();
                void prepare();
              }}
            >
              <span style={sectionTitleStyle}>Capture target</span>
              <FieldRow>
                <Field
                  label="Target"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  placeholder="current_pane or a URL"
                  disabled={running}
                />
                <Field
                  label="Recipient"
                  value={recipient}
                  onChange={(e) => setRecipient(e.target.value)}
                  inputMode="email"
                  placeholder="name@example.com"
                  hint="Optional — without it the email step stays not_configured."
                  disabled={running}
                />
              </FieldRow>
              <div style={actionsRowStyle}>
                <button
                  type="submit"
                  className="btn btn--accent"
                  disabled={running || !sidecarReady}
                  title="Prepare the capture plan (the backend never auto-sends)"
                >
                  {running ? "Preparing..." : "Prepare capture plan"}
                </button>
              </div>
              <p style={noticeStyle} aria-label="GRAB honesty note">
                Nothing is emailed automatically. GRAB only prepares a local
                screenshot plan; sending requires a user-confirmed mail
                integration.
              </p>
            </form>
            <PlanView running={running} error={error} result={result} />
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={result?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection
            label="recipient"
            value={payload?.recipient ?? "not set"}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${result?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="mode" value="draft only" tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PlanView({
  running,
  error,
  result,
}: {
  running: boolean;
  error: string | null;
  result: FunctionCallResult<GRABData> | null;
}): ReactNode {
  if (running) {
    return (
      <section style={planCardStyle} aria-label="GRAB plan">
        <span style={sectionTitleStyle}>Plan</span>
        <Skeleton height={18} />
        <Skeleton height={14} />
        <Skeleton height={14} width="80%" />
      </section>
    );
  }
  if (error) {
    return (
      <section style={planCardStyle} aria-label="GRAB plan">
        <span style={sectionTitleStyle}>Plan</span>
        <Empty title="Function error" body={error} icon="!" />
      </section>
    );
  }
  if (!result) {
    return (
      <section style={planCardStyle} aria-label="GRAB plan">
        <span style={sectionTitleStyle}>Plan</span>
        <Empty
          title="No plan yet"
          body="Set a target and press Prepare capture plan to build the draft."
          icon="•"
        />
      </section>
    );
  }
  const p = result.data;
  const warnings = (result.warnings ?? []) as string[];
  const nextActions = Array.isArray(p?.next_actions) ? p.next_actions : [];
  return (
    <section style={planCardStyle} aria-label="GRAB plan">
      <span style={sectionTitleStyle}>Plan · nothing transmitted</span>
      <div style={stepsStyle}>
        {(p?.rows ?? []).map((row, i) => (
          <div key={`${row.step ?? "step"}-${i}`} style={stepRowStyle}>
            <span style={monoStrongStyle}>{row.step ?? "—"}</span>
            <span style={bodyStyle}>{row.target ?? "—"}</span>
            <Pill
              tone={
                row.status === "ready"
                  ? "positive"
                  : row.status === "draft_only"
                    ? "warn"
                    : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {row.status ?? "—"}
            </Pill>
            <Pill
              tone={row.transmits_data ? "negative" : "muted"}
              variant="soft"
              withDot={false}
            >
              {row.transmits_data ? "would transmit" : "local only"}
            </Pill>
            <span style={monoMutedStyle}>{row.output ?? "—"}</span>
          </div>
        ))}
      </div>
      {warnings.length > 0 ? (
        <div role="note" style={warnBoxStyle} aria-label="GRAB warnings">
          {warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      ) : null}
      {nextActions.length > 0 ? (
        <div style={nextActionsBoxStyle}>
          <span style={sectionTitleStyle}>Next actions</span>
          <ul style={nextActionsListStyle}>
            {nextActions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/* ── styles ────────────────────────────────────────────────────────── */

const twoColLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(280px, 1fr) minmax(280px, 1fr)",
  gap: 14,
  alignItems: "start",
};

const formCardStyle: CSSProperties = {
  display: "grid",
  gap: 12,
  padding: 12,
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
};

const planCardStyle: CSSProperties = {
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
  fontSize: 10,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const actionsRowStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
};

const noticeStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  lineHeight: 1.6,
  color: "var(--text-mute)",
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
};

const stepsStyle: CSSProperties = {
  display: "grid",
  gap: 6,
};

const stepRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "80px 1fr auto auto",
  gap: 8,
  alignItems: "center",
  padding: "4px 0",
  borderBottom: "1px solid var(--border-subtle)",
};

const warnBoxStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 12,
  color: "var(--text-primary)",
};

const nextActionsBoxStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  paddingTop: 8,
  borderTop: "1px solid var(--border-subtle)",
};

const nextActionsListStyle: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  color: "var(--text-mute)",
  fontSize: 11,
  lineHeight: 1.6,
};

const bodyStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontSize: 12,
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-primary)",
  fontWeight: 600,
  fontSize: 12,
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
  fontSize: 11,
};
