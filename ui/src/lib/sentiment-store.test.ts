import { beforeEach, describe, expect, it, vi } from "vitest";
import { labelForScore, useSentimentStore } from "./sentiment-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  // hard reset between tests to avoid bleed-over from prior aborts
  useSentimentStore.setState({
    score: 0,
    label: "Neutral",
    mentions: 0,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
  });
  mock.mockReset();
});

describe("labelForScore thresholds", () => {
  it("score >= 0.66 → Strongly Bullish", () => {
    expect(labelForScore(0.66)).toBe("Strongly Bullish");
    expect(labelForScore(1)).toBe("Strongly Bullish");
  });
  it("0.33 <= score < 0.66 → Cautiously Bullish", () => {
    expect(labelForScore(0.33)).toBe("Cautiously Bullish");
    expect(labelForScore(0.5)).toBe("Cautiously Bullish");
  });
  it("|score| < 0.33 → Neutral", () => {
    expect(labelForScore(0)).toBe("Neutral");
    expect(labelForScore(0.32)).toBe("Neutral");
    expect(labelForScore(-0.32)).toBe("Neutral");
  });
  it("-0.66 <= score < -0.33 → Cautiously Bearish", () => {
    expect(labelForScore(-0.5)).toBe("Cautiously Bearish");
    expect(labelForScore(-0.34)).toBe("Cautiously Bearish");
  });
  it("score < -0.66 → Strongly Bearish", () => {
    expect(labelForScore(-0.67)).toBe("Strongly Bearish");
    expect(labelForScore(-1)).toBe("Strongly Bearish");
  });
});

describe("sentiment-store.refresh", () => {
  it("single symbol → calls /api/x/symbol_chip and updates score", async () => {
    mock.mockResolvedValueOnce({
      symbol: "AAPL",
      ok: true,
      post_count: 100,
      bullish_score: 0.5,
    });
    await useSentimentStore.getState().refresh(["AAPL"]);
    const s = useSentimentStore.getState();
    expect(mock).toHaveBeenCalledTimes(1);
    expect(mock.mock.calls[0][0]).toBe("/api/x/symbol_chip?symbol=AAPL");
    expect(s.score).toBeCloseTo(0.5, 5);
    expect(s.label).toBe("Cautiously Bullish");
    expect(s.mentions).toBe(100);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
    expect(s.lastUpdated).toBeInstanceOf(Date);
  });

  it("multiple symbols aggregate by mention-weighted average", async () => {
    // 0.8 weighted 100 + (-0.4) weighted 300 = 80 - 120 = -40
    // total mentions = 400 → score = -0.1
    mock.mockResolvedValueOnce({
      symbol: "A",
      ok: true,
      post_count: 100,
      bullish_score: 0.8,
    });
    mock.mockResolvedValueOnce({
      symbol: "B",
      ok: true,
      post_count: 300,
      bullish_score: -0.4,
    });
    await useSentimentStore.getState().refresh(["A", "B"]);
    const s = useSentimentStore.getState();
    expect(s.mentions).toBe(400);
    expect(s.score).toBeCloseTo(-0.1, 5);
    expect(s.label).toBe("Neutral");
  });

  it("symbols with zero mentions or missing score are skipped", async () => {
    // empty/no-post chips should not poison the average
    mock.mockResolvedValueOnce({ symbol: "A", ok: false, post_count: 0 });
    mock.mockResolvedValueOnce({
      symbol: "B",
      ok: true,
      post_count: 50,
      bullish_score: 0.7,
    });
    await useSentimentStore.getState().refresh(["A", "B"]);
    const s = useSentimentStore.getState();
    expect(s.mentions).toBe(50);
    expect(s.score).toBeCloseTo(0.7, 5);
    expect(s.label).toBe("Strongly Bullish");
  });

  it("all-fail → score collapses to 0 / Neutral, no error", async () => {
    // mention-less data → aggregate score = 0, label Neutral
    mock.mockResolvedValueOnce({ symbol: "A", ok: false, post_count: 0 });
    mock.mockResolvedValueOnce({ symbol: "B", ok: false, post_count: 0 });
    await useSentimentStore.getState().refresh(["A", "B"]);
    const s = useSentimentStore.getState();
    expect(s.score).toBe(0);
    expect(s.label).toBe("Neutral");
    expect(s.mentions).toBe(0);
    expect(s.error).toBeNull();
  });

  it("error path: fetch rejects → sets error, keeps last good", async () => {
    // First populate with a known-good aggregate
    mock.mockResolvedValueOnce({
      symbol: "AAPL",
      ok: true,
      post_count: 100,
      bullish_score: 0.5,
    });
    await useSentimentStore.getState().refresh(["AAPL"]);
    expect(useSentimentStore.getState().score).toBeCloseTo(0.5, 5);

    // Now make Promise.allSettled itself throw by stubbing the impl. The cheap
    // way is to inject a rejection that propagates as a non-allSettled path:
    // override the global to raise.
    const origAllSettled = Promise.allSettled;
    Promise.allSettled = vi.fn(() => {
      throw new Error("network exploded");
    }) as unknown as typeof Promise.allSettled;
    try {
      await useSentimentStore.getState().refresh(["BAD"]);
    } finally {
      Promise.allSettled = origAllSettled;
    }
    const s = useSentimentStore.getState();
    expect(s.error).toContain("network exploded");
    // Last good values preserved
    expect(s.score).toBeCloseTo(0.5, 5);
    expect(s.mentions).toBe(100);
    expect(s.label).toBe("Cautiously Bullish");
  });

  it("concurrent refresh aborts the previous request", async () => {
    // First refresh: never resolves on its own — we'll cancel it via the
    // second refresh. We use a deferred to keep it pending and assert the
    // controller was aborted by the second call.
    let firstResolve!: (v: XSymbolChipLike) => void;
    const firstPromise = new Promise<XSymbolChipLike>((res) => {
      firstResolve = res;
    });
    mock.mockReturnValueOnce(firstPromise);
    // Second refresh resolves immediately.
    mock.mockResolvedValueOnce({
      symbol: "Z",
      ok: true,
      post_count: 200,
      bullish_score: -0.8,
    });

    const p1 = useSentimentStore.getState().refresh(["A"]);
    // Grab the controller created by the first refresh — it's on state until
    // the second refresh replaces it.
    const firstController = useSentimentStore.getState()._inflight;
    expect(firstController).not.toBeNull();

    const p2 = useSentimentStore.getState().refresh(["Z"]);
    // After kicking off p2 the first controller should be aborted.
    expect(firstController!.signal.aborted).toBe(true);

    // Let p1's pending fetch resolve — its post-await abort guard should
    // bail BEFORE writing state.
    firstResolve({
      symbol: "A",
      ok: true,
      post_count: 1_000_000,
      bullish_score: 1,
    });

    await Promise.all([p1, p2]);
    const s = useSentimentStore.getState();
    // Final state must be p2's, not p1's.
    expect(s.mentions).toBe(200);
    expect(s.score).toBeCloseTo(-0.8, 5);
    expect(s.label).toBe("Strongly Bearish");
  });
});

type XSymbolChipLike = {
  symbol: string;
  ok: boolean;
  post_count: number;
  bullish_score?: number;
};
