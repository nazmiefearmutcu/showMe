/**
 * COUN pane — explicit-state honesty (COUN#2, COUN#4).
 *
 * The backend states gaps, staleness and the missing curated profile in the
 * response (warnings, reason, stale, profile_state). These tests pin that the
 * pane shows them to the user instead of hiding them behind the status pill.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { COUNPane } from "./COUN";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: unknown;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error ?? null,
    refetch: vi.fn(),
  }),
}));

beforeEach(() => {
  localStorage.removeItem("showme.coun.country");
  mockFn.state = "ok";
});
afterEach(() => {
  cleanup();
});

const JP_WARNING =
  "country 'JP' has no curated profile; no reference values are served";
const JP_PROFILE_REASON =
  "no curated reference profile for country 'JP'; no reference values are invented for it";

function jpLivePayload() {
  return {
    data: {
      country: "JP",
      rows: [
        {
          key: "policy_rate",
          section: "rates",
          metric: "Policy rate",
          value: 1.25,
          unit: "%",
          as_of: "2026-11-03",
          source_mode: "BIS CBPOL",
        },
      ],
      cards: [{ label: "Policy rate", value: 1.25 }],
      source_mode: "live_macro",
      country_known: false,
      profile_state: {
        status: "needs_input",
        reason: JP_PROFILE_REASON,
        next_actions: ["Choose a curated country: US, EU, GB or TR."],
      },
    },
    sources: ["btmm"],
    warnings: [JP_WARNING],
    elapsed_ms: 500,
  };
}

describe("COUN pane — explicit unknown-country state", () => {
  it("shows the backend warning and the missing-profile state to the user", () => {
    mockFn.data = jpLivePayload();
    render(<COUNPane code="COUN" />);

    const notes = screen.getByRole("note", { name: /COUN warnings/i });
    expect(within(notes).getByText(JP_WARNING)).toBeInTheDocument();
    expect(screen.getByText(JP_PROFILE_REASON)).toBeInTheDocument();
  });
});

describe("COUN pane — row reasons and notes", () => {
  it("shows the reason of an unavailable row next to its metric", () => {
    mockFn.data = {
      data: {
        country: "US",
        rows: [
          {
            key: "fiscal_balance",
            section: "fiscal",
            metric: "Fiscal balance",
            value: null,
            unit: "% GDP",
            as_of: null,
            source_mode: "provider_unavailable",
            reason: "no keyless live provider is wired for Fiscal balance in US",
          },
        ],
        cards: [],
        source_mode: "provider_unavailable",
      },
      sources: [],
      warnings: [],
    };
    render(<COUNPane code="COUN" />);

    expect(
      screen.getByText("no keyless live provider is wired for Fiscal balance in US"),
    ).toBeInTheDocument();
  });

  it("shows the reason of a stale row and does not count it as live", () => {
    const reason =
      "latest observation 2022-10-01 is 1500 days old; the limit for this series is 120 days. Shown with its as-of date; not treated as live.";
    mockFn.data = {
      data: {
        country: "EU",
        rows: [
          {
            key: "unemployment",
            section: "labor",
            metric: "Unemployment rate",
            value: 6.666667,
            unit: "%",
            as_of: "2022-10-01",
            source_mode: "fred",
            stale: true,
            reason,
            note: "euro-area aggregate, not a single member state",
          },
        ],
        cards: [],
        source_mode: "stale_macro",
      },
      sources: ["fred"],
      warnings: [],
    };
    render(<COUNPane code="COUN" />);

    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(
      screen.getByText("euro-area aggregate, not a single member state"),
    ).toBeInTheDocument();
    expect(screen.getByText("stale")).toBeInTheDocument();
  });
});
