/**
 * Market mood card on the Welcome dashboard.
 *
 * The card renders the CNN Fear & Greed reading held by `useSentimentStore`
 * (fed by `/api/sentiment/market-gauge`). Pins:
 *  - no number is ever shown without an accepted reading;
 *  - ok:false shows the backend reason and no score;
 *  - a transport error offers Retry;
 *  - the reading shows the score, rating, change vs previous close and as-of.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { Welcome } from "./Welcome";
import { useAppStore } from "@/lib/store";
import { useSentimentStore } from "@/lib/sentiment-store";
import { formatUtcStamp } from "@/functions/awareness/FearGreedGauge";

// Welcome's useFunction calls would otherwise try to hit the sidecar in jsdom;
// stub them. Returning `idle` keeps the loading/skeleton paths benign.
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({ state: "idle", data: null, error: null, refetch: () => {} }),
}));

const refreshSpy = vi.fn();

function freshAsOf(): string {
  // Two hours ago: well inside the 36 h staleness window.
  return new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
}

function reading(
  overrides: Partial<
    NonNullable<ReturnType<typeof useSentimentStore.getState>["gauge"]>
  > = {},
) {
  return {
    score: 22.4,
    rating: "Extreme Fear",
    as_of: "2026-11-06T23:59:00Z",
    previous_close: 24.6,
    source: "CNN Fear & Greed via Awareness",
    stale: false,
    providerStatus: null,
    cryptoScore: null,
    cryptoRating: null,
    ...overrides,
  };
}

beforeEach(() => {
  cleanup();
  localStorage.clear();
  // Force "booting" so the auto-refresh effect bails and tests control the store.
  useAppStore.setState({
    sidecarStatus: "booting",
    sidecarPort: null,
    engineRoot: null,
    functionIndex: [],
  });
  useSentimentStore.setState({
    gauge: null,
    unavailableReason: null,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
    refresh: refreshSpy,
  });
  refreshSpy.mockReset();
});

describe("Market mood card — states", () => {
  it("first mount (no reading, loading) shows Loading and no score", () => {
    useSentimentStore.setState({ loading: true });
    const { getByTestId, queryByTestId } = render(<Welcome />);
    expect(getByTestId("sentiment-label").textContent).toBe("Loading…");
    expect(queryByTestId("sentiment-score")).toBeNull();
    expect(queryByTestId("sentiment-gauge")).toBeNull();
  });

  it("backend ok:false shows the reason verbatim and renders no number", () => {
    useSentimentStore.setState({
      unavailableReason: "awareness-markets is not running",
      gauge: null,
    });
    const { getByTestId, queryByTestId, container } = render(<Welcome />);
    expect(getByTestId("sentiment-label").textContent).toBe("Market mood unavailable");
    expect(getByTestId("sentiment-reason").textContent).toBe(
      "awareness-markets is not running",
    );
    expect(queryByTestId("sentiment-score")).toBeNull();
    expect(queryByTestId("sentiment-gauge")).toBeNull();
    expect(container.querySelector('[data-testid="market-mood"]')?.textContent).not.toMatch(
      /\b\d{2}\b/,
    );
  });

  it("transport error with no reading offers Retry, which refreshes", () => {
    useSentimentStore.setState({ error: "503 Service Unavailable" });
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("sentiment-label").textContent).toBe("Market mood unavailable");
    const retry = getByTestId("sentiment-retry");
    act(() => {
      fireEvent.click(retry);
    });
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });
});

describe("Market mood card — accepted reading", () => {
  it("shows the score, rating, change vs previous close and the source line", () => {
    const asOf = freshAsOf();
    useSentimentStore.setState({
      gauge: reading({ as_of: asOf, previous_close: 24.6 }),
      lastUpdated: new Date(),
    });
    const { getByTestId, container } = render(<Welcome />);
    expect(getByTestId("sentiment-score").textContent).toBe("22");
    expect(getByTestId("sentiment-label").textContent).toBe("Extreme fear");
    expect(getByTestId("sentiment-change").textContent).toBe("−2.2 vs prev close");
    expect(getByTestId("sentiment-gauge").getAttribute("aria-label")).toBe(
      "Fear and Greed gauge at 22, extreme fear",
    );
    expect(container.querySelector(".aw-mood__source")?.textContent).toContain(
      `CNN Fear & Greed, as of ${formatUtcStamp(asOf)}.`,
    );
  });

  it("no previous close → change shows an em dash, not a default", () => {
    useSentimentStore.setState({
      gauge: reading({ as_of: freshAsOf(), previous_close: null }),
      lastUpdated: new Date(),
    });
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("sentiment-change").textContent).toBe("—");
  });

  it("a reading older than 36 h is flagged stale", () => {
    useSentimentStore.setState({
      gauge: reading({ as_of: "2026-11-01T23:59:00Z" }),
      lastUpdated: new Date(),
    });
    const { container } = render(<Welcome />);
    expect(container.querySelector(".aw-mood__stale")?.textContent).toContain("stale");
  });

  it("the MSENT jump button opens the market sentiment pane", () => {
    useSentimentStore.setState({
      gauge: reading({ as_of: freshAsOf() }),
      lastUpdated: new Date(),
    });
    const { getByRole } = render(<Welcome />);
    fireEvent.click(getByRole("button", { name: "MSENT" }));
    expect(window.location.hash).toBe("#/fn/MSENT");
  });
});

describe("Market mood card — refresh", () => {
  it("auto-refresh fires once sidecar becomes healthy", () => {
    // Status was "booting" in beforeEach — effect bails.
    const { rerender } = render(<Welcome />);
    expect(refreshSpy).not.toHaveBeenCalled();

    act(() => {
      useAppStore.setState({ sidecarStatus: "healthy" });
    });
    rerender(<Welcome />);
    expect(refreshSpy).toHaveBeenCalled();
  });
});

describe("Welcome — demo data banners on BRIEF + MOVERS", () => {
  it("renders 'Demo data' banner on the BRIEF panel", () => {
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("brief-demo-banner").textContent).toMatch(/Demo data/i);
  });

  it("renders 'Demo data' badge on the MOVERS panel header", () => {
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("movers-demo-banner").textContent).toMatch(/Demo data/i);
  });
});

describe("Market mood card — F6 notices (M-6, M-7)", () => {
  it("keeps the reading and says a refresh failed after a good reading", () => {
    useSentimentStore.setState({
      gauge: reading({ as_of: freshAsOf() }),
      lastUpdated: new Date(),
      error: "sidecar timeout",
    });
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("sentiment-refresh-error").textContent).toContain(
      "Refresh failed: sidecar timeout",
    );
    expect(getByTestId("sentiment-score").textContent).toBe("22");
  });

  it("flags a degraded CNN provider next to the reading", () => {
    useSentimentStore.setState({
      gauge: reading({
        as_of: freshAsOf(),
        stale: true,
        providerStatus: {
          provider: "sent.cnn_fng",
          status: "degraded",
          last_error: "HTTP 503",
        },
      }),
      lastUpdated: new Date(),
    });
    const { getByTestId } = render(<Welcome />);
    const notice = getByTestId("sentiment-provider-stale").textContent ?? "";
    expect(notice).toContain("sent.cnn_fng");
    expect(notice).toContain("HTTP 503");
    expect(getByTestId("sentiment-score").textContent).toBe("22");
  });

  it("the source line carries the crypto reading as a footnote", () => {
    useSentimentStore.setState({
      gauge: reading({ as_of: freshAsOf(), cryptoScore: 28, cryptoRating: "Fear" }),
      lastUpdated: new Date(),
    });
    const { container } = render(<Welcome />);
    expect(container.querySelector(".aw-mood__source")?.textContent).toContain(
      "Crypto: 28, fear.",
    );
  });

  it("no crypto reading means no crypto footnote", () => {
    useSentimentStore.setState({
      gauge: reading({ as_of: freshAsOf() }),
      lastUpdated: new Date(),
    });
    const { container } = render(<Welcome />);
    expect(container.querySelector(".aw-mood__source")?.textContent).not.toContain(
      "Crypto",
    );
  });
});
