/**
 * Lane D (frozen contract §D) — KAOS defaults in the bot store.
 *
 * Pins:
 *   - openNew() drafts the KAOS Multibot defaults: engine "kaos", name
 *     "KAOS Multibot", both venues preseeded, mode shadow, 60s tick;
 *   - the POST body carries the venue literals the backend validates;
 *   - migration safety: legacy payloads WITHOUT the additive fields keep
 *     loading and rendering untouched (bot-store has NO local persistence —
 *     the persisted shape lives server-side, where old records default to
 *     engine "spec"; the UI contract is simply "absent field = hide").
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useBotStore } from "./bot-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useBotStore.setState({
    bots: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, saving: false, toggling: false, error: null,
    _openController: null,
  });
  mock.mockReset();
});

describe("KAOS blank-draft defaults (_BLANK_BOT)", () => {
  it("openNew drafts the KAOS Multibot with both venues, shadow, 60s tick", () => {
    useBotStore.getState().openNew();
    const draft = useBotStore.getState().draft;
    expect(draft).not.toBeNull();
    expect(draft?.name).toBe("KAOS Multibot");
    expect(draft?.engine).toBe("kaos");
    expect(draft?.mode).toBe("shadow");
    expect(draft?.tick_interval_seconds).toBe(60);
    expect(draft?.venues).toHaveLength(2);
    const [crypto, nasdaq] = draft?.venues ?? [];
    expect(crypto).toMatchObject({
      id: "crypto", exchange_id: "binanceusdm",
      market: "crypto-futures", risk_profile: "crypto",
    });
    expect(crypto?.symbols).toHaveLength(20);
    expect(nasdaq).toMatchObject({
      id: "nasdaq", exchange_id: "alpaca",
      market: "us-equities", risk_profile: "equity",
    });
    expect(nasdaq?.symbols).toHaveLength(20);
  });

  it("POSTs the backend-valid venue literals when saving a KAOS draft", async () => {
    mock.mockResolvedValueOnce({
      id: "new", strategy_id: "kaos-multibot", credential_id: "c",
      exchange_id: "binanceusdm", symbol: "BTC/USDT", timeframe: "15m",
      tick_interval_seconds: 60, mode: "shadow", enabled: false,
      created_at: "", updated_at: "", engine: "kaos",
    });
    useBotStore.getState().openNew();
    useBotStore.getState().setDraftField("strategy_id", "kaos-multibot");
    useBotStore.getState().setDraftField("credential_id", "c");
    useBotStore.getState().setDraftField("exchange_id", "binanceusdm");
    useBotStore.getState().setDraftField("symbol", "BTC/USDT");
    await useBotStore.getState().save();
    // save() chains loadList() after the POST, so assert on the FIRST call
    // (the POST itself) rather than the total call count.
    const [url, init] = mock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/bots");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.engine).toBe("kaos");
    expect(body.name).toBe("KAOS Multibot");
    expect(body.venues).toHaveLength(2);
    expect(body.venues[0].market).toBe("crypto-futures");
    expect(body.venues[0].risk_profile).toBe("crypto");
    expect(body.venues[1].market).toBe("us-equities");
    expect(body.venues[1].risk_profile).toBe("equity");
  });
});

describe("legacy payload migration safety (additive fields only)", () => {
  it("loads a legacy list meta without engine/venues and does not flag it KAOS", async () => {
    mock.mockResolvedValueOnce({
      records: [{
        id: "old", strategy_id: "rsi-mean-revert", credential_id: "c",
        exchange_id: "binance", symbol: "BTC/USDT", timeframe: "1h",
        mode: "shadow", enabled: false, created_at: "", updated_at: "",
      }],
    });
    await useBotStore.getState().loadList();
    const bots = useBotStore.getState().bots;
    expect(bots).toHaveLength(1);
    expect(bots[0].engine).toBeUndefined();
    expect(bots[0].venues).toBeUndefined();
    expect(bots[0].venue_rows).toBeUndefined();
  });

  it("opens a legacy KAOS-seeded record carrying venues + venue_rows", async () => {
    mock.mockResolvedValueOnce({
      id: "seed", strategy_id: "kaos-multibot", credential_id: "kaos-local",
      exchange_id: "binanceusdm", symbol: "BTC/USDT", timeframe: "15m",
      tick_interval_seconds: 60, mode: "shadow", enabled: false,
      created_at: "", updated_at: "", engine: "kaos",
      venues: [
        { id: "crypto", exchange_id: "binanceusdm", market: "crypto-futures",
          symbols: ["BTC/USDT:USDT"], risk_profile: "crypto" },
        { id: "nasdaq", exchange_id: "alpaca", market: "us-equities",
          symbols: ["SPY"], risk_profile: "equity" },
      ],
      venue_rows: [
        { venue_id: "crypto", market: "crypto-futures", lane_status: "idle" },
        { venue_id: "nasdaq", market: "us-equities", lane_status: "PAPER (no Alpaca keys)" },
      ],
    });
    await useBotStore.getState().openExisting("seed");
    const draft = useBotStore.getState().draft;
    expect(draft?.engine).toBe("kaos");
    expect(draft?.venues).toHaveLength(2);
    expect(draft?.venue_rows).toHaveLength(2);
    expect(draft?.venue_rows?.[1]?.lane_status).toBe("PAPER (no Alpaca keys)");
  });
});
