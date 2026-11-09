import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { VCAPPane } from "./VCAP";
import { defaultQuery, type Observation, type Payload, type Source } from "./vcap/types";
import { CSV_COLUMNS } from "./vcap/imports";

const mocks = vi.hoisted(() => ({
  useFunction: vi.fn(),
  runFunction: vi.fn(),
  download: vi.fn(),
}));
vi.mock("@/lib/useFunction", () => ({ useFunction: mocks.useFunction }));
vi.mock("@/lib/functions", () => ({ runFunction: mocks.runFunction }));
vi.mock("./vcap/exports", async (original) => ({
  ...(await original<typeof import("./vcap/exports")>()),
  download: mocks.download,
}));
const snapshot = "a".repeat(64);
const sources: Source[] = [
  {
    source_id: "oecd",
    source_name: "OECD",
    scopes: ["countries"],
    available_geographies: ["USA", "GBR"],
    access_mode: "automatic",
    access_status: "available",
    source_url: "https://oecd.org/research",
    terms_url: "https://oecd.org/terms",
    access_notes: "Annual investment; observed country coverage only.",
  },
  {
    source_id: "kpmg_pitchbook",
    source_name: "KPMG / PitchBook",
    scopes: ["global", "countries"],
    access_mode: "import",
    access_status: "import_required",
    access_notes: "Import owned or licensed data.",
  },
  {
    source_id: "crunchbase",
    source_name: "Crunchbase",
    scopes: ["global", "countries", "crypto"],
    access_mode: "import",
    access_status: "import_required",
  },
  {
    source_id: "startups_watch",
    source_name: "startups.watch",
    scopes: ["turkey"],
    access_mode: "import",
    access_status: "import_required",
  },
  {
    source_id: "defillama",
    source_name: "DefiLlama",
    scopes: ["crypto"],
    access_mode: "optional_key",
    access_status: "not_configured",
    access_notes: "Configure optional connector or import data.",
    validation_summary: { input_records: 10, accepted_records: 8, future_records: 2 },
  },
  {
    source_id: "nsf_ncses_2020",
    source_name: "NSF NCSES / PitchBook — 2020 historical report",
    scopes: ["global", "countries"],
    access_mode: "automatic",
    access_status: "available",
    published_at: "2020-01-15",
  },
  {
    source_id: "nsf_ncses",
    source_name: "NSF NCSES / PitchBook — 2026 report",
    scopes: ["global", "countries"],
    access_mode: "automatic",
    access_status: "available",
    published_at: "2026-05-01",
  },
  {
    source_id: "galaxy",
    source_name: "Galaxy",
    scopes: ["crypto"],
    access_mode: "import",
    access_status: "import_required",
  },
];
const row: Observation = {
  source_id: "oecd",
  source_name: "OECD",
  scope: "countries",
  geography: "USA",
  period: "2025",
  period_start: "2025-01-01",
  period_end: "2025-12-31",
  frequency: "annual",
  metric: "investment",
  stage: "total",
  unit: "USD",
  value: 131680318838.1091,
  status: "reported",
  published_at: null,
  retrieved_at: "2026-10-31T10:00:00Z",
  snapshot_id: snapshot,
  methodology_version: "v1",
};
function payload(overrides: Partial<Payload> = {}): Payload {
  return {
    status: "ok",
    query: defaultQuery(),
    rows: [row],
    sources,
    snapshots: [
      {
        snapshot_id: snapshot,
        source_id: "oecd",
        source_name: "OECD",
        published_at: null,
        retrieved_at: row.retrieved_at!,
        observation_count: 1,
      },
    ],
    comparison: { blocked_pairs: [], comparable_pairs: [] },
    ...overrides,
  };
}
let result: {
  state: string;
  data?: { data: Payload; metadata: Record<string, unknown> };
  error?: Error;
  refetch: ReturnType<typeof vi.fn>;
};
function lastParams() {
  return mocks.useFunction.mock.calls.at(-1)?.[0].params;
}
const dataset = {
  schema_version: 1,
  source_id: "custom_owned",
  source_name: "My source",
  source_url: "https://example.org/report",
  published_at: "2026-10-01",
  methodology: "Company HQ announced investments",
  methodology_version: "v1",
  geography_basis: "company_hq",
  date_basis: "announced",
  sector: "all",
  observations: [
    {
      scope: "countries",
      geography: "GBR",
      period: "2024",
      metric: "investment",
      stage: "total",
      unit: "USD",
      value: 42,
      status: "reported",
    },
  ],
};
function chooseFile(text: string, name: string, size = text.length) {
  fireEvent.change(screen.getByLabelText("Import VCAP dataset file"), {
    target: { files: [{ name, size, text: () => Promise.resolve(text) }] },
  });
}
beforeEach(() => {
  localStorage.clear();
  mocks.useFunction.mockReset();
  mocks.runFunction.mockReset();
  mocks.download.mockReset();
  result = {
    state: "ok",
    data: { data: payload(), metadata: { data_mode: "official", cached: true } },
    refetch: vi.fn(),
  };
  mocks.useFunction.mockImplementation(() => result);
});
afterEach(cleanup);

