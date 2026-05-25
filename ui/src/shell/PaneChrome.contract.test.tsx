/**
 * Contract envelope smoke — verifies PaneChrome renders the rebuild
 * contract strip (mode pill / as-of / sources / warnings / next-actions)
 * when the pane-contract-store has a snapshot for the (code, symbol).
 */
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { PaneChrome } from "./PaneChrome";
import { usePaneContractStore } from "@/lib/pane-contract-store";

// Minimal workspace + appStore mocks to satisfy PaneChrome dependencies.
import { useWorkspace } from "@/lib/workspace";
import { useAppStore } from "@/lib/store";

beforeEach(() => {
  // Fresh contract store per test
  usePaneContractStore.setState({ byKey: {} });
  // Fresh workspace
  useWorkspace.setState({
    tree: { kind: "leaf", id: "L1", code: "GP", symbol: "AAPL" },
    focusedId: "L1",
  } as never);
  // Provide a function index entry so PaneChrome renders without crashing
  useAppStore.setState({
    functionIndex: [{ code: "GP", name: "Generic Price", category: "charts_tech", description: "test" }],
  } as never);
});

describe("PaneChrome contract envelope", () => {
  it("does not render when no contract snapshot exists", () => {
    render(<PaneChrome leafId="L1" code="GP" symbol="AAPL" />);
    expect(screen.queryByTestId("pane-chrome-contract")).toBeNull();
  });

  it("renders mode pill + sources when snapshot present (inline contract)", () => {
    usePaneContractStore.getState().record("GP", "AAPL", {
      dataMode: "live_exchange",
      asOf: new Date().toISOString(),
      sources: ["binance"],
      latencyMs: 42,
      warnings: [],
      nextActions: ["Open HP", "Open FA"],
      receivedAt: Date.now(),
    });
    render(<PaneChrome leafId="L1" code="GP" symbol="AAPL" />);
    const envelope = screen.getByTestId("pane-chrome-contract");
    expect(envelope.getAttribute("data-data-mode")).toBe("live_exchange");
    const mode = screen.getByTestId("pane-chrome-mode");
    expect(mode.textContent).toMatch(/LIVE/);
    const sources = screen.getByTestId("pane-chrome-sources");
    expect(sources.textContent).toMatch(/binance/);
    // Inline contract no longer renders the next-actions chip — full
    // next-actions list is in the mode pill's hover title instead.
    expect(screen.queryByTestId("pane-chrome-next-actions")).toBeNull();
  });

  it("renders warning count when warnings are present", () => {
    usePaneContractStore.getState().record("GP", "AAPL", {
      dataMode: "modeled",
      sources: ["internal_model"],
      warnings: ["live source down — using modeled fallback"],
      receivedAt: Date.now(),
    });
    render(<PaneChrome leafId="L1" code="GP" symbol="AAPL" />);
    const warn = screen.getByTestId("pane-chrome-warnings");
    expect(warn.textContent).toMatch(/⚠\s*1/);
    expect(warn.title).toMatch(/modeled fallback/);
  });

});
