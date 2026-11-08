/**
 * ONCH pane — live data_mode must not read as a muted/unknown state.
 *
 * The backend now reports data_mode "live" when every row was fetched in the
 * same call (ONCH#2). The header pill must render that mode with the positive
 * tone, the same tone the pane gives "live_official".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { ONCHPane } from "./ONCH";

const mockFn: { state: string; data: unknown } = { state: "idle", data: undefined };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/** The useFunction envelope `data` (the pane reads `data.data` as the payload). */
function payloadWithMode(dataMode: string) {
  return {
    sources: ["mempool", "coingecko"],
    elapsed_ms: 12,
    asOf: "2026-11-08T00:00:00+00:00",
    data: {
      status: dataMode === "provider_unavailable" ? "provider_unavailable" : "ok",
      data_mode: dataMode,
      chain: "BTC",
      rows: [
        {
          metric: "Fastest Fee",
          value: "1",
          unit: "sat/vB",
          source: "mempool",
          context: "Next-block inclusion",
        },
      ],
      series: [],
      cards: [{ label: "Chain", value: "BTC" }],
      summary: "summary",
    },
  };
}

function modePill(container: HTMLElement, text: string): HTMLElement | undefined {
  return Array.from(container.querySelectorAll<HTMLElement>(".ds-pill")).find(
    (el) => el.textContent?.trim() === text,
  );
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("ONCH pane — data_mode pill tone", () => {
  it("renders data_mode live with the positive tone", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWithMode("live");

    const { container } = render(<ONCHPane code="ONCH" />);
    const pill = modePill(container, "live");
    expect(pill).toBeDefined();
    expect(pill!.className).toContain("ds-pill--tone-positive");
  });

  it("keeps the warn tone for delayed_reference", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWithMode("delayed_reference");

    const { container } = render(<ONCHPane code="ONCH" />);
    const pill = modePill(container, "delayed_reference");
    expect(pill).toBeDefined();
    expect(pill!.className).toContain("ds-pill--tone-warn");
  });
});
