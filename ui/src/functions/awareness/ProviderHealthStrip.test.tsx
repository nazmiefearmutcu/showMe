import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AwarenessUnavailable } from "./AwarenessUnavailable";
import { ProviderHealthStrip } from "./ProviderHealthStrip";

const NOW = Date.parse("2026-11-08T12:00:00Z");

describe("ProviderHealthStrip", () => {
  it("shows feed counts and the last update when everything is fresh", () => {
    render(
      <ProviderHealthStrip
        nowMs={NOW}
        feedHealth={{ ok: 84, degraded: 0, down: 0 }}
        providers={[{ provider: "news.feeds", status: "ok", last_ok_at: "2026-11-08T11:58:00Z" }]}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("84 feeds fresh");
    expect(screen.getByRole("status")).toHaveTextContent("Updated 11:58 UTC");
  });

  it("switches to the warn variant and names the failing provider", () => {
    render(
      <ProviderHealthStrip
        nowMs={NOW}
        providers={[
          { provider: "econ.nasdaq", status: "ok", last_ok_at: "2026-11-08T11:30:00Z" },
          { provider: "econ.forexfactory", status: "down", last_error: "429 rate limited" },
        ]}
      />,
    );
    const strip = screen.getByRole("status");
    expect(strip.className).toContain("aw-health--warn");
    expect(strip).toHaveTextContent("Last good update 11:30 UTC, 30 min ago");
    expect(strip).toHaveTextContent("econ.forexfactory failing: 429 rate limited");
  });
});

describe("AwarenessUnavailable", () => {
  it("renders the verbatim reason, never rows, and retries", () => {
    const retry = vi.fn();
    render(<AwarenessUnavailable reason="awareness service is not running at http://127.0.0.1:8086" onRetry={retry} subject="news" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Awareness service is not running");
    expect(screen.getByText(/127\.0\.0\.1:8086/)).toBeInTheDocument();
    screen.getByRole("button", { name: "Retry" }).click();
    expect(retry).toHaveBeenCalledOnce();
  });
});
