import { useEffect, useState, type CSSProperties } from "react";
import { Pill } from "@/design-system";
import { fetchXSymbolChip, type XSymbolChip } from "@/lib/xai";
import { navigate } from "@/lib/router";

/**
 * Compact X-sentiment chip embedded in symbol-bound panes (DES / TOP / NI / CN ...).
 * One inline pill + score + click → opens the full XSEN pane for that symbol.
 *
 * Failures are silent: if the AI sidecar is offline or the query returns no
 * posts, the chip simply hides itself instead of polluting the host pane.
 */
export function XSenChip({
  symbol,
  limit = 60,
  since,
  compact = false,
}: {
  symbol: string | null | undefined;
  limit?: number;
  since?: string;
  compact?: boolean;
}) {
  const [chip, setChip] = useState<XSymbolChip | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error">("idle");

  useEffect(() => {
    if (!symbol) {
      setChip(null);
      setState("idle");
      return;
    }
    let cancelled = false;
    setState("loading");
    fetchXSymbolChip(symbol, { limit, since })
      .then((response) => {
        if (cancelled) return;
        setChip(response);
        setState(response.ok ? "ok" : "error");
      })
      .catch(() => {
        if (cancelled) return;
        setChip(null);
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, limit, since]);

  if (!symbol) return null;
  if (state === "idle") return null;
  if (state === "loading") {
    return (
      <span style={{ ...wrapper, opacity: 0.55 }} title="X sentiment loading…">
        <span style={dot} />
        <span style={hint}>X · loading</span>
      </span>
    );
  }
  if (state === "error" || !chip || !chip.ok) {
    return null;
  }

  const score = chip.bullish_score ?? 0;
  const tone =
    chip.mood === "bullish"
      ? "positive"
      : chip.mood === "bearish"
        ? "negative"
        : "warn";
  const titleText = chip.summary_tr ?? `X mood for ${chip.symbol}: ${chip.mood ?? "—"}`;
  const handleClick = () => {
    try {
      navigate(`/symbol/${encodeURIComponent(chip.symbol)}/XSEN`);
    } catch {
      // best-effort; no toast — chip should be silent on failure
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      title={titleText}
      style={{
        ...wrapper,
        cursor: "pointer",
        border: "1px solid var(--border-subtle)",
        background: "var(--bg-elev-2)",
      }}
    >
      <Pill tone={tone} withDot={false}>
        X · {chip.mood ?? "—"}
      </Pill>
      <span style={scoreText} data-positive={score >= 0}>
        {score >= 0 ? "+" : ""}
        {score.toFixed(2)}
      </span>
      {!compact ? (
        <span style={hint}>
          {chip.post_count} posts · {chip.dominant?.emotion ?? "—"} / {chip.dominant?.topic ?? "—"}
        </span>
      ) : null}
    </button>
  );
}

const wrapper: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "2px 6px 2px 4px",
  borderRadius: 12,
  border: "1px solid transparent",
  background: "transparent",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
};

const dot: CSSProperties = {
  display: "inline-block",
  width: 6,
  height: 6,
  borderRadius: 3,
  background: "var(--accent)",
};

const scoreText: CSSProperties = {
  fontWeight: 700,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--text-primary)",
};

const hint: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
};
