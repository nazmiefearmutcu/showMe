/**
 * HOME terminal-grade upgrades — data sufficiency, a11y, display quality.
 *
 * Covers:
 *   A1. Movers `useFunction` is invoked with the LIVE param so the sidecar
 *       returns real movers instead of the deterministic reference deck.
 *   A2. BRIEF panel wires live articles; the demo banner is shown only when
 *       the live call is empty/failed and hidden once articles arrive.
 *   B3. Interactive tiles / rows / quick-functions expose aria-labels.
 *   B4. Async loading/placeholder regions announce via role="status".
 *   B5. The sentiment Retry button uses the shared terminal-action class.
 *   C6. Numeric cells carry the tabular-figures class.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import { useAppStore } from "@/lib/store";
import { useSentimentStore } from "@/lib/sentiment-store";
import { Welcome } from "./Welcome";

// Capture every useFunction call so we can assert on the MOST + BRIEF args.
const useFunctionCalls: Array<Record<string, unknown>> = [];
let briefPayload: unknown = null;
let briefState = "ok";
// Per-code state override (e.g. force PORT into "loading" for the skeleton test).
const stateByCode: Record<string, string> = {};

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    useFunctionCalls.push(args);
    const code = args.code as string;
    if (code === "BRIEF") {
      return { state: briefState, data: briefPayload, error: null, refetch: () => {} };
    }
    const forced = stateByCode[code];
    if (forced) {
      return { state: forced, data: null, error: null, refetch: () => {} };
    }
    return { state: "idle", data: null, error: null, refetch: () => {} };
  },
}));

vi.mock("@/lib/market-data", () => ({
  useLiveQuotes: () => ({}),
}));

vi.mock("@/lib/watchlist", async () => {
  const actual = await vi.importActual<typeof import("@/lib/watchlist")>(
    "@/lib/watchlist",
  );
  return actual;
});

beforeEach(() => {
  useFunctionCalls.length = 0;
  briefPayload = null;
  briefState = "ok";
  for (const k of Object.keys(stateByCode)) delete stateByCode[k];
  localStorage.clear();
  useAppStore.setState({
    sidecarStatus: "healthy",
    sidecarPort: 8765,
    engineRoot: null,
    functionIndex: [
      { code: "MOST", name: "Most Active", category: "screen", description: "" },
      { code: "BRIEF", name: "Daily Brief", category: "news", description: "" },
    ],
  });
  useSentimentStore.setState({
    score: 0,
    label: "Neutral",
    mentions: 0,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
    refresh: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
});

describe("A1. Movers request live data", () => {
  it("invokes useFunction for MOST with live:true", async () => {
    render(<Welcome />);
    await waitFor(() => {
      expect(useFunctionCalls.some((c) => c.code === "MOST")).toBe(true);
    });
    const mostCall = useFunctionCalls.find((c) => c.code === "MOST");
    expect(mostCall).toBeTruthy();
    const params = mostCall!.params as Record<string, unknown>;
    expect(params.live).toBe(true);
    expect(params.limit).toBeGreaterThan(0);
  });
});

describe("A2. BRIEF live wiring", () => {
  it("invokes useFunction for BRIEF", async () => {
    render(<Welcome />);
    await waitFor(() => {
      expect(useFunctionCalls.some((c) => c.code === "BRIEF")).toBe(true);
    });
  });

  it("shows the demo banner when BRIEF has no live articles", async () => {
    briefPayload = { data: { status: "empty", articles: [] } };
    const { findByTestId } = render(<Welcome />);
    const banner = await findByTestId("brief-demo-banner");
    expect(banner.textContent).toMatch(/Demo data/i);
  });

  it("hides the demo banner and renders live ribbons when articles arrive", async () => {
    briefPayload = {
      data: {
        status: "ok",
        articles: [
          {
            title: "Fed holds rates steady amid cooling inflation",
            url: "https://example.com/fed",
            source: "Reuters",
            matched_symbol: "MACRO",
            section: "top_stories",
          },
          {
            title: "NVDA guidance lifts semis",
            url: "https://example.com/nvda",
            source: "Bloomberg",
            matched_symbol: "NVDA",
            section: "watchlist",
          },
        ],
      },
    };
    const { queryByTestId, findByText } = render(<Welcome />);
    // A real headline renders.
    await findByText(/Fed holds rates steady/i);
    // The demo banner is gone.
    expect(queryByTestId("brief-demo-banner")).toBeNull();
    // The live indicator is present.
    expect(queryByTestId("brief-live-banner")).not.toBeNull();
  });
});

describe("B3. aria-labels on interactive elements", () => {
  it("market tiles, mover rows and quick-functions carry aria-labels", async () => {
    const { findByTestId, container } = render(<Welcome />);
    const btc = await findByTestId("kpi-tile-BTC");
    expect(btc.getAttribute("aria-label")).toMatch(/bitcoin/i);
    // A quick-function button exposes its code.
    const quick = Array.from(container.querySelectorAll(".terminal-command")).find(
      (b) => b.textContent?.includes("OMON"),
    );
    expect(quick?.getAttribute("aria-label")).toMatch(/OMON/);
    // A mover row exposes its symbol.
    const anyMover = container.querySelector("[data-testid^='mover-row-']");
    expect(anyMover?.getAttribute("aria-label")).toBeTruthy();
  });

  it("watchlist rows carry aria-labels", async () => {
    localStorage.setItem(
      "showme.watchlist",
      JSON.stringify({ rows: [{ symbol: "AAPL" }] }),
    );
    const { container } = render(<Welcome />);
    await waitFor(() => {
      expect(container.querySelector("[role='grid']")).not.toBeNull();
    });
    const row = container.querySelector(
      ".terminal-watchlist__row:not(.terminal-watchlist__row--head)",
    );
    expect(row?.getAttribute("aria-label")).toMatch(/AAPL/);
  });
});

describe("B4. loading regions announce", () => {
  it("newsflow placeholder container is a live region", async () => {
    const { container } = render(<Welcome />);
    const region = container.querySelector(".terminal-newsflow");
    expect(region?.getAttribute("aria-live")).toBe("polite");
  });
});

describe("B5. sentiment retry uses the shared action class", () => {
  it("retry button carries the terminal-action class", async () => {
    useSentimentStore.setState({
      loading: false,
      error: "503 Service Unavailable",
      lastUpdated: null,
    });
    const { findByTestId } = render(<Welcome />);
    const retry = await findByTestId("sentiment-retry");
    expect(retry.className).toMatch(/terminal-action/);
  });
});

describe("C6. tabular numeric class on numeric cells", () => {
  it("KPI tile values carry the numeric class", async () => {
    const { findByTestId } = render(<Welcome />);
    const btc = await findByTestId("kpi-tile-BTC");
    const value = btc.querySelector(".terminal-market-tile__value");
    expect(value?.className).toMatch(/terminal-grid-numeric/);
  });
});

describe("D. loading regions render role=status", () => {
  it("BRIEF loading region has role=status while BRIEF is loading", async () => {
    briefState = "loading";
    briefPayload = null; // no articles → not live → loading branch renders
    const { findByTestId } = render(<Welcome />);
    const region = await findByTestId("brief-loading");
    expect(region.getAttribute("role")).toBe("status");
  });

  it("watchlist loading region has role=status while PORT is loading", async () => {
    stateByCode.PORT = "loading";
    const { findByTestId } = render(<Welcome />);
    const region = await findByTestId("watchlist-loading");
    expect(region.getAttribute("role")).toBe("status");
  });
});

describe("Movers data honesty", () => {
  it("demo mover rows render the missing sentinel for change, not a fake tick", async () => {
    const { container } = render(<Welcome />);
    await waitFor(() => {
      expect(
        container.querySelector("[data-testid^='mover-row-']"),
      ).not.toBeNull();
    });
    const demoRow = container.querySelector(
      "[data-testid^='mover-row-'][data-demo='1']",
    );
    expect(demoRow).not.toBeNull();
    // The change cell must not show a fabricated "+0.01%/-0.01%".
    expect(demoRow!.textContent).not.toMatch(/0\.01%/);
    expect(demoRow!.textContent).toContain("—");
  });
});
