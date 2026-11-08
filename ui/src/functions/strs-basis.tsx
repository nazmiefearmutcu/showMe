import { Pill } from "@/design-system";

/**
 * STRS#6: the stress run's valuation basis, stated on screen.
 *
 * The backend reports `price_source` (top-level for a named or custom run,
 * `summary.price_source` for a compare run). Before this strip the pane never
 * read it, so a run valued at average cost looked the same as a live one.
 */
export function strsPriceSource(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as { price_source?: unknown; summary?: { price_source?: unknown } };
  const raw = p.price_source ?? p.summary?.price_source;
  return typeof raw === "string" && raw.length > 0 ? raw : null;
}

export function strsBasisText(source: string): { tone: "warn" | "positive"; text: string } | null {
  if (source === "live_quote") {
    return { tone: "positive", text: "Valuation: live quotes for every position." };
  }
  if (source === "mixed") {
    return {
      tone: "warn",
      text: "Valuation: Mixed basis, with some positions at average cost, not live marks (see warnings).",
    };
  }
  if (source === "portfolio_state_cost") {
    return { tone: "warn", text: "Valuation: average cost, not live marks (no live refresh)." };
  }
  // Any other value (e.g. "n/a" for an empty portfolio) carries no basis to state.
  return null;
}

export function StrsPriceBasis({ payload }: { payload: unknown }) {
  const source = strsPriceSource(payload);
  const basis = source ? strsBasisText(source) : null;
  if (!basis) return null;
  return (
    <div className="portfolio-warning-strip" role="status" data-testid="strs-price-basis">
      <Pill tone={basis.tone} variant="soft" withDot={false}>
        {basis.text}
      </Pill>
    </div>
  );
}
