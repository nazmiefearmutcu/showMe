/**
 * CDE pane — CRUD render-contract + honesty tests.
 *
 * CDE is full CRUD over a local formula store. These tests pin:
 *
 *  - the load states (loading / error / ok);
 *  - an empty store labels the injected rows as EXAMPLES, never stored;
 *  - backend input_error / calc_error reasons surface verbatim;
 *  - an evaluate payload renders a TRUE/FALSE result card;
 *  - the add form commits (footer action reflects it, client validation
 *    blocks an empty submit);
 *  - stored rows expose a Remove control, examples do not.
 *
 * `useFunction` is mocked via mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CDEPane } from "./CDE";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

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
    refetch: vi.fn(),
  }),
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const exampleRows = [
  {
    name: "large_cap_tech",
    formula: 'sector = "Technology" AND marketCap > 50000000000',
    operation: "example",
  },
  {
    name: "cheap_quality",
    formula: "pe < 25 AND beta < 1.2",
    operation: "example",
  },
];

const storedRows = [
  {
    name: "cheap_quality",
    formula: "pe < 25 AND beta < 1.2",
    operation: "custom_field",
  },
];

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("CDE pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<CDEPane code="CDE" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<CDEPane code="CDE" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders rows when ok", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ready", rows: storedRows, count: 1 } },
    });
    const { container } = render(<CDEPane code="CDE" />);
    expect(container.textContent).toContain("cheap_quality");
  });
});

describe("CDE pane — store honesty", () => {
  it("labels backend-injected rows as examples when the store is empty", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ready", rows: exampleRows, count: 0 } },
    });
    render(<CDEPane code="CDE" />);
    expect(
      screen.getByText(/bundled examples/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByTitle("Remove stored field cheap_quality"),
    ).toBeNull();
  });

  it("surfaces backend input_error reasons verbatim", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "input_error",
          reason: "formula parse error: unexpected token",
          rows: storedRows,
          count: 1,
        },
      },
    });
    render(<CDEPane code="CDE" />);
    expect(
      screen.getByText(/formula parse error: unexpected token/),
    ).toBeInTheDocument();
  });
});

describe("CDE pane — evaluate + forms", () => {
  it("renders a TRUE evaluation card from an evaluate payload", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ready",
          rows: [
            {
              name: "cheap_quality",
              formula: "pe < 25 AND beta < 1.2",
              operation: "evaluation",
              evaluation: true,
            },
          ],
          count: 1,
          evaluation: {
            name: "cheap_quality",
            value: true,
            formula: "pe < 25 AND beta < 1.2",
          },
        },
      },
    });
    render(<CDEPane code="CDE" />);
    expect(screen.getByText("TRUE")).toBeInTheDocument();
  });

  it("keeps the stored-field count and rows from an evaluate payload (F6)", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ready",
          rows: [
            {
              name: "cheap_quality",
              formula: "pe < 25 AND beta < 1.2",
              operation: "custom_field",
            },
            {
              name: "low_beta",
              formula: "beta < 1.2",
              operation: "custom_field",
            },
          ],
          // The backend now reports the real store size on evaluate — the
          // old code repurposed count=1 and hid every stored field.
          count: 2,
          evaluation: {
            name: "cheap_quality",
            value: true,
            formula: "pe < 25 AND beta < 1.2",
          },
        },
      },
    });
    const { container } = render(<CDEPane code="CDE" />);
    expect(screen.getByText("TRUE")).toBeInTheDocument();
    const kpi = screen.getByText("Stored fields").closest(".stat-card");
    expect(kpi?.textContent).toContain("2");
    expect(container.textContent).toContain("low_beta");
  });

  it("blocks an empty add submit with client validation", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ready", rows: storedRows, count: 1 } },
    });
    render(<CDEPane code="CDE" />);
    fireEvent.click(screen.getByTitle("Store the field"));
    expect(
      screen.getByText(/Name and formula are both required/i),
    ).toBeInTheDocument();
    // Footer action stays on list — nothing was committed.
    expect(screen.getByText("list")).toBeInTheDocument();
  });

  it("commits a filled add form into the footer action", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ready", rows: storedRows, count: 1 } },
    });
    render(<CDEPane code="CDE" />);
    fireEvent.change(screen.getByLabelText("New field name"), {
      target: { value: "value_screens" },
    });
    fireEvent.change(screen.getByLabelText("New field formula"), {
      target: { value: "pe < 15" },
    });
    fireEvent.click(screen.getByTitle("Store the field"));
    expect(screen.getByText("add value_screens")).toBeInTheDocument();
  });

  it("offers Remove only for stored rows, not examples", () => {
    setMockFn({
      state: "ok",
      data: {
        data: { status: "ready", rows: [...storedRows, ...exampleRows], count: 1 },
      },
    });
    render(<CDEPane code="CDE" />);
    expect(screen.getByTitle("Remove stored field cheap_quality")).toBeInTheDocument();
    expect(
      screen.queryByTitle("Remove stored field large_cap_tech"),
    ).toBeNull();
  });
});
