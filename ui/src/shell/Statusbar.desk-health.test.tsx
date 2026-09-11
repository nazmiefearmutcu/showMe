/**
 * Lane L4 — Statusbar desk-health segment (campaign 2026-09-11).
 *
 * The statusbar previously carried sidecar/runtime/tape/fn/clock but no
 * desk-level data-health rollup. This pins the new segment:
 *   - hidden entirely with zero recorded pane contracts (no data, no claim);
 *   - LIVE/DEGRADED/STALE counts + worst latency + last-update age;
 *   - segment tiers drive the StatusSection tone (stale → negative).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Statusbar } from "./Statusbar";
import {
  PANE_STALE_AFTER_MS,
  recordPaneContract,
  usePaneContractStore,
} from "@/lib/pane-contract-store";
import { leaf, split, useWorkspace } from "@/lib/workspace";
import { __resetTapeHealthForTests } from "@/lib/tape-health";

beforeEach(() => {
  usePaneContractStore.setState({ byKey: {} });
  // R1-F3: the rollup is scoped to the panes currently in the workspace.
  useWorkspace.setState({ tree: leaf("HOME") });
  __resetTapeHealthForTests();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Statusbar — desk data health", () => {
  it("renders nothing when no pane has recorded a contract", () => {
    render(<Statusbar />);
    expect(screen.queryByTestId("desk-health")).toBeNull();
  });

  it("rolls up live/degraded/stale counts, worst latency, and update age", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    useWorkspace.setState({
      tree: split("h", [leaf("GP", "AAPL"), leaf("HP", "MSFT"), leaf("FA", "TSLA")]),
    });
    const now = Date.now();
    recordPaneContract("GP", "AAPL", {
      dataMode: "live_exchange",
      asOf: new Date(now - 2_000).toISOString(),
      receivedAt: now - 2_000,
      latencyMs: 42,
    });
    recordPaneContract("HP", "MSFT", {
      dataMode: "delayed_reference",
      asOf: new Date(now - 3_000).toISOString(),
      receivedAt: now - 3_000,
      latencyMs: 84,
    });
    recordPaneContract("FA", "TSLA", {
      dataMode: "live_exchange",
      asOf: new Date(now - PANE_STALE_AFTER_MS - 60_000).toISOString(),
      receivedAt: now - 10_000,
    });

    render(<Statusbar />);
    const segment = screen.getByTestId("desk-health");
    expect(segment.getAttribute("data-desk-health")).toBe("1/1/1");
    expect(segment.textContent).toContain("LIVE 1");
    expect(segment.textContent).toContain("DEGRADED 1");
    expect(segment.textContent).toContain("STALE 1");
    expect(segment.textContent).toContain("84ms");
    expect(segment.textContent).toContain("2s");
  });

  it("shows only the live count + age on a clean desk", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    useWorkspace.setState({ tree: leaf("GP", "AAPL") });
    const now = Date.now();
    recordPaneContract("GP", "AAPL", {
      dataMode: "live_exchange",
      asOf: new Date(now - 3_000).toISOString(),
      receivedAt: now - 3_000,
    });
    render(<Statusbar />);
    const segment = screen.getByTestId("desk-health");
    expect(segment.getAttribute("data-desk-health")).toBe("1/0/0");
    expect(segment.textContent).toContain("LIVE 1");
    expect(segment.textContent).not.toContain("DEGRADED");
    expect(segment.textContent).not.toContain("STALE");
    expect(segment.textContent).toContain("3s");
  });
});
