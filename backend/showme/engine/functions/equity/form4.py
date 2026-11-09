"""FORM4 — SEC Form 4 (insider transactions) calendar."""

from __future__ import annotations

import asyncio
import calendar
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
                                  metadata={"provider_errors": [f"sec_edgar: {str(e) or type(e).__name__}"]})
        # Aggregate counts
        rows = _filter_rows(rows, months=months, transaction_types=transaction_types)
        # FORM4#6: the yfinance rows are the returned table, so the same window and
        # transaction-type filters apply to them (they were returned unfiltered).
        have_yfin = bool(yfin_rows)
        if have_yfin:
            yfin_rows = _filter_rows(yfin_rows, months=months, transaction_types=transaction_types)
        parsed_rows = yfin_rows if have_yfin else _filing_rows(sym, rows)
        # FORM4#7: the monthly histogram counts the same rows the table shows (it used to
        # count the SEC filing list, which can be a different length and set).
        by_month: dict[str, int] = {}
        for r in parsed_rows:
            d = str(r.get("filingDate") or "")[:7]   # YYYY-MM
            if d:
                by_month[d] = by_month.get(d, 0) + 1
        # FORM4#4: without yfinance the SEC rows are filing metadata only (no filer,
        # shares, price or transaction). They are not live parsed trades.
        metadata_only = bool(parsed_rows) and not have_yfin
        if metadata_only:
            status = "metadata_only"
        elif parsed_rows:
            status = "ok"
        else:
            status = "empty" if have_yfin else "provider_unavailable"
        summary = _form4_summary_rows(parsed_rows)
        extra: dict[str, Any] = {}
        if metadata_only:
            extra["next_actions"] = [
                "Enable yfinance holdings to get per-trade insider rows (filer, shares, price).",
                "Parsing the Form 4 XML ownership documents is needed for per-trade SEC values.",
            ]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": status,
                "data_mode": "delayed_reference" if (parsed_rows or have_yfin) else "provider_unavailable",
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
                **extra,
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
        # FORM4#8: no dated rows means no as-of date; never the request time.
        "as_of": None,
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
        raw_transaction = item.get("Transaction") or item.get("transaction")
        text = item.get("Text") or item.get("text")
        # FORM4#1: yfinance leaves Transaction blank for many filers and carries the
        # direction in Text ("Sale at price 325.75 per share."). Read both.
        transaction_type = _yfinance_transaction_type(raw_transaction, text)
        rows.append({
            "symbol": symbol,
            "filingDate": transaction_date,
            "transaction_date": transaction_date,
            "date": transaction_date,
            "filer": filer,
            "insider": filer,
            "position": item.get("Position") or item.get("position"),
            "role": item.get("Position") or item.get("position"),
            "transaction": raw_transaction or text,
            "transaction_type": transaction_type,
            "side": transaction_type,
            "shares": shares,
            "value": value,
            "notional": value,
            "ownership": item.get("Ownership") or item.get("ownership"),
            "source_mode": "yfinance_insider_transactions",
        })
    return [r for r in rows if r.get("insider") or r.get("transaction") or r.get("shares")]


def _yfinance_transaction_type(transaction: Any, text: Any) -> str:
    """Direction word for a yfinance insider row; ``""`` when neither field names one."""
    for raw in (transaction, text):
        value = str(raw or "").strip().lower()
        if not value:
            continue
        if value.startswith(("sale", "sell", "automatic sale", "disposition")):
            return "sell"
        if value.startswith(("purchase", "buy", "acquisition")):
            return "buy"
        if value.startswith("gift") or "stock gift" in value:
            return "gift"
        if "award" in value or "grant" in value:
            return "grant"
        if "exercise" in value:
            return "option_exercise"
    fallback = str(transaction or "").strip()
    return _normalize_transaction_type(fallback) if fallback else ""


