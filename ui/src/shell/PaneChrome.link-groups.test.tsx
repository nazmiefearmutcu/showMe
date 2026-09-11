/**
 * L3 (campaign 2026-09-11) — always-visible link-group badge + menu.
 *
 * The H2 finding: link groups existed but were invisible (buried in the ⋯
 * menu) and there was no desk-wide "link all" action. These tests pin the
 * badge state, the per-pane assignment flow, and the desk-wide actions
 * against the real workspace store.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { PaneChrome } from "./PaneChrome";
import { findLeaf, leaf, split, useWorkspace } from "@/lib/workspace";
import { useAppStore } from "@/lib/store";
import { usePaneContractStore } from "@/lib/pane-contract-store";

function setTwoLeafTree(): void {
  const a = { ...leaf("DES", "AAPL"), id: "L1" };
  const b = { ...leaf("GP", "MSFT"), id: "L2" };
  useWorkspace.setState({ tree: split("h", [a, b], [0.5, 0.5]), focusedId: "L1" });
}

beforeEach(() => {
  cleanup();
  usePaneContractStore.setState({ byKey: {} });
  useAppStore.setState({
    functionIndex: [{ code: "DES", name: "Description", category: "equity", description: "test" }],
  } as never);
  setTwoLeafTree();
});

describe("PaneChrome — link-group badge", () => {
  it("always renders; unlinked is neutral and shows a dash", () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" />);
    const badge = screen.getByTestId("pane-chrome-link-badge");
    expect(badge.getAttribute("data-link-group")).toBe("");
    expect(badge.textContent).toBe("–");
    expect(badge.getAttribute("aria-haspopup")).toBe("menu");
  });

  it("shows the group letter when the leaf is linked", () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" linkGroup="B" />);
    const badge = screen.getByTestId("pane-chrome-link-badge");
    expect(badge.getAttribute("data-link-group")).toBe("B");
    expect(badge.textContent).toBe("B");
  });

  it("menu is closed until the badge is clicked", () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" />);
    expect(screen.queryByTestId("pane-chrome-link-menu")).toBeNull();
    fireEvent.click(screen.getByTestId("pane-chrome-link-badge"));
    expect(screen.getByTestId("pane-chrome-link-menu")).toBeTruthy();
  });

  it("assigning a group writes it to this leaf", () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" />);
    fireEvent.click(screen.getByTestId("pane-chrome-link-badge"));
    const menu = screen.getByTestId("pane-chrome-link-menu");
    fireEvent.click(within(menu).getByText("B"));
    expect(findLeaf(useWorkspace.getState().tree, "L1")?.linkGroup).toBe("B");
    expect(findLeaf(useWorkspace.getState().tree, "L2")?.linkGroup).toBeUndefined();
  });

  it("Unlink clears this pane's group only", () => {
    useWorkspace.getState().setLeafLinkGroup("L1", "C");
    useWorkspace.getState().setLeafLinkGroup("L2", "C");
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" linkGroup="C" />);
    fireEvent.click(screen.getByTestId("pane-chrome-link-badge"));
    fireEvent.click(screen.getByTestId("pane-chrome-link-unlink"));
    expect(findLeaf(useWorkspace.getState().tree, "L1")?.linkGroup).toBeUndefined();
    expect(findLeaf(useWorkspace.getState().tree, "L2")?.linkGroup).toBe("C");
  });

  it("Link all panes assigns every leaf the target group (current, else A)", () => {
    useWorkspace.getState().setLeafLinkGroup("L1", "D");
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" linkGroup="D" />);
    fireEvent.click(screen.getByTestId("pane-chrome-link-badge"));
    const linkAll = screen.getByTestId("pane-chrome-link-all");
    expect(linkAll.textContent).toContain("D"); // kbd shows the resolved target
    fireEvent.click(linkAll);
    expect(findLeaf(useWorkspace.getState().tree, "L1")?.linkGroup).toBe("D");
    expect(findLeaf(useWorkspace.getState().tree, "L2")?.linkGroup).toBe("D");
  });

  it("Link all panes from an unlinked pane defaults to group A", () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" />);
    fireEvent.click(screen.getByTestId("pane-chrome-link-badge"));
    expect(screen.getByTestId("pane-chrome-link-all").textContent).toContain("A");
    fireEvent.click(screen.getByTestId("pane-chrome-link-all"));
    expect(findLeaf(useWorkspace.getState().tree, "L1")?.linkGroup).toBe("A");
    expect(findLeaf(useWorkspace.getState().tree, "L2")?.linkGroup).toBe("A");
  });

  it("Clear all links unlinks every leaf", () => {
    useWorkspace.getState().setAllLinkGroups("B");
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" linkGroup="B" />);
    fireEvent.click(screen.getByTestId("pane-chrome-link-badge"));
    fireEvent.click(screen.getByTestId("pane-chrome-link-clear"));
    expect(findLeaf(useWorkspace.getState().tree, "L1")?.linkGroup).toBeUndefined();
    expect(findLeaf(useWorkspace.getState().tree, "L2")?.linkGroup).toBeUndefined();
  });

  it("opening the ⋯ menu closes the link menu (only one popup at a time)", () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" />);
    fireEvent.click(screen.getByTestId("pane-chrome-link-badge"));
    expect(screen.getByTestId("pane-chrome-link-menu")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Pane actions" }));
    expect(screen.queryByTestId("pane-chrome-link-menu")).toBeNull();
    expect(screen.getByTestId("pane-chrome-menu")).toBeTruthy();
  });
});
