import { expect, test } from "@playwright/test";
import { FUNCTION_INDEX_FIXTURE } from "./_fixtures/sidecar-fixtures";
import {
  seedBrowserShellLocalStorage,
  stubSidecar,
} from "./_fixtures/stub-sidecar";

// CI uses its installed Chromium; developers can opt into a local supported channel.
test.use({ channel: process.env.SHOWME_E2E_BROWSER_CHANNEL });

function vcapFixture() {
  const snapshot = "a".repeat(64);
  const query = {
    scope: "countries",
    source_ids: ["oecd"],
    geographies: ["USA"],
    metric: "investment",
    stage: "total",
    frequency: "annual",
    unit: "USD",
    start_year: 2007,
    end_year: new Date().getFullYear(),
    financing_scope: "vc",
    vintage: null,
    refresh: false,
  };
  const rows = [
    { period: "2021", value: 100_000_000, status: "reported" },
    { period: "2022", value: null, status: "missing" },
    { period: "2023", value: 0, status: "reported" },
    // No 2024 observation: its empty time interval must remain present.
    { period: "2025", value: 200_000_000, status: "reported" },
  ].map((row) => ({
    ...row,
    source_id: "oecd",
    source_name: "OECD fixture",
    scope: "countries",
    geography: "USA",
    period_start: `${row.period}-01-01`,
    period_end: `${row.period}-12-31`,
    frequency: "annual",
    metric: "investment",
    stage: "total",
    unit: "USD",
    published_at: null,
    retrieved_at: "2026-10-31T10:00:00Z",
    snapshot_id: snapshot,
    vintage: snapshot,
    methodology_version: "fixture-v1",
    sector: "all",
    geography_basis: "company_hq",
    date_basis: "source_defined",
    financing_scope: "vc",
  }));
  return {
    code: "VCAP",
    instrument: null,
    status: "ok",
    fetched_at: "2026-10-31T10:00:00Z",
    sources: ["reference_vcap:oecd"],
    warnings: [],
    elapsed_ms: 1,
    metadata: {
      data_mode: "official",
      cached: true,
      stale: false,
      live: false,
    },
    data: {
      status: "ok",
      query,
      rows,
      sources: [
        {
          source_id: "oecd",
          source_name: "OECD fixture",
          scopes: ["countries"],
          available_scopes: ["countries"],
          available_geographies: ["USA"],
          access_mode: "automatic",
          access_status: "available",
          access_notes:
            "Deterministic browser fixture; this is not production source data.",
          source_url: "https://www.oecd.org/",
          terms_url: "https://www.oecd.org/en/about/terms-conditions.html",
        },
      ],
      snapshots: [
        {
          snapshot_id: snapshot,
          source_id: "oecd",
          source_name: "OECD fixture",
          published_at: null,
          retrieved_at: "2026-10-31T10:00:00Z",
          observation_count: 4,
        },
      ],
      comparison: { comparable_pairs: [], blocked_pairs: [] },
      methodology:
        "Source-specific fixture observations. Missing is distinct from zero.",
    },
  };
}

test("VCAP filters stay inside the pane at 960px and the chart preserves missing versus zero", async ({
  page,
}) => {
  await page.setViewportSize({ width: 960, height: 800 });
  await seedBrowserShellLocalStorage(page);
  const tracker = await stubSidecar(page, {
    functions: { VCAP: vcapFixture() },
  });
  await page.route("**/api/function-index", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        ...FUNCTION_INDEX_FIXTURE,
        { code: "VCAP", name: "Venture Capital Research", category: "macro" },
      ]),
    }),
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/#/fn/VCAP");
  const pane = page.getByTestId("vcap-pane");
  await expect(pane.getByTestId("vcap-chart").locator("rect")).toHaveCount(3);
  await expect(
    pane.getByText("Data through 2025", { exact: true }),
  ).toBeVisible();
  for (const width of [1440, 960, 640]) {
    await page.setViewportSize({ width, height: 800 });
    const layout = await pane.evaluate((node) => {
      const paneBounds = node.getBoundingClientRect();
      const body = node.querySelector(".vcap-body") as HTMLElement;
      const controls = Array.from(
        node.querySelectorAll(
          ".vcap-filter-grid input, .vcap-filter-grid select, .vcap-filter-grid button",
        ),
      );
      return {
        bodyClientWidth: body.clientWidth,
        bodyScrollWidth: body.scrollWidth,
        filters: controls.map((control) => {
          const bounds = control.getBoundingClientRect();
          return {
            name:
              control.closest("label")?.textContent?.trim() ??
              control.textContent?.trim(),
            inside:
              bounds.left >= paneBounds.left &&
              bounds.right <= paneBounds.right + 1,
            width: bounds.width,
          };
        }),
        regionsInside: [
          ".vcap-controls",
          ".vcap-source-picker",
          ".vcap-chart",
          "[data-testid=vcap-observation-table]",
        ].every((selector) => {
          const bounds = node.querySelector(selector)!.getBoundingClientRect();
          return (
            bounds.left >= paneBounds.left &&
            bounds.right <= paneBounds.right + 1
          );
        }),
      };
    });
    expect(layout.filters.length).toBeGreaterThanOrEqual(9);
    for (const filter of layout.filters)
      expect(
        filter.inside && filter.width > 0,
        `${filter.name} clipped at viewport ${width}px`,
      ).toBe(true);
    expect(
      layout.regionsInside,
      `VCAP content regions overflow at ${width}px`,
    ).toBe(true);
    expect(layout.bodyScrollWidth).toBeLessThanOrEqual(
      layout.bodyClientWidth + 1,
    );
  }
  const chart = pane.getByTestId("vcap-chart");
  const zero = chart.locator('rect[data-period="2023"]');
  await expect(zero).toHaveAttribute("data-value", "0");
  await expect(zero).toHaveAttribute("height", "1");
  await expect(zero.locator("title")).toContainText("0 USD; reported");
  await expect(chart.locator("path title")).toContainText(
    "2022; OECD fixture; USA; total; Missing; missing",
  );
  const positions = await chart
    .locator("rect")
    .evaluateAll((nodes) =>
      nodes.map((node) => ({
        period: node.getAttribute("data-period"),
        x: Number(node.getAttribute("x")),
      })),
    );
  expect(
    (positions[2].x - positions[1].x) / (positions[1].x - positions[0].x),
  ).toBeCloseTo(1, 1);
  await expect(pane.getByTestId("vcap-observation-table")).toContainText(
    "Missing",
  );
  expect(errors).toEqual([]);
  tracker.assertNoCriticalFallthroughs();
});
