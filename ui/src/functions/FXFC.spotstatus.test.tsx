/**
 * FXFC#4-RQ: the spot pill must not call a non-fresh yfinance spot "live".
 * An off-session print or a quote with no upstream time is labelled as such.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FXFCPane } from "./FXFC";

const h = vi.hoisted(() => ({ data: null as unknown }));

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: h.data,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

function payload(spotQuoteStatus: string | null, sourceMode = "live_yfinance_quote") {
  const row = {
    pair: "EURUSD",
    horizon: "3M",
    tenor_years: 0.25,
    spot: 1.1,
    forecast: 1.1027,
    lower_band: null,
    upper_band: null,
    forward_points: 0.0027,
    vol_annualized: null,
    source_mode: sourceMode,
  };
  return {
    warnings: [] as string[],
    sources: ["yfinance"],
    elapsed_ms: 1,
    data: {
      pair: "EURUSD",
      spot: 1.1,
      source_mode: sourceMode,
      spot_quote_status: spotQuoteStatus,
      forecast: [row],
      curve: [row],
    },
  };
}

afterEach(() => {
  cleanup();
});

describe("FXFC spot status pill", () => {
  it("shows live spot only for a fresh quote", () => {
    h.data = payload("fresh");
    render(<FXFCPane code="FXFC" symbol="EURUSD" />);
    expect(screen.getByText("live spot")).toBeInTheDocument();
  });

  it("does not label an off-session print as live spot", () => {
    h.data = payload("off_session");
    render(<FXFCPane code="FXFC" symbol="EURUSD" />);
    expect(screen.queryByText("live spot")).toBeNull();
    expect(screen.getByText("off-session print")).toBeInTheDocument();
  });

  it("does not label a quote with no upstream time as live spot", () => {
    h.data = payload("quote_time_unavailable");
    render(<FXFCPane code="FXFC" symbol="EURUSD" />);
    expect(screen.queryByText("live spot")).toBeNull();
    expect(screen.getByText("spot time unknown")).toBeInTheDocument();
  });

  it("keeps stale spot as stale", () => {
    h.data = payload("stale");
    render(<FXFCPane code="FXFC" symbol="EURUSD" />);
    expect(screen.getByText("stale spot")).toBeInTheDocument();
  });

  it.each(["live_ecb_reference", "live_official"])(
    "FXFC#4-RQ: an ECB-based %s spot is a daily fix, not live spot",
    (mode) => {
      h.data = payload("not_applicable", mode);
      render(<FXFCPane code="FXFC" symbol="EURUSD" />);
      expect(screen.queryByText("live spot")).toBeNull();
      expect(screen.getByText("ECB daily fix")).toBeInTheDocument();
    },
  );
});
