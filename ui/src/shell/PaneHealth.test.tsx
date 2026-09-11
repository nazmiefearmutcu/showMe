/**
 * Lane L4 — PaneHealth chip (campaign 2026-09-11).
 *
 * Pins the honest display contract:
 *   - no contract data → renders nothing at all;
 *   - contract prop or leafId store lookup both resolve the same chip;
 *   - tier dot derives from the frozen health selectors;
 *   - age is formatted and keeps ticking; latency shows when declared;
 *   - popover carries the exact as-of time, source list, and warnings.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PaneHealth } from "./PaneHealth";
import { PANE_STALE_AFTER_MS, recordPaneContract, usePaneContractStore } from "@/lib/pane-contract-store";
import { useWorkspace } from "@/lib/workspace";

// Deterministic clock rendering — the popover's exact stamp must not depend
// on the machine timezone.
vi.mock("@/lib/timezone", () => ({
  useTimezone: () => "UTC",
  formatDate: () => "11 Sep 2026",
  formatTime: () => "12:34:56",
}));

beforeEach(() => {
  usePaneContractStore.setState({ byKey: {} });
  useWorkspace.setState({
    tree: { kind: "leaf", id: "L1", code: "GP", symbol: "AAPL" },
    focusedId: "L1",
  } as never);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function chip(): HTMLElement {
  const host = screen.getByTestId("pane-health");
  const button = host.querySelector("button");
  if (!button) throw new Error("pane-health chip button missing");
  return button;
}

describe("PaneHealth", () => {
  it("renders NOTHING when no contract exists for the leaf and none is passed", () => {
    const { container } = render(<PaneHealth leafId="L1" />);
    expect(container.querySelector('[data-testid="pane-health"]')).toBeNull();
  });

  it("renders NOTHING for an unknown leafId", () => {
    const { container } = render(<PaneHealth leafId="does-not-exist" />);
    expect(container.querySelector('[data-testid="pane-health"]')).toBeNull();
  });

  it("renders live tier + age + latency from an explicit contract prop", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    const now = Date.now();
    render(
      <PaneHealth
        contract={{
          dataMode: "live_exchange",
          asOf: new Date(now - 2_000).toISOString(),
          receivedAt: now - 2_000,
          latencyMs: 84,
        }}
      />,
    );
    const el = chip();
    expect(el.getAttribute("data-tier")).toBe("live");
    expect(el.textContent).toContain("2s");
    expect(el.textContent).toContain("84ms");
  });

  it("resolves (code, symbol) from the workspace when mounted by leafId", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    const now = Date.now();
    recordPaneContract("GP", "AAPL", {
      dataMode: "live_exchange",
      asOf: new Date(now - 1_000).toISOString(),
      receivedAt: now - 1_000,
      latencyMs: 12,
    });
    render(<PaneHealth leafId="L1" />);
    expect(chip().getAttribute("data-tier")).toBe("live");
    expect(chip().textContent).toContain("1s");
  });

  it("marks warnings as degraded and shows the warning list in the popover", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    const now = Date.now();
    render(
      <PaneHealth
        contract={{
          dataMode: "live_exchange",
          asOf: new Date(now - 1_000).toISOString(),
          receivedAt: now - 1_000,
          sources: ["binance"],
          warnings: ["live source down — modeled fallback"],
        }}
      />,
    );
    expect(chip().getAttribute("data-tier")).toBe("degraded");

    fireEvent.click(chip());
    const popover = screen.getByTestId("pane-health-popover");
    expect(popover).toHaveTextContent("binance");
    expect(popover).toHaveTextContent("live source down — modeled fallback");
    expect(screen.getByTestId("pane-health-asof").textContent).toContain("11 Sep 2026 12:34:56");
    expect(screen.getByTestId("pane-health-warnings").textContent).toContain("modeled fallback");
  });

  it("marks old asOf as stale and ages it in minute vocabulary", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    const now = Date.now();
    render(
      <PaneHealth
        contract={{
          dataMode: "live_exchange",
          asOf: new Date(now - PANE_STALE_AFTER_MS - 60_000).toISOString(),
          receivedAt: now - PANE_STALE_AFTER_MS - 60_000,
        }}
      />,
    );
    expect(chip().getAttribute("data-tier")).toBe("stale");
    expect(chip().textContent).toContain("6m");
  });

  it("keeps the displayed age ticking while mounted", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    const now = Date.now();
    render(
      <PaneHealth
        contract={{
          dataMode: "live_exchange",
          asOf: new Date(now - 2_000).toISOString(),
          receivedAt: now - 2_000,
        }}
      />,
    );
    expect(chip().textContent).toContain("2s");
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    expect(chip().textContent).toContain("5s");
  });

  it("closes the popover on mouse leave", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    const now = Date.now();
    render(
      <PaneHealth
        contract={{ dataMode: "live_exchange", receivedAt: now - 1_000 }}
      />,
    );
    fireEvent.mouseEnter(chip());
    expect(screen.getByTestId("pane-health-popover")).toBeInTheDocument();
    fireEvent.mouseLeave(chip());
    expect(screen.queryByTestId("pane-health-popover")).toBeNull();
  });
});
