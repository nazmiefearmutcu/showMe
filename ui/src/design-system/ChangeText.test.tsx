import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChangeText } from "./ChangeText";

describe("<ChangeText>", () => {
  it("formats positive numbers with + and green color token", () => {
    render(<ChangeText value={1.234} />);
    const node = screen.getByText(/\+1\.23/);
    expect(node).toBeInTheDocument();
    expect(node).toHaveStyle({ color: "var(--positive)" });
  });

  it("formats negatives with minus glyph and red token", () => {
    render(<ChangeText value={-0.5} />);
    const node = screen.getByText(/−0\.50/);
    expect(node).toBeInTheDocument();
    expect(node).toHaveStyle({ color: "var(--negative)" });
  });

  it("renders em-dash for null/NaN", () => {
    render(<ChangeText value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("supports prefix/suffix without sign when signed=false", () => {
    render(<ChangeText value={42} prefix="$" digits={0} signed={false} />);
    expect(screen.getByText(/\$42/)).toBeInTheDocument();
  });
});
