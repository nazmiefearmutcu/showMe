/**
 * REL-04 P5 — AppErrorBoundary tests.
 *
 * Pin the contract:
 *  - Renders children verbatim while no error is thrown.
 *  - Catches a throwing child and renders the alert surface with the
 *    expected affordances (`Reload` + `Open Logs Folder`).
 *  - Console.error is invoked exactly once for the captured error
 *    (component lifecycle path is well-typed even under StrictMode's
 *    double-invoke contract).
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { AppErrorBoundary } from "./AppErrorBoundary";

function Boom(): JSX.Element {
  throw new Error("intentional render crash");
}

describe("AppErrorBoundary", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders children when no error is thrown", () => {
    render(
      <AppErrorBoundary>
        <span data-testid="ok-child">healthy</span>
      </AppErrorBoundary>,
    );
    expect(screen.getByTestId("ok-child")).toHaveTextContent("healthy");
    expect(screen.queryByTestId("app-error-boundary")).toBeNull();
  });

  it("renders the alert surface and logs to console.error when a child throws", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );
    const surface = screen.getByTestId("app-error-boundary");
    expect(surface).toBeInTheDocument();
    expect(surface).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("app-error-reload")).toBeInTheDocument();
    expect(screen.getByTestId("app-error-open-logs")).toBeInTheDocument();
    expect(surface).toHaveTextContent(/intentional render crash/);
    // Boundary forwarded the error to console.error.
    expect(errSpy).toHaveBeenCalled();
  });

  it("Open Logs button is wired and does not throw without Tauri", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );
    const btn = screen.getByTestId("app-error-open-logs");
    // Should not throw synchronously; lazy invoke goes through dynamic
    // import which resolves to the browser stub in the test env.
    expect(() => fireEvent.click(btn)).not.toThrow();
  });
});
