"""SPLC — Supply Chain (10-K text-mining stub).

Plan §7.7: no good free relationship feed exists; this is approximate
10-K text mining. This version fetches the latest 10-K from SEC EDGAR
and mines customer/supplier concentration language plus the debt-maturity
section; reference rows are clearly labelled when extraction finds
nothing.
"""

from __future__ import annotations

import asyncio
import html as _html
import re
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import frame_rows, reference_profile


@FunctionRegistry.register
class SPLCFunction(BaseFunction):
    code = "SPLC"
    name = "Supply Chain (approximate)"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        filings = pd.DataFrame()
        customers: list[dict[str, Any]] = []
        suppliers: list[dict[str, Any]] = []
        debt_section: str | None = None
        filing_url: str | None = None
        try:
            if self.deps.sec_edgar:
                req_timeout = float(params.get("timeout", params.get("sec_timeout", 8.0)))
                sec_timeout = max(1.0, min(req_timeout - 1.0, 4.0))
                df = await asyncio.wait_for(
                    self.deps.sec_edgar.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=sec_timeout,
                )
                if isinstance(df, pd.DataFrame) and "form" in df.columns:
                    filings = df[df["form"] == "10-K"].head(3)
                    if not filings.empty:
                        latest = filings.iloc[0]
                        cik = await asyncio.wait_for(
                            self.deps.sec_edgar.cik_for(instrument.symbol),
                            timeout=sec_timeout,
                        )
                        acc = (latest.get("accessionNumber") or "").replace("-", "")
                        doc = latest.get("primaryDocument")
                        if cik and acc and doc:
                            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
                            filing_url = url
                            try:
                                import httpx
                                async with httpx.AsyncClient(
                                    timeout=sec_timeout,
                                    headers={"User-Agent": "ShowMe dev showme@example.com"},
                                    follow_redirects=True,
                                ) as cli:
                                    r = await cli.get(url)
                                    if r.status_code == 200:
                                        import re as _re
                                        text = _html.unescape(_re.sub(r"<[^>]+>", " ", r.text))
                                        from showme.engine.core.sec_taxonomy import (
                                            TENK_CUSTOMER_PATTERNS,
                                            TENK_DEBT_MATURITY_PATTERNS,
                                            TENK_SUPPLIER_PATTERNS,
                                            find_section_window,
                                        )
                                        debt_section = find_section_window(text, TENK_DEBT_MATURITY_PATTERNS, window=2000)
                                        # SPLC#1: scan every concentration match, not only the first window.
                                        headings = _concentration_headings(
                                            text, TENK_CUSTOMER_PATTERNS, TENK_SUPPLIER_PATTERNS,
                                            [_REVENUE_CONCENTRATION])
                                        customers = _extract_concentration(
                                            text, [*TENK_CUSTOMER_PATTERNS, _REVENUE_CONCENTRATION],
                                            headings)
                                        suppliers = _extract_concentration(
                                            text, TENK_SUPPLIER_PATTERNS, headings)
                            except Exception as e:
                                warnings.append(f"10-K fetch: {e}")
        except Exception as e:
            warnings.append(f"sec_edgar: {e}")
        data: dict[str, Any] = {
            "status": "ok" if customers or suppliers else "reference_relationships",
            "filings": filings,
            "customers": customers,
            "suppliers": suppliers,
            "debt_maturity_section": (debt_section or "")[:1000],
        }
        reference_peers = [
            str(p) for p in (reference_profile(instrument.symbol).get("peers") or [])
        ]
        data["rows"] = _relationship_rows(
            instrument.symbol, customers, suppliers, filings,
            peers=reference_peers, filing_url=filing_url,
        )
        sources = ["sec_edgar"]
        if not customers and not suppliers:
            ref = reference_profile(instrument.symbol)
            ref_rows = [
                {"symbol": instrument.symbol, "source_url": None, **item, "disclosed_pct": None, "source_mode": "reference_supply_chain_10k_language"}
                for item in [*ref.get("customers", []), *ref.get("suppliers", [])]
            ]
            comp_rows = [
                {"symbol": instrument.symbol, "relationship": "competitor", "counterparty": str(p).strip().upper(), "ticker": str(p).strip().upper(), "confidence": 0.35, "disclosed_pct": None, "source_url": None, "source_mode": "reference_sector_peer_list"}
                for p in (ref.get("peers") or [])
            ]
            if ref_rows or comp_rows:
                data["rows"] = [*ref_rows, *comp_rows]
                data["customers"] = [r for r in ref_rows if "customer" in str(r.get("relationship", ""))]
                data["suppliers"] = [r for r in ref_rows if "supplier" in str(r.get("relationship", ""))]
                sources = ["sec_edgar", "supply_chain_reference"]
        if (not isinstance(filings, pd.DataFrame) or filings.empty) and not data.get("rows"):
            data = {
                "status": "provider_unavailable",
                "rows": [{
                    "symbol": instrument.symbol,
                    "relationship": "provider_unavailable",
                    "counterparty": None,
                    "confidence": None,
                    "source_mode": "supply_chain_unavailable",
                }],
                "filings": [{
                    "symbol": instrument.symbol,
                    "form": "10-K",
                    "status": "provider_unavailable",
                }],
                "customers": [],
                "suppliers": [],
                "debt_maturity_section": "",
            }
            sources = ["supply_chain_model"]
        if data.get("status") != "provider_unavailable":
            relationship = _relationship_param(params.get("relationship"))
            min_pct, pct_warning = _min_pct_param(params.get("min_pct"))
            if pct_warning:
                warnings.append(pct_warning)
            data["rows"] = _apply_filters(data.get("rows") or [], relationship, min_pct)
            # SPLC#3: the raw customers/suppliers dicts carry no relationship key,
            # so tag them first; otherwise the relationship filter drops every row.
            data["customers"] = _apply_filters(
                _as_relationship_rows(data.get("customers") or [], "customer"), relationship, min_pct)
            data["suppliers"] = _apply_filters(
                _as_relationship_rows(data.get("suppliers") or [], "supplier"), relationship, min_pct)
            if relationship != "both" or min_pct > 0:
                data["filters_applied"] = {"relationship": relationship, "min_pct": min_pct}
                if not data["rows"]:
                    # Filters removed every row: say so rather than keep an upstream status.
                    data["status"] = "empty"
                    data["reason"] = (
                        f"No extracted counterparty matches relationship={relationship} "
                        f"with min_pct={min_pct:g}; the filing may disclose none at that share."
                    )
        data["methodology"] = "SPLC approximates supply-chain relationships by scanning recent 10-K sections for customer/supplier concentration language. Reference rows are labelled when extraction finds no explicit counterparty rows. Rows with a disclosed share below min_pct, or without one when min_pct is set, are dropped."
        data["field_dictionary"] = {
            "relationship": "customer, supplier, competitor, filing-evidence, or unavailable state.",
            "counterparty": "Named or summarized relationship counterparty.",
            "confidence": "Extraction confidence; lower values indicate approximate/reference rows.",
            "disclosed_pct": "Share of revenue or inputs stated in the 10-K, in percent (22.0 = 22%); null when not disclosed.",
            "fiscal_year": "Fiscal year the disclosed share refers to, read from its sentence; null when the sentence names none. The latest disclosed year per counterparty is reported.",
            "source_url": "EDGAR URL of the 10-K the row was extracted from; null for reference rows.",
            "source_mode": "SEC extraction or labelled reference fallback.",
        }
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources,
            metadata={
                "note": "Regex-based extraction; spaCy NER refinement next iter.",
                "provider_errors": warnings,
            },
        )


