"""FORM4 — SEC Form 4 (insider transactions) calendar."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import date_label, finite, frame_rows


@FunctionRegistry.register
class FORM4Function(BaseFunction):
    code = "FORM4"
    name = "Insider Transactions"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Recent SEC Form 4 (insider) filings for the given ticker."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (instrument.symbol if instrument else
               params.get("symbol") or "").upper()
        if not sym:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["symbol required"])
        yfin_rows: list[dict[str, Any]] = []
        try:
            if self.deps.yfinance:
                holdings = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(kind=DataKind.HOLDINGS, instrument=instrument)),
                    timeout=float(params.get("yfinance_timeout", 5)),
                )
                yfin_rows = _insider_rows_from_yfinance(sym, holdings)
        except Exception:
            yfin_rows = []
        months = _coerce_months(params.get("months"))
        transaction_types = _coerce_list(params.get("transaction_types"))
        if not self.deps.sec_edgar:
            data = _fallback_form4(sym)
            if yfin_rows:
                rows = _filter_rows(yfin_rows, months=months, transaction_types=transaction_types)
                summary = _form4_summary_rows(rows)
                data.update(
                    {
                        "status": "delayed_reference",
                        "rows": rows,
                        "filings": rows,
                        "data_mode": "delayed_reference",
                        **summary,
                    },
                )
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=data,
                                  sources=["yfinance"] if yfin_rows else ["form4_model"])
        try:
            rows = await asyncio.wait_for(
                self.deps.sec_edgar.form4_filings(sym, limit=int(params.get("limit", 40))),
                timeout=float(params.get("timeout", 8)),
            )
        except Exception as e:
            data = _fallback_form4(sym)
            if yfin_rows:
                rows = _filter_rows(yfin_rows, months=months, transaction_types=transaction_types)
                summary = _form4_summary_rows(rows)
                data.update(
                    {
                        "status": "delayed_reference",
                        "rows": rows,
                        "filings": rows,
                        "methodology": (
                            "SEC Form 4 is currently unavailable. "
                            "Returning yfinance holdings-based insider rows as best-effort."
                        ),
                        "data_mode": "delayed_reference",
                        "next_actions": [
                            "Retry with provider_mode=live_official once SEC feed is available.",
                            "Use provider logs to inspect form4 request errors.",
                                    *data.get("next_actions", []),
                        ],
                        "warnings": [
                            "SEC provider unavailable; yfinance-based rows are best-effort fallback.",
                            *data.get("warnings", []),
                        ],
                        **summary,
                    },
                )
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=data,
                                  sources=["yfinance", "form4_model"] if yfin_rows else ["form4_model"],
                                  metadata={"provider_errors": [f"sec_edgar: {e}"]})
        # Aggregate counts
        rows = _filter_rows(rows, months=months, transaction_types=transaction_types)
        by_month: dict[str, int] = {}
        for r in rows:
            d = (r.get("filingDate") or "")[:7]   # YYYY-MM
            if d:
                by_month[d] = by_month.get(d, 0) + 1
        parsed_rows = yfin_rows or _filing_rows(sym, rows)
        summary = _form4_summary_rows(parsed_rows)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok" if parsed_rows else "provider_unavailable",
                "data_mode": "live_official" if parsed_rows and not yfin_rows else "delayed_reference" if parsed_rows else "provider_unavailable",
                "symbol": sym,
                "n": len(parsed_rows),
                "rows": parsed_rows,
                "filings": rows,
                "as_of": summary.get("as_of"),
                "by_month": [
                    {"month": k, "count": v}
                    for k, v in sorted(by_month.items(), reverse=True)
                ],
                "methodology": "FORM4 prefers parsed insider-transaction tables from Yahoo holdings data and keeps SEC Form 4 filing links as evidence. If XML transaction parsing is unavailable, rows are labelled as filing metadata instead of pretending to be parsed trades.",
                "field_dictionary": {
                    "insider": "Reporting owner or insider name.",
                    "transaction": "Transaction description/code when parsed.",
                    "transaction_type": "Normalized transaction direction (buy / sell / grant / option_exercise).",
                    "shares": "Shares transacted or reported.",
                    "value": "Reported transaction value when available.",
                    "filing_url": "SEC primary document URL or provider link.",
                },
                **summary,
            },
            sources=["yfinance", "sec_edgar"] if yfin_rows else ["sec_edgar"],
        )


def _fallback_form4(symbol: str) -> dict[str, Any]:
    # Returns empty rows/filings so the UI does not see all-None sentinel rows
    # masquerading as real Form 4 data. next_actions guides the user to a fix.
    return {
        "status": "provider_unavailable",
        "symbol": symbol,
        "n": 0,
        "data_mode": "provider_unavailable",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "rows": [],
        "filings": [],
        "by_month": [],
        "methodology": "SEC Form 4 or provider insider transaction data is required.",
        "next_actions": [
            "Configure the SEC EDGAR Form 4 adapter or enable yfinance holdings.",
            "Retry the call with live=true once a provider is available.",
        ],
    }


def _insider_rows_from_yfinance(symbol: str, holdings: Any) -> list[dict[str, Any]]:
    frame = (holdings or {}).get("insider_transactions") if isinstance(holdings, dict) else None
    rows: list[dict[str, Any]] = []
    for item in frame_rows(frame, limit=40):
        shares = finite(item.get("Shares") or item.get("shares"))
        value = finite(item.get("Value") or item.get("value"))
        filer = item.get("Insider") or item.get("insider") or item.get("Person")
        transaction_date = date_label(item.get("Start Date") or item.get("startDate") or item.get("Date") or item.get("index"))
        transaction_type = _normalize_transaction_type(item.get("Transaction"))
        rows.append({
            "symbol": symbol,
            "filingDate": transaction_date,
            "transaction_date": transaction_date,
            "date": transaction_date,
            "filer": filer,
            "insider": filer,
            "position": item.get("Position") or item.get("position"),
            "role": item.get("Position") or item.get("position"),
            "transaction": item.get("Transaction") or item.get("transaction"),
            "transaction_type": transaction_type,
            "side": transaction_type,
            "shares": shares,
            "value": value,
            "notional": value,
            "ownership": item.get("Ownership") or item.get("ownership"),
            "source_mode": "yfinance_insider_transactions",
        })
    return [r for r in rows if r.get("insider") or r.get("transaction") or r.get("shares")]


def _filing_rows(symbol: str, filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in filings[:40]:
        filer = item.get("reportingOwner") or item.get("ownerName")
        filing_date = item.get("filingDate") or item.get("filing_date") or item.get("date")
        transaction_type = _normalize_transaction_type(item.get("transactionType") or item.get("acquiredDisposedCode") or item.get("type"))
        rows.append({
            "symbol": symbol,
            "filingDate": filing_date,
            "transaction_date": filing_date,
            "date": filing_date,
            "filer": filer,
            "insider": filer,
            "role": item.get("directorOfficerTitle") or item.get("officerTitle") or item.get("position") or item.get("positionTitle"),
            "transaction": _readable_transaction(item),
            "transaction_type": transaction_type,
            "side": transaction_type,
            "acquiredDisposedCode": item.get("acquiredDisposedCode"),
            "shares": finite(item.get("transactionShares")),
            "value": finite(item.get("transactionValue")),
            "price": finite(item.get("transactionPricePerShare")),
            "filing_url": item.get("primaryDocument") or item.get("url"),
            "accession": item.get("accessionNumber"),
            "source_mode": "sec_form4_filing_metadata",
        })
    return rows


def _coerce_months(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 6
    if value < 1:
        return 1
    if value > 24:
        return 24
    return value


def _coerce_list(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip().lower() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part.strip().lower() for part in raw.split(",") if part.strip()]
    return []


def _to_timestamp(row: dict[str, Any]) -> datetime | None:
    return _pick_tx_time(row)


def _in_month_window(ts: datetime | None, months: int) -> bool:
    if ts is None:
        return True
    if months <= 0:
        return True
    now = datetime.now(timezone.utc)
    window_days = months * 31
    return (now - ts).days <= window_days


def _normalize_transaction_type(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    if text in {"p", "purchase", "acquisition", "acquired"}:
        return "buy"
    if text in {"g", "grant", "award"}:
        return "grant"
    if text in {"j", "option", "exercise"}:
        return "option_exercise"
    if text in {"s", "d", "x", "v", "r", "sell", "disposition", "disposed", "forfeit"}:
        return "sell"
    if "option" in text:
        return "option_exercise"
    if "other" in text:
        return "other"
    return text.replace(" ", "_")


def _readable_transaction(item: dict[str, Any]) -> str:
    description = (
        item.get("transactionDescription")
        or item.get("transaction")
        or item.get("acquiredDisposedCode")
        or item.get("type")
        or "Form 4 filing document"
    )
    return str(description)


def _matches_types(row: dict[str, Any], selected_types: list[str]) -> bool:
    if not selected_types:
        return True
    tx_type = _normalize_transaction_type(
        row.get("transaction_type")
        or row.get("acquiredDisposedCode")
        or row.get("transaction")
        or row.get("type")
    )
    if not tx_type:
        return False
    return tx_type in set(selected_types)


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    months: int,
    transaction_types: list[str],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    selected = set(transaction_types)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if selected and not _matches_types(row, list(selected)):
            continue
        if not _in_month_window(_to_timestamp(row), months):
            continue
        out.append(row)
    return out


def _form4_summary_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    filing_count = len(rows)
    net_shares = 0.0
    has_shares = False
    net_notional = 0.0
    has_notional = False
    buyers = set[str]()
    sellers = set[str]()
    latest_ts: datetime | None = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        direction = _infer_direction(row)
        shares = finite(row.get("shares") or row.get("share") or row.get("share_delta") or row.get("net_shares"))
        if shares is not None:
            if direction < 0:
                net_shares -= abs(shares)
            elif direction > 0:
                net_shares += abs(shares)
            else:
                net_shares += shares
            has_shares = True

        value = finite(row.get("value") or row.get("notional") or row.get("signed_value"))
        if value is not None:
            if direction < 0:
                net_notional -= abs(value)
            elif direction > 0:
                net_notional += abs(value)
            else:
                net_notional += value
            has_notional = True
        elif shares is not None:
            price = finite(row.get("price") or row.get("unit_price") or row.get("price_per_share"))
            if price is not None:
                notional = shares * price
                if direction < 0:
                    notional = -abs(notional)
                elif direction > 0:
                    notional = abs(notional)
                net_notional += notional
                has_notional = True

        insider = row.get("insider") or row.get("filer") or row.get("reportingOwner") or row.get("holder")
        if direction > 0 and isinstance(insider, str):
            buyers.add(insider.strip())
        elif direction < 0 and isinstance(insider, str):
            sellers.add(insider.strip())

        tx_dt = _pick_tx_time(row)
        if tx_dt is not None and (latest_ts is None or tx_dt > latest_ts):
            latest_ts = tx_dt

    out: dict[str, Any] = {
        "filing_count": filing_count,
    }
    if has_shares:
        out["net_shares"] = net_shares
    if has_notional:
        out["net_notional"] = net_notional
    if buyers:
        out["buyer_count"] = len(buyers)
    if sellers:
        out["seller_count"] = len(sellers)
    out["as_of"] = (latest_ts or datetime.now(timezone.utc)).isoformat()
    return out


def _infer_direction(row: dict[str, Any]) -> int:
    code = str(
        row.get("acquiredDisposedCode")
        or row.get("transactionCode")
        or row.get("action")
        or row.get("transaction_type")
        or row.get("direction")
        or ""
    ).strip().lower()
    if code in {"p", "a", "g", "j", "e"}:
        return 1
    if code in {"s", "d", "x", "v", "r"}:
        return -1

    description = str(
        row.get("transaction")
        or row.get("description")
        or row.get("transaction_description")
        or row.get("transaction_desc")
        or row.get("type")
        or row.get("action_type")
    ).strip().lower()
    if not description:
        return 0

    if any(keyword in description for keyword in ("sell", "disposition", "disposed", "forfeit", "surrender", "issue out", "cancel")):
        return -1
    if any(keyword in description for keyword in ("buy", "purchase", "acquire", "award", "exercise", "subscription", "option", "grant", "issue", "receive", "vest", "transfer in")):
        return 1
    return 0


def _pick_tx_time(row: dict[str, Any]) -> datetime | None:
    raw = (
        row.get("filingDate")
        or row.get("transactionDate")
        or row.get("date")
        or row.get("period")
        or row.get("event_date")
        or row.get("timestamp")
    )
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        try:
            ms = float(raw)
            if ms > 0:
                return datetime.fromtimestamp(ms, tz=timezone.utc)
        except (TypeError, ValueError):
            return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        if "/" in text:
            try:
                parsed = datetime.strptime(text[:10], "%Y/%m/%d").replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                return None
        return None
