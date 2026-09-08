/**
 * BQUANT pane — not-configured honesty tests.
 *
 * The backend returns a readiness manifest, not notebook data. Without a
 * mounted Jupyter runtime the pane must render an explicit NOT-CONFIGURED
 * state (reason + next actions + what the pane WOULD render) and never a
 * faked notebook surface. These tests pin:
 *
 *  - the load states (loading / error / ok);
 *  - the not_configured payload renders the negative pill, the backend
 *    reason, the next actions, and the would-render note;
 *  - no notebook-launcher surface is faked for a not_configured payload;
 *  - a configured (status=ok) payload flips the pills positive;
 *  - the refresh control re-checks readiness.
 *
 * `useFunction` is mocked via mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BQUANTPane } from "./BQUANT";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetch = vi.fn();

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch,
  }),
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const notConfiguredPayload = {
  data: {
    data: {
      status: "not_configured",
      reason: "No mounted Jupyter runtime or local example notebooks were detected.",
      next_actions: [
        "Start a Jupyter server from the ShowMe launcher before using BQUANT.",
        "Mount /notebook or provide a reachable notebook_url in Advanced params.",
      ],
      rows: [
        {
          component: "Notebook route",
          status: "not_configured",
          value: "/notebook",
          action: "Open only after a Jupyter server is mounted by the launcher.",
        },
        {
          component: "Kernel modules",
          status: "available",
          value: "showme.data, showme.functions, showme.portfolio",
          action: "Import these modules in a notebook cell.",
        },
        {
          component: "Examples",
          status: "missing",
          value: "examples/01_quickstart.ipynb, examples/02_backtest.ipynb",
          action: "Create or mount notebooks before treating this as an executable notebook surface.",
        },
      ],
      summary: {
        notebook_ready: false,
        notebook_url: "/notebook",
        examples_found: 0,
        preloaded_modules: 3,
      },
    },
    sources: ["local_notebook_manifest"],
    elapsed_ms: 0.1,
  },
};

const configuredPayload = {
  data: {
    data: {
      ...notConfiguredPayload.data.data,
      status: "ok",
      reason: null,
      next_actions: [],
      rows: [
        {
          component: "Notebook route",
          status: "configured",
          value: "/notebook",
          action: "Open only after a Jupyter server is mounted by the launcher.",
        },
        {
          component: "Kernel modules",
          status: "available",
          value: "showme.data, showme.functions, showme.portfolio",
          action: "Import these modules in a notebook cell.",
        },
        {
          component: "Examples",
          status: "found",
          value: "examples/01_quickstart.ipynb, examples/02_backtest.ipynb",
          action: "Create or mount notebooks before treating this as an executable notebook surface.",
        },
      ],
      summary: {
        notebook_ready: true,
        notebook_url: "/notebook",
        examples_found: 2,
        preloaded_modules: 3,
      },
    },
    sources: ["local_notebook_manifest"],
    elapsed_ms: 0.1,
  },
};

beforeEach(() => {
  refetch.mockClear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("BQUANT pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<BQUANTPane code="BQUANT" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<BQUANTPane code="BQUANT" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("BQUANT pane — not-configured honesty", () => {
  it("renders the explicit not-configured state with reason + next actions", () => {
    setMockFn({ state: "ok", ...notConfiguredPayload });
    render(<BQUANTPane code="BQUANT" />);
    expect(screen.getByText(/BQuant is not configured/i)).toBeInTheDocument();
    expect(
      screen.getByText(/No mounted Jupyter runtime/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Start a Jupyter server from the ShowMe launcher/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/not configured/i).length).toBeGreaterThan(0);
  });

  it("states what the pane WOULD render once configured", () => {
    setMockFn({ state: "ok", ...notConfiguredPayload });
    render(<BQUANTPane code="BQUANT" />);
    expect(
      screen.getByText(/would render a notebook launcher/i),
    ).toBeInTheDocument();
  });

  it("renders the readiness checklist rows", () => {
    setMockFn({ state: "ok", ...notConfiguredPayload });
    const { container } = render(<BQUANTPane code="BQUANT" />);
    expect(container.textContent).toContain("Notebook route");
    expect(container.textContent).toContain("Kernel modules");
    expect(container.textContent).toContain("Examples");
  });

  it("never fakes a notebook surface while unconfigured", () => {
    setMockFn({ state: "ok", ...notConfiguredPayload });
    const { container } = render(<BQUANTPane code="BQUANT" />);
    expect(container.textContent).toContain("renders NO notebook surface");
    expect(screen.queryByTitle("Open notebook")).toBeNull();
    expect(screen.queryByText(/Launch notebook/i)).toBeNull();
  });
});

describe("BQUANT pane — configured payload", () => {
  it("flips the readiness pills positive when status=ok", () => {
    setMockFn({ state: "ok", ...configuredPayload });
    render(<BQUANTPane code="BQUANT" />);
    expect(screen.getByText(/notebook ready/i)).toBeInTheDocument();
    expect(screen.queryByText(/BQuant is not configured/i)).toBeNull();
  });
});

describe("BQUANT pane — refresh", () => {
  it("re-checks readiness from the refresh control", () => {
    setMockFn({ state: "ok", ...notConfiguredPayload });
    render(<BQUANTPane code="BQUANT" />);
    fireEvent.click(screen.getByTitle("Re-check notebook readiness"));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