_RELATIONSHIP_CHOICES = ("both", "customer", "supplier")


def _relationship_param(value: Any) -> str:
    """Normalise the relationship input; unknown values fall back to ``both``."""
    text = str(value or "both").strip().lower()
    return text if text in _RELATIONSHIP_CHOICES else "both"


def _min_pct_param(value: Any) -> tuple[float, str | None]:
    """Parse min_pct. Returns (threshold, warning). Invalid input is disclosed."""
    if value is None or str(value).strip() == "":
        return 0.0, None
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        return 0.0, f"min_pct {value!r} is not a number; no share threshold applied."
    if threshold != threshold or threshold < 0:
        return 0.0, f"min_pct {value!r} is out of range; no share threshold applied."
    return threshold, None


# A comma splits only before a lowercase word and a period only before a capital,
# so "Foo, Inc. represented" keeps its full name.
_CLAUSE_SPLIT = re.compile(r"[;:]\s+|,\s+(?=[a-z])|\.\s+(?=[A-Z])")
_DIRECT_CUSTOMER = re.compile(r"((?:one|another)\s+direct\s+customer)\s*$", re.IGNORECASE)
# "sales to Foo Corp" / "net revenues from Foo Corp": the verb phrase is not part of the name.
_LEAD_SALES_PHRASE = re.compile(r"^(?:net\s+)?(?:sales|revenues?)\s+(?:to|from)\s+", re.IGNORECASE)
_MAX_LABEL_CHARS = 60
# NVIDIA-style MD&A heading: "Concentration of Revenue" introduces the percentage sentences.
_REVENUE_CONCENTRATION = re.compile(r"concentration\s+of\s+(?:revenues?|sales)\b", re.IGNORECASE)
# Longest distance searched after a heading. The 10-K percentage sentence can sit
# several thousand characters after its heading; 20,000 covers the disclosed
# concentration blocks while still stopping at an unrelated section.
_CONCENTRATION_WINDOW_CHARS = 20000
# A business segment, product line, region or revenue line is a share of revenue,
# not a counterparty: "Compute and Networking segment accounted for 80% of total
# revenue" after a "Major customers" heading must not become a customer.
_NON_COUNTERPARTY = re.compile(
    r"\b(?:segments?|reportable|geograph\w*|regions?|product\s+lines?|business\s+units?|divisions?)\b"
    r"|^(?:total\s+|net\s+|consolidated\s+)?(?:revenues?|sales)$",
    re.IGNORECASE,
)
_FISCAL_YEAR = re.compile(r"fiscal\s+(?:year\s+)?(20\d{2})\b", re.IGNORECASE)


