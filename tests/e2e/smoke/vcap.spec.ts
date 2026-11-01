import { expect, test, type Page } from "@playwright/test";
import process from "node:process";
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
  const positions = await chart.locator("rect").evaluateAll((nodes) =>
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

// This route echoes each applied query; a static fixture cannot catch an axis that
// ignores Apply or a control that silently replaces a persisted publisher/date.
async function stubCalendarQueries(page: Page) {
  const tracker = await stubSidecar(page);
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
  const base = vcapFixture();
  const nsfSources = [
    {
      source_id: "nsf_ncses_2020",
      source_name: "NSF NCSES / PitchBook — 2020 historical report",
      scopes: ["global", "countries"],
      published_at: "2020-01-15",
    },
    {
      source_id: "nsf_ncses",
      source_name: "NSF NCSES / PitchBook — 2026 report",
      scopes: ["global", "countries"],
      published_at: "2026-05-01",
    },
  ].map((source) => ({
    ...source,
    available_geographies: ["WORLD", "USA"],
    access_mode: "automatic",
    access_status: "available",
  }));
  const requests: Record<string, unknown>[] = [];
  await page.route("**/api/fn/VCAP", (route) => {
    const query = route.request().postDataJSON() as typeof base.data.query;
    requests.push(query);
    const global = query.scope === "global";
    const selected = nsfSources.filter((source) =>
      query.source_ids.includes(source.source_id),
    );
    const nsfRows = selected.map((source) => ({
      ...base.data.rows[0],
      ...source,
      scope: query.scope,
      geography: global ? "WORLD" : "USA",
      period: source.source_id === "nsf_ncses_2020" ? "1999" : "2024",
      value:
        source.source_id === "nsf_ncses_2020"
          ? global
            ? 24_548_000_000
            : 22_545_000_000
          : 354_144_000_000,
    }));
    const rows = [...(global ? [] : base.data.rows), ...nsfRows].filter(
      (row) => +row.period >= query.start_year && +row.period <= query.end_year,
    );
    const allSources = [...base.data.sources, ...nsfSources];
    const series = query.source_ids.flatMap((source_id) =>
      query.geographies.map((geography) => {
        const source = allSources.find(
          (source) => source.source_id === source_id,
        );
        const start =
          source_id === "nsf_ncses_2020"
            ? 1999
            : source_id === "nsf_ncses"
              ? 2013
              : 2007;
        const end =
          source_id === "nsf_ncses_2020"
            ? 2018
            : source_id === "nsf_ncses"
              ? 2024
              : 2025;
        const supported =
          source_id === "oecd" || source_id.startsWith("nsf_ncses");
        return {
          source_id,
          source_name: source?.source_name ?? source_id,
          geography,
          first_period: supported ? String(start) : null,
          last_period: supported ? String(end) : null,
          periods: supported
            ? Array.from({ length: end - start + 1 }, (_, i) =>
                String(start + i),
              )
            : [],
          published_at: source?.published_at ?? null,
        };
      }),
    );
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...base,
        data: {
          ...base.data,
          query,
          rows,
          sources: allSources,
          coverage: {
            requested_start: String(query.start_year),
            requested_end: String(query.end_year),
            series,
          },
        },
      }),
    });
  });
  return { tracker, requests };
}

