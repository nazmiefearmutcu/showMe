import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { INDXPane } from "./INDX";
import { useIndicatorStore } from "@/lib/indicator-store";

const FIXTURES = [
  { id: "rsi", display_name: "RSI", family: "momentum", short_description: "OB/OS",
    long_description: "Wilder", formula: "RSI=...",
    parameters: [{ name: "period", type: "int", default: 14, min: 2, max: 100, effect: "düşür → hızlı" }],
    confidence: 9, confidence_rationale: "range güvenilir",
    suggested_strategy: { name: "MR", summary: "S", rules: ["entry", "exit"] }, references: ["Wilder 1978"] },
  { id: "ema", display_name: "EMA", family: "trend", short_description: "MA",
    long_description: "", formula: "", parameters: [], confidence: 8,
    confidence_rationale: "", suggested_strategy: {}, references: [] },
];

beforeEach(() => {
  useIndicatorStore.setState({ entries: FIXTURES, loading: false, error: null, selectedId: null });
});

describe("INDX pane", () => {
  it("renders the indicator grid", () => {
    render(<INDXPane />);
    expect(screen.getByText("RSI")).toBeInTheDocument();
    expect(screen.getByText("EMA")).toBeInTheDocument();
  });

  it("search narrows results", () => {
    render(<INDXPane />);
    fireEvent.change(screen.getByPlaceholderText(/indikat/i), { target: { value: "rsi" } });
    expect(screen.getByText("RSI")).toBeInTheDocument();
    expect(screen.queryByText("EMA")).toBeNull();
  });

  it("family chip filters by family", () => {
    render(<INDXPane />);
    fireEvent.click(screen.getByRole("button", { name: /^trend$/i }));
    expect(screen.queryByText("RSI")).toBeNull();
    expect(screen.getByText("EMA")).toBeInTheDocument();
  });

  it("selecting renders detail view with confidence + parameters", () => {
    render(<INDXPane />);
    fireEvent.click(screen.getByText("RSI"));
    // "Wilder" appears in both long_description and a reference entry, so
    // multiple matches are expected — assert >=1.
    expect(screen.getAllByText(/Wilder/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/period/i)).toBeInTheDocument();
    // Confidence chip text "9/10" appears in BOTH the grid card AND the detail header.
    expect(screen.getAllByText(/9\/10/).length).toBeGreaterThanOrEqual(1);
  });

  it("empty filter shows fallback copy", () => {
    render(<INDXPane />);
    fireEvent.change(screen.getByPlaceholderText(/indikat/i), { target: { value: "xyzzy" } });
    expect(screen.getByText(/eşleşen indikat/i)).toBeInTheDocument();
  });
});
