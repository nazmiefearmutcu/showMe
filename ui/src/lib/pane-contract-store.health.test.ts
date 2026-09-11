/**
 * Lane L4 — desk-health rollup (campaign 2026-09-11).
 *
 * Pins the frozen health semantics:
 *   - tier classification (live / degraded / stale) and its precedence
 *     (age > warnings > declared mode);
 *   - the staleness threshold constant and its boundary;
 *   - the pure desk aggregation (counts, worst latency, freshest update);
 *   - the `useDeskHealth` React binding over the real store.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  PANE_STALE_AFTER_MS,
  computeDeskHealth,
  formatLatencyMs,
  leafContractKeys,
  paneAgeMs,
  paneHealthTier,
  paneStampedAt,
  recordPaneContract,
  useDeskHealth,
  usePaneContractStore,
  type PaneContractSnapshot,
} from "./pane-contract-store";
import { leaf, split, useWorkspace } from "./workspace";

const NOW = Date.parse("2026-09-11T12:00:00Z");

function snap(partial: Partial<PaneContractSnapshot> = {}): PaneContractSnapshot {
  return {
    dataMode: "live_exchange",
    asOf: new Date(NOW - 2_000).toISOString(),
    receivedAt: NOW - 2_000,
    ...partial,
  };
}

beforeEach(() => {
  usePaneContractStore.setState({ byKey: {} });
});

describe("paneHealthTier", () => {
  it("classifies live modes (official + exchange) as live when fresh + clean", () => {
    expect(paneHealthTier(snap({ dataMode: "live_exchange" }), NOW)).toBe("live");
    expect(paneHealthTier(snap({ dataMode: "live_official" }), NOW)).toBe("live");
  });

  it("classifies non-live declared modes as degraded", () => {
    for (const mode of [
      "delayed_reference",
      "modeled",
      "cached_snapshot",
      "provider_unavailable",
      "not_configured",
    ]) {
      expect(paneHealthTier(snap({ dataMode: mode }), NOW), mode).toBe("degraded");
    }
  });

  it("never claims live for a contract with no declared mode", () => {
    expect(paneHealthTier(snap({ dataMode: undefined }), NOW)).toBe("degraded");
  });

  it("warnings degrade an otherwise-live contract", () => {
    expect(
      paneHealthTier(snap({ warnings: ["live source down — modeled fallback"] }), NOW),
    ).toBe("degraded");
  });

  it("stale age outranks warnings and a live declared mode", () => {
    const old = new Date(NOW - PANE_STALE_AFTER_MS - 1).toISOString();
    expect(
      paneHealthTier(
        snap({ asOf: old, warnings: ["still warning"], dataMode: "live_exchange" }),
        NOW,
      ),
    ).toBe("stale");
  });

  it("staleness threshold is an exact boundary (> threshold, not >=)", () => {
    const at = new Date(NOW - PANE_STALE_AFTER_MS).toISOString();
    const past = new Date(NOW - PANE_STALE_AFTER_MS - 1).toISOString();
    expect(paneHealthTier(snap({ asOf: at }), NOW)).toBe("live");
    expect(paneHealthTier(snap({ asOf: past }), NOW)).toBe("stale");
    expect(PANE_STALE_AFTER_MS).toBeGreaterThan(60_000);
  });

  it("falls back to receivedAt when asOf is missing or unparseable", () => {
    const fresh = snap({ asOf: undefined, receivedAt: NOW - 1_000 });
    expect(paneHealthTier(fresh, NOW)).toBe("live");
    const old = snap({ asOf: "not-a-date", receivedAt: NOW - PANE_STALE_AFTER_MS - 1 });
    expect(paneHealthTier(old, NOW)).toBe("stale");
  });

  it("clock skew on a future asOf clamps the age to zero (never flashes stale)", () => {
    const future = snap({ asOf: new Date(NOW + 60_000).toISOString() });
    expect(paneAgeMs(future, NOW)).toBe(0);
    expect(paneHealthTier(future, NOW)).toBe("live");
  });
});

describe("paneStampedAt / paneAgeMs", () => {
  it("prefers the payload asOf over receivedAt", () => {
    const s = snap({ asOf: new Date(NOW - 5_000).toISOString(), receivedAt: NOW - 1_000 });
    expect(paneStampedAt(s)).toBe(NOW - 5_000);
    expect(paneAgeMs(s, NOW)).toBe(5_000);
  });

  it("uses receivedAt when no usable asOf exists", () => {
    const s = snap({ asOf: undefined, receivedAt: NOW - 7_000 });
    expect(paneStampedAt(s)).toBe(NOW - 7_000);
    expect(paneAgeMs(s, NOW)).toBe(7_000);
  });
});

describe("computeDeskHealth", () => {
  it("counts each tier exactly once across mixed contracts", () => {
    const byKey: Record<string, PaneContractSnapshot> = {
      "GP::AAPL": snap(),
      "HP::MSFT": snap({ dataMode: "delayed_reference" }),
      "FA::TSLA": snap({ asOf: new Date(NOW - PANE_STALE_AFTER_MS - 1).toISOString() }),
    };
    const health = computeDeskHealth(byKey, NOW);
    expect(health.live).toBe(1);
    expect(health.degraded).toBe(1);
    expect(health.stale).toBe(1);
  });

  it("worst latency is the max declared, null when none declared", () => {
    const withLatency = computeDeskHealth(
      {
        a: snap({ latencyMs: 42 }),
        b: snap({ latencyMs: 84 }),
        c: snap({ latencyMs: 12 }),
      },
      NOW,
    );
    expect(withLatency.worstLatencyMs).toBe(84);
    expect(computeDeskHealth({ a: snap(), b: snap() }, NOW).worstLatencyMs).toBeNull();
  });

  it("lastUpdatedAt is the freshest receivedAt, null on an empty map", () => {
    const health = computeDeskHealth(
      {
        a: snap({ receivedAt: NOW - 60_000 }),
        b: snap({ receivedAt: NOW - 1_000 }),
        c: snap({ receivedAt: NOW - 10_000 }),
      },
      NOW,
    );
    expect(health.lastUpdatedAt).toBe(NOW - 1_000);
    expect(computeDeskHealth({}, NOW)).toEqual({
      live: 0,
      degraded: 0,
      stale: 0,
      worstLatencyMs: null,
      lastUpdatedAt: null,
    });
  });
});

describe("useDeskHealth", () => {
  it("starts empty and rolls up recorded contracts reactively", () => {
    const { result } = renderHook(() => useDeskHealth());
    expect(result.current.live).toBe(0);
    expect(result.current.lastUpdatedAt).toBeNull();

    act(() => {
      // R1-F3: the rollup is scoped to the panes currently in the workspace.
      useWorkspace.setState({
        tree: split("h", [leaf("GP", "AAPL"), leaf("HP", "MSFT")]),
      });
      const now = Date.now();
      recordPaneContract("GP", "AAPL", {
        dataMode: "live_exchange",
        asOf: new Date(now - 1_000).toISOString(),
        latencyMs: 42,
        receivedAt: now - 1_000,
      });
      recordPaneContract("HP", "MSFT", {
        dataMode: "modeled",
        warnings: ["fallback in use"],
        receivedAt: now - 2_000,
      });
    });

    expect(result.current.live).toBe(1);
    expect(result.current.degraded).toBe(1);
    expect(result.current.stale).toBe(0);
    expect(result.current.worstLatencyMs).toBe(42);
    expect(result.current.lastUpdatedAt).not.toBeNull();
  });

  it("excludes contracts whose pane is no longer in the workspace (ghosts)", () => {
    const { result } = renderHook(() => useDeskHealth());
    act(() => {
      useWorkspace.setState({ tree: leaf("GP", "AAPL") });
      const now = Date.now();
      recordPaneContract("GP", "AAPL", {
        dataMode: "live_exchange",
        asOf: new Date(now).toISOString(),
        receivedAt: now,
      });
      // Retargeted/closed pane — its cached contract must not inflate the desk.
      recordPaneContract("SCAN", undefined, {
        dataMode: "modeled",
        warnings: ["stale scan"],
        receivedAt: now - 60_000,
      });
      recordPaneContract("WCRS", "EURUSD", {
        dataMode: "live_exchange",
        receivedAt: now,
      });
    });
    expect(result.current.live).toBe(1);
    expect(result.current.degraded).toBe(0);
    expect(result.current.stale).toBe(0);
    // The key helper drives the scoping — sanity-check it directly.
    expect(leafContractKeys(useWorkspace.getState().tree)).toEqual(["GP::AAPL"]);
  });
});

describe("formatLatencyMs", () => {
  it("renders sub-second latency in ms and seconds above", () => {
    expect(formatLatencyMs(84)).toBe("84ms");
    expect(formatLatencyMs(999.6)).toBe("1000ms");
    expect(formatLatencyMs(1_200)).toBe("1.2s");
    expect(formatLatencyMs(-5)).toBe("0ms");
  });
});