test("persisted 1999 country selection changes applied calendar and keeps its OECD source until the explicit historical action", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 960, height: 800 });
  await seedBrowserShellLocalStorage(page);
  await page.addInitScript(
    (query) => localStorage.setItem("showme.vcap.query", JSON.stringify(query)),
    { ...vcapFixture().data.query, start_year: 1999, end_year: 2026 },
  );
  const { tracker, requests } = await stubCalendarQueries(page);
  await page.goto("/#/fn/VCAP");
  const pane = page.getByTestId("vcap-pane");
  const chart = pane.getByTestId("vcap-chart");
  await expect(chart).toContainText("1999");
  await expect(chart).toContainText("2026");
  await expect(pane.getByTestId("vcap-coverage-summary")).toContainText(
    "No data before 2007",
  );
  expect(requests[0].source_ids).toEqual(["oecd"]);
  const before = Number(
    await chart.locator('rect[data-period="2025"]').getAttribute("x"),
  );
  await pane.getByLabel("Start year", { exact: true }).fill("2007");
  await expect(chart).toContainText("1999");
  expect(
    Number(await chart.locator('rect[data-period="2025"]').getAttribute("x")),
  ).toBe(before);
  await pane.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(chart).toContainText("2007");
  await expect(chart).not.toContainText("1999");
  expect(
    Number(await chart.locator('rect[data-period="2025"]').getAttribute("x")),
  ).toBeLessThan(before);
  await pane.getByLabel("Start year", { exact: true }).fill("1999");
  await pane.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(chart).toContainText("1999");
  await pane.getByRole("button", { name: "Year table", exact: true }).click();
  const table = pane.getByTestId("vcap-year-table");
  await expect(
    table.getByRole("rowheader", { name: "1999", exact: true }),
  ).toBeVisible();
  await expect(
    table.getByRole("rowheader", { name: "1999", exact: true }).locator(".."),
  ).toContainText("Unavailable before 2007");
  await expect(
    table.getByRole("rowheader", { name: "2022", exact: true }).locator(".."),
  ).toContainText("Missing amount");
  await expect(
    table.getByRole("rowheader", { name: "2023", exact: true }).locator(".."),
  ).toContainText("0 USD");
  await expect(
    table.getByRole("rowheader", { name: "2024", exact: true }).locator(".."),
  ).toContainText("Not reported");
  await page.screenshot({
    path: testInfo.outputPath("persisted-country-1999.png"),
    fullPage: true,
  });
  await pane
    .getByRole("button", { name: "Add historical 1999–2018 source" })
    .click();
  await expect(pane.getByLabel("Start year", { exact: true })).toHaveValue(
    "1999",
  );
  await expect
    .poll(() => requests.at(-1)?.source_ids)
    .toEqual(["nsf_ncses_2020", "oecd"]);
  expect(requests.at(-1)?.geographies).toEqual(["USA"]);
  await expect(
    table.getByRole("rowheader", { name: "1999", exact: true }).locator(".."),
  ).toContainText("22545000000 USD");
  tracker.assertNoCriticalFallthroughs();
});

test("saved global legacy selection loads the published annual preset and real 1999/2024 edition columns", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 960, height: 800 });
  await seedBrowserShellLocalStorage(page);
  await page.addInitScript(
    (query) => localStorage.setItem("showme.vcap.query", JSON.stringify(query)),
    {
      ...vcapFixture().data.query,
      scope: "global",
      source_ids: ["kpmg_pitchbook", "crunchbase"],
      geographies: ["WORLD"],
      frequency: "quarterly",
      start_year: 1999,
      end_year: 2026,
    },
  );
  const { tracker, requests } = await stubCalendarQueries(page);
  await page.goto("/#/fn/VCAP");
  const pane = page.getByTestId("vcap-pane");
  await expect(
    pane.getByRole("button", { name: "Load published global data" }),
  ).toBeEnabled();
  expect(requests[0].source_ids).toEqual(["crunchbase", "kpmg_pitchbook"]);
  await pane
    .getByRole("button", { name: "Load published global data" })
    .click();
  const table = pane.getByTestId("vcap-year-table");
  await expect(table).toContainText("2020 historical report");
  await expect(table).toContainText("2026 report");
  await expect(
    table.getByRole("rowheader", { name: "1999", exact: true }).locator(".."),
  ).toContainText("24548000000 USD");
  await expect(
    table.getByRole("rowheader", { name: "2024", exact: true }).locator(".."),
  ).toContainText("354144000000 USD");
  await expect(
    table.getByRole("rowheader", { name: "2026", exact: true }).locator(".."),
  ).toContainText("Unavailable after 2024");
  await expect(table.getByRole("columnheader")).toHaveCount(3);
  await expect(pane.getByLabel("Frequency")).toHaveValue("annual");
  await expect(pane.getByLabel("Start year", { exact: true })).toHaveValue(
    "1999",
  );
  for (const width of [1440, 960, 640]) {
    await page.setViewportSize({ width, height: 800 });
    expect(
      await pane.evaluate((node) => {
        const body = node.querySelector(".vcap-body") as HTMLElement;
        return body.scrollWidth <= body.clientWidth + 1;
      }),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 960, height: 800 });
  await page.screenshot({
    path: testInfo.outputPath("global-year-table-1999.png"),
    fullPage: true,
  });
  await table.screenshot({
    path: testInfo.outputPath("global-table-detail.png"),
  });
  tracker.assertNoCriticalFallthroughs();
});
