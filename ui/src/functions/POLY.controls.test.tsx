/**
 * POLY#4 — the pane exposes the topic search and the status filter that the
 * seed declares (query "Topic", status open | closed | resolved | all).
 * Before this, params were a constant { status: "open", min_liquidity_usd }
 * so neither the topic nor any other status could be reached.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { POLYPane } from "./POLY";

const { useFunctionSpy, refetchSpy } = vi.hoisted(() => ({
  useFunctionSpy: vi.fn(),
  refetchSpy: vi.fn(),
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    useFunctionSpy(args);
    return {
      state: "ok",
      data: { data: { status: "ok", data_mode: "delayed_reference", rows: [] }, sources: ["polymarket"] },
      error: null,
      refetch: refetchSpy,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

function lastParams(): Record<string, unknown> | undefined {
  const last = useFunctionSpy.mock.calls.at(-1)?.[0] as { params?: Record<string, unknown> };
  return last?.params;
}

beforeEach(() => {
  localStorage.clear();
  useFunctionSpy.mockClear();
  refetchSpy.mockClear();
});

afterEach(() => {
  cleanup();
});

describe("POLY#4 topic and status controls", () => {
  it("offers the seed's four status options", () => {
    render(<POLYPane code="POLY" />);
    const select = screen.getByLabelText("Status") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["open", "closed", "resolved", "all"]);
  });

  it("sends the chosen status to the function", () => {
    render(<POLYPane code="POLY" />);
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "resolved" } });
    expect(lastParams()?.status).toBe("resolved");
  });

  it("sends the topic as query once it is submitted", () => {
    render(<POLYPane code="POLY" />);
    fireEvent.change(screen.getByLabelText("Topic"), { target: { value: "  fed cuts " } });
    // Typing alone must not fire a request per keystroke.
    expect(lastParams()).not.toHaveProperty("query");
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(lastParams()?.query).toBe("fed cuts");
  });

  it("keeps the default request unchanged when no topic is entered", () => {
    render(<POLYPane code="POLY" />);
    expect(lastParams()).toEqual({ status: "open", min_liquidity_usd: 10_000 });
  });

  it("names the selected status in the empty state instead of always saying open", () => {
    render(<POLYPane code="POLY" />);
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "closed" } });
    expect(screen.getByText("No closed markets")).toBeTruthy();
  });
});
