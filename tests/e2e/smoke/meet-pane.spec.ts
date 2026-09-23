import { expect, test } from "@playwright/test";
import { seedBrowserShellLocalStorage, stubSidecar } from "./_fixtures/stub-sidecar";

function fixture() {
  const now = Date.now();
  const calendar = {
    id: "economic:audit", kind: "economic", title: "Audit CPI release", countries: ["US"],
    country_names: ["United States"], when_utc: new Date(now - 3600000).toISOString(),
    impact: "high", currencies: ["USD"], pairs: ["EURUSD"], source: "audit_fixture",
    spot: false, pinned: true, seconds_to_event: -3600,
    details: { actual: "3.9%", forecast: "3.8%", previous: "3.7%", unit: "%" },
  };
  const wire = {
    id: "world:audit", kind: "world", title: "Bitcoin ETF inflows rise", countries: [],
    country_names: [], when_utc: new Date(now - 60000).toISOString(),
    impact: "medium", currencies: [], pairs: ["BTCUSD"], source: "audit_fixture",
    spot: false, pinned: false, seconds_to_event: -60,
    details: { asset_tags: ["BTC", "ETF"], topic_tags: [], event_type: "etf_flow",
      summary: "Fixture summary for browser integration.", url: "https://example.test/news" },
  };
  return {
    code: "MEET", instrument: null, status: "ok", sources: ["audit_fixture"], warnings: [],
    fetched_at: new Date(now).toISOString(), metadata: {},
    data: { status: "ok", as_of: new Date(now).toISOString(), rows: [wire, calendar],
      upcoming: [], past: [wire, calendar], row_count: 2, upcoming_count: 0, past_count: 2,
      country_index: [], country_catalog: [{ iso: "US", name: "United States" }], alerts: [],
      window: { days_ahead: 90, days_back: 7 },
      data_quality: { row_count: 2, timed_count: 2, undated_count: 0,
        source_traceable_count: 2, url_traceable_count: 1, duplicate_rows_dropped: 0,
        rows_capped_at_limit: 5, active_source_tiers: ["audit_fixture"] },
    },
  };
}

test("MEET footer keeps long sources inside their slot at different widths", async ({ page }) => {
  const response = fixture();
  response.sources = ["forex_factory", "financecalendar", "rss+gdelt_gal+gdelt_gal"];
  await seedBrowserShellLocalStorage(page);
  await stubSidecar(page, { functions: { MEET: response } });
  await page.goto("/#/fn/MEET");
  const footer = page.locator(".meet-pane .ds-pane-footer");
  await expect(footer.getByTitle(response.sources.join(", "))).toBeVisible();
  for (const width of [1440, 960, 640]) {
    await page.setViewportSize({ width, height: 950 });
    const layout = await footer.evaluate((node) => {
      const bounds = node.getBoundingClientRect();
      const slots = Array.from(node.querySelectorAll(":scope > .ds-status"));
      const rects = slots.map(slot => slot.getBoundingClientRect());
      const value = slots[0].querySelector(".ds-status__value") as HTMLElement;
      return {
        fits: rects.every(r => r.left >= bounds.left && r.right <= bounds.right + 1),
        overlaps: rects.some((a, i) => rects.slice(i + 1).some(b =>
          a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom)),
        clipped: getComputedStyle(value).overflow === "hidden",
        ellipsis: getComputedStyle(value).textOverflow === "ellipsis",
      };
    });
    expect(layout).toEqual({ fits: true, overlaps: false, clipped: true, ellipsis: true });
  }
});

test("MEET production pane renders units, details and sends filters", async ({ page }) => {
  await seedBrowserShellLocalStorage(page);
  await stubSidecar(page, { functions: { MEET: fixture() } });
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/fn/MEET")) requests.push(request.url());
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/#/symbol/AAPL/MEET");
  await expect(page.getByLabel("World-event filters")).toBeVisible();
  await expect(page.getByLabel("MEET data quality")).toContainText("5 excluded by result limit");
  await page.getByRole("button", { name: "Calendar", exact: true }).first().click();
  await expect(page.getByText("3.9%", { exact: true }).first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText("3.9%%");
  await page.getByLabel("Data filter", { exact: true }).selectOption("with_actual");
  await expect.poll(() => requests.some(url => new URL(url).searchParams.get("data_filter") === "with_actual")).toBe(true);
  await page.getByRole("button", { name: "Wire", exact: true }).click();
  await page.getByRole("button", { name: /Bitcoin ETF inflows rise/ }).click();
  await expect(page.getByRole("region", { name: "Event detail" })).toContainText("etf_flow");
  await page.getByLabel("Result limit", { exact: true }).selectOption("1000");
  await expect.poll(() => requests.some(url => new URL(url).searchParams.get("limit") === "1000")).toBe(true);
  expect(errors).toEqual([]);
});