def _clean_counterparty(raw: Any) -> str | None:
    """Reduce a regex-captured name to a counterparty label, or None when it is a fragment.

    The concentration regex captures up to 40 characters before "represented",
    so a capture can start mid-clause ("l year 2026, sales to one direct
    customer") or span a sentence ("of net sales. Gamma Ltd"). Only the last
    clause is kept; a leading "sales to" / "revenue from" is removed;
    "one/another direct customer" becomes the explicit label; anything that
    does not start with a capital letter, or runs past _MAX_LABEL_CHARS, is
    dropped rather than guessed.
    """
    segment = _CLAUSE_SPLIT.split(str(raw or "").strip())[-1].strip()
    segment = _LEAD_SALES_PHRASE.sub("", segment).strip()
    if not segment or _NON_COUNTERPARTY.search(segment):
        return None
    m = _DIRECT_CUSTOMER.search(segment)
    if m:
        label = m.group(1)
        return label[0].upper() + label[1:].lower()
    if not segment[0].isupper() or len(segment) > _MAX_LABEL_CHARS:
        return None
    return segment


def _concentration_headings(text: str, *pattern_groups: list[re.Pattern]) -> list[int]:
    """Sorted start offsets of every customer or supplier heading in the document."""
    return sorted({
        m.start()
        for patterns in pattern_groups
        for pattern in patterns
        for m in pattern.finditer(text)
    })