describe("VCAP measurement controls", () => {
  it("defaults to useful OECD country research; batches free-text/source controls behind Apply", () => {
    render(<VCAPPane code="VCAP" />);
    expect(lastParams()).toMatchObject({
      action: "query",
      ...defaultQuery(),
      refresh: false,
    });
    fireEvent.change(screen.getByLabelText("Geographies"), {
      target: { value: "USA, GBR" },
    });
    fireEvent.change(screen.getByLabelText("Start year"), { target: { value: "2020" } });
    fireEvent.click(screen.getByLabelText("Crunchbase"));
    expect(lastParams().geographies).toEqual(["USA"]);
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(lastParams()).toMatchObject({
      source_ids: ["crunchbase", "oecd"],
      geographies: ["GBR", "USA"],
      start_year: 2020,
    });
    expect(screen.getByTestId("vcap-observation-table")).toHaveTextContent(
      "131680318838.1091 USD",
    );
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeDisabled();
    expect(screen.getByText(/Updating selection. Displayed data:/)).toHaveTextContent(
      "USA · annual",
    );
  });
  it.each([
    ["Global", "global", ["nsf_ncses_2020", "nsf_ncses"], "WORLD", "annual"],
    ["Turkey", "turkey", ["startups_watch"], "TUR", "quarterly"],
    ["Crypto & Web3", "crypto", ["defillama", "galaxy"], "WORLD", "quarterly"],
  ])(
    "switches %s with coherent source/geography/frequency defaults",
    (label, scope, ids, geo, frequency) => {
      render(<VCAPPane code="VCAP" />);
      fireEvent.click(screen.getByRole("button", { name: String(label) }));
      expect(lastParams()).toMatchObject({
        scope,
        source_ids: ids,
        geographies: [geo],
        frequency,
        unit: "USD",
        financing_scope: "vc",
      });
    },
  );
  it("requires COUNT for deals and explains broad crypto financing", () => {
    render(<VCAPPane code="VCAP" />);
    fireEvent.change(screen.getByLabelText("Metric"), { target: { value: "deals" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(lastParams()).toMatchObject({ metric: "deals", unit: "COUNT" });
    fireEvent.click(screen.getByRole("button", { name: "Crypto & Web3" }));
    fireEvent.change(screen.getByLabelText("Financing scope"), {
      target: { value: "all_raises" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(lastParams().financing_scope).toBe("all_raises");
    expect(screen.getByText(/includes token sales, ICOs/)).toBeInTheDocument();
  });
  it("rejects invalid years/geographies before changing fetch parameters", () => {
    render(<VCAPPane code="VCAP" />);
    fireEvent.change(screen.getByLabelText("Geographies"), { target: { value: "WORLD" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Geographies must match");
    expect(lastParams().geographies).toEqual(["USA"]);
    fireEvent.change(screen.getByLabelText("Geographies"), { target: { value: "USA" } });
    fireEvent.change(screen.getByLabelText("Start year"), { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter years");
    expect(lastParams().start_year).toBe(2007);
  });
  it("pins and clears a saved release, and loads versions through the existing service", async () => {
    mocks.runFunction.mockResolvedValue({ data: payload() });
    render(<VCAPPane code="VCAP" />);
    fireEvent.change(screen.getByLabelText("Release"), { target: { value: snapshot } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(lastParams().vintage).toBe(snapshot);
    fireEvent.change(screen.getByLabelText("Release"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(lastParams().vintage).toBeNull();
    fireEvent.click(screen.getByText("Release history and methodology"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh release history" }));
    await waitFor(() =>
      expect(mocks.runFunction).toHaveBeenCalledWith("VCAP", {
        params: { action: "versions" },
      }),
    );
  });
});
describe("VCAP evidence and states", () => {
  it("keeps the chart on applied dates until Apply, then expands to 1999 even with unchanged source rows", () => {
    const component = render(<VCAPPane code="VCAP" />);
    const x = () =>
      Number(screen.getByTestId("vcap-chart").querySelector("rect")!.getAttribute("x"));
    const old = x();
    fireEvent.change(screen.getByLabelText("Start year"), { target: { value: "1999" } });
    expect(screen.getByTestId("vcap-chart")).not.toHaveTextContent("1999");
    expect(x()).toBe(old);
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(lastParams().start_year).toBe(1999);
    // The old payload remains honestly labelled until the response arrives.
    expect(x()).toBe(old);
    result.data!.data = payload({ query: { ...defaultQuery(), start_year: 1999 } });
    component.rerender(<VCAPPane code="VCAP" />);
    expect(screen.getByTestId("vcap-chart")).toHaveTextContent("1999");
    expect(x()).toBeGreaterThan(old);
    fireEvent.click(screen.getByRole("button", { name: "Year table" }));
    expect(
      within(screen.getByTestId("vcap-year-table")).getByRole("rowheader", {
        name: "1999",
      }),
    ).toBeInTheDocument();
  });
  it("shows authoritative 2007 source boundaries and an explicit historical action for an empty 1999 request", () => {
    const query = {
      ...defaultQuery(),
      source_ids: ["oecd", "crunchbase"],
      geographies: ["GBR", "USA"],
      start_year: 1999,
      end_year: 2000,
      vintage: snapshot,
    };
    localStorage.setItem("showme.vcap.query", JSON.stringify(query));
    result.data!.data = payload({
      query,
      rows: [],
      coverage: {
        requested_start: "1999",
        requested_end: "2000",
        series: query.geographies.map((geography) => ({
          source_id: "oecd",
          source_name: "OECD",
          geography,
          first_period: "2007",
          last_period: "2025",
          periods: ["2007", "2025"],
        })),
      },
    });
    render(<VCAPPane code="VCAP" />);
    expect(lastParams().source_ids).toEqual(["crunchbase", "oecd"]);
    expect(screen.getByTestId("vcap-coverage-summary")).toHaveTextContent(
      "No data before 2007",
    );
    expect(screen.getByTestId("vcap-chart")).toHaveTextContent("1999");
    expect(screen.getByTestId("vcap-chart").querySelectorAll("rect")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Year table" }));
    expect(screen.getByTestId("vcap-year-table")).toHaveTextContent(
      "Unavailable before 2007",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Add historical 1999–2018 source" }),
    );
    expect(lastParams()).toMatchObject({
      source_ids: ["crunchbase", "nsf_ncses_2020", "oecd"],
      geographies: ["GBR", "USA"],
      start_year: 1999,
      end_year: 2000,
      vintage: null,
    });
  });
  it.each([
    { frequency: "quarterly" },
    { metric: "deals", unit: "COUNT" },
    { stage: "seed" },
    { unit: "PERCENT_GDP" },
  ])("offers no historical action for an incompatible measurement %j", (changes) => {
    const query = { ...defaultQuery(), start_year: 1999, ...changes };
    localStorage.setItem("showme.vcap.query", JSON.stringify(query));
    render(<VCAPPane code="VCAP" />);
    expect(
      screen.queryByRole("button", { name: "Add historical 1999–2018 source" }),
    ).not.toBeInTheDocument();
  });
  it("preserves applied years across scope changes and discards unsubmitted draft years", () => {
    localStorage.setItem(
      "showme.vcap.query",
      JSON.stringify({ ...defaultQuery(), start_year: 1999, end_year: 2024 }),
    );
    render(<VCAPPane code="VCAP" />);
    fireEvent.change(screen.getByLabelText("Start year"), { target: { value: "1980" } });
    for (const scope of ["Global", "Countries", "Turkey", "Crypto & Web3"]) {
      fireEvent.click(screen.getByRole("button", { name: scope }));
      expect(lastParams()).toMatchObject({ start_year: 1999, end_year: 2024 });
    }
  });
  it("opens global research as separate NSF edition columns with a real 1999 amount and preserves actual exports", () => {
    const query = defaultQuery("global");
    localStorage.setItem("showme.vcap.query", JSON.stringify(query));
    const nsfRows = [
      {
        ...row,
        scope: "global" as const,
        geography: "WORLD",
        period: "1999",
        source_id: "nsf_ncses_2020",
        source_name: sources[5].source_name,
        value: 24_548_000_000,
        published_at: "2020-01-15",
        underlying_access_date: "2019-09-21",
        publication_id: "NSB-2020-4",
        publication_table: "S8-62",
        global_total_basis: "Published Global total row",
      },
      {
        ...row,
        scope: "global" as const,
        geography: "WORLD",
        period: "2024",
        source_id: "nsf_ncses",
        source_name: sources[6].source_name,
        value: 354_144_000_000,
        published_at: "2026-05-01",
      },
    ];
    result.data!.data = payload({
      query,
      rows: nsfRows,
      coverage: {
        requested_start: "1999",
        requested_end: String(query.end_year),
        series: [
          {
            source_id: "nsf_ncses_2020",
            source_name: nsfRows[0].source_name,
            geography: "WORLD",
            first_period: "1999",
            last_period: "2018",
            periods: ["1999", "2018"],
            published_at: "2020-01-15",
          },
          {
            source_id: "nsf_ncses",
            source_name: nsfRows[1].source_name,
            geography: "WORLD",
            first_period: "2013",
            last_period: "2024",
            periods: ["2013", "2024"],
            published_at: "2026-05-01",
          },
        ],
      },
    });
    render(<VCAPPane code="VCAP" />);
    const table = screen.getByTestId("vcap-year-table");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(3);
    expect(table).toHaveTextContent("2020 historical report");
    expect(table).toHaveTextContent("2026 report");
    expect(table).toHaveTextContent("24548000000 USD");
    expect(table).toHaveTextContent("354144000000 USD");
    expect(table).toHaveTextContent("Unavailable after 2024");
    expect(within(table).getAllByRole("rowheader")).toHaveLength(query.end_year - 1999 + 1);
    expect(screen.queryByTestId("vcap-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("vcap-observation-table")).toHaveTextContent(
      "Underlying data accessed 2019-09-21",
    );
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    const exported = JSON.parse(mocks.download.mock.calls[0][0]);
    expect(exported.rows).toHaveLength(2);
    expect(exported.rows[0]).toMatchObject({
      underlying_access_date: "2019-09-21",
      publication_id: "NSB-2020-4",
      publication_table: "S8-62",
      global_total_basis: "Published Global total row",
    });
    expect(exported.coverage.series).toHaveLength(2);
  });
  it("distinguishes reported zero, explicit missing amount, absent year and outside coverage", () => {
    const query = { ...defaultQuery(), start_year: 2020, end_year: 2026 };
    localStorage.setItem("showme.vcap.query", JSON.stringify(query));
    result.data!.data = payload({
      query,
      rows: [
        { ...row, period: "2021", value: 0 },
        { ...row, period: "2022", value: null, status: "missing" },
        row,
      ],
      coverage: {
        requested_start: "2020",
        requested_end: "2026",
        series: [
          {
            source_id: "oecd",
            source_name: "OECD",
            geography: "USA",
            first_period: "2021",
            last_period: "2025",
            periods: ["2021", "2022", "2025"],
          },
        ],
      },
    });
    render(<VCAPPane code="VCAP" />);
    fireEvent.click(screen.getByRole("button", { name: "Year table" }));
    const table = screen.getByTestId("vcap-year-table");
    for (const [period, text] of [
      ["2020", "Unavailable before 2021"],
      ["2021", "0 USD"],
      ["2022", "Missing amount"],
      ["2023", "Not reported"],
      ["2026", "Unavailable after 2025"],
    ]) {
      expect(
        within(table).getByRole("rowheader", { name: period }).closest("tr"),
      ).toHaveTextContent(text);
    }
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(mocks.download.mock.calls[0][0].split("\r\n")).toHaveLength(4);
  });
  it("offers an explicit published global preset for an empty legacy saved selection, preserving dates", () => {
    const query = {
      ...defaultQuery("global"),
      source_ids: ["kpmg_pitchbook", "crunchbase"],
      frequency: "quarterly" as const,
      start_year: 1999,
      end_year: 2024,
    };
    localStorage.setItem("showme.vcap.query", JSON.stringify(query));
    result.data!.data = payload({ query, rows: [], status: "empty" });
    render(<VCAPPane code="VCAP" />);
    expect(lastParams().source_ids).toEqual(["crunchbase", "kpmg_pitchbook"]);
    fireEvent.click(screen.getByRole("button", { name: "Load published global data" }));
    expect(lastParams()).toMatchObject({
      source_ids: ["nsf_ncses_2020", "nsf_ncses"],
      start_year: 1999,
      end_year: 2024,
      frequency: "annual",
    });
    expect(lastParams().vintage).toBeUndefined();
  });
  it("bounds long quarterly windows and wide series selections with independent paging", () => {
    const geographies = ["USA", "GBR", "DEU", "FRA", "IND", "JPN", "CAN"];
    const query = {
      ...defaultQuery(),
      start_year: 1900,
      frequency: "quarterly" as const,
      geographies,
    };
    localStorage.setItem("showme.vcap.query", JSON.stringify(query));
    result.data!.data = payload({ query, rows: [] });
    render(<VCAPPane code="VCAP" />);
    fireEvent.click(screen.getByRole("button", { name: "Year table" }));
    const table = screen.getByTestId("vcap-year-table");
    expect(within(table).getAllByRole("rowheader")).toHaveLength(32);
    expect(within(table).getAllByRole("columnheader")).toHaveLength(7);
    expect(table).toHaveTextContent("1900-Q1");
    fireEvent.click(screen.getByRole("button", { name: "Next periods" }));
    expect(table).toHaveTextContent("1908-Q1");
    fireEvent.click(screen.getByRole("button", { name: "Next series" }));
    expect(within(table).getAllByRole("columnheader")).toHaveLength(2);
    expect(table).toHaveTextContent("CAN");
  });
  it("does not warn about unavailable time before Q1 of the same applied start year", () => {
    const query = {
      ...defaultQuery(),
      start_year: 2025,
      end_year: 2025,
      frequency: "quarterly" as const,
    };
    localStorage.setItem("showme.vcap.query", JSON.stringify(query));
    result.data!.data = payload({
      query,
      rows: [],
      coverage: {
        requested_start: "2025-Q1",
        requested_end: "2025-Q4",
        series: [
          {
            source_id: "oecd",
            source_name: "OECD",
            geography: "USA",
            first_period: "2025-Q1",
            last_period: "2025-Q4",
            periods: ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"],
          },
        ],
      },
    });
    render(<VCAPPane code="VCAP" />);
    expect(screen.getByTestId("vcap-coverage-summary")).not.toHaveTextContent(
      "No data before",
    );
    expect(screen.getByTestId("vcap-coverage-summary")).not.toHaveTextContent(
      "No data after",
    );
  });
  it("distinguishes the actual latest measurement from the requested year range", () => {
    render(<VCAPPane code="VCAP" />);
    expect(screen.getByText("Data through 2025")).toBeInTheDocument();
    expect(screen.getAllByText(/2007–2026/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Refresh sources" }));
    expect(lastParams().refresh).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Refresh sources" }));
    expect(result.refetch).toHaveBeenCalledOnce();
  });
  it("keeps source references and next actions available without rows", () => {
    result.data!.data = payload({
      rows: [],
      status: "empty",
      reason: "Import a complete release.",
    });
    render(<VCAPPane code="VCAP" />);
    expect(screen.getByText("No matching observations")).toBeInTheDocument();
    expect(screen.getByTestId("vcap-sources")).toHaveTextContent("import required");
    expect(screen.getByRole("link", { name: "Research / methodology" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(screen.queryByText(/^live$/i)).not.toBeInTheDocument();
  });
  it("handles an empty catalogue, loading and errors honestly", () => {
    result.data!.data = payload({ rows: [], sources: [] });
    const view = render(<VCAPPane code="VCAP" />);
    expect(screen.getByText(/No source catalogue is available/)).toBeInTheDocument();
    result = { state: "loading", refetch: vi.fn() };
    view.rerender(<VCAPPane code="VCAP" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading source catalogue");
    result = { state: "error", error: new Error("Provider unreachable"), refetch: vi.fn() };
    view.rerender(<VCAPPane code="VCAP" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Provider unreachable");
  });
  it("discloses stale cache, provisional/partial cutoffs and source validation outside rows", () => {
    result.data!.metadata = { stale: true, cached: true, data_mode: "official" };
    result.data!.data = payload({
      rows: [
        {
          ...row,
          status: "provisional",
          is_partial: true,
          coverage_cutoff: "2026-10-31T10:00:00Z",
          coverage_note: "Year to date",
        },
      ],
      cache_note: "Cached release is stale after provider failure.",
    });
    render(<VCAPPane code="VCAP" />);
    expect(screen.getByText("Stale cached release")).toBeInTheDocument();
    expect(screen.getByTestId("vcap-observation-table")).toHaveTextContent(
      "provisional · partial period",
    );
    expect(screen.getByTestId("vcap-observation-table")).toHaveTextContent(
      "Coverage through 2026-10-31",
    );
    expect(screen.getByTestId("vcap-sources")).toHaveTextContent(
      "input records: 10; accepted records: 8; future records: 2",
    );
    expect(screen.getByTestId("vcap-chart").querySelector("rect title")).toHaveTextContent(
      "131680318838.1091 USD; provisional; partial period",
    );
  });
  it("shows blocked comparison reasons without inventing a numeric gap", () => {
    result.data!.data = payload({
      comparison: {
        comparable_pairs: [],
        blocked_pairs: [
          {
            left: "a",
            right: "b",
            reasons: ["Independent methodologies; normalized gap blocked."],
          },
        ],
      },
    });
    render(<VCAPPane code="VCAP" />);
    fireEvent.click(screen.getByText("Comparison eligibility"));
    expect(
      screen.getByText(/Independent methodologies; normalized gap blocked/),
    ).toBeInTheDocument();
  });
  it("bounds table rendering to 100 rows and exports all exact observations", () => {
    result.data!.data = payload({
      rows: Array.from({ length: 205 }, (_, i) => ({ ...row, value: i })),
    });
    render(<VCAPPane code="VCAP" />);
    expect(
      within(screen.getByTestId("vcap-observation-table")).getAllByRole("row"),
    ).toHaveLength(101);
    fireEvent.click(screen.getByRole("button", { name: "Next rows" }));
    expect(screen.getByText(/205 rows · page 2 of 3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(JSON.parse(mocks.download.mock.calls[0][0]).rows).toHaveLength(205);
  });
});
describe("VCAP local import workflow", () => {
  it("selects at most 64 imported geographies and discloses the remaining coverage", async () => {
    const geographies = Array.from(
      { length: 65 },
      (_, i) =>
        `A${String.fromCharCode(65 + Math.floor(i / 26))}${String.fromCharCode(65 + (i % 26))}`,
    );
    const wideDataset = {
      ...dataset,
      observations: geographies.map((geography) => ({
        ...dataset.observations[0],
        geography,
      })),
    };
    mocks.runFunction.mockResolvedValue({ data: payload({ snapshot_id: snapshot }) });
    render(<VCAPPane code="VCAP" />);
    chooseFile(JSON.stringify(wideDataset), "wide.json");
    await waitFor(() =>
      expect(screen.getByText(/Imported release saved locally:/)).toBeInTheDocument(),
    );
    expect(lastParams().geographies).toEqual(geographies.slice(0, 64));
    expect(mocks.runFunction.mock.calls[0][1].params.dataset.observations).toHaveLength(65);
    expect(screen.getByText(/Imported release saved locally:/)).toHaveTextContent(
      "Showing 64 of 65 geographies",
    );
    expect(screen.getByText(/Imported release saved locally:/)).toHaveTextContent(
      "1 additional geography remains available",
    );
    const priorParams = lastParams();
    fireEvent.change(screen.getByLabelText("Geographies"), {
      target: { value: geographies.join(",") },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByRole("alert")).toHaveTextContent("maximum 64");
    expect(lastParams()).toEqual(priorParams);
  });
  it.each(["json", "csv"])(
    "imports %s and selects its exact saved release and measurement",
    async (format) => {
      mocks.runFunction.mockResolvedValue({ data: payload({ snapshot_id: snapshot }) });
      render(<VCAPPane code="VCAP" />);
      const record = { ...dataset, ...dataset.observations[0] } as Record<string, unknown>;
      const text =
        format === "json"
          ? JSON.stringify({ dataset })
          : [
              CSV_COLUMNS.join(","),
              CSV_COLUMNS.map((key) => record[key] ?? "").join(","),
            ].join("\n");
      chooseFile(text, `owned.${format}`);
      await waitFor(() =>
        expect(screen.getByText(/Imported release saved locally:/)).toBeInTheDocument(),
      );
      expect(mocks.runFunction).toHaveBeenCalledWith("VCAP", {
        params: { action: "import", dataset },
      });
      expect(lastParams()).toMatchObject({
        source_ids: ["custom_owned"],
        geographies: ["GBR"],
        start_year: 2024,
        end_year: 2024,
        vintage: snapshot,
      });
    },
  );
  it("rejects invalid files locally, and keeps displayed observations on backend validation failure", async () => {
    render(<VCAPPane code="VCAP" />);
    chooseFile("{", "invalid.json");
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid JSON"),
    );
    expect(mocks.runFunction).not.toHaveBeenCalled();
    chooseFile("", "huge.csv", 2000001);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("no larger than 2 MB"),
    );
    mocks.runFunction.mockResolvedValue({
      data: payload({ status: "input_error", reason: "Duplicate observation" }),
    });
    chooseFile(JSON.stringify(dataset), "owned.json");
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Duplicate observation"),
    );
    expect(lastParams().source_ids).toEqual(["oecd"]);
    expect(screen.getByTestId("vcap-observation-table")).toHaveTextContent(
      "131680318838.1091 USD",
    );
  });
  it("downloads empty source-aware templates with no fabricated values", () => {
    render(<VCAPPane code="VCAP" />);
    fireEvent.click(screen.getByRole("button", { name: "JSON template" }));
    expect(JSON.parse(mocks.download.mock.calls[0][0])).toMatchObject({
      source_id: "oecd",
      source_url: null,
      observations: [],
    });
    fireEvent.click(screen.getByRole("button", { name: "CSV template" }));
    expect(mocks.download.mock.calls[1][0]).toBe(CSV_COLUMNS.join(",") + "\r\n");
  });
});
