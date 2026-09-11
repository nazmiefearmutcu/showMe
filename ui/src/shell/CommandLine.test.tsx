/**
 * Lane L2 — CommandLine component (campaign 2026-09-11).
 *
 * Covers: security+function execution, bare code/symbol execution, verb
 * execution through the action registry, unknown handling, the `/` hotkey
 * with its editable-target guard, Escape blur, suggestion arrows, and
 * session history stepping.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CommandLine, useCommandLineHotkey } from "./CommandLine";
import { useAppStore } from "@/lib/store";
import { useWorkspace } from "@/lib/workspace";
import {
  __resetForTests as resetHistory,
  getCommandHistory,
  pushCommandHistory,
} from "@/lib/command-history";
import { __resetForTests as resetRecents } from "@/lib/palette-recents";
import { listRecentActionIds } from "@/lib/palette-actions";
import { clearRecentSymbols } from "@/lib/symbols";

function setIndex() {
  useAppStore.setState({
    functionIndex: [
      { code: "DES", name: "Description", category: "equity", description: "" },
      { code: "GP", name: "Generic Price", category: "chart", description: "" },
      { code: "FA", name: "Financial Analysis", category: "equity", description: "" },
    ],
  });
}

function focusLeaf(code: string, symbol?: string) {
  useWorkspace.setState({
    tree: { kind: "leaf", id: "L1", code, symbol },
    focusedId: "L1",
  } as never);
}

function Harness() {
  useCommandLineHotkey();
  return <CommandLine />;
}

function input(): HTMLInputElement {
  return screen.getByRole("combobox") as HTMLInputElement;
}

beforeEach(() => {
  window.location.hash = "#/";
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetHistory();
  resetRecents();
  clearRecentSymbols();
  setIndex();
  focusLeaf("DES");
});

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-preset");
});

describe("CommandLine — execution", () => {
  it("MSFT GP offers the pinned row and Enter opens /symbol/MSFT/GP", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "MSFT GP" } });
    expect(screen.getByRole("option", { name: /Open GP with MSFT/ })).toBeTruthy();
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(window.location.hash).toBe("#/symbol/MSFT/GP");
  });

  it("reverse order GP MSFT resolves identically", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "GP MSFT" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(window.location.hash).toBe("#/symbol/MSFT/GP");
  });

  it("a bare symbol binds to the focused pane's function", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "MSFT" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(window.location.hash).toBe("#/symbol/MSFT/DES");
  });

  it("a bare function code opens the function", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "gp" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(window.location.hash).toBe("#/fn/GP");
  });

  it("a lowercase verb runs the matching palette action", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "theme" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(document.documentElement.getAttribute("data-preset")).toBe("midnight");
  });

  it("a typed verb shadows a fuzzy function suggestion (R1-F1)", () => {
    // Seed a function whose name matches the verb so a fuzzy row exists.
    useAppStore.setState({
      functionIndex: [
        { code: "DVD", name: "Dividends & Splits", category: "equity", description: "" },
        { code: "DES", name: "Description", category: "equity", description: "" },
      ],
    });
    focusLeaf("DES");
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "split" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    // The action ran (focused pane split) — not a navigation to DVD.
    expect(window.location.hash).not.toBe("#/fn/DVD");
    expect(useWorkspace.getState().tree.kind).toBe("split");
  });

  it("replays palette action ids recorded in history (R1-F9)", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "theme.toggle-dark-light" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    // The unknown-token fallback routed the id through the action registry.
    expect(listRecentActionIds()).toContain("theme.toggle-dark-light");
  });

  it("unknown input is kept and the grammar hint is shown", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "zzzzz" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(input().value).toBe("zzzzz");
    expect(screen.getByText(/No match/)).toBeTruthy();
  });

  it("the GO button submits the typed command", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "GP" } });
    fireEvent.click(screen.getByRole("button", { name: /Run command \(GO\)/ }));
    expect(window.location.hash).toBe("#/fn/GP");
  });

  it("records executed commands in session history", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "GP" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(getCommandHistory()[0]).toBe("GP");
  });

  it("renders the suggestion menu through a body portal (titlebar clips overflow)", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "GP" } });
    const menu = document.body.querySelector(".cmdline__menu");
    expect(menu).toBeTruthy();
    // Portal target is <body>, not the (overflow: hidden) titlebar subtree.
    expect(menu?.parentElement).toBe(document.body);
  });
});

describe("CommandLine — hotkey + keyboard", () => {
  it("'/' focuses the command input", () => {
    render(<Harness />);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "/", bubbles: true }));
    });
    expect(document.activeElement).toBe(input());
  });

  it("'/' does not steal focus from an editable target", () => {
    render(<Harness />);
    const other = document.createElement("input");
    document.body.appendChild(other);
    other.focus();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "/", bubbles: true }));
    });
    expect(document.activeElement).toBe(other);
    other.remove();
  });

  it("Escape blurs the input", () => {
    render(<CommandLine />);
    input().focus();
    expect(document.activeElement).toBe(input());
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(document.activeElement).not.toBe(input());
  });

  it("ArrowUp/Down step history when no suggestion is open", () => {
    pushCommandHistory("zzz");
    render(<CommandLine />);
    fireEvent.keyDown(input(), { key: "ArrowUp" });
    expect(input().value).toBe("zzz");
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(input().value).toBe("");
  });

  it("ArrowDown moves the suggestion selection while the menu is open", () => {
    render(<CommandLine />);
    fireEvent.change(input(), { target: { value: "e" } });
    const options = screen.getAllByRole("option");
    expect(options.length).toBeGreaterThan(1);
    expect(options[0].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input(), { key: "ArrowUp" });
    expect(screen.getAllByRole("option")[0].getAttribute("aria-selected")).toBe("true");
  });
});
