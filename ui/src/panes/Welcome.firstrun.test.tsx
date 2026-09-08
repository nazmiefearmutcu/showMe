/**
 * Lane D — U9 first-run desk setup card on the Welcome dashboard.
 *
 * Pins the offer-once contract:
 *   - pristine HOME tree + empty watchlist + unanswered flag → card shows
 *     with the three builtin presets + seed + skip actions;
 *   - accepting a preset swaps the workspace to the preset tree and
 *     records the answer (never nags again);
 *   - seeding fills the saved watchlist (rows render live immediately);
 *   - Skip records the answer without touching the desk;
 *   - a previously-answered user never sees the card;
 *   - a restored (non-pristine) desk never sees the card.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { Welcome } from "./Welcome";
import { useAppStore } from "@/lib/store";
import { useSentimentStore } from "@/lib/sentiment-store";
import { leaf, split, useWorkspace, type WorkspaceNode } from "@/lib/workspace";
import { FIRST_RUN_DONE_KEY } from "@/lib/first-run";

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({ state: "idle", data: null, error: null, refetch: () => {} }),
}));

vi.mock("@/lib/market-data", () => ({
  useLiveQuotes: () => ({}),
}));

function snapshotWorkspace(): { tree: WorkspaceNode; focusedId: string } {
  const { tree, focusedId } = useWorkspace.getState();
  return { tree, focusedId };
}

function restoreWorkspace(snap: { tree: WorkspaceNode; focusedId: string }) {
  useWorkspace.setState({ tree: snap.tree, focusedId: snap.focusedId });
}

beforeEach(() => {
  localStorage.clear();
  useAppStore.setState({
    sidecarStatus: "booting",
    sidecarPort: null,
    engineRoot: null,
    functionIndex: [],
  });
  useSentimentStore.setState({
    score: 0,
    label: "Neutral",
    mentions: 0,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
  });
  const home = leaf("HOME");
  useWorkspace.setState({ tree: home, focusedId: home.id });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("Welcome first-run desk setup (U9)", () => {
  it("offers the card on a pristine first run", async () => {
    const snap = snapshotWorkspace();
    try {
      const { findByTestId } = render(<Welcome />);
      const card = await findByTestId("first-run-card");
      expect(card.textContent).toContain("Set up your desk");
      expect(
        document.querySelector("[data-testid='first-run-preset-markets-overview']"),
      ).toBeTruthy();
      expect(
        document.querySelector("[data-testid='first-run-preset-trading-desk']"),
      ).toBeTruthy();
      expect(document.querySelector("[data-testid='first-run-preset-macro']")).toBeTruthy();
      expect(document.querySelector("[data-testid='first-run-seed']")).toBeTruthy();
      expect(document.querySelector("[data-testid='first-run-skip']")).toBeTruthy();
    } finally {
      restoreWorkspace(snap);
    }
  });

  it("accepting a preset loads the desk AND records the answer", async () => {
    const snap = snapshotWorkspace();
    try {
      const { findByTestId } = render(<Welcome />);
      const btn = await findByTestId("first-run-preset-markets-overview");
      fireEvent.click(btn);

      // Workspace swapped to the preset tree (DES/GP/WEI/TOP), flag stored.
      await waitFor(() => {
        expect(useWorkspace.getState().tree.kind).toBe("split");
      });
      expect(localStorage.getItem(FIRST_RUN_DONE_KEY)).toBe("1");

      // With the tree no longer pristine, the card is gone even though the
      // watchlist is still empty.
      expect(document.querySelector("[data-testid='first-run-card']")).toBeNull();
    } finally {
      restoreWorkspace(snap);
    }
  });

  it("seeding the starter watchlist fills the desk and records the answer", async () => {
    const snap = snapshotWorkspace();
    try {
      const { findByTestId, findByRole } = render(<Welcome />);
      const seed = await findByTestId("first-run-seed");
      fireEvent.click(seed);

      // 8 starter rows → watchEmpty flips false → the live grid renders.
      await findByRole("grid");
      expect(localStorage.getItem(FIRST_RUN_DONE_KEY)).toBe("1");
      expect(document.querySelector("[data-testid='first-run-card']")).toBeNull();
    } finally {
      restoreWorkspace(snap);
    }
  });

  it("Skip records the answer without touching the desk", async () => {
    const snap = snapshotWorkspace();
    try {
      const { findByTestId, queryByTestId } = render(<Welcome />);
      const skip = await findByTestId("first-run-skip");
      fireEvent.click(skip);

      await waitFor(() => {
        expect(localStorage.getItem(FIRST_RUN_DONE_KEY)).toBe("1");
      });
      expect(queryByTestId("first-run-card")).toBeNull();
      // Desk untouched: still a single HOME leaf.
      expect(useWorkspace.getState().tree.kind).toBe("leaf");
      // The plain empty-state CTA is still offered.
      expect(queryByTestId("watchlist-empty-cta")).not.toBeNull();
    } finally {
      restoreWorkspace(snap);
    }
  });

  it("never nags once the flag is stored (even on a pristine desk)", async () => {
    const snap = snapshotWorkspace();
    try {
      localStorage.setItem(FIRST_RUN_DONE_KEY, "1");
      const { findByTestId, queryByTestId } = render(<Welcome />);
      await findByTestId("watchlist-empty-state");
      expect(queryByTestId("first-run-card")).toBeNull();
      expect(queryByTestId("watchlist-empty-cta")).not.toBeNull();
    } finally {
      restoreWorkspace(snap);
    }
  });

  it("never nags when the workspace restored a real desk (non-pristine tree)", async () => {
    const snap = snapshotWorkspace();
    try {
      const top = split("h", [leaf("DES", "AAPL"), leaf("GP", "AAPL")]);
      useWorkspace.setState({ tree: top, focusedId: leaf("HOME").id });
      const { findByTestId, queryByTestId } = render(<Welcome />);
      await findByTestId("watchlist-empty-state");
      expect(queryByTestId("first-run-card")).toBeNull();
    } finally {
      restoreWorkspace(snap);
    }
  });
});
