"""SEC 8-K Item codes + SPLC / DDIS section regexes.

8-K Item taxonomy: https://www.sec.gov/files/form-8-k.pdf
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EightKItem:
    code: str           # "1.01"
    title: str
    category: str       # "agreements"|"finance"|"governance"|"securities"|"reg_fd"|"earnings"|"other"


ITEMS_8K: dict[str, EightKItem] = {
    "1.01": EightKItem("1.01", "Entry into a Material Definitive Agreement", "agreements"),
    "1.02": EightKItem("1.02", "Termination of a Material Definitive Agreement", "agreements"),
    "1.03": EightKItem("1.03", "Bankruptcy or Receivership", "finance"),
    "1.04": EightKItem("1.04", "Mine Safety", "other"),
    "2.01": EightKItem("2.01", "Completion of Acquisition or Disposition of Assets", "agreements"),
    "2.02": EightKItem("2.02", "Results of Operations and Financial Condition", "earnings"),
    "2.03": EightKItem("2.03", "Creation of a Direct Financial Obligation", "finance"),
    "2.04": EightKItem("2.04", "Triggering Events Increasing/Accelerating Obligation", "finance"),
    "2.05": EightKItem("2.05", "Costs Associated with Exit/Disposal Activities", "finance"),
    "2.06": EightKItem("2.06", "Material Impairments", "finance"),
    "3.01": EightKItem("3.01", "Notice of Delisting / Failure to Satisfy Listing Rule", "securities"),
    "3.02": EightKItem("3.02", "Unregistered Sales of Equity Securities", "securities"),
    "3.03": EightKItem("3.03", "Material Modification to Rights of Security Holders", "securities"),
    "4.01": EightKItem("4.01", "Changes in Registrant's Certifying Accountant", "governance"),
    "4.02": EightKItem("4.02", "Non-Reliance on Previously Issued Financial Statements", "finance"),
    "5.01": EightKItem("5.01", "Changes in Control of Registrant", "governance"),
    "5.02": EightKItem("5.02", "Departure / Election / Appointment of Directors or Officers", "governance"),
    "5.03": EightKItem("5.03", "Amendments to Articles / Bylaws / Change in Fiscal Year", "governance"),
    "5.04": EightKItem("5.04", "Temporary Suspension of Trading Under Employee Benefit Plans", "governance"),
    "5.05": EightKItem("5.05", "Amendment to Code of Ethics or Waiver", "governance"),
    "5.06": EightKItem("5.06", "Change in Shell Company Status", "governance"),
    "5.07": EightKItem("5.07", "Submission of Matters to a Vote of Security Holders", "governance"),
    "5.08": EightKItem("5.08", "Shareholder Director Nominations", "governance"),
    "6.01": EightKItem("6.01", "ABS Informational and Computational Material", "other"),
    "6.02": EightKItem("6.02", "Change of Servicer or Trustee", "other"),
    "6.03": EightKItem("6.03", "Change in Credit Enhancement / External Support", "other"),
    "6.04": EightKItem("6.04", "Failure to Make Required Distribution", "other"),
    "6.05": EightKItem("6.05", "Securities Act Updating Disclosure", "other"),
    "7.01": EightKItem("7.01", "Regulation FD Disclosure", "reg_fd"),
    "8.01": EightKItem("8.01", "Other Events", "other"),
    "9.01": EightKItem("9.01", "Financial Statements and Exhibits", "other"),
}


_ITEM_RE = re.compile(
    r"Item\s+(\d+\.\d{2})[\s:.—–-]*(.+?)(?=Item\s+\d+\.\d{2}|$)",
    re.IGNORECASE | re.DOTALL,
)


def categorize_8k_text(text: str) -> list[dict[str, str]]:
    """Extract Item code(s) + summary from 8-K plain text.

    Returns: [{"code": "1.01", "title": "...", "category": "...", "snippet": "..."}, ...]
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _ITEM_RE.finditer(text or ""):
        code = m.group(1)
        if code in seen:
            continue
        seen.add(code)
        item = ITEMS_8K.get(code, EightKItem(code, "Unknown 8-K Item", "other"))
        snippet = (m.group(2) or "").strip()[:300]
        out.append({"code": code, "title": item.title, "category": item.category,
                    "snippet": snippet})
    return out


# ── 10-K section regexes (SPLC, DDIS) ──
TENK_CUSTOMER_PATTERNS = [
    re.compile(r"customer\s+concentrat\w+", re.I),
    re.compile(r"major\s+customers?", re.I),
    re.compile(r"significant\s+customers?", re.I),
]

TENK_SUPPLIER_PATTERNS = [
    re.compile(r"supplier\s+concentrat\w+", re.I),
    re.compile(r"major\s+suppliers?", re.I),
    re.compile(r"significant\s+suppliers?", re.I),
]

TENK_DEBT_MATURITY_PATTERNS = [
    re.compile(r"(?:maturit(?:y|ies)|aggregate\s+maturit\w+)", re.I),
    re.compile(r"long[\s\-]*term\s+debt\s+maturit\w+", re.I),
]


def find_section_window(text: str, patterns: list[re.Pattern], window: int = 3000) -> str | None:
    """Return text chunk around the first regex match (rough section locator)."""
    if not text:
        return None
    for p in patterns:
        m = p.search(text)
        if m:
            start = max(0, m.start() - 200)
            end = min(len(text), m.end() + window)
            return text[start:end]
    return None


_PERCENT_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*%")
_NAME_NEAR_PCT = re.compile(
    r"([A-Z][A-Za-z0-9&\.\,\-\s]{2,40}?)\s+(?:represented|accounted for|was approximately|comprised)\s+(?:approximately\s+)?(\d{1,2}(?:\.\d)?)\s*%",
    re.I,
)


def extract_customer_concentration(section_text: str) -> list[dict[str, Any]]:  # type: ignore[name-defined]
    """Best-effort: pick out "Customer X represented Y% of revenues" patterns."""
    out: list[dict[str, Any]] = []
    if not section_text:
        return out
    for m in _NAME_NEAR_PCT.finditer(section_text):
        out.append({"name": m.group(1).strip(), "pct": float(m.group(2))})
    return out


# Type-fix: extract_customer_concentration uses Any but it's not imported here.
# The caller passes a string and gets a list; the inline annotation is loose.
from typing import Any  # noqa: E402