def _extract_concentration(
    text: str, patterns: list[re.Pattern], headings: list[int]
) -> list[dict[str, Any]]:
    """Run concentration extraction over every match of every pattern (SPLC#1).

    Each heading match gets a window from the heading to the next heading of any
    customer/supplier kind (or to _CONCENTRATION_WINDOW_CHARS, whichever is
    shorter), so a percentage sentence well after the first hit is still scanned
    and a customer window never reads into the supplier section. Windows are
    processed in document order and each counterparty label is reported once,
    with the first disclosure found, so a later fiscal year's repeat of the same
    label does not appear as a second current share.
    """
    candidates: list[tuple[int, dict[str, Any]]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            end = min(len(text), match.start() + _CONCENTRATION_WINDOW_CHARS)
            following = [h for h in headings if h > match.start()]
            if following:
                end = min(end, following[0])
            window = text[match.start():end]
            for item in _concentration_items(window):
                candidates.append((match.start(), item))

    # One row per counterparty. Between two disclosures that both name a fiscal year,
    # the later year wins, so a prior-year share listed earlier in the filing is not
    # presented as current. A disclosure that names no year is not compared with a
    # dated one (its year is unknown, so it may be the current share): the first
    # disclosure in document order is kept, and the row keeps that mention's position.
    chosen: dict[str, dict[str, Any]] = {}
    for _, item in sorted(candidates, key=lambda c: c[0]):
        name = _clean_counterparty(item.get("name"))
        if name is None:
            continue
        row = {"name": name, "pct": float(item["pct"]), "fiscal_year": item["fiscal_year"]}
        prior = chosen.get(name.lower())
        if prior is None:
            chosen[name.lower()] = row
        elif (
            prior["fiscal_year"] is not None
            and row["fiscal_year"] is not None
            and row["fiscal_year"] > prior["fiscal_year"]
        ):
            chosen[name.lower()] = row
    return list(chosen.values())


def _fiscal_year_for(window: str, pct_start: int) -> int | None:
    """Fiscal year named in the sentence holding a percentage (before it, else after it).

    None when the sentence names no fiscal year: the share is then reported
    without an as-of year rather than assigned one.
    """
    sentence_start = max(window.rfind(". ", 0, pct_start), window.rfind("; ", 0, pct_start)) + 1
    before = _FISCAL_YEAR.findall(window[sentence_start:pct_start])
    if before:
        return int(before[-1])
    sentence_end = window.find(". ", pct_start)
    after_text = window[pct_start: sentence_end if sentence_end != -1 else len(window)]
    after = _FISCAL_YEAR.findall(after_text)
    return int(after[0]) if after else None


def _concentration_items(window: str) -> list[dict[str, Any]]:
    """Name, share and fiscal year of each "X represented N%" sentence in a window."""
    # Same sentence pattern as sec_taxonomy.extract_customer_concentration, kept
    # with offsets so each share can be tied to its own sentence's fiscal year.
    from showme.engine.core.sec_taxonomy import _NAME_NEAR_PCT

    return [
        {
            "name": m.group(1).strip(),
            "pct": float(m.group(2)),
            "fiscal_year": _fiscal_year_for(window, m.start(2)),
        }
        for m in _NAME_NEAR_PCT.finditer(window)
    ]


def _as_relationship_rows(items: list[dict[str, Any]], relationship: str) -> list[dict[str, Any]]:
    """Give customers/suppliers items the row keys the filters read."""
    return [
        {
            **item,
            "relationship": relationship,
            "disclosed_pct": item.get("disclosed_pct", item.get("pct")),
        }
        for item in items
    ]


def _classify(relationship: Any) -> str:
    text = str(relationship or "").lower()
    if "customer" in text:
        return "customer"
    if "supplier" in text:
        return "supplier"
    return "other"


def _apply_filters(
    rows: list[dict[str, Any]], relationship: str, min_pct: float
) -> list[dict[str, Any]]:
    """Apply the relationship and min_pct inputs server-side.

    Unavailable-state rows always pass through so the outage stays visible.
    A row with no disclosed share cannot prove it meets ``min_pct``, so it is
    dropped whenever a threshold above zero is requested.
    """
    kept: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("relationship") or "") == "provider_unavailable":
            kept.append(row)
            continue
        if relationship != "both" and _classify(row.get("relationship")) != relationship:
            continue
        if min_pct > 0:
            pct = row.get("disclosed_pct")
            if pct is None or float(pct) < min_pct:
                continue
        kept.append(row)
    return kept


def _relationship_rows(
    symbol: str,
    customers: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
    filings: pd.DataFrame,
    peers: list[str] | None = None,
    filing_url: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for item in customers:
        rows.append({"symbol": symbol, "relationship": "customer", "counterparty": item.get("name") or item.get("counterparty") or item.get("text"), "confidence": item.get("confidence", 0.55), "disclosed_pct": item.get("pct"), "fiscal_year": item.get("fiscal_year"), "source_url": filing_url, "source_mode": "sec_10k_customer_extraction"})
    for item in suppliers:
        rows.append({"symbol": symbol, "relationship": "supplier", "counterparty": item.get("name") or item.get("counterparty") or item.get("text"), "confidence": item.get("confidence", 0.55), "disclosed_pct": item.get("pct"), "fiscal_year": item.get("fiscal_year"), "source_url": filing_url, "source_mode": "sec_10k_supplier_extraction"})
    # Competitor rows come from the labelled reference sector peer list (ticker
    # when the peer entry is a ticker); 10-K concentration mining does not
    # extract competitors, so these rows stay explicitly reference-sourced.
    for peer in peers or []:
        ticker = str(peer).strip().upper()
        rows.append({"symbol": symbol, "relationship": "competitor", "counterparty": ticker, "ticker": ticker, "confidence": 0.35, "disclosed_pct": None, "source_url": None, "source_mode": "reference_sector_peer_list"})
    if not rows:
        for item in frame_rows(filings, limit=3):
            rows.append({"symbol": symbol, "relationship": "evidence_filing", "counterparty": item.get("form"), "filingDate": item.get("filingDate"), "confidence": 0.2, "disclosed_pct": None, "source_url": filing_url, "source_mode": "sec_10k_filing_evidence"})
    return rows
