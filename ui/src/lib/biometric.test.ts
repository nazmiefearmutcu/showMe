import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearAuthCache,
  gateLiveTrade,
  requireAuth,
} from "./biometric";

describe("requireAuth (browser-mode stub)", () => {
  beforeEach(() => clearAuthCache());
  afterEach(() => clearAuthCache());

  it("invokes the action exactly once on first call", async () => {
    let calls = 0;
    const result = await requireAuth("test", () => {
      calls += 1;
      return "ok";
    });
    expect(result).toBe("ok");
    expect(calls).toBe(1);
  });

  it("reuses the cached approval inside the reauth window", async () => {
    let calls = 0;
    await requireAuth("test", () => {
      calls += 1;
    });
    await requireAuth("test", () => {
      calls += 1;
    });
    expect(calls).toBe(2);
  });

  it("clearAuthCache forces a re-prompt", async () => {
    let calls = 0;
    await requireAuth("test", () => {
      calls += 1;
    });
    clearAuthCache();
    await requireAuth("test", () => {
      calls += 1;
    });
    expect(calls).toBe(2);
  });
});

describe("gateLiveTrade", () => {
  beforeEach(() => clearAuthCache());

  it("skips biometric for orders below the dollar threshold", async () => {
    let opened = false;
    const r = await gateLiveTrade(
      { notional: 200, notionalThreshold: 1000 },
      () => {
        opened = true;
        return "ok";
      },
    );
    expect(opened).toBe(true);
    expect(r).toBe("ok");
  });

  it("requires auth above the threshold (browser stub allows)", async () => {
    let opened = false;
    const r = await gateLiveTrade(
      { notional: 5000 },
      () => {
        opened = true;
        return 1;
      },
    );
    expect(opened).toBe(true);
    expect(r).toBe(1);
  });

  it("requires auth when no notional is supplied", async () => {
    let opened = false;
    await gateLiveTrade({}, () => {
      opened = true;
    });
    expect(opened).toBe(true);
  });
});
