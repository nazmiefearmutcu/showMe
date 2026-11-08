import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ImportanceMeter } from "./ImportanceMeter";
import { QualityPill } from "./QualityPill";
import { SentimentChip } from "./SentimentChip";
import { StoryDrawer } from "./StoryDrawer";
import { StoryList } from "./StoryList";
import { StoryRow } from "./StoryRow";
import { TierBadge } from "./TierBadge";
import { EntityChip } from "./EntityChip";
import { hhmmUtc, hourLabel, parseQualityReason, signedValue } from "./format";
import type { NewsRow, NewsPayload } from "./news-types";
import type { UseFunctionResult } from "@/lib/useFunction";

const useFunctionMock = vi.fn();
const setFocusedTargetMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));
vi.mock("@/lib/workspace", () => ({
  useWorkspace: (
    selector: (s: { setFocusedTarget: typeof setFocusedTargetMock }) => unknown,
  ) => selector({ setFocusedTarget: setFocusedTargetMock }),
}));

const idle: UseFunctionResult<NewsPayload> = { state: "idle", refetch: () => undefined };

function makeRow(overrides: Partial<NewsRow> = {}): NewsRow {
  return {
    id: "n1",
    title: "Chip export rules tighten for Nvidia",
    url: "https://news.example/chips",
    publisher: "Reuters",
    publisher_tier: 1,
    published_at: "2026-11-08T09:14:00Z",
    summary: "Regulators expanded restrictions.",
    excerpt: null,
    language: "en",
    content_type: "news",
    symbols: ["NVDA"],
    countries: ["US"],
    topics: ["export_controls"],
    asset_classes: ["equity"],
    entities: [{ type: "equity", id: "NVDA", name: "NVIDIA", confidence: 0.91 }],
    sentiment: "negative",
    sentiment_score: -0.42,
    sentiment_confidence: 0.93,
    sentiment_model: "ProsusAI/finbert",
    entity_sentiment: {
      NVDA: { label: "negative", score: -0.5, confidence: 0.8, model: "ProsusAI/finbert" },
    },
    importance: 86,
    quality_label: "premium",
    quality_score: 88,
    quality_reasons: ["tier2:+10", "depth_body300:+12", "corroboration:-4"],
    story_id: "s1",
    story_size: 3,
    is_paywalled: false,
    ...overrides,
  } as NewsRow;
}

