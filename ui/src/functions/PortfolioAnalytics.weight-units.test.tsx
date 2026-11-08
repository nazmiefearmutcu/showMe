/**
 * UI-4 — plain `weight` fields are not percent by magnitude.
 *
 * The backends disagree on the unit of a bare `weight` key: rpar / pcas /
 * port_opt emit a fraction (0-1), pvar emits percent (x100) under the same key.
 * The shared formatter used to guess by magnitude (|v| <= 1 => fraction), so a
 * percent-unit 0.8 rendered as "80.00%" and a 120% leverage weight rendered as
 * "1.20%". A bare weight now shows the raw number with no % sign; the explicit
 * `*_pct` siblings carry the percent.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioAnalyticsPane } from "./PortfolioAnalytics";

function mockOk(payload: Record<string, unknown>) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: payload,
      metadata: { live: true },
      sources: ["showme engine"],
      warnings: [],
      elapsed_ms: 90,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

describe("PORTX bare weight units (UI-4)", () => {
  it("does not render a percent-unit 0.8 weight as 80.00%", () => {
    mockOk({ status: "ok", rows: [{ symbol: "AAA", weight: 0.8 }] });
    const { container } = render(<PortfolioAnalyticsPane code="PVAR" symbol="" />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("80.00%");
    expect(text).not.toContain("0.8%");
  });

  it("does not render a 120% leverage weight as 1.20%", () => {
    mockOk({ status: "ok", rows: [{ symbol: "AAA", weight: 1.2 }] });
    const { container } = render(<PortfolioAnalyticsPane code="RPAR" symbol="" />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("1.20%");
    expect(text).toContain("1.2000");
  });

  it("does not render a fraction weight 0.25 as a percent", () => {
    mockOk({ status: "ok", rows: [{ symbol: "AAA", weight: 0.25 }] });
    const { container } = render(<PortfolioAnalyticsPane code="RPAR" symbol="" />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("25.00%");
    expect(text).not.toContain("0.25%");
    expect(text).toContain("0.2500");
  });

  it("still renders an explicit weight_pct column as a percent", () => {
    mockOk({ status: "ok", rows: [{ symbol: "AAA", weight_pct: 25 }] });
    const { container } = render(<PortfolioAnalyticsPane code="RPAR" symbol="" />);
    expect(container.textContent ?? "").toContain("25.00%");
  });
});
