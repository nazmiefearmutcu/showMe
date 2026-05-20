/**
 * Pins `mergeLivePayload`: when the sidecar returns recognisable shape,
 * the template's mock data is replaced by live values; otherwise the
 * mock survives. S13 added this overlay so 8 of 10 S13 codes
 * (template-backed) finally show real backend data instead of fake mock.
 */
import { describe, expect, it } from "vitest";
import { mergeLivePayload } from "./TemplateRenderer";
import { getMockTemplate } from "./mock-data";

describe("mergeLivePayload", () => {
  it("returns the mock untouched when the payload is not an object", () => {
    const tpl = getMockTemplate("STRS")!;
    expect(mergeLivePayload(tpl, "STRS", null)).toEqual(tpl);
    expect(mergeLivePayload(tpl, "STRS", undefined)).toEqual(tpl);
    expect(mergeLivePayload(tpl, "STRS", "string")).toEqual(tpl);
  });

  it("overlays a generic `items` array onto the template's feed", () => {
    const tpl = getMockTemplate("TLDR")!;
    const merged = mergeLivePayload(tpl, "TLDR", {
      items: [
        {
          title: "live headline #1",
          source: "rss",
          summary: "summary 1",
          published_at: "2026-05-17T13:00:00Z",
          sentiment: "positive",
          impact: 4,
        },
        {
          title: "live headline #2",
          source: "gdelt",
          summary: "summary 2",
          published_at: "2026-05-17T13:05:00Z",
          sentiment: "negative",
        },
      ],
    });
    expect(merged.feed).toBeTruthy();
    expect(merged.feed?.length).toBe(2);
    expect(merged.feed?.[0].title).toBe("live headline #1");
    expect(merged.feed?.[0].source).toBe("rss");
    expect(merged.feed?.[0].tone).toBe("pos");
    expect(merged.feed?.[1].tone).toBe("neg");
  });

  it("overlays a generic `rows` array onto the template's tableRows", () => {
    const tpl = getMockTemplate("TLH")!;
    const merged = mergeLivePayload(tpl, "TLH", {
      rows: [
        { Symbol: "AAPL", "Loss lot": "L-1", Loss: "-$100", "Est. tax saved": "$25", Swap: "MSFT" },
        { Symbol: "TSLA", "Loss lot": "L-2", Loss: "-$200", "Est. tax saved": "$50", Swap: "RIVN" },
      ],
    });
    expect(merged.tableRows?.length).toBe(2);
    expect(merged.tableRows?.[0].Symbol).toBe("AAPL");
    expect(merged.tableRows?.[1].Symbol).toBe("TSLA");
  });

  it("TRDH adapter shows close-countdown for open exchanges, open-countdown for closed", () => {
    const tpl = getMockTemplate("TRDH")!;
    const merged = mergeLivePayload(tpl, "TRDH", {
      rows: [
        {
          exchange: "NYSE",
          is_open_now: true,
          next_open_utc: "2026-05-18T13:30:00Z",
          next_close_utc: "2026-05-17T20:00:00Z",
          hours_until_open: 22.5,
          hours_until_close: 4.5,
        },
        {
          exchange: "LSE",
          is_open_now: false,
          next_open_utc: "2026-05-18T08:00:00Z",
          next_close_utc: "2026-05-18T16:30:00Z",
          hours_until_open: 18.0,
          hours_until_close: 26.5,
        },
      ],
    });
    expect(merged.tableCols).toEqual([
      "Exchange",
      "Status",
      "Next event (UTC)",
      "Countdown",
    ]);
    expect(merged.tableRows?.length).toBe(2);
    const [nyse, lse] = merged.tableRows!;
    expect(nyse.Exchange).toBe("NYSE");
    expect(nyse.Status).toBe("OPEN");
    // NYSE is open → countdown is to close (4.5h)
    expect(nyse["Next event (UTC)"]).toBe("20:00");
    expect(nyse.Countdown).toBe("4.5h");
    expect(lse.Status).toBe("CLOSED");
    // LSE is closed → countdown is to open (18.0h)
    expect(lse["Next event (UTC)"]).toBe("08:00");
    expect(lse.Countdown).toBe("18.0h");
    expect(merged.sub).toMatch(/1 open now/);
  });

  it("overlays `cards` onto kpis when no per-code adapter handled them", () => {
    const tpl = getMockTemplate("TRA")!;
    const merged = mergeLivePayload(tpl, "TRA", {
      cards: [
        { label: "TWR YTD", value: 0.184, tone: "pos" },
        { label: "IRR YTD", value: "+19.2%", tone: "pos" },
      ],
    });
    expect(merged.kpis?.length).toBe(2);
    expect(merged.kpis?.[0].label).toBe("TWR YTD");
    expect(merged.kpis?.[0].tone).toBe("pos");
  });

  it("falls back to the mock when the payload has no recognisable shape", () => {
    const tpl = getMockTemplate("STRS")!;
    const merged = mergeLivePayload(tpl, "STRS", { unrelated: { nested: 1 } });
    expect(merged.tableRows).toEqual(tpl.tableRows);
    expect(merged.feed).toEqual(tpl.feed);
    expect(merged.kpis).toEqual(tpl.kpis);
  });
});