def _filing_rows(symbol: str, filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in filings[:40]:
        filer = item.get("reportingOwner") or item.get("ownerName")
        filing_date = item.get("filingDate") or item.get("filing_date") or item.get("date")
        transaction_type = _normalize_transaction_type(item.get("transactionType") or item.get("acquiredDisposedCode") or item.get("type"))
        url = item.get("url")
        rows.append({
            "symbol": symbol,
            "filingDate": filing_date,
            "transaction_date": filing_date,
            "date": filing_date,
            "filer": filer,
            "insider": filer,
            "role": item.get("directorOfficerTitle") or item.get("officerTitle") or item.get("position") or item.get("positionTitle"),
            # FORM4#4: no description in the filing list means no transaction text; do not
            # invent a "Form 4 filing document" label for it.
            "transaction": _readable_transaction(item) if _has_description(item) else None,
            "transaction_type": transaction_type,
            "side": transaction_type,
            "acquiredDisposedCode": item.get("acquiredDisposedCode"),
            "shares": finite(item.get("transactionShares")),
            "value": finite(item.get("transactionValue")),
            "price": finite(item.get("transactionPricePerShare")),
            # Only an absolute link is a usable filing URL (a relative XSL stub is not).
            "filing_url": url if isinstance(url, str) and url.startswith(("http://", "https://")) else None,
            # The SEC adapter returns ``accession``; accept the raw EDGAR key too.
            "accession": item.get("accessionNumber") or item.get("accession"),
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
    # FORM4#8: a calendar-month lookback (6 months is not 186 days).
    return ts >= _months_back(datetime.now(timezone.utc), months)


def _months_back(now: datetime, months: int) -> datetime:
    total = now.year * 12 + (now.month - 1) - months
    year, month0 = divmod(total, 12)
    day = min(now.day, calendar.monthrange(year, month0 + 1)[1])
    return now.replace(year=year, month=month0 + 1, day=day)


def _normalize_transaction_type(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    if text in {"p", "purchase", "acquisition", "acquired"}:
        return "buy"
    if text in {"g", "grant", "award", "a"}:
        return "grant"
    if text in {"j", "option", "exercise", "x", "m", "c", "o"}:
        return "option_exercise"
    if text in {"e", "f", "h"}:
        return "other"
    if text in {"s", "d", "v", "r", "sell", "sale", "disposition", "disposed", "forfeit"}:
        return "sell"
    if "option" in text:
        return "option_exercise"
    if "other" in text:
        return "other"
    return text.replace(" ", "_")


def _has_description(item: dict[str, Any]) -> bool:
    return any(
        str(item.get(key) or "").strip()
        for key in ("transactionDescription", "transaction", "acquiredDisposedCode", "type")
    )


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
    shares_known = False
    shares_unknown = False
    net_notional = 0.0
    notional_known = False
    notional_unknown = False
    unclassified = 0
    buyers = set[str]()
    sellers = set[str]()
    latest_ts: datetime | None = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed = _direction(row)
        if parsed is None:
            unclassified += 1
        direction = parsed or 0
        shares = finite(row.get("shares") or row.get("share") or row.get("share_delta") or row.get("net_shares"))
        if shares is not None:
            if parsed is None:
                # FORM4#1: an unparsed direction is not a neutral one; it must not read as 0.
                shares_unknown = True
            else:
                # HNT-16: known-neutral transactions (gifts, J-other, grants) move no net.
                shares_known = True
                if direction < 0:
                    net_shares -= abs(shares)
                elif direction > 0:
                    net_shares += abs(shares)

        value = finite(row.get("value") or row.get("notional") or row.get("signed_value"))
        if value is not None:
            if parsed is None:
                notional_unknown = True
            else:
                notional_known = True
                if direction < 0:
                    net_notional -= abs(value)
                elif direction > 0:
                    net_notional += abs(value)
        elif shares is not None:
            price = finite(row.get("price") or row.get("unit_price") or row.get("price_per_share"))
            if price is not None:
                if parsed is None:
                    notional_unknown = True
                elif direction != 0:
                    notional = shares * price
                    net_notional += -abs(notional) if direction < 0 else abs(notional)
                    notional_known = True

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
        "unclassified_count": unclassified,
    }
    # Net is a computed flow only over parsed directions; when every contributing
    # row is unparsed it is null (unknown), never 0.
    if shares_known:
        out["net_shares"] = net_shares
    elif shares_unknown:
        out["net_shares"] = None
    if notional_known:
        out["net_notional"] = net_notional
    elif notional_unknown:
        out["net_notional"] = None
    if buyers:
        out["buyer_count"] = len(buyers)
    if sellers:
        out["seller_count"] = len(sellers)
    out["as_of"] = latest_ts.isoformat() if latest_ts is not None else None
    return out


def _infer_direction(row: dict[str, Any]) -> int:
    """Signed direction; unknown and known-neutral both read as 0 (see ``_direction``)."""
    direction = _direction(row)
    return 0 if direction is None else direction


def _direction(row: dict[str, Any]) -> int | None:
    """+1 buy, -1 sell, 0 known-neutral (gift, grant, other), None when not parseable."""
    code = str(
        row.get("acquiredDisposedCode")
        or row.get("transactionCode")
        or row.get("action")
        or row.get("transaction_type")
        or row.get("direction")
        or ""
    ).strip().lower()
    # HNT-16 fix: SEC Form 4 ``G`` (gift) and ``J`` (other) transactions are
    # not market purchases — classifying them as +1 inflated "net insider
    # buying" whenever an executive gifted shares. They now count as
    # neutral (direction 0), like the description-path default.
    # FORM4#3: P is the only open-market purchase code and S the only open-market
    # sale. X/M (derivative exercise, acquires common stock) and A (grant), E/H
    # (derivative expiration), F (tax/exercise-price withholding), C/O are not
    # buys or sales, so they are known-neutral rather than +1 / -1.
    if code in {"p", "buy"}:
        return 1
    if code in {"s", "d", "v", "r", "sell"}:
        return -1
    if code in {"a", "c", "e", "f", "g", "h", "j", "m", "o", "x", "gift", "grant", "other", "option_exercise"}:
        return 0

    description = str(
        row.get("transaction")
        or row.get("description")
        or row.get("transaction_description")
        or row.get("transaction_desc")
        or row.get("type")
        or row.get("action_type")
    ).strip().lower()
    if not description:
        return None

    if any(keyword in description for keyword in ("sell", "sale", "disposition", "disposed", "forfeit", "surrender", "issue out", "cancel")):
        return -1
    # HNT-16 fix: "grant"/"award" descriptions (yfinance "Stock Award(Grant)",
    # Transaction="Grant") follow the G-code treatment — neutral, not net buying.
    if any(keyword in description for keyword in ("gift", "grant", "award")):
        return 0
    # FORM4#3: derivative exercise / conversion is not an open-market purchase.
    if any(keyword in description for keyword in ("exercise", "option", "conversion")):
        return 0
    if any(keyword in description for keyword in ("buy", "purchase", "acquire", "subscription", "issue", "receive", "vest", "transfer in")):
        return 1
    return None


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
