export function ImportHelp() {
  return (
    <details className="vcap-details">
      <summary>Import format and missing values</summary>
      <p>
        Start with a template and fill every source field: publisher, HTTPS research
        reference, publication date, methodology and its version, geography basis, date
        basis and sector. JSON contains one dataset with an observations array; an outer
        dataset wrapper is also accepted.
      </p>
      <p>
        CSV uses one observation per row. Repeat identical source metadata in every row.
        Period is YYYY or YYYY-Q1 through YYYY-Q4. Scope is countries, global, turkey or
        crypto. Geography is an ISO3 code or an explicit WORLD / TUR_DIASPORA total. Metric
        is investment, deals or fundraising; stage is total, seed, early or late; unit is
        USD, PERCENT_GDP or COUNT. Status is reported, provisional or missing.
      </p>
      <p>
        A missing value is null in JSON or blank / null in CSV and requires missing status.
        Zero is a numeric observation. Use financing_scope=all_raises only for broad crypto
        financing including token sales; otherwise use vc. Quotes preserve commas and
        newlines in CSV.
      </p>
      <p>
        Importing a complete source release selects that coverage. Earlier releases remain
        accessible through the release selector. The server checks every measurement before
        saving the release.
      </p>
    </details>
  );
}
