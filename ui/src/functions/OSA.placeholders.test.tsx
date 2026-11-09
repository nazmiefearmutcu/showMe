/**
 * OSA placeholder honesty (T10): the pane never puts a template strike,
 * expiry or vol on the request path as if the user had entered it.
 *
 * Pins:
 *  - a fresh pane has no legs and sends none (nothing is priced);
 *  - a preset is leg structure only: strike, expiry and vol stay blank;
 *  - a stored leg with a missing field keeps it blank (no 100 / 0.25 fill);
 *  - clearing an input sends null, and a new leg guesses no expiry or vol.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OSAPane } from "./OSA";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const mockCalls: { params?: Record<string, unknown> } = {};

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args?: { params?: Record<string, unknown> }) => {
    mockCalls.params = args?.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

function legsSent(): Array<Record<string, unknown>> {
  return (mockCalls.params?.legs ?? []) as Array<Record<string, unknown>>;
}

function storedLegs(): Array<Record<string, unknown>> {
  return JSON.parse(localStorage.getItem("showme.osa.legs") ?? "[]");
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  mockCalls.params = undefined;
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("OSA placeholder honesty (T10)", () => {
  it("starts with no legs and sends none, so nothing is priced from a template", () => {
    render(<OSAPane code="OSA" symbol="SPY" />);
    expect(legsSent()).toEqual([]);
    expect(screen.queryByLabelText("Leg 1 strike")).toBeNull();
    expect(screen.getByText(/No legs yet/i)).toBeInTheDocument();
  });

  it("applies a preset as leg structure only: strike, expiry and vol stay blank", () => {
    render(<OSAPane code="OSA" symbol="SPY" />);
    fireEvent.click(screen.getByText("BULL CALL"));
    const sent = legsSent();
    expect(sent).toHaveLength(2);
    for (const leg of sent) {
      expect(leg.strike).toBeNull();
      expect(leg.expiry).toBeNull();
      expect(leg.vol).toBeNull();
    }
    expect(sent[0]).toMatchObject({ qty: 1, type: "CALL" });
    expect(sent[1]).toMatchObject({ qty: -1, type: "CALL" });
    expect((screen.getByLabelText("Leg 1 strike") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Leg 1 expiry years") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Leg 1 implied volatility decimal") as HTMLInputElement).value).toBe("");
  });

  it("does not fill a missing stored strike, expiry or vol with 100 or 0.25", () => {
    localStorage.setItem("showme.osa.legs", JSON.stringify([{ qty: 1, type: "CALL" }]));
    render(<OSAPane code="OSA" symbol="SPY" />);
    const sent = legsSent();
    expect(sent).toHaveLength(1);
    expect(sent[0].strike).toBeNull();
    expect(sent[0].expiry).toBeNull();
    expect(sent[0].vol).toBeNull();
    expect((screen.getByLabelText("Leg 1 strike") as HTMLInputElement).value).toBe("");
  });

  it("sends null when a strike is cleared, and persists null rather than a number", () => {
    localStorage.setItem(
      "showme.osa.legs",
      JSON.stringify([{ qty: 1, strike: 105, type: "CALL", expiry: 0.5, vol: 0.3 }]),
    );
    render(<OSAPane code="OSA" symbol="SPY" />);
    fireEvent.change(screen.getByLabelText("Leg 1 strike"), { target: { value: "" } });
    expect(legsSent()[0].strike).toBeNull();
    expect(storedLegs()[0].strike).toBeNull();
  });

  it("opens a new leg with no expiry or vol guessed when no spot is entered", () => {
    render(<OSAPane code="OSA" symbol="SPY" />);
    fireEvent.click(screen.getByTitle("Add a leg (max 4)"));
    expect(legsSent()[0]).toMatchObject({ qty: 1, type: "CALL", strike: null, expiry: null, vol: null });
  });

  it("anchors a new leg strike on the entered spot, still with no expiry or vol", () => {
    render(<OSAPane code="OSA" symbol="SPY" />);
    fireEvent.change(screen.getByLabelText("Underlying spot price"), { target: { value: "735" } });
    fireEvent.click(screen.getByTitle("Add a leg (max 4)"));
    expect(legsSent()[0]).toMatchObject({ strike: 735, expiry: null, vol: null });
  });

  it("drops a stored leg that has no valid side, instead of defaulting it to CALL", () => {
    localStorage.setItem("showme.osa.legs", JSON.stringify([{ qty: 1, strike: 100 }]));
    render(<OSAPane code="OSA" symbol="SPY" />);
    expect(legsSent()).toEqual([]);
  });

  it("no longer advertises a 0.25 default IV", () => {
    render(<OSAPane code="OSA" symbol="SPY" />);
    expect(document.body.textContent ?? "").not.toMatch(/default 0\.25/);
  });
});