beforeEach(() => {
  useFunctionMock.mockReset();
  useFunctionMock.mockReturnValue(idle);
  setFocusedTargetMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("format helpers", () => {
  it("uses a real minus sign and explicit plus for signed values", () => {
    expect(signedValue(-0.42)).toBe("−0.42");
    expect(signedValue(0.71)).toBe("+0.71");
    expect(signedValue(0)).toBe("0.00");
  });

  it("formats UTC HH:MM and tolerates bad input", () => {
    expect(hhmmUtc("2026-11-08T09:04:00Z")).toBe("09:04");
    expect(hhmmUtc("nope")).toBe("--:--");
    expect(hhmmUtc(null)).toBe("--:--");
  });

  it("parses quality reasons into labels and points, keeping unknown names raw", () => {
    expect(parseQualityReason("tier2:+10")).toMatchObject({
      name: "tier2",
      points: 10,
      label: "Tier 2 publisher",
    });
    expect(parseQualityReason("mystery:-3")).toMatchObject({
      name: "mystery",
      points: -3,
      label: "mystery",
    });
    expect(parseQualityReason("plain")).toMatchObject({ points: null, label: "plain" });
  });

  it("names windows compactly", () => {
    expect(hourLabel(6)).toBe("6h");
    expect(hourLabel(72)).toBe("3d");
  });
});

describe("TierBadge", () => {
  it("shows the tier with a descriptive title", () => {
    render(<TierBadge tier={1} />);
    const badge = screen.getByLabelText("Tier 1");
    expect(badge).toHaveTextContent("T1");
    expect(badge).toHaveAttribute("title", "Tier 1: wire or official source");
  });
});

describe("SentimentChip", () => {
  it("uses glyph and sign per threshold, never colour alone", () => {
    const { rerender, container } = render(
      <SentimentChip score={0.71} model="ProsusAI/finbert" confidence={0.93} />,
    );
    expect(container.querySelector(".aw-sent--pos")).not.toBeNull();
    expect(screen.getByText("+0.71")).toBeInTheDocument();
    rerender(<SentimentChip score={-0.42} model="lexicon (aw-fin-1)" />);
    expect(container.querySelector(".aw-sent--neg")).not.toBeNull();
    expect(screen.getByText("−0.42")).toBeInTheDocument();
    rerender(<SentimentChip score={0.05} />);
    expect(container.querySelector(".aw-sent--neu")).not.toBeNull();
  });

  it("puts the model name in the tooltip", () => {
    render(
      <SentimentChip
        score={0.71}
        model="ProsusAI/finbert"
        confidence={0.93}
        label="Positive"
      />,
    );
    expect(screen.getByLabelText(/ProsusAI\/finbert/)).toHaveAttribute(
      "title",
      "Positive +0.71, ProsusAI/finbert, confidence 0.93",
    );
  });

  it("renders nothing when the score is missing (no default value)", () => {
    const { container } = render(<SentimentChip score={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ImportanceMeter", () => {
  it("fills ceil(importance/25) bars and marks >= 70 as hot", () => {
    const { container } = render(<ImportanceMeter importance={86} />);
    expect(container.querySelectorAll(".aw-imp__bar--on")).toHaveLength(4);
    expect(container.querySelector(".aw-imp--hot")).not.toBeNull();
    expect(screen.getByLabelText("Importance 86 of 100")).toBeInTheDocument();
  });

  it("is not hot below 70", () => {
    const { container } = render(<ImportanceMeter importance={40} />);
    expect(container.querySelectorAll(".aw-imp__bar--on")).toHaveLength(2);
    expect(container.querySelector(".aw-imp--hot")).toBeNull();
  });
});

describe("EntityChip", () => {
  it("calls back when interactive and stays a span otherwise", () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <EntityChip kind="symbol" label="NVDA" onClick={onClick} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "symbol NVDA" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(<EntityChip kind="country" label="US" />);
    expect(screen.queryByRole("button", { name: "country US" })).toBeNull();
    expect(screen.getByText("US")).toBeInTheDocument();
  });

  it("shows topics with underscores as words", () => {
    render(<EntityChip kind="topic" label="export_controls" />);
    expect(screen.getByText("export controls")).toBeInTheDocument();
  });
});

describe("QualityPill", () => {
  it("opens the reasons popover, moves focus in, and Esc returns focus to the ? button", () => {
    render(
      <QualityPill
        label="premium"
        score={88}
        reasons={["tier2:+10", "corroboration:-4"]}
      />,
    );
    const why = screen.getByRole("button", { name: "Why premium: show quality reasons" });
    fireEvent.click(why);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Tier 2 publisher")).toBeInTheDocument();
    expect(within(dialog).getByText("−4")).toBeInTheDocument();
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(why).toHaveFocus();
  });
});

describe("StoryRow", () => {
  it("shows publisher, tier, UTC time and the open-link button without hiding them", () => {
    render(<StoryRow row={makeRow()} code="TOP" />);
    expect(screen.getByText("Reuters")).toBeInTheDocument();
    expect(screen.getByLabelText("Tier 1")).toBeInTheDocument();
    expect(screen.getByText("09:14 UTC")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open article at Reuters" }),
    ).toBeInTheDocument();
  });

  it("labels the article with publisher, relative time and title", () => {
    render(<StoryRow row={makeRow()} code="TOP" />);
    const article = screen.getByRole("article");
    expect(article.getAttribute("aria-label")).toMatch(
      /^Reuters, .+ ago: Chip export rules tighten for Nvidia$/,
    );
  });

  it("opens the article externally from the headline", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<StoryRow row={makeRow()} code="TOP" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Chip export rules tighten for Nvidia" }),
    );
    expect(open).toHaveBeenCalledWith(
      "https://news.example/chips",
      "_blank",
      "noopener,noreferrer",
    );
    open.mockRestore();
  });

  it("marks paywalled rows with an accessible label", () => {
    render(<StoryRow row={makeRow({ is_paywalled: true })} code="TOP" />);
    expect(screen.getByRole("img", { name: "Paywalled at source" })).toBeInTheDocument();
  });

  it("shows +N sources and fetches the story only when expanded", () => {
    render(<StoryRow row={makeRow()} code="TOP" symbol="NVDA" />);
    const more = screen.getByRole("button", { name: /\+2 sources/ });
    expect(more).toHaveAttribute("aria-expanded", "false");
    const lastCallBefore = useFunctionMock.mock.calls.at(-1)?.[0];
    expect(lastCallBefore).toMatchObject({ enabled: false, params: { story_id: "s1" } });
    useFunctionMock.mockReturnValue({
      state: "ok",
      refetch: () => undefined,
      data: {
        data: {
          status: "ok",
          story: {
            id: "s1",
            items: [
              {
                id: "i2",
                title: "Second outlet on the same story",
                publisher_name: "Bloomberg",
                publisher_tier: 2,
                url: "https://bbg.example/x",
                published_at: "2026-11-08T09:20:00Z",
              },
            ],
          },
        },
      },
    });
    fireEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Second outlet on the same story")).toBeInTheDocument();
    expect(screen.getByText("Bloomberg")).toBeInTheDocument();
    const lastCallAfter = useFunctionMock.mock.calls.at(-1)?.[0];
    expect(lastCallAfter).toMatchObject({ enabled: true, code: "TOP", symbol: "NVDA" });
  });

  it("omits the expander when the story has one source", () => {
    render(<StoryRow row={makeRow({ story_size: 1 })} code="TOP" />);
    expect(screen.queryByRole("button", { name: /sources/ })).toBeNull();
  });

  it("sends DES navigation for an equity chip", () => {
    render(<StoryRow row={makeRow()} code="TOP" />);
    fireEvent.click(screen.getByRole("button", { name: "symbol NVDA" }));
    expect(setFocusedTargetMock).toHaveBeenCalledWith("DES", "NVDA");
  });

  it("shows the content-type badge only for non-news types", () => {
    const { rerender } = render(
      <StoryRow row={makeRow({ content_type: "analysis" })} code="TOP" />,
    );
    expect(screen.getByText("analysis")).toBeInTheDocument();
    rerender(<StoryRow row={makeRow({ content_type: "news" })} code="TOP" />);
    expect(screen.queryByText("news")).toBeNull();
  });
});

describe("StoryList and StoryDrawer", () => {
  it("opens the drawer on row click and closes it with Escape", () => {
    render(
      <StoryList
        rows={[makeRow(), makeRow({ id: "n2", title: "Second story" })]}
        code="TOP"
        ariaLabel="Stories"
      />,
    );
    fireEvent.click(screen.getByRole("article", { name: /Second story/ }));
    const dialog = screen.getByRole("dialog", { name: "Story" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Story" })).toBeNull();
  });

  it("the drawer shows lead item, quality reasons and entity sentiment", () => {
    render(
      <StoryDrawer
        row={makeRow()}
        code="TOP"
        hasPrev={false}
        hasNext={false}
        onPrev={() => undefined}
        onNext={() => undefined}
        onClose={() => undefined}
      />,
    );
    expect(screen.getByText("Lead")).toBeInTheDocument();
    expect(screen.getByText("Tier 2 publisher")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/ProsusAI\/finbert/)).toHaveLength(2);
    expect(screen.getByText("3 sources, first seen 09:14 UTC")).toBeInTheDocument();
  });

  it("j and k move focus between rows", () => {
    render(
      <StoryList
        rows={[makeRow(), makeRow({ id: "n2", title: "Second story" })]}
        code="TOP"
        ariaLabel="Stories"
      />,
    );
    const first = screen.getByRole("article", { name: /Chip export/ });
    first.focus();
    fireEvent.keyDown(first, { key: "j" });
    expect(screen.getByRole("article", { name: /Second story/ })).toHaveFocus();
  });
});
