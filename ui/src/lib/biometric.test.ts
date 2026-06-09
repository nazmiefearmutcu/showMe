/**
 * Biometric bridge — fail-CLOSED security contract.
 *
 * The bridge is a security primitive: "BIO never silently approves." These
 * tests pin BOTH modes via a mockable `@/lib/tauri`:
 *
 *  - Browser mode (isInTauri()=false): there is no LocalAuthentication bridge,
 *    so `requestBiometric` DENIES (allowed:false, via:"unavailable") and the
 *    gates (`requireAuth` / `gateLiveTrade`) refuse to run the action — except
 *    the documented sub-$1000 carve-out, which never calls requireAuth at all.
 *  - Tauri mode (mocked invoke): a successful invoke runs the action once and
 *    warms the 5-min reauth cache; a rejected invoke fails CLOSED (no throw)
 *    and the gate rejects.
 *
 * This file replaces the old fail-OPEN suite (which asserted "browser stub
 * allows") — that behaviour was the bug the bridge fix removes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/* ── @/lib/tauri mock (mutable isInTauri + invoke) ─────────────────────── */

const tauriState = {
  inTauri: false,
  invoke: vi.fn<(cmd: string, args?: Record<string, unknown>) => Promise<unknown>>(),
};

vi.mock("@/lib/tauri", () => ({
  isInTauri: () => tauriState.inTauri,
  invoke: (cmd: string, args?: Record<string, unknown>) =>
    tauriState.invoke(cmd, args),
}));

import {
  clearAuthCache,
  gateLiveTrade,
  requestBiometric,
  requireAuth,
} from "./biometric";

beforeEach(() => {
  clearAuthCache();
  tauriState.inTauri = false;
  tauriState.invoke.mockReset();
});
afterEach(() => {
  clearAuthCache();
});

/* ── Browser mode (no bridge) — fail CLOSED ────────────────────────────── */

describe("biometric bridge — browser mode (no LocalAuthentication bridge)", () => {
  it("requestBiometric DENIES (allowed:false, via:'unavailable')", async () => {
    const res = await requestBiometric("test");
    expect(res.allowed).toBe(false);
    expect(res.via).toBe("unavailable");
    expect(res.capabilities).toEqual({
      biometry_available: false,
      passcode_available: false,
      biometry_kind: "none",
    });
    // Never calls into the (absent) Tauri bridge.
    expect(tauriState.invoke).not.toHaveBeenCalled();
  });

  it("requireAuth REJECTS and never runs the action", async () => {
    let calls = 0;
    await expect(
      requireAuth("test", () => {
        calls += 1;
        return "ok";
      }),
    ).rejects.toThrow(/auth denied \(unavailable\)/);
    expect(calls).toBe(0);
  });

  it("gateLiveTrade ABOVE the threshold REJECTS (action not called)", async () => {
    let opened = false;
    await expect(
      gateLiveTrade({ notional: 5000 }, () => {
        opened = true;
        return 1;
      }),
    ).rejects.toThrow(/auth denied/);
    expect(opened).toBe(false);
  });

  it("gateLiveTrade with no notional REJECTS", async () => {
    let opened = false;
    await expect(
      gateLiveTrade({}, () => {
        opened = true;
      }),
    ).rejects.toThrow(/auth denied/);
    expect(opened).toBe(false);
  });

  it("gateLiveTrade BELOW the dollar threshold STILL runs the action (carve-out)", async () => {
    // Documented sub-$1000 carve-out: never calls requireAuth, so it runs even
    // in browser mode. This is intentional and preserved.
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
    expect(tauriState.invoke).not.toHaveBeenCalled();
  });
});

/* ── Tauri mode (mocked invoke) ────────────────────────────────────────── */

describe("biometric bridge — Tauri mode (LocalAuthentication present)", () => {
  beforeEach(() => {
    tauriState.inTauri = true;
  });

  it("a successful invoke runs the action once AND warms the 5-min cache", async () => {
    tauriState.invoke.mockResolvedValue({
      allowed: true,
      reason: "test",
      via: "touch_id",
      capabilities: {
        biometry_available: true,
        passcode_available: true,
        biometry_kind: "touch_id",
      },
    });

    let calls = 0;
    const action = () => {
      calls += 1;
      return "ok";
    };

    const first = await requireAuth("test", action);
    expect(first).toBe("ok");
    expect(calls).toBe(1);
    expect(tauriState.invoke).toHaveBeenCalledTimes(1);

    // Second call within the warm window runs WITHOUT a second invoke.
    const second = await requireAuth("test", action);
    expect(second).toBe("ok");
    expect(calls).toBe(2);
    expect(tauriState.invoke).toHaveBeenCalledTimes(1);
  });

  it("clearAuthCache forces a re-prompt (a second invoke)", async () => {
    tauriState.invoke.mockResolvedValue({
      allowed: true,
      reason: "test",
      via: "touch_id",
      capabilities: {
        biometry_available: true,
        passcode_available: true,
        biometry_kind: "touch_id",
      },
    });

    await requireAuth("test", () => undefined);
    expect(tauriState.invoke).toHaveBeenCalledTimes(1);
    clearAuthCache();
    await requireAuth("test", () => undefined);
    expect(tauriState.invoke).toHaveBeenCalledTimes(2);
  });

  it("an invoke that REJECTS fails CLOSED (no throw, via:'unavailable')", async () => {
    tauriState.invoke.mockRejectedValue(new Error("OS call blew up"));
    const res = await requestBiometric("test");
    expect(res.allowed).toBe(false);
    expect(res.via).toBe("unavailable");
  });

  it("requireAuth REJECTS when the invoke errors (gate denies, action not run)", async () => {
    tauriState.invoke.mockRejectedValue(new Error("OS call blew up"));
    let calls = 0;
    await expect(
      requireAuth("test", () => {
        calls += 1;
      }),
    ).rejects.toThrow(/auth denied \(unavailable\)/);
    expect(calls).toBe(0);
  });

  it("a user-denied invoke rejects the gate (allowed:false honoured)", async () => {
    tauriState.invoke.mockResolvedValue({
      allowed: false,
      reason: "test",
      via: "denied",
      capabilities: {
        biometry_available: true,
        passcode_available: true,
        biometry_kind: "touch_id",
      },
    });
    let calls = 0;
    await expect(
      requireAuth("test", () => {
        calls += 1;
      }),
    ).rejects.toThrow(/auth denied \(denied\)/);
    expect(calls).toBe(0);
  });
});
