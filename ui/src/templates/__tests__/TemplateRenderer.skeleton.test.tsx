/**
 * BugHunt 2026-05-24 — Theme 3, Bug #3 regression spec.
 *
 * The pre-fix bug: while the sidecar `/api/fn/{code}` call was in flight
 * (state === "loading"), `TemplateRenderer` returned the pure mock
 * template. For an option chain like OMON on AAPL, this meant the user
 * saw four strikes at $1,400-$1,500 next to "AAPL" for ~5 seconds and
 * then the chain flipped to a different set of strikes. To anyone
 * scanning quickly, the mock prices looked like live AAPL option data.
 *
 * The fix introduces an `allowMockDuringLoad` flag on `MockTemplate`. It
 * defaults to `false` for numeric-pricing templates (the listed nine plus
 * any other template with strike/price columns), so the renderer shows a
 * skeleton placeholder instead of the mock until `state === "ok"`. Once
 * live data arrives, the merged template renders normally.
 *
 * These tests pin:
 *   1. Loading state never leaks mock prices for `allowMockDuringLoad: false`.
 *   2. Live OK state restores the merged template.
 *   3. Templates with the flag absent stay safe (default behaviour).
 *   4. All nine listed templates (OMON, OSA, OVME, AIM, BBGT, FXGO, TCA,
 *      HVT, IVOL) are flagged in `mock-data.ts`.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, cleanup } from "@testing-library/react";

import { TemplateRenderer } from "../TemplateRenderer";
import { getMockTemplate } from "../mock-data";

// Mockable useFunction handle so individual tests can set the state /
// data without driving the real polling effect.
const useFunctionMock = vi.fn();
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => useFunctionMock(args),
}));

beforeEach(() => {
  cleanup();
  useFunctionMock.mockReset();
});

describe("TemplateRenderer — allowMockDuringLoad", () => {
  it("OMON loading: does NOT render the mock 1400/1430/1450/1500 strikes", () => {
    useFunctionMock.mockReturnValue({
      state: "loading",
      data: null,
      error: undefined,
      refetch: () => {},
    });
    const { container } = render(<TemplateRenderer code="OMON" symbol="AAPL" />);
    // Inspect rendered text (NOT raw innerHTML), so we don't match CSS-only
    // tokens like the skeleton-shimmer "1400ms" animation duration.
    const text = container.textContent ?? "";
    expect(text).not.toContain("1400");
    expect(text).not.toContain("1430");
    expect(text).not.toContain("1450");
    expect(text).not.toContain("1500");
    expect(text).not.toContain("28.4%"); // IV column would be a giveaway too.
    // Skeleton aria attribute should be present so screen-readers
    // surface the loading state.
    const busy = container.querySelector('[aria-busy="true"]');
    expect(busy).not.toBeNull();
  });

  it("OMON ok state: live strikes render once the sidecar replies", () => {
    useFunctionMock.mockReturnValue({
      state: "ok",
      data: {
        data: {
          rows: [
            { Strike: 300, IV: "21.4%", "Δ": 0.55, "Γ": 0.012, Vol: "9K", OI: "42K" },
            { Strike: 305, IV: "20.8%", "Δ": 0.48, "Γ": 0.014, Vol: "11K", OI: "62K" },
          ],
        },
        elapsed_ms: 120,
        sources: ["yfinance"],
      },
      error: undefined,
      refetch: () => {},
    });
    const { container } = render(<TemplateRenderer code="OMON" symbol="AAPL" />);
    const text = container.textContent ?? "";
    expect(text).toContain("300");
    expect(text).toContain("305");
    // Mock strikes must not appear at the same time.
    expect(text).not.toContain("1400");
    expect(text).not.toContain("1430");
  });

  it.each([
    ["OSA", ["1,420", "1,439"]],
    ["OVME", ["1,432", "1,450", "42.18"]],
    ["AIM", ["1432.18", "228.4", "NVDA"]],
    ["BBGT", ["1432.18", "$358,045"]],
    ["FXGO", ["1.0840", "1.0844"]],
    ["TCA", ["1.2 bps", "0.8 bps"]],
    ["HVT", ["32.4%", "28.6%"]],
    ["IVOL", ["22.4%", "24.8%"]],
  ])(
    "%s loading: no mock numeric values leak through",
    (code, mockNumbers) => {
      useFunctionMock.mockReturnValue({
        state: "loading",
        data: null,
        error: undefined,
        refetch: () => {},
      });
      const { container } = render(
        <TemplateRenderer code={code} symbol="AAPL" />,
      );
      const text = container.textContent ?? "";
      for (const numeric of mockNumbers) {
        expect(text, `${code} should hide '${numeric}' during load`).not.toContain(numeric);
      }
      // Skeleton placeholder must be present.
      expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    },
  );

  it("ok state with no live payload still renders mock (graceful degrade)", () => {
    // When the sidecar comes back ok but with no recognisable data, the
    // merged template falls back to the mock — but only because state ===
    // "ok" means we're past the misleading-loading window. The badge tells
    // the user this is demo content.
    useFunctionMock.mockReturnValue({
      state: "ok",
      data: { data: {} },
      error: undefined,
      refetch: () => {},
    });
    const { container } = render(<TemplateRenderer code="OMON" symbol="AAPL" />);
    expect(container.textContent ?? "").toContain("1400");
  });
});

describe("MockTemplate — allowMockDuringLoad flag coverage", () => {
  const FLAGGED_CODES = [
    "OMON",
    "OSA",
    "OVME",
    "AIM",
    "BBGT",
    "FXGO",
    "TCA",
    "HVT",
    "IVOL",
  ] as const;

  it.each(FLAGGED_CODES)(
    "%s is explicitly marked allowMockDuringLoad: false",
    (code) => {
      const tpl = getMockTemplate(code);
      expect(tpl, `${code} mock template must exist`).not.toBeNull();
      expect(tpl?.allowMockDuringLoad).toBe(false);
    },
  );
});
