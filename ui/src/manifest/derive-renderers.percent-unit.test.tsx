/**
 * UI-6: a manifest percent column declared with unit "ratio" holds a decimal
 * fraction and must render as percent (0.0123 -> 1.23%). Other percent columns
 * are already percent points and keep their value.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { pickRenderer } from "./derive-renderers";

describe("manifest table percent columns honour the declared unit", () => {
  it("scales a ratio-unit percent column by 100 and leaves plain percent columns alone", () => {
    const table = pickRenderer({ table_schema: {} } as never).table;
    expect(table).not.toBeNull();
    const Table = table!;
    const schema = {
      columns: [
        { key: "symbol", label: "Symbol", kind: "text" },
        { key: "dividend_yield", label: "Div Y", kind: "percent", unit: "ratio", format: "%.2f" },
        { key: "change_pct", label: "Chg", kind: "percent", format: "%.2f" },
      ],
      sortable: false,
      filterable: false,
    } as never;
    const payload = { rows: [{ symbol: "AAA", dividend_yield: 0.0123, change_pct: 1.5 }] } as never;

    render(<Table schema={schema} payload={payload} />);

    expect(screen.getByText("1.23%")).toBeInTheDocument();
    expect(screen.getByText("1.50%")).toBeInTheDocument();
    expect(screen.queryByText("0.01%")).toBeNull();
  });
});
