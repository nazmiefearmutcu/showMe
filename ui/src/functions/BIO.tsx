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
  type BioVia,
  type BiometricCapabilities,
  type BiometricResult,
  type BiometryKind,
} from "@/lib/biometric";
import { formatMissing, formatNumber } from "@/lib/format";
import { relativeTimeLabel } from "@/lib/time";
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
  /** A1 — accessible name so state isn't conveyed by colour alone. */
  ariaLabel: string;
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
    // D2 — honest freshness via the shared relativeTimeLabel; no fabricated time.
    const lastLabel = lastTs
      ? relativeTimeLabel(new Date(lastTs).toISOString()) ?? formatMissing
      : "henüz yok";
    const total = verifyCount.allowed + verifyCount.denied;
    const winRate = total > 0 ? Math.round((verifyCount.allowed / total) * 100) : null;
    const allowedCount = formatNumber(verifyCount.allowed);
    const deniedCount = formatNumber(verifyCount.denied);
    // D1 — human-readable biometry kind (touch_id → "Touch ID", none → "—").
    const biometryLabel = biometryKindLabel(caps.biometry_kind);
    const biometrySub = caps.biometry_available
      ? "available"
      : "Biyometri yalnızca masaüstü uygulamada kullanılabilir";
    const lastResultText = result
      ? result.allowed
        ? "ALLOWED"
        : "DENIED"
      : "NOT RUN";
    return [
      {
        key: "biometry",
        label: "Biometry",
        primary: biometryLabel,
        sub: biometrySub,
        tone: caps.biometry_available ? "positive" : "muted",
        icon: "◉",
        ariaLabel: `Biometry: ${biometryLabel} — ${caps.biometry_available ? "kullanılabilir" : "kullanılamıyor"}`,
      },
      {
        key: "passcode",
        label: "Device passcode",
        primary: caps.passcode_available ? "ENABLED" : "DISABLED",
        sub: "macOS owner policy",
        tone: caps.passcode_available ? "positive" : "warn",
        icon: "▣",
        ariaLabel: `Device passcode: ${caps.passcode_available ? "ENABLED" : "DISABLED"}`,
      },
      {
        key: "last",
        label: "Last verify",
        primary: lastResultText,
        // D1 — human-readable via; D2 — honest relative freshness.
        sub: result
          ? `${viaLabel(result.via)} · ${lastLabel}`
          : "click verify to open OS prompt",
        tone: result ? (result.allowed ? "positive" : "negative") : "muted",
        icon: "⌖",
        // A1 — include result + via + freshness so allowed/denied isn't colour-only.
        ariaLabel: result
          ? `Last verify: ${lastResultText} — ${viaLabel(result.via)}, ${lastLabel}`
          : `Last verify: ${lastResultText}`,
      },
      {
        key: "session",
        label: "Session",
        // D3 — counts via formatNumber for locale consistency.
        primary:
          total === 0
            ? formatMissing
            : `${allowedCount} / ${formatNumber(total)}${winRate != null ? ` · ${winRate}%` : ""}`,
        sub:
          total === 0
            ? "no verifications this session"
            : `allowed · ${allowedCount} · denied · ${deniedCount}`,
        tone: total === 0 ? "muted" : winRate != null && winRate >= 80 ? "positive" : "warn",
        icon: "◇",
        ariaLabel:
          total === 0
            ? "Session: no verifications this session"
            : `Session: ${allowedCount} allowed of ${formatNumber(total)}`,
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
                aria-busy={loading}
                aria-label="Biyometrik doğrulama iste"
                title={!caps ? "Yetenekler yükleniyor…" : undefined}
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
              // A3 — the load transition is announced; scoped to the !caps state
              // only (the steady-state card grid below is NOT wrapped, so it
              // won't re-announce on every refresh).
              <div role="status" aria-live="polite" aria-busy>
                <Skeleton height={128} />
              </div>
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
      aria-label={card.ariaLabel}
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

// D1 — map the OS biometry kind to a human label ("none" → honest "—").
function biometryKindLabel(kind: BiometryKind): string {
  switch (kind) {
    case "touch_id":
      return "Touch ID";
    case "face_id":
      return "Face ID";
    case "none":
    default:
      return formatMissing;
  }
}

// D1 — map the verify `via` to a human label for the Last-verify sub-line.
function viaLabel(via: BioVia): string {
  switch (via) {
    case "touch_id":
      return "Touch ID";
    case "face_id":
      return "Face ID";
    case "password":
      return "Passcode";
    case "denied":
      return "Reddedildi";
    case "unavailable":
    case "stub":
      return "Kullanılamıyor";
    default:
      return via;
  }
}
