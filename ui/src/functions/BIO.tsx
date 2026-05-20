/**
 * BIO — Bloomberg-grade biometric / authentication status pane.
 *
 * Status grid with 4 cards (Biometry / Passcode / Last Verify / Capabilities),
 * each showing icon + label + primary metric + sub-metrics + status dot.
 * Bottom log stream shows the local verifier history (rolling, not persisted).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Field,
  type LogEntry,
  LogStream,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusSection,
} from "@/design-system";
import {
  capabilities,
  requestBiometric,
  type BiometricCapabilities,
  type BiometricResult,
} from "@/lib/biometric";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

type StatusTone = "positive" | "negative" | "warn" | "muted" | "neutral";

interface BioStatusCard {
  key: string;
  label: string;
  primary: string;
  sub: string;
  tone: StatusTone;
  icon: string;
}

export function BIOPane({ code }: FunctionPaneProps) {
  const [caps, setCaps] = useState<BiometricCapabilities | null>(null);
  const [result, setResult] = useState<BiometricResult | null>(null);
  const [reason, setReason] = useState("ShowMe biometric verification");
  const [loading, setLoading] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [verifyCount, setVerifyCount] = useState({ allowed: 0, denied: 0 });
  const lastVerifiedAt = useRef<number | null>(null);

  const appendLog = (entry: LogEntry) => {
    setLogs((prev) => [...prev.slice(-49), entry]);
  };

  const refresh = async () => {
    setCaps(null);
    const next = await capabilities();
    setCaps(next);
    appendLog({
      ts: new Date().toISOString(),
      level: "info",
      message: `capabilities · biometry=${next.biometry_kind} avail=${next.biometry_available} pass=${next.passcode_available}`,
      source: "bio",
    });
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const verify = async () => {
    setLoading(true);
    appendLog({
      ts: new Date().toISOString(),
      level: "debug",
      message: `verify · request reason="${reason.trim() || "ShowMe biometric verification"}"`,
      source: "bio",
    });
    try {
      const out = await requestBiometric(
        reason.trim() || "ShowMe biometric verification",
      );
      setResult(out);
      setCaps(await capabilities());
      lastVerifiedAt.current = Date.now();
      setVerifyCount((c) =>
        out.allowed
          ? { allowed: c.allowed + 1, denied: c.denied }
          : { allowed: c.allowed, denied: c.denied + 1 },
      );
      appendLog({
        ts: new Date().toISOString(),
        level: out.allowed ? "info" : "warn",
        message: `verify · ${out.allowed ? "allowed" : "denied"} via ${out.via} — ${out.reason}`,
        source: "bio",
      });
    } catch (err) {
      appendLog({
        ts: new Date().toISOString(),
        level: "error",
        message: `verify · failed: ${err instanceof Error ? err.message : String(err)}`,
        source: "bio",
      });
    } finally {
      setLoading(false);
    }
  };

  const cards = useMemo<BioStatusCard[]>(() => {
    if (!caps) return [];
    const lastTs = lastVerifiedAt.current;
    const lastLabel = lastTs ? formatRelTime(lastTs) : "never";
    const total = verifyCount.allowed + verifyCount.denied;
    const winRate = total > 0 ? Math.round((verifyCount.allowed / total) * 100) : null;
    return [
      {
        key: "biometry",
        label: "Biometry",
        primary: caps.biometry_kind.replace("_", " ").toUpperCase(),
        sub: caps.biometry_available ? "available" : "unavailable",
        tone: caps.biometry_available ? "positive" : "muted",
        icon: "◉",
      },
      {
        key: "passcode",
        label: "Device passcode",
        primary: caps.passcode_available ? "ENABLED" : "DISABLED",
        sub: "macOS owner policy",
        tone: caps.passcode_available ? "positive" : "warn",
        icon: "▣",
      },
      {
        key: "last",
        label: "Last verify",
        primary: result
          ? result.allowed
            ? "ALLOWED"
            : "DENIED"
          : "NOT RUN",
        sub: result
          ? `${result.via} · ${lastLabel}`
          : "click verify to open OS prompt",
        tone: result ? (result.allowed ? "positive" : "negative") : "muted",
        icon: "⌖",
      },
      {
        key: "session",
        label: "Session",
        primary:
          total === 0
            ? "—"
            : `${verifyCount.allowed} / ${total}${winRate != null ? ` · ${winRate}%` : ""}`,
        sub:
          total === 0
            ? "no verifications this session"
            : `allowed · ${verifyCount.allowed} · denied · ${verifyCount.denied}`,
        tone: total === 0 ? "muted" : winRate != null && winRate >= 80 ? "positive" : "warn",
        icon: "◇",
      },
    ];
  }, [caps, result, verifyCount]);

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Biometric Auth"
          subtitle="macOS LocalAuthentication"
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={caps?.biometry_available ? "positive" : "muted"}
                variant="soft"
                withDot={Boolean(caps?.biometry_available)}
              >
                {caps?.biometry_available ? "READY" : "NO BIO"}
              </Pill>
              <LoadStatePill state={caps ? "ok" : "loading"} />
              <button
                className="btn btn--accent bio-verify-btn"
                type="button"
                onClick={verify}
                disabled={loading || !caps}
              >
                {loading ? "Verifying…" : "Verify"}
              </button>
              <RefreshButton
                loading={!caps}
                onClick={refresh}
                title="Refresh capabilities"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-grid-gap-14">
            <Field
              label="Prompt reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Reason shown in the OS prompt"
            />

            {!caps ? (
              <Skeleton height={128} />
            ) : (
              <div className="bio-card-grid">
                {cards.map((card) => (
                  <StatusCard key={card.key} card={card} />
                ))}
              </div>
            )}

            <div className="bio-log-section">
              <div className="bio-log-head">
                <span className="bio-log-label">Verifier log</span>
                <Pill tone="muted" variant="soft" withDot={false}>
                  {logs.length} events
                </Pill>
              </div>
              <LogStream entries={logs} maxHeight={180} follow monoFontSize={11} />
            </div>
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="STORAGE"
            value="none"
            tone="muted"
          />
          <StatusSection
            label="PROMPT"
            value="user-initiated"
            tone="muted"
          />
          <StatusSection
            label="SESSION"
            value={`${verifyCount.allowed} ok · ${verifyCount.denied} no`}
            tone={
              verifyCount.denied > verifyCount.allowed && verifyCount.denied > 0
                ? "warn"
                : "neutral"
            }
            withDot={verifyCount.allowed > 0}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function StatusCard({ card }: { card: BioStatusCard }) {
  const fg =
    card.tone === "positive"
      ? "var(--positive)"
      : card.tone === "negative"
        ? "var(--negative)"
        : card.tone === "warn"
          ? "var(--warn)"
          : card.tone === "muted"
            ? "var(--text-mute)"
            : "var(--text-primary)";
  const bg =
    card.tone === "positive"
      ? "var(--positive-soft)"
      : card.tone === "negative"
        ? "var(--negative-soft)"
        : card.tone === "warn"
          ? "var(--warn-soft)"
          : "color-mix(in srgb, var(--text-mute) 12%, transparent)";
  return (
    <div
      className="bio-status-card"
      style={{
        ["--bio-fg" as string]: fg,
        ["--bio-bg" as string]: bg,
      }}
    >
      <div className="bio-status-card__head">
        <span className="bio-status-card__label">
          <span aria-hidden className="bio-status-card__icon">{card.icon}</span>
          {card.label}
        </span>
        <span aria-hidden className="bio-status-card__dot" />
      </div>
      <div className="bio-status-card__primary">{card.primary}</div>
      <div className="bio-status-card__sub">{card.sub}</div>
      <span aria-hidden className="bio-status-card__bg" />
    </div>
  );
}

function formatRelTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 1500) return "now";
  if (diff < 60_000) return `${Math.round(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  return `${Math.round(diff / 3_600_000)}h ago`;
}
