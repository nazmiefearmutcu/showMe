/**
 * Owner report (2026-09-16): typing "/settings" into the sidebar search
 * returned "FN 0 / 157" — a leading command punctuation ("/", ">", "#")
 * matched nothing. The query must be sanitized before matching so
 * "/settings" finds SET Settings.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Sidebar } from "./Sidebar";
import { useAppStore } from "@/lib/store";

function seedIndex() {
  useAppStore.setState({
    functionIndex: [
      { code: "SET", name: "Settings", category: "tools", description: "Desk settings" },
      { code: "DES", name: "Description", category: "equity", description: "" },
      { code: "GP", name: "Generic Price", category: "chart", description: "" },
    ],
  });
  useAppStore.getState().toggleSidebar(true);
}

beforeEach(() => {
  window.location.hash = "#/";
  seedIndex();
});

afterEach(() => {
  cleanup();
});

describe("Sidebar search sanitization", () => {
  it("finds Settings when the query carries a leading command slash", () => {
    render(<Sidebar />);
    const input = screen.getByPlaceholderText("code, name, category");
    fireEvent.change(input, { target: { value: "/settings" } });
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("still finds Settings with a bare query", () => {
    render(<Sidebar />);
    const input = screen.getByPlaceholderText("code, name, category");
    fireEvent.change(input, { target: { value: "settings" } });
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });
});
