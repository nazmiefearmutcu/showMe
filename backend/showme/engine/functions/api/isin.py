"""ISIN — Cross-reference any identifier (ISIN/CUSIP/SEDOL/Ticker) via OpenFIGI."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.data_sources.reference.openfigi_adapter import OpenFIGIRateLimited


_ID_TYPES = ("ID_ISIN", "ID_CUSIP", "ID_SEDOL", "TICKER", "ID_BB_GLOBAL")
# Total pacing wait for one call across all of its batches: the function timeout
# is 14 s, so once this budget is spent the remaining batches are reported as
# rate-limited per identifier instead of being waited for.
_MAX_PACING_WAIT_SECONDS = 8.0
# Wall-clock budget for all OpenFIGI work in one call (pacing waits plus HTTP
# latency). It sits under the 14 s function timeout with room for the rest of
# the call. Batches that cannot finish inside it are reported per identifier.
_CALL_WALL_BUDGET_SECONDS = 11.0


def _looks_like_isin(s: str) -> bool:
    """Structural ISIN shape: 2 letters, 9 alphanumerics, 1 digit (check not verified)."""
    s = s.strip().upper()
    return len(s) == 12 and s[:2].isalpha() and s[2:11].isalnum() and s[-1].isdigit()


def _isin_check_digit(s: str) -> bool:
    """Luhn-like check digit for 12-char ISIN identifiers."""
    if len(s) != 12 or not s[-1].isdigit():
        return False
    digits = ""
    for ch in s[:-1]:
        if ch.isdigit():
            digits += ch
        elif ch.isalpha():
            digits += str(ord(ch) - 55)
        else:
            return False
    total = 0
    for idx, ch in enumerate(reversed(digits)):
        n = int(ch)
        if idx % 2 == 0:
            n *= 2
            if n >= 10:
                n -= 9
        total += n
    check = (10 - (total % 10)) % 10
    return check == int(s[-1])


def _detect_id_type(s: str) -> str:
    s = s.strip().upper()
    if not s:
        return "TICKER"
    # ISIN: 12 chars, 2 alpha country prefix + 9 alnum + 1 numeric check
    if (
        len(s) == 12
        and s[:2].isalpha()
        and s[2:11].isalnum()
        and s[-1].isdigit()
        and _isin_check_digit(s)
    ):
        return "ID_ISIN"
    # CUSIP: 9 alphanumeric chars with a numeric check digit at the end.
    # CUSIPs may be all-digit (e.g. AAPL = 037833100) or contain letters,
    # so do not require an alpha character — just check the structural
    # pattern: 9 alnum + last digit + at least one digit in the prefix.
    if (
        len(s) == 9
        and s.isalnum()
        and s[-1].isdigit()
        and any(c.isdigit() for c in s[:-1])
    ):
        return "ID_CUSIP"
    # SEDOL: 7 chars, last numeric, no vowels in the first 6 (UK convention)
    if (
        len(s) == 7
        and s.isalnum()
        and s[-1].isdigit()
        and not any(c in "AEIOU" for c in s[:6])
    ):
        return "ID_SEDOL"
    return "TICKER"


def _next_actions(flat_rows: list[dict[str, Any]], unresolved: int, limited_reason: str | None) -> list[str]:
    actions: list[str] = []
    if unresolved:
        actions.append(
            "Re-run the unresolved identifiers after the OpenFIGI window resets, or set OPENFIGI_API_KEY."
            if limited_reason else "Re-run the unresolved identifiers."
        )
    if not flat_rows:
        actions.append("Try ID Type TICKER for common symbols such as AAPL, MSFT, or SPY.")
    return actions


@FunctionRegistry.register
class ISINFunction(BaseFunction):
    code = "ISIN"
    name = "Symbol Cross-Reference"
    category = "api"
    description = "Resolve ISIN/CUSIP/SEDOL/Ticker → OpenFIGI canonical record + cross IDs."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        ids = params.get("ids") or params.get("id") or params.get("query") or []
        if isinstance(ids, str):
            ids = [s.strip() for s in ids.split(",") if s.strip()]
        if not ids and instrument:
            ids = [instrument.symbol]
        if not ids:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_required",
                    "reason": "Identifier required.",
                    "next_actions": ["Enter a ticker such as AAPL or an ISIN such as US0378331005."],
                    "rows": [],
                },
                warnings=["ids required (or pass instrument)"],
            )
        if not self.deps.openfigi:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "OpenFIGI adapter is not configured.",
                    "next_actions": ["Configure the OpenFIGI adapter or use ticker-only local symbol search."],
                    "rows": [],
                    "data_mode": "not_configured",
                },
                sources=["openfigi"],
                warnings=["no openfigi adapter"],
            )
        id_type = (params.get("id_type") or "").upper()
        if id_type and id_type not in _ID_TYPES:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": f"Unknown id_type {id_type!r}.",
                    "next_actions": ["Use one of " + ", ".join(_ID_TYPES) + ", or leave ID type on AUTO."],
                    "rows": [],
                },
                warnings=[f"unknown id_type {id_type!r}"],
            )
        try:
            limit = max(1, min(int(params.get("limit") or 25), 100))
        except Exception:
            limit = 25
        jobs = [(id_type or _detect_id_type(v), v) for v in ids]
        # A 12-character ISIN-shaped input with a wrong check digit is neither a
        # valid ISIN nor a ticker: report it and never send it to OpenFIGI.
        invalid: dict[int, str] = {
            i: "invalid ISIN check digit (ISO 6166)"
            for i, (t, v) in enumerate(jobs)
            if not id_type and t == "TICKER" and _looks_like_isin(v)
        }
        query = [i for i in range(len(jobs)) if i not in invalid]
        adapter = self.deps.openfigi
        chunk_size = max(1, int(getattr(adapter, "max_jobs_per_request", 10) or 10))
        resolved: dict[int, dict[str, Any]] = {}
        failures: dict[int, str] = {}
        warnings: list[str] = [f"{jobs[i][1]}: {why}; not sent to OpenFIGI as a ticker" for i, why in invalid.items()]
        failures.update(invalid)
        limited_reason: str | None = None
        # OpenFIGI takes up to max_jobs_per_request identifiers per POST, so one
        # call covers a whole batch. Anonymous budget: 10 jobs/request, 25 requests/min.
        # One pacing budget for the whole call, not per batch: every batch may
        # only wait for what is left of it, so the call stays inside the timeout.
        pacing_deadline = time.monotonic() + _MAX_PACING_WAIT_SECONDS
        call_deadline = time.monotonic() + _CALL_WALL_BUDGET_SECONDS
        budget_label = f"{_CALL_WALL_BUDGET_SECONDS:g} s"
        for start in range(0, len(query), chunk_size):
            idxs = query[start:start + chunk_size]
            chunk = [jobs[i] for i in idxs]
            if limited_reason is not None:
                for i in idxs:
                    failures[i] = limited_reason
                continue
            wall_left = call_deadline - time.monotonic()
            if wall_left <= 0:
                reason = (
                    f"OpenFIGI call time budget ({budget_label}) was used up before this batch "
                    "was sent; the identifiers were not looked up."
                )
                if reason not in warnings:
                    warnings.append(reason)
                for i in idxs:
                    failures[i] = reason
                continue
            remaining = max(0.0, pacing_deadline - time.monotonic())
            try:
                got = await asyncio.wait_for(
                    adapter.lookup_batch(chunk, max_wait_seconds=remaining),
                    timeout=wall_left,
                )
            except asyncio.TimeoutError:
                reason = (
                    f"OpenFIGI did not answer within this call's {budget_label} time budget; "
                    "the identifiers in this batch were not resolved."
                )
                if reason not in warnings:
                    warnings.append(reason)
                for i in idxs:
                    failures[i] = reason
                continue
            except OpenFIGIRateLimited as exc:
                retry = f" Retry in about {exc.retry_after:.0f} s." if exc.retry_after else ""
                # The exception text already says whether a request was sent
                # (local pacing) or OpenFIGI answered HTTP 429.
                limited_reason = f"{exc}.{retry} Set OPENFIGI_API_KEY for the 250 requests/min budget."
                warnings.append(limited_reason)
                for i in idxs:
                    failures[i] = limited_reason
                continue
            except Exception as e:  # noqa: BLE001 — per-batch, the rest still resolve
                reason = f"lookup failed: {e}"
                warnings.append(reason)
                for i in idxs:
                    failures[i] = reason
                continue
            for i, item in zip(idxs, got):
                if (item or {}).get("error"):
                    failures[i] = f"OpenFIGI: {item['error']}"
                    continue
                resolved[i] = item

        out: list[dict[str, Any]] = []
        flat_rows: list[dict[str, Any]] = []
        for i, (t, v) in enumerate(jobs):
            if i in failures:
                out.append({"input": v, "id_type": t, "error": failures[i], "matches": []})
                continue
            rows = (resolved.get(i) or {}).get("data") or []
            match_rows = [
                {
                    "input": v,
                    "id_type": t,
                    "rank": f"#{idx + 1}",
                    "figi": r.get("figi"),
                    "ticker": r.get("ticker"),
                    "name": r.get("name"),
                    "market_sector": r.get("marketSector"),
                    "security_type": r.get("securityType"),
                    "security_type2": r.get("securityType2"),
                    "exchange": r.get("exchCode"),
                    "composite_figi": r.get("compositeFIGI"),
                    "share_class_figi": r.get("shareClassFIGI"),
                }
                for idx, r in enumerate(rows[:limit])
            ]
            flat_rows.extend(match_rows)
            out.append({
                "input": v, "id_type": t,
                "matches": [
                    {
                        "figi": r.get("figi"),
                        "ticker": r.get("ticker"),
                        "name": r.get("name"),
                        "marketSector": r.get("marketSector"),
                        "securityType": r.get("securityType"),
                        "securityType2": r.get("securityType2"),
                        "exchCode": r.get("exchCode"),
                        "compositeFIGI": r.get("compositeFIGI"),
                        "shareClassFIGI": r.get("shareClassFIGI"),
                    } for r in rows
                ],
            })
        unresolved = len(failures)
        provider_failed = [i for i in failures if i not in invalid]
        if flat_rows and unresolved:
            status = "partial"
        elif flat_rows:
            status = "ok"
        elif provider_failed:
            status = "provider_unavailable"
        elif invalid:
            status = "input_error"
        else:
            status = "empty"
        reason = None
        if unresolved and not flat_rows:
            reason = limited_reason or next(iter(failures.values()))
        # Provenance follows the outcome (ISIN data_mode fix, merged onto the
        # batched lookup): live only when OpenFIGI answered at least one job.
        provider_attempts = len(query)
        provider_failures = sum(1 for i in query if i in failures)
        if provider_attempts == 0:
            data_mode = "explicit_unavailable"
        elif provider_failures == provider_attempts:
            data_mode = "provider_unavailable"
        else:
            data_mode = "live_official"
        # Exchange-level total across every group (match_groups keep the full
        # OpenFIGI list; only the flat ``rows`` view is capped by ``limit``).
        exchange_total = sum(len(g.get("matches") or []) for g in out)
        inputs_resolved = sum(1 for g in out if not g.get("error") and g.get("matches"))
        inputs_failed = sum(1 for g in out if g.get("error"))
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                **({"reason": reason} if reason else {}),
                "rows": flat_rows,
                "match_groups": out,
                "summary": {
                    "inputs": len(ids),
                    "matches": exchange_total,
                    "rows_returned": len(flat_rows),
                    "id_type": id_type or "auto",
                    "limit_per_input": limit,
                    "unresolved": unresolved,
                },
                "matches": exchange_total,
                "inputs_resolved": inputs_resolved,
                "inputs_failed": inputs_failed,
                "data_mode": data_mode,
                "as_of": datetime.now(timezone.utc).isoformat(),
                "methodology": (
                    "ISIN maps the visible identifier to an OpenFIGI lookup type. "
                    "If ID Type is AUTO, ShowMe detects ISIN/CUSIP/SEDOL by length and falls back to TICKER; "
                    "a 12-character ISIN-shaped input with a wrong check digit is reported as an error and not queried. "
                    "The flat rows view is capped by limit per input; match_groups and the match count keep every OpenFIGI match."
                ),
                "field_dictionary": {
                    "input": "Identifier entered by the user.",
                    "id_type": "OpenFIGI lookup type used for the request.",
                    "rank": "Provider match order shown as a label; it is not a metric to chart.",
                    "figi": "OpenFIGI security identifier.",
                    "composite_figi": "Composite FIGI for all trading venues where available.",
                    "share_class_figi": "FIGI representing the issuer share class.",
                    "exchange": "OpenFIGI exchange code.",
                },
                "next_actions": _next_actions(flat_rows, unresolved, limited_reason),
            },
            sources=["openfigi"],
            warnings=warnings,
        )
