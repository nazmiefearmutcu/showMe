/**
 * PaneState — the shared async-state body wrapper.
 *
 * Pins the branch contract:
 *   - idle/loading → skeleton stack (aria-busy, testid)
 *   - error        → message + Retry callback
 *   - empty        → honest empty title/body + Retry
 *   - ok           → children only
 *   - refreshing   → children + inline stale strip, data stays visible
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PaneError, PaneState } from "./PaneState";

afterEach(() => {
  cleanup();
});

describe("PaneState", () => {
  it("renders a dense skeleton stack while loading", () => {
    const { container } = render(
      <PaneState state="loading" onRetry={() => undefined}>
        <span>content</span>
      </PaneState>,
    );
    expect(screen.getByTestId("pane-state-loading")).toBeTruthy();
    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
    // default 4 rows → 1 hero block + 3 slim rows
    expect(container.querySelectorAll(".ds-skeleton").length).toBe(4);
    expect(screen.queryByText("content")).toBeNull();
  });

  it("treats idle as loading", () => {
    render(
      <PaneState state="idle">
        <span>content</span>
      </PaneState>,
    );
    expect(screen.getByTestId("pane-state-loading")).toBeTruthy();
  });

  it("renders the error branch with the message and a working Retry", () => {
    const onRetry = vi.fn();
    render(
      <PaneState state="error" error={new Error("sidecar exploded")} onRetry={onRetry}>
        <span>content</span>
      </PaneState>,
    );
    expect(screen.getByTestId("pane-state-error")).toBeTruthy();
    expect(screen.getByText("sidecar exploded")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("content")).toBeNull();
  });

  it("accepts string errors and custom retry labels", () => {
    render(
      <PaneState state="error" error="provider down" onRetry={() => undefined} retryLabel="Re-check">
        <span>content</span>
      </PaneState>,
    );
    expect(screen.getByText("provider down")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Re-check" })).toBeTruthy();
  });

  it("renders the empty branch with honest title/body", () => {
    const onRetry = vi.fn();
    render(
      <PaneState
        state="ok"
        empty
        emptyTitle="No events"
        emptyBody="Provider returned no dated events."
        onRetry={onRetry}
        children={<span>content</span>}
      />,
    );
    expect(screen.getByTestId("pane-state-empty")).toBeTruthy();
    expect(screen.getByText("No events")).toBeTruthy();
    expect(screen.getByText("Provider returned no dated events.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalled();
    expect(screen.queryByText("content")).toBeNull();
  });

  it("renders children on ok without extra chrome", () => {
    render(
      <PaneState state="ok">
        <span>content</span>
      </PaneState>,
    );
    expect(screen.getByTestId("pane-state-ok")).toBeTruthy();
    expect(screen.getByText("content")).toBeTruthy();
    expect(screen.queryByTestId("pane-state-refreshing")).toBeNull();
  });

  it("keeps stale data visible and shows the refreshing strip", () => {
    render(
      <PaneState state="refreshing">
        <span>stale content</span>
      </PaneState>,
    );
    const strip = screen.getByTestId("pane-state-refreshing");
    expect(strip.getAttribute("data-stale")).toBe("true");
    expect(strip.getAttribute("role")).toBe("status");
    expect(screen.getByText("stale content")).toBeTruthy();
  });

  it("exports PaneError as a standalone composition primitive", () => {
    render(<PaneError message="boom" />);
    expect(screen.getByText("boom")).toBeTruthy();
  });
});
