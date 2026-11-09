/**
 * ASOF-2 follow-up: the desk freshness stamp must be the observation time, never the compute time.
 *
 * The backend envelope carries `asOf` (the observation date, null when the payload declares none)
 * and `fetched_at` (when the server answered). Stamping `fetched_at` as the pane's `asOf` made a
 * monthly series read as current. These tests drive the real `runFunction` stamping path.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/sidecar", () => ({
  waitForSidecarReady: async () => "http://127.0.0.1:9",
  loadSidecarAuthToken: async () => null,
}));

import { runFunction } from "./functions";
import { observationAsOf, paneHealthTier, usePaneContractStore } from "./pane-contract-store";

const NOW_ISO = new Date().toISOString();

function envelope(extra: Record<string, unknown>): Record<string, unknown> {
  return {
    code: "ECST",
    instrument: null,
    data: { rows: [] },
    metadata: {},
    sources: ["fred_csv"],
    warnings: [],
    elapsed_ms: 3,
    fetched_at: NOW_ISO,
    ...extra,
  };
}

function stubFetchWith(body: Record<string, unknown>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
}

beforeEach(() => {
  usePaneContractStore.setState({ byKey: {} });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("pane freshness stamp is the observation time (ASOF-2 follow-up)", () => {
  it("stamps a monthly series with its envelope observation date, not the server answer time", async () => {
    stubFetchWith(envelope({ asOf: "2026-09-01", retrievedAt: NOW_ISO }));
    await runFunction("ECST", { symbol: "CPIAUCSL" });
    const snap = usePaneContractStore.getState().byKey["ECST::CPIAUCSL"];
    // Red before the fix: asOf was fetched_at (now), so the monthly print read as current.
    expect(snap?.asOf).toBe("2026-09-01");
    // A date-only print has no known cadence: it reads degraded, never live, and is not
    // judged against the 5-minute intraday window (which would mark it stale forever).
    expect(paneHealthTier(snap!, Date.now())).toBe("degraded");
  });

  it("does not stamp fetched_at as the observation time when the envelope declares none", async () => {
    stubFetchWith(envelope({ asOf: null }));
    await runFunction("ECST", { symbol: "CPIAUCSL" });
    const snap = usePaneContractStore.getState().byKey["ECST::CPIAUCSL"];
    expect(snap?.asOf).toBeUndefined();
  });

  it("prefers the payload's own as_of over the envelope asOf", async () => {
    stubFetchWith(envelope({ asOf: "2026-09-01", data: { rows: [], as_of: "2026-09-14" } }));
    await runFunction("ECST", { symbol: "CPIAUCSL" });
    const snap = usePaneContractStore.getState().byKey["ECST::CPIAUCSL"];
    expect(snap?.asOf).toBe("2026-09-14");
  });
});

describe("observationAsOf", () => {
  it("returns the first declared observation date in precedence order", () => {
    expect(observationAsOf({ asOf: "2026-09-01" }, { as_of: "2026-09-14" })).toBe("2026-09-14");
    expect(observationAsOf({ as_of: "2026-09-02", asOf: "2026-09-01" }, {})).toBe("2026-09-02");
    expect(observationAsOf({ asOf: "2026-09-01" }, {})).toBe("2026-09-01");
  });

  it("never falls back to the compute or serve time", () => {
    expect(observationAsOf({ fetched_at: NOW_ISO }, {})).toBeUndefined();
    expect(observationAsOf({ asOf: null, fetched_at: NOW_ISO }, { as_of: "" })).toBeUndefined();
  });
});
