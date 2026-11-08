import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  MARKET_GAUGE_PATH,
  isGaugeStale,
  parseMarketGauge,
  useSentimentStore,
} from "./sentiment-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

const OK_BODY = {
  ok: true,
  score: 22.4,
  rating: "Extreme Fear",
  as_of: "2026-11-06T23:59:00Z",
  previous_close: 20.2,
  source: "CNN Fear & Greed via Awareness",
};

beforeEach(() => {
  useSentimentStore.setState({
    gauge: null,
    unavailableReason: null,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
  });
  mock.mockReset();
});

describe("parseMarketGauge", () => {
  it("accepts a well-formed ok answer", () => {
    const parsed = parseMarketGauge(OK_BODY);
    expect("gauge" in parsed && parsed.gauge.score).toBe(22.4);
    expect("gauge" in parsed && parsed.gauge.previous_close).toBe(20.2);
  });

  it("returns the backend reason verbatim for ok:false", () => {
    expect(parseMarketGauge({ ok: false, reason: "awareness down: ECONNREFUSED" })).toEqual(
      {
        reason: "awareness down: ECONNREFUSED",
      },
    );
  });

  it("never yields a score for ok:false without a reason", () => {
    expect(parseMarketGauge({ ok: false })).toEqual({ reason: "Market gauge unavailable" });
    expect(parseMarketGauge(null)).toEqual({ reason: "Market gauge unavailable" });
  });

  it("rejects an ok answer whose score is out of range or missing", () => {
    expect("reason" in parseMarketGauge({ ...OK_BODY, score: 140 })).toBe(true);
    expect("reason" in parseMarketGauge({ ...OK_BODY, score: null })).toBe(true);
    expect("reason" in parseMarketGauge({ ...OK_BODY, score: Number.NaN })).toBe(true);
  });

  it("rejects an ok answer without a parseable timestamp", () => {
    expect("reason" in parseMarketGauge({ ...OK_BODY, as_of: "yesterday-ish" })).toBe(true);
  });
});

describe("isGaugeStale", () => {
  it("flags readings older than 36 h", () => {
    const now = Date.parse("2026-11-08T12:00:00Z");
    expect(isGaugeStale("2026-11-06T11:59:00Z", now)).toBe(true);
    expect(isGaugeStale("2026-11-07T13:00:00Z", now)).toBe(false);
  });
});

describe("sentiment-store.refresh", () => {
  it("fetches the market-gauge route and stores the reading", async () => {
    mock.mockResolvedValueOnce(OK_BODY);
    await useSentimentStore.getState().refresh();
    expect(mock.mock.calls[0][0]).toBe(MARKET_GAUGE_PATH);
    const s = useSentimentStore.getState();
    expect(s.gauge?.score).toBe(22.4);
    expect(s.gauge?.rating).toBe("Extreme Fear");
    expect(s.unavailableReason).toBeNull();
    expect(s.error).toBeNull();
    expect(s.loading).toBe(false);
    expect(s.lastUpdated).toBeInstanceOf(Date);
  });

  it("ok:false clears any number and surfaces the reason", async () => {
    mock.mockResolvedValueOnce(OK_BODY);
    await useSentimentStore.getState().refresh();
    mock.mockResolvedValueOnce({ ok: false, reason: "awareness down" });
    await useSentimentStore.getState().refresh();
    const s = useSentimentStore.getState();
    expect(s.gauge).toBeNull();
    expect(s.unavailableReason).toBe("awareness down");
  });

  it("transport failure keeps the last good reading and sets error", async () => {
    mock.mockResolvedValueOnce(OK_BODY);
    await useSentimentStore.getState().refresh();
    mock.mockRejectedValueOnce(new Error("sidecar offline"));
    await useSentimentStore.getState().refresh();
    const s = useSentimentStore.getState();
    expect(s.error).toBe("sidecar offline");
    expect(s.gauge?.score).toBe(22.4);
    expect(s.loading).toBe(false);
  });

  it("a newer refresh aborts the older one and its answer is dropped", async () => {
    let firstResolve!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => (firstResolve = res)));
    mock.mockResolvedValueOnce({ ...OK_BODY, score: 80 });

    const p1 = useSentimentStore.getState().refresh();
    const firstController = useSentimentStore.getState()._inflight;
    expect(firstController).not.toBeNull();

    const p2 = useSentimentStore.getState().refresh();
    expect(firstController!.signal.aborted).toBe(true);

    firstResolve({ ...OK_BODY, score: 5 });
    await Promise.all([p1, p2]);
    expect(useSentimentStore.getState().gauge?.score).toBe(80);
  });
});
