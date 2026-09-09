/**
 * Lane D (frozen contract §D) — KAOS badge rendering.
 *
 * Pins the honesty contract on the shared badges:
 *   - the PAPER banner renders the backend's exact lane_status text when
 *     venue_rows prove the nasdaq lane is paper;
 *   - the banner is ABSENT (never faked) when rows are missing, undecidable,
 *     or the lane is keyed/shadow;
 *   - venue chips render only from payload venues;
 *   - the KAOS engine chip marks kaos records.
 */
import { describe, expect, it } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { KaosEngineBadge, KaosLaneBanner, VenueBadges } from "./KaosBadges";
import type { KaosLaneRow } from "@/lib/kaos-venues";

const paperRows: KaosLaneRow[] = [
  { venue_id: "crypto", market: "crypto-futures", lane_status: "shadow (paper fills)" },
  { venue_id: "nasdaq", market: "us-equities", lane_status: "PAPER (no Alpaca keys)" },
];

describe("KaosLaneBanner", () => {
  it("renders the backend's exact paper text when provable", () => {
    const { getByTestId } = render(<KaosLaneBanner venueRows={paperRows} />);
    const banner = getByTestId("kaos-nasdaq-paper-banner");
    expect(banner.textContent).toContain("PAPER (no Alpaca keys)");
  });

  it("renders the bars-unavailable paper variant verbatim", () => {
    const rows: KaosLaneRow[] = [
      { venue_id: "nasdaq", market: "us-equities",
        lane_status: "PAPER (no Alpaca keys) — bars unavailable" },
    ];
    const { getByTestId } = render(<KaosLaneBanner venueRows={rows} />);
    expect(getByTestId("kaos-nasdaq-paper-banner").textContent).toContain(
      "PAPER (no Alpaca keys) — bars unavailable",
    );
  });

  it("renders NOTHING when venue_rows is absent (hide, never fake)", () => {
    const { queryByTestId } = render(<KaosLaneBanner venueRows={undefined} />);
    expect(queryByTestId("kaos-nasdaq-paper-banner")).toBeNull();
  });

  it("renders NOTHING for empty or crypto-only rows", () => {
    const a = render(<KaosLaneBanner venueRows={[]} />);
    expect(a.queryByTestId("kaos-nasdaq-paper-banner")).toBeNull();
    cleanup();
    const b = render(<KaosLaneBanner venueRows={[
      { venue_id: "crypto", market: "crypto-futures", lane_status: "idle" },
    ]} />);
    expect(b.queryByTestId("kaos-nasdaq-paper-banner")).toBeNull();
  });

  it("renders NOTHING when the nasdaq lane is NOT paper (idle/shadow)", () => {
    const idle = render(<KaosLaneBanner venueRows={[
      { venue_id: "nasdaq", market: "us-equities", lane_status: "idle" },
    ]} />);
    expect(idle.queryByTestId("kaos-nasdaq-paper-banner")).toBeNull();
    cleanup();
    const shadow = render(<KaosLaneBanner venueRows={[
      { venue_id: "nasdaq", market: "us-equities", lane_status: "shadow (paper fills)" },
    ]} />);
    expect(shadow.queryByTestId("kaos-nasdaq-paper-banner")).toBeNull();
  });
});

describe("VenueBadges", () => {
  const venues = [
    { id: "crypto", exchange_id: "binanceusdm", market: "crypto-futures",
      symbols: ["BTC/USDT:USDT"], risk_profile: "crypto" },
    { id: "nasdaq", exchange_id: "alpaca", market: "us-equities",
      symbols: ["SPY"], risk_profile: "equity" },
  ];

  it("renders one chip per venue (crypto + nasdaq)", () => {
    const { getByTestId } = render(<VenueBadges venues={venues} />);
    const badges = getByTestId("kaos-venue-badges");
    expect(badges.textContent).toContain("CRYPTO");
    expect(badges.textContent).toContain("NASDAQ");
  });

  it("renders NOTHING when venues are absent or empty (defensive)", () => {
    const a = render(<VenueBadges venues={undefined} />);
    expect(a.queryByTestId("kaos-venue-badges")).toBeNull();
    cleanup();
    const b = render(<VenueBadges venues={[]} />);
    expect(b.queryByTestId("kaos-venue-badges")).toBeNull();
  });
});

describe("KaosEngineBadge", () => {
  it("renders the KAOS chip", () => {
    const { getByTestId } = render(<KaosEngineBadge />);
    expect(getByTestId("kaos-engine-badge").textContent).toBe("KAOS");
  });
});
