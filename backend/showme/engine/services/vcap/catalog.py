"""Access strategies are explicit; a reference link is not a data license."""
from __future__ import annotations

import copy
import os
from typing import Any


def _source(sid: str, name: str, scopes: list[str], url: str | None, terms: str | None,
            notes: str, mode: str = "import", lineage: str | None = None) -> dict[str, Any]:
    return {"source_id": sid, "source_name": name, "scopes": scopes,
            "available_scopes": scopes, "geographies": [], "available_geographies": [],
            "metrics": ["investment", "deals", "fundraising"],
            "frequencies": ["annual", "quarterly"], "stages": ["total", "seed", "early", "late"],
            "units": ["USD", "COUNT", "PERCENT_GDP"], "access_mode": mode,
            "access_notes": notes, "source_url": url, "terms_url": terms,
            "references": [url, terms], "lineage": lineage or name,
            "status": "import_required", "access_status": "import_required",
            "available_metrics": [], "available_frequencies": [], "available_stages": [],
            "available_units": [], "row_count": 0}


SOURCE_CATALOG = {
    "oecd": _source("oecd", "OECD Venture Capital Investments", ["countries"],
        "https://data-explorer.oecd.org/", "https://www.oecd.org/en/about/terms-conditions.html",
        "Automatic fixed SDMX CSV; annual country investment, USD and percent GDP. Actual observed country coverage only; never a derived world total. Non-production dataflow: consult source methodology and observation flags.", "automatic"),
    "defillama": _source("defillama", "DefiLlama Raises", ["crypto"],
        "https://defillama.com/raises", "https://api-docs.defillama.com/",
        "Optional server-side SHOWME_DEFILLAMA_API_KEY (Pro). Announcement-date raises include equity, tokens and ICOs. API lacks instrument/HQ classification: only explicitly labelled all_raises is automated; strict VC needs classified imports. No geographic inference.", "optional_key"),
    "kpmg_pitchbook": _source("kpmg_pitchbook", "KPMG / PitchBook Venture Pulse", ["global", "countries", "turkey"],
        "https://kpmg.com/xx/en/what-we-do/industries/private-enterprise/venture-pulse.html",
        "https://pitchbook.com/terms-and-conditions",
        "Reference reports use PitchBook lineage. Import a dataset you own or are licensed to use; reports do not imply redistribution rights. No scraping or assumed report API.", lineage="KPMG Venture Pulse / PitchBook"),
    "crunchbase": _source("crunchbase", "Crunchbase", ["global", "countries", "turkey", "crypto"],
        "https://news.crunchbase.com/methodology/", "https://data.crunchbase.com/docs/data-access-terms",
        "Validated local import of owned/licensed data; paid exports/API access are not provisioned here. Methodology and retrospective revisions remain source-specific."),
    "cb_insights": _source("cb_insights", "CB Insights", ["global", "countries", "turkey", "crypto"],
        "https://www.cbinsights.com/research/", "https://www.cbinsights.com/additional-terms/",
        "Reference research and owned/licensed import only; no undocumented report API or restricted report extraction."),
    "dealroom": _source("dealroom", "Dealroom", ["global", "countries", "turkey", "crypto"],
        "https://dealroom.co/", "https://dealroom.co/terms-and-conditions",
        "Import owned/licensed series with explicit company/fund geography and sector boundaries; no assumed open export license."),
    "startups_watch": _source("startups_watch", "startups.watch", ["turkey"],
        "https://startups.watch/faq", "https://startups.watch/tos",
        "Turkey ecosystem reference; validated owned/licensed imports only. Chamber-of-commerce validation and retrospective revisions may alter reported totals; diaspora requires an explicit TUR_DIASPORA observation."),
    "galaxy": _source("galaxy", "Galaxy Research", ["crypto"],
        "https://www.galaxy.com/insights/research/", "https://www.galaxy.com/terms-of-use/",
        "Crypto/blockchain venture research reference; locally import only data you may use. Investment, deals and fund fundraising remain distinct; no report-copying API."),
    "custom": _source("custom", "Custom / licensed dataset", ["global", "countries", "turkey", "crypto"],
        None, None,
        "Use a custom lowercase source_id plus source_name, HTTPS provenance and complete methodology. Imported data stays local. No external fetch is performed."),
}
SOURCE_CATALOG["oecd"].update(metrics=["investment"], frequencies=["annual"], units=["USD", "PERCENT_GDP"])
SOURCE_CATALOG["defillama"].update(metrics=["investment", "deals"], units=["USD", "COUNT"])
SOURCE_CATALOG["custom"]["references"] = []


def catalogue(snapshots: list[dict[str, Any]], access: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    entries = copy.deepcopy(SOURCE_CATALOG)
    for snapshot in snapshots:
        data = snapshot["dataset"]
        sid = data["source_id"]
        if sid not in entries:
            entries[sid] = _source(sid, data["source_name"], [], data["source_url"], data["source_url"], "User-provided local dataset; consult its methodology and licensing.")
        entry = entries[sid]
        if sid == "custom":
            entry["source_name"] = data["source_name"]
        rows = data["observations"]
        entry.update(status="available", access_status="available", row_count=len(rows))
        for available, field in (("available_scopes", "scope"), ("available_geographies", "geography"), ("available_metrics", "metric"), ("available_frequencies", "frequency"), ("available_stages", "stage"), ("available_units", "unit")):
            entry[available] = sorted({r[field] for r in rows})
        entry["geographies"] = entry["available_geographies"]
        entry["snapshot_id"] = snapshot["snapshot_id"]
        entry["published_at"] = data.get("published_at")
        entry["retrieved_at"] = snapshot["retrieved_at"]
        if "validation_summary" in data:
            entry["validation_summary"] = data["validation_summary"]
    if not os.environ.get("SHOWME_DEFILLAMA_API_KEY") and entries["defillama"]["status"] != "available":
        entries["defillama"].update(status="not_configured", access_status="not_configured")
    for sid, status in (access or {}).items():
        if sid in entries:
            entries[sid].update(status)
    return [entries[sid] for sid in sorted(entries)]
