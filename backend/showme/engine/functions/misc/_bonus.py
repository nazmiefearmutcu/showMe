"""Bonus fonksiyonlar — Plan §26.2 'Spec'te olmayan' davetine cevap.

LITM — Litigation Monitor (SEC EDGAR 8-K items 1.03 / 1.04 litigation; 3.03 / 5.02 / 5.03 governance, labelled apart)
MOSS — Most Volatile (annualized vol ranking)
CHGS — Chart Studies preset (TECH'in hızlı çağrı sürümü)
APPL — Applicable Industry/Sector codes (GICS lookup)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import EXCHANGE_LEGEND, reference_profile


@FunctionRegistry.register
class LITMFunction(BaseFunction):
    """LITM — Litigation Monitor."""
    code = "LITM"
    name = "Litigation Monitor"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"
    description = "Recent 8-K items 1.03/1.04 (bankruptcy, mine safety) within the lookback; 3.03/5.02/5.03 governance items are labelled apart."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("LITM requires an instrument symbol")
        # Default-polarity flip (2026-09-08): LITM now hits the live SEC
        # EDGAR feed by default; ``reference=true`` opts back into the
        # labelled local model template.
        live = not _truthy(params.get("reference"))
        if not live or instrument.asset_class.value != "EQUITY" or not self.deps.sec_edgar:
            reason = (
                "LITM live SEC EDGAR feed is not applicable for this asset class."
                if instrument.asset_class.value != "EQUITY"
                else "SEC EDGAR adapter unavailable; litigation monitor is showing its labelled local model."
            )
            warnings = [reason] if live else []
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_fallback_litm(instrument),
                                  sources=["litigation_monitor_model"],
                                  warnings=warnings,
                                  metadata={"live": False, "fallback": True,
                                            "data_mode": "modeled"})
        from showme.engine.functions.equity.cact import CACTFunction
        cact = CACTFunction(self.deps)
        timeout = max(1.0, min(float(params.get("sec_timeout", 3)), 5.0))
        # Scan every 8-K row of the EDGAR filing frame, not just the newest one.
        scan_limit = max(1, min(int(params.get("max_documents") or _LITM_SCAN_LIMIT), _LITM_SCAN_LIMIT))
        res = await cact.execute(instrument=instrument, sec_timeout=timeout,
                                 yfinance_timeout=max(1.0, min(float(params.get("yfinance_timeout", 3)), 5.0)),
                                 max_documents=scan_limit)
        events = (res.data or {}).get("events_8k", []) or []
        frame = (res.data or {}).get("sec_filings")
        frame_has_items = (
            frame is not None and hasattr(frame, "columns")
            and "form" in frame.columns and "items" in frame.columns
        )
        scanned = _scan_8k_candidates(events, frame if frame_has_items else None, scan_limit)
        # LITM#2: the lookback input bounds the scan. Undated rows are kept.
        months = _lookback_months(params.get("months"))
        window_from = (datetime.now(timezone.utc).date() - timedelta(days=round(months * 30.44))).isoformat()
        scanned = [e for e in scanned if _on_or_after(e.get("filing_date"), window_from)]
        classifiable = frame_has_items or any(e.get("item_codes") or e.get("code") for e in events)
        keep = _LITM_KEEP_ITEMS
        litm = []
        for e in scanned:
            matched = [c for c in e["item_codes"] if c in keep]
            if matched:
                # LITM#3: legal-proceeding items and governance items are labelled apart.
                category = "litigation" if any(c in _LITM_LITIGATION_ITEMS for c in matched) else "governance"
                litm.append({**e, "code": ",".join(matched), "matched_codes": matched, "category": category})
        dates = sorted(str(e["filing_date"]) for e in scanned if e.get("filing_date"))
        scan_window = {"from": dates[0], "to": dates[-1]} if dates else None
        rows = [{
            "symbol": instrument.symbol,
            "event_type": f"{e['category']}_item",
            "category": e["category"],
            "item_code": e.get("code"),
            "filing_date": e.get("filing_date") or e.get("report_date"),
            "severity": "review",
            "source_mode": "sec_edgar_8k",
            "accession": e.get("accession"),
            "document": e.get("document"),
        } for e in litm]
        if not classifiable:
            status = "provider_unavailable"
            rows = [{
                "symbol": instrument.symbol,
                "event_type": "item_codes_unavailable",
                "item_code": None,
                "filing_date": None,
                "severity": "unknown",
                "source_mode": "sec_edgar_items_missing",
                "all_8k_events": len(scanned),
            }]
            reason = ("SEC EDGAR filing rows carry no 8-K item codes, so litigation items cannot be "
                      "classified; this is not a verified absence of events.")
        elif not rows and not scanned:
            status = "empty"
            reason = ("The SEC filing feed has no 8-K filings in the scanned window, so there were no 8-K "
                      "items to classify; this is not a verified absence of litigation events.")
            rows = [{
                "symbol": instrument.symbol,
                "event_type": "no_8k_filings_in_window",
                "item_code": None,
                "filing_date": None,
                "severity": "none",
                "source_mode": "sec_edgar_no_8k_rows",
                "all_8k_events": 0,
                "scanned_8k": 0,
                "scan_window": None,
            }]
        elif not rows:
            status = "empty"
            reason = None
            rows = [{
                "symbol": instrument.symbol,
                "event_type": "no_litigation_event_found",
                "item_code": None,
                "filing_date": None,
                "severity": "none",
                "source_mode": "sec_edgar_no_matching_8k_item",
                "all_8k_events": len(scanned),
                "scanned_8k": len(scanned),
                "scan_window": scan_window,
            }]
        else:
            status = "ok"
            reason = None
        payload = {
            "status": status,
            "rows": rows,
            "litigation_filings": litm,
            "kept_item_codes": sorted(keep),
            "litigation_codes": sorted(_LITM_LITIGATION_ITEMS),
            "governance_codes": sorted(_LITM_GOVERNANCE_ITEMS),
            "lookback_months": months,
            "window_from": window_from,
            "all_8k_events": len(scanned),
            "scanned_8k": len(scanned),
            "scan_window": scan_window,
            "item_codes_available": bool(frame_has_items),
            "methodology": "LITM reads the 8-K item codes of every 8-K row in the SEC EDGAR filing feed dated within the lookback (months, default 24) and keeps items 1.03 and 1.04 (category litigation) and 3.03, 5.02 and 5.03 (category governance, not legal proceedings). An empty result is reported only after the full scan (scanned_8k rows); without item codes the status is provider_unavailable.",
            "field_dictionary": {
                "item_code": "SEC 8-K item code(s) matched by the filter.",
                "category": "litigation (items 1.03, 1.04) or governance (items 3.03, 5.02, 5.03).",
                "event_type": "litigation_item or governance_item, per the category.",
                "severity": "ShowMe review flag, not legal advice.",
                "source_mode": "SEC evidence state for the row.",
                "scanned_8k": "Number of 8-K filing rows examined.",
            },
        }
        if reason:
            payload["reason"] = reason
            payload["next_actions"] = ["Retry once the SEC EDGAR filing feed returns item codes."]
        return FunctionResult(code=self.code, instrument=instrument,
                              data=payload,
                              sources=res.sources or ["litigation_monitor_model"],
                              metadata={"provider_errors": (res.metadata or {}).get("provider_errors", [])})


_LITM_SCAN_LIMIT = 1000
# Narrow filter: only these 8-K item codes count as litigation/governance events.
keep = {"1.03", "1.04", "3.03", "5.02", "5.03"}
_LITM_KEEP_ITEMS = frozenset(keep)
# LITM#3: 1.03 (bankruptcy/receivership) and 1.04 (mine safety) are legal-proceeding
# items; 3.03, 5.02 and 5.03 are security-holder-rights and officer/charter changes.
_LITM_LITIGATION_ITEMS = frozenset({"1.03", "1.04"})
_LITM_GOVERNANCE_ITEMS = frozenset({"3.03", "5.02", "5.03"})
_LITM_LOOKBACK_DEFAULT = 24
_LITM_LOOKBACK_RANGE = (3, 60)


def _lookback_months(value: Any) -> int:
    """LITM#2: the seed's months input (3-60, default 24), clamped to that range."""
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: float('inf') parses but cannot be converted to int.
        parsed = _LITM_LOOKBACK_DEFAULT
    return max(_LITM_LOOKBACK_RANGE[0], min(_LITM_LOOKBACK_RANGE[1], parsed))


def _on_or_after(value: Any, cutoff_iso: str) -> bool:
    """True when a filing is dated on or after the lookback start. A row without a
    parseable date is kept rather than silently dropped from the scan."""
    text = str(value or "")[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return True
    return text >= cutoff_iso


def _split_item_codes(raw: Any) -> list[str]:
    if not isinstance(raw, str):
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _scan_8k_candidates(events: list[dict[str, Any]], frame: Any, scan_limit: int) -> list[dict[str, Any]]:
    """Every 8-K candidate with its item codes; frame rows win over CACT event rows
    for the same accession. Rows without a code list contribute no codes."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if frame is not None and hasattr(frame, "iterrows"):
        eight_k = frame[frame["form"].astype(str).str.startswith("8-K")].head(scan_limit)
        for _, r in eight_k.iterrows():
            acc = str(r.get("accessionNumber") or "")
            seen.add(acc)
            out.append({
                "accession": acc or None,
                "filing_date": r.get("filingDate"),
                "report_date": r.get("reportDate"),
                "document": r.get("primaryDocument"),
                "item_codes": _split_item_codes(r.get("items")),
            })
    for e in events:
        if not isinstance(e, dict):
            continue
        # CACT puts a placeholder ({category, status: provider_unavailable})
        # into events_8k when the feed has no 8-K rows: that is not a filing
        # and must never count as a scanned 8-K (review of LITM#1).
        if str(e.get("status") or "").lower() in {"provider_unavailable", "unavailable", "empty"} or not (
            e.get("accession") or e.get("filing_date") or e.get("document")
        ):
            continue
        acc = str(e.get("accession") or "")
        if acc and acc in seen:
            continue
        if acc:
            seen.add(acc)
        codes = _split_item_codes(e.get("items")) or _split_item_codes(e.get("code"))
        out.append({
            "accession": e.get("accession"),
            "filing_date": e.get("filing_date"),
            "report_date": e.get("report_date"),
            "document": e.get("document"),
            "item_codes": codes,
        })
    return out


def _fallback_litm(instrument: Instrument) -> dict[str, Any]:
    asset_class = instrument.asset_class.value
    status = "local_litigation_model" if asset_class == "EQUITY" else f"not_applicable_for_{asset_class.lower()}"
    return {
        "status": "provider_unavailable" if asset_class == "EQUITY" else "not_applicable",
        "rows": [{
            "symbol": instrument.symbol,
            "event_type": "provider_unavailable",
            "item_code": None,
            "filing_date": None,
            "severity": "unknown",
            "source_mode": status,
        }],
        "litigation_filings": [{
            "symbol": instrument.symbol,
            "code": None,
            "category": "litigation",
            "status": status,
        }],
        "all_8k_events": 0,
        "methodology": "LITM requires SEC 8-K filing/event rows and filters them by litigation/governance item code.",
    }


@FunctionRegistry.register
class MOSSFunction(BaseFunction):
    """MOSS — Most Volatile (realised vol ranking across a universe)."""
    code = "MOSS"
    name = "Most Volatile"
    category = "screen"
    description = "Realised volatility leaderboard across watchlist or universe."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = _parse_symbol_list(
            params.get("universe") or params.get("symbols") or _moss_default_universe()
        )
        if instrument and instrument.symbol not in symbols:
            symbols.insert(0, instrument.symbol)
        symbols = list(dict.fromkeys(str(s).upper() for s in symbols if str(s).strip()))
        days = max(20, min(int(params.get("days", 90) or 90), 365 * 3))
        limit = max(1, min(int(params.get("limit", len(symbols)) or len(symbols)), 200))
        # Default-polarity flip (2026-09-08): the realized-vol screen is
        # live by default; ``reference=true`` serves the labelled template.
        if _truthy(params.get("reference")):
            rows = _moss_template(symbols, days)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_moss_payload(rows[:limit], [], symbols, days, live=False),
                sources=["volatility_model"],
                metadata={"universe_size": len(symbols), "days": days,
                          "live": False, "data_mode": "modeled"},
            )
        if not self.deps.yfinance:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_moss_unavailable(symbols, days, "yfinance provider is unavailable"),
                sources=["no_live_source"],
                metadata={"universe_size": len(symbols), "days": days, "live": False, "fallback": True},
            )
        # A realised-vol scan needs a few seconds per historical series on the
        # shared longest-history path; the generic route default (3s) would
        # cancel most of the cross-asset universe, so floor it at 6s.
        try:
            timeout = max(6.0, min(float(params.get("yfinance_timeout", 8) or 8), 10.0))
        except (TypeError, ValueError):
            timeout = 8.0
        # Bounded fan-out (WEI pattern): the default universe is now
        # cross-asset (~40+ symbols), so the scan runs under a semaphore with
        # a screen-level deadline and the provider rate-limit bucket bypassed
        # (bounded concurrency replaces it). Symbols still pending at the
        # deadline are cancelled AND emitted as explicit vol=null rows below.
        _screen_timeout_raw = params.get("screen_timeout", 11.0)
        try:
            screen_timeout = max(1.0, min(float(_screen_timeout_raw or 11.0), 12.0))
        except (TypeError, ValueError):
            screen_timeout = 11.0
        try:
            concurrency = max(1, min(int(float(params.get("quote_concurrency", 12) or 12)), 12))
        except (TypeError, ValueError):
            concurrency = 12
        semaphore = asyncio.Semaphore(concurrency)

        async def _vol(s):
            async with semaphore:
                try:
                    inst = await self.deps.symbol_registry.resolve(s) if self.deps.symbol_registry else None
                    if not inst:
                        # Asset-class hint (not a blanket EQUITY) so the
                        # cross-asset default universe maps correctly on the
                        # provider (BTCUSDT -> BTC-USD, EURUSD=X stays FX).
                        inst = Instrument(
                            symbol=s,
                            asset_class=AssetClass(_moss_asset_class_hint(s)),
                        )
                    df = await asyncio.wait_for(
                        self.deps.yfinance.fetch(DataRequest(
                            kind=DataKind.OHLCV,
                            instrument=inst,
                            start=datetime.now(timezone.utc) - timedelta(days=days),
                            interval="1d",
                            extra={
                                "bypass_rate_limit": True,
                                # A realised-vol screen only needs the requested
                                # lookback window; without this the shared
                                # longest-history race would pull decades of
                                # daily bars per symbol and blow the scan budget.
                                "deep_history": False,
                            },
                        )),
                        timeout=timeout,
                    )
                    if df.empty:
                        return {"symbol": s, "error": "empty price history"}
                    rets = df["close"].pct_change().dropna()
                    if rets.empty:
                        return {"symbol": s, "error": "not enough returns"}
                    periods = _moss_periods_per_year(inst.asset_class if inst else None)
                    vol = float(rets.std() * (periods ** 0.5))
                    return {
                        "row": {
                            "symbol": s,
                            "asset_class": inst.asset_class.value if inst else "EQUITY",
                            "vol_annualized": vol,
                            "vol": vol,
                            "vol_pct": vol * 100,
                            "periods_per_year": periods,
                            "samples": int(len(rets)),
                            "last_close": float(df["close"].iloc[-1]),
                            "start": _date_label(df.index[0]),
                            "end": _date_label(df.index[-1]),
                        },
                        "history": _moss_history(df, s, periods),
                    }
                except Exception as exc:  # noqa: BLE001
                    return {"symbol": s, "error": str(exc)}

        tasks = [asyncio.create_task(_vol(s)) for s in symbols]
        done, pending = await asyncio.wait(tasks, timeout=screen_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        results: list[Any] = []
        for task in done:
            try:
                results.append(task.result())
            except Exception as exc:  # noqa: BLE001
                results.append({"error": str(exc)})
        provider_errors = [
            f"{r.get('symbol')}: {r.get('error')}"
            for r in results
            if isinstance(r, dict) and r.get("error")
        ]
        if pending:
            provider_errors.append(
                f"{len(pending)} symbol(s) exceeded the {screen_timeout:.0f}s scan budget"
            )
        good = [r for r in results if isinstance(r, dict) and isinstance(r.get("row"), dict)]
        resolved_symbols = {str(r["row"].get("symbol") or "").upper() for r in good}
        rows = [r["row"] for r in good]
        rows.sort(key=lambda x: float(x.get("vol_annualized") or 0.0), reverse=True)
        # Requirement: pending/unresolved symbols are NEVER silently dropped.
        # They ride along as explicit vol=null rows (state="unavailable") so
        # the pane can label them instead of showing a smaller universe than
        # the one it claims to scan.
        unavailable_rows: list[dict[str, Any]] = [
            {
                "symbol": symbol,
                "asset_class": _moss_asset_class_hint(symbol),
                "vol_annualized": None,
                "vol": None,
                "vol_pct": None,
                "samples": 0,
                "last_close": None,
                "state": "unavailable",
            }
            for symbol in symbols
            if symbol.upper() not in resolved_symbols
        ]
        if not rows:
            # R2 M-2: mirror the no-adapter fallback envelope — the
            # zero-rows failure path must carry fallback/live markers and
            # surface the provider errors as warnings, not metadata-only.
            reason = "no symbols returned usable price history"
            envelope = _moss_unavailable(symbols, days, reason)
            if unavailable_rows:
                envelope["rows"] = unavailable_rows
                envelope["unavailable"] = len(unavailable_rows)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=envelope,
                sources=["no_live_source"],
                metadata={
                    "universe_size": len(symbols),
                    "days": days,
                    "provider_errors": provider_errors,
                    "live": False,
                    "fallback": True,
                    "data_mode": "provider_unavailable",
                },
                warnings=[reason, *provider_errors[:10]],
            )
        histories = {r["row"]["symbol"]: r.get("history", []) for r in good}
        top_symbol = rows[0]["symbol"]
        history = histories.get(top_symbol, [])
        rows = [*rows, *unavailable_rows][:limit]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_moss_payload(rows, history, symbols, days, live=True),
            sources=["yfinance"],
            metadata={
                "universe_size": len(symbols),
                "scanned": len(symbols),
                "resolved": len(good),
                "unavailable": len(unavailable_rows),
                "days": days,
                "live": True,
                "top_symbol": top_symbol,
                "history_points": len(history),
                "provider_errors": provider_errors[:10],
            },
        )


@FunctionRegistry.register
class CHGSFunction(BaseFunction):
    """CHGS — Chart Studies (preset TECH bundle)."""
    code = "CHGS"
    name = "Chart Studies"
    asset_classes = (
        AssetClass.EQUITY,
        AssetClass.CRYPTO,
        AssetClass.ETF,
        AssetClass.FX,
        AssetClass.COMMODITY,
        AssetClass.BOND,
    )
    category = "chart"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("CHGS requires an instrument symbol")
        # Default-polarity flip (2026-09-08): CHGS defers to the live TECH
        # studies by default; ``reference=true`` serves the labelled
        # synthetic chart template.
        if _truthy(params.get("reference")):
            rows = _chart_template(instrument.symbol)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "reference",
                    "data_mode": "modeled",
                    "symbol": instrument.symbol,
                    "last": rows[-1]["close"],
                    "rows": rows,
                    "rsi_14": 54.2,
                    "sma_20": rows[-1]["close"] * 0.985,
                    "sma_50": rows[-1]["close"] * 0.962,
                },
                metadata={"alias_of": "TECH", "live": False, "data_mode": "modeled"},
                sources=["showme_chart_model"],
            )
        from showme.engine.functions.chart.tech import TECHFunction
        tech_params = dict(params)
        # CHGS#2: the router injects a routed agent default ``limit=6`` into
        # every call. TECH reads ``limit`` as the bar tail and clamps it to
        # 60..5000, so a 1Y request came back as 60 bars (~3 months). CHGS has
        # no tail/limit input of its own; its window is driven by ``days``, so
        # the leaked limit is dropped and TECH's manifest tail default applies.
        # An explicit ``tail``/``bars`` from the caller still wins.
        if "tail" not in tech_params and "bars" not in tech_params:
            tech_params.pop("limit", None)
        tech = TECHFunction(self.deps)
        result = await tech.execute(instrument=instrument, **tech_params)
        return FunctionResult(
            code=self.code,
            instrument=result.instrument,
            data=result.data,
            metadata={**(result.metadata or {}), "alias_of": "TECH"},
            sources=result.sources,
            warnings=result.warnings,
        )


@FunctionRegistry.register
class APPLFunction(BaseFunction):
    """APPL — Applicable industry/sector taxonomy lookup."""
    code = "APPL"
    name = "Industry Taxonomy"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("APPL requires an instrument symbol")
        # Default-polarity flip (2026-09-08): APPL resolves the live
        # provider taxonomy by default; ``reference=true`` serves the
        # bundled crosswalk.
        reference = _truthy(params.get("reference"))
        live = (not reference) and _truthy(params.get("live", True))
        if not live or not self.deps.yfinance:
            if reference:
                reason = "reference=true; serving bundled taxonomy crosswalk"
            elif not live:
                reason = "live=false; serving bundled taxonomy template"
            else:
                reason = "yfinance adapter not configured; taxonomy fell back to bundled defaults"
            warnings = [reason] if (live and not self.deps.yfinance) else []
            status = "reference_only" if (reference or not live) else "provider_unavailable"
            template = _taxonomy_template(instrument, status, reason)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=template,
                sources=_appl_template_sources(template),
                metadata={"live": False, "fallback": True,
                          "data_mode": "reference",
                          "provider_errors": [reason]},
                warnings=warnings,
            )
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
        try:
            rd = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA,
                    instrument=instrument,
                    extra={"timeout": timeout},
                )),
                timeout=timeout + 1,
            )
        except Exception as exc:
            reason = f"yfinance refdata failed ({type(exc).__name__}); no live classification returned"
            template = _taxonomy_template(instrument, "provider_unavailable", reason)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=template,
                sources=_appl_template_sources(template),
                metadata={"live": False, "fallback": True, "data_mode": "reference",
                          "provider_errors": [f"yfinance: {exc}"]},
            )
        profile = reference_profile(instrument.symbol)
        rows = _taxonomy_rows(instrument, rd.sector, rd.industry, rd.country, rd.currency, rd.exchange, profile)
        # APPL#2: the GICS/NAICS/ICB crosswalk is bundled per symbol only.
        crosswalk_used = any(r.get("source_mode") == "reference_taxonomy_crosswalk" for r in rows)
        # APPL#1: CIK / SIC / fiscal year end / latest filings from SEC EDGAR.
        sec_timeout = max(1.0, min(float(params.get("sec_timeout", 4)), 6.0))
        ids, sec_error = await _appl_sec_identifiers(self.deps.sec_edgar, instrument.symbol, sec_timeout)
        rows.extend(_appl_identifier_rows(ids))
        live_sources = ["yfinance"]
        if crosswalk_used:
            live_sources.append("taxonomy_crosswalk_static")
        if ids["cik"]:
            live_sources.append("sec_edgar")
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"status": "ok",
                                     "sector": rd.sector, "industry": rd.industry,
                                     "country": rd.country, "currency": rd.currency,
                                     "exchange": rd.exchange,
                                     "exchange_name": EXCHANGE_LEGEND.get(str(rd.exchange or ""), rd.exchange),
                                     "crosswalk_status": "bundled" if crosswalk_used else "not_bundled",
                                     "cik": ids["cik"],
                                     "sic_code": ids["sic_code"],
                                     "sic_description": ids["sic_description"],
                                     "fiscal_year_end": ids["fiscal_year_end"],
                                     "latest_filings": ids["latest_filings"],
                                     "rows": rows,
                                     "peers": [{"symbol": s, "peer_set": "reference_sector_peer"} for s in profile.get("peers", [])],
                                     "methodology": "APPL combines live provider sector/industry fields and keyless SEC EDGAR identifiers (CIK, SIC, fiscal year end, latest 10-K/10-Q/8-K filings) with a labelled GICS/NAICS/ICB crosswalk only where one is bundled for the symbol (crosswalk_status). Exchange codes are expanded for end-user readability.",
                                     "field_dictionary": {
                                         "level": "Taxonomy level or provider field.",
                                         "classification": "Human-readable classification value.",
                                         "source_mode": "live_yfinance, sec_edgar_submissions, or labelled reference taxonomy crosswalk.",
                                         "crosswalk_status": "bundled when a static GICS/NAICS/ICB crosswalk exists for the symbol, else not_bundled.",
                                     }},
                              sources=live_sources,
                              warnings=[sec_error] if sec_error else [],
                              metadata={"live": True, "data_mode": "live_yfinance"})


_APPL_FILING_FORMS = ("10-K", "10-Q", "8-K")


def _appl_template_sources(template: dict[str, Any]) -> list[str]:
    """APPL#4: template payloads name the static crosswalk only when it supplied rows."""
    sources = ["taxonomy_model"]
    if template.get("crosswalk_status") == "bundled":
        sources.append("taxonomy_crosswalk_static")
    return sources


async def _appl_sec_identifiers(sec: Any, symbol: str, timeout: float) -> tuple[dict[str, Any], str | None]:
    """CIK, SIC, fiscal year end and latest filings from SEC EDGAR (keyless).

    Each field stays None unless its lookup succeeded: nothing is inferred or
    stubbed. Returns (identifiers, warning-or-None).
    """
    out: dict[str, Any] = {"cik": None, "sic_code": None, "sic_description": None,
                           "fiscal_year_end": None, "latest_filings": []}
    if sec is None:
        return out, "sec_edgar adapter not configured; CIK, SIC and fiscal year end not resolved"
    try:
        cik = await asyncio.wait_for(sec.cik_for(symbol), timeout=timeout)
        if not cik:
            return out, f"sec_edgar: no CIK found for {symbol}"
        sub = await asyncio.wait_for(sec.submissions(str(cik)), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - reported as a warning, never raised
        return out, f"sec_edgar: {type(exc).__name__}: {exc}"[:200]
    if not isinstance(sub, dict):
        return out, "sec_edgar: submissions payload was not an object"
    out["cik"] = str(cik)
    out["sic_code"] = str(sub.get("sic") or "") or None
    out["sic_description"] = sub.get("sicDescription") or None
    out["fiscal_year_end"] = str(sub.get("fiscalYearEnd") or "") or None
    recent = (sub.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []

    def _nth(key: str, i: int) -> Any:
        lst = recent.get(key) or []
        return lst[i] if i < len(lst) else None

    filings: list[dict[str, Any]] = []
    for i, form in enumerate(forms):
        if str(form or "").upper() not in _APPL_FILING_FORMS:
            continue
        filings.append({
            "form": form,
            "filing_date": _nth("filingDate", i),
            "accession": _nth("accessionNumber", i),
            "document": _nth("primaryDocument", i),
        })
        if len(filings) >= 5:
            break
    out["latest_filings"] = filings
    return out, None


def _appl_identifier_rows(ids: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for level, key in (("CIK", "cik"), ("SIC", "sic_code"),
                       ("SIC description", "sic_description"),
                       ("Fiscal year end (MMDD)", "fiscal_year_end")):
        value = ids.get(key)
        if value:
            rows.append({"level": level, "classification": value, "source_mode": "sec_edgar_submissions"})
    return rows


def _taxonomy_template(instrument: Instrument, status: str, reason: str) -> dict[str, Any]:
    """Honest no-provider payload: no sector/industry/exchange is invented.

    APPL#3 (review): the old template stamped placeholder classifications
    ("Equity", "Listed Security", "Exchange", "Global") as data. Those values are
    now null; only real bundled crosswalk rows and the instrument-registry asset
    class remain in ``rows``.
    """
    profile = reference_profile(instrument.symbol)
    rows = _taxonomy_rows(instrument, None, None, None, None, None, profile,
                          source_mode="reference_taxonomy_template")
    rows = [r for r in rows if r.get("classification") is not None]
    return {
        "status": status,
        "reason": reason,
        "next_actions": ["Retry with live=true when the yfinance refdata provider is reachable."],
        "sector": None,
        "industry": None,
        "country": None,
        "currency": None,
        "exchange": None,
        "exchange_name": None,
        "crosswalk_status": "bundled" if any(
            r.get("source_mode") == "reference_taxonomy_crosswalk" for r in rows) else "not_bundled",
        "rows": rows,
        "methodology": "No live provider classification was returned, so provider fields are null. Only bundled crosswalk rows and the instrument-registry asset class are shown.",
        "field_dictionary": {
            "level": "Taxonomy level or provider field.",
            "classification": "Human-readable classification value; null fields are not available.",
            "source_mode": "reference_taxonomy_crosswalk or instrument_registry.",
        },
    }


def _taxonomy_rows(
    instrument: Instrument,
    sector: Any,
    industry: Any,
    country: Any,
    currency: Any,
    exchange: Any,
    profile: dict[str, Any],
    source_mode: str = "live_yfinance",
) -> list[dict[str, Any]]:
    # APPL#3: the provider-field rows carry the caller's source_mode, so the
    # reference template is never labelled as a live yfinance value.
    rows = [
        {"level": "Provider sector", "classification": sector, "source_mode": source_mode},
        {"level": "Provider industry", "classification": industry, "source_mode": source_mode},
        {"level": "Exchange", "classification": EXCHANGE_LEGEND.get(str(exchange or ""), exchange), "raw_code": exchange, "source_mode": source_mode},
        {"level": "Country", "classification": country, "source_mode": source_mode},
        {"level": "Currency", "classification": currency, "source_mode": source_mode},
    ]
    for key, label in [
        ("gics_sector", "GICS sector"),
        ("gics_industry_group", "GICS industry group"),
        ("gics_industry", "GICS industry"),
        ("gics_sub_industry", "GICS sub-industry"),
        ("naics", "NAICS"),
        ("icb", "ICB"),
    ]:
        value = profile.get(key)
        if value:
            rows.append({"level": label, "classification": value, "source_mode": "reference_taxonomy_crosswalk"})
    if len(rows) <= 5:
        rows.append({"level": "Asset class", "classification": instrument.asset_class.value, "source_mode": "instrument_registry"})
    return rows


def _chart_template(symbol: str) -> list[dict[str, Any]]:
    base = 78000.0 if symbol.upper().endswith(("USDT", "USD")) else 100.0
    return [
        {
            "date": f"template-{idx + 1:02d}",
            "open": round(base * (1 + (idx - 5) * 0.003), 4),
            "high": round(base * (1 + (idx - 5) * 0.003 + 0.008), 4),
            "low": round(base * (1 + (idx - 5) * 0.003 - 0.007), 4),
            "close": round(base * (1 + (idx - 5) * 0.003 + 0.002), 4),
            "volume": 1_000_000 + idx * 75_000,
        }
        for idx in range(10)
    ]


def _parse_symbol_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


# ── MOSS — default cross-asset scan universe ─────────────────────────────
# Liquid names only: the realised-vol scan fetches daily OHLCV per symbol,
# so the default stays bounded (~40 symbols) and runs under a semaphore with
# a screen deadline. Equities are shared with MOST's verified subset; the
# crypto/FX/commodity legs were live-verified on 2026-09-15.
_MOSS_EQUITY_COUNT = 24
_MOSS_CRYPTO_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
)
_MOSS_FX_SYMBOLS: tuple[str, ...] = (
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X",
    "USDCAD=X", "USDCHF=X", "NZDUSD=X", "EURJPY=X",
)
_MOSS_COMMODITY_SYMBOLS: tuple[str, ...] = ("GC=F", "CL=F", "SI=F", "NG=F")
_MOSS_EQUITY_FALLBACK: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "LLY",
    "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ", "WMT", "ABBV",
    "NFLX", "BAC", "KO", "CRM",
)


def _moss_default_universe() -> list[str]:
    """Default MOSS scan universe: ~24 equities + crypto + FX + commodities.

    The equity leg imports MOST's verified liquid subset so the two screens
    cannot drift; if that import ever fails the curated fallback keeps the
    screen working.
    """
    equities: tuple[str, ...] = _MOSS_EQUITY_FALLBACK
    try:
        from showme.engine.functions.screen._funcs import _MOST_EQUITY_SYMBOLS

        if _MOST_EQUITY_SYMBOLS:
            equities = tuple(_MOST_EQUITY_SYMBOLS)[:_MOSS_EQUITY_COUNT]
    except Exception:  # noqa: BLE001
        equities = _MOSS_EQUITY_FALLBACK
    return [
        *equities,
        *_MOSS_CRYPTO_SYMBOLS,
        *_MOSS_FX_SYMBOLS,
        *_MOSS_COMMODITY_SYMBOLS,
    ]


def _moss_asset_class_hint(symbol: str) -> str:
    """Uppercase ``AssetClass`` value for a raw screen symbol."""
    upper = symbol.upper()
    if upper.endswith("=X"):
        return AssetClass.FX.value
    if upper.endswith("=F"):
        return AssetClass.COMMODITY.value
    if upper.endswith(("USDT", "USDC")) or (upper.endswith("USD") and len(upper) > 3):
        return AssetClass.CRYPTO.value
    return AssetClass.EQUITY.value


def _moss_payload(
    rows: list[dict[str, Any]],
    history: list[dict[str, Any]],
    symbols: list[str],
    days: int,
    *,
    live: bool,
) -> dict[str, Any]:
    top_symbol = rows[0]["symbol"] if rows else None
    return {
        "status": "ok" if live else "reference",
        "data_mode": "live_yfinance" if live else "modeled",
        "rows": rows,
        "history": history,
        "universe": symbols,
        "lookback_days": days,
        "top_symbol": top_symbol,
        "live": live,
        "methodology": (
            "Ranks the selected universe by annualized realized volatility: "
            "std(daily close-to-close returns) * sqrt(252) for equities, FX and commodities, "
            "and * sqrt(365) for crypto (24/7 daily closes; each row carries periods_per_year). "
            "The default universe is a "
            "liquid cross-asset sample (equities + crypto + FX + commodities); symbols the "
            "provider does not answer inside the scan budget are emitted with vol=null "
            "(state=unavailable) rather than dropped. The chart shows the rolling 20-session "
            "annualized volatility history for the current top symbol."
        ),
        "field_dictionary": {
            "vol_annualized": "Annualized realized volatility as a decimal.",
            "vol_pct": "Annualized realized volatility in percent.",
            "samples": "Number of daily return observations used.",
            "history.vol": "Rolling 20-session annualized realized volatility for the top symbol.",
        },
    }


def _moss_unavailable(symbols: list[str], days: int, reason: str) -> dict[str, Any]:
    return {
        "status": "provider_unavailable",
        "reason": reason,
        "rows": [],
        "history": [],
        "universe": symbols,
        "lookback_days": days,
        "next_actions": ["Check the yfinance provider and rerun with a smaller universe or shorter range."],
        "methodology": "Requires daily close history to compute realized volatility.",
    }


_MOSS_EXCHANGE_PERIODS = 252  # equity, FX and commodity exchange sessions
_MOSS_CRYPTO_PERIODS = 365  # crypto trades every calendar day, so its daily closes run 365 a year


def _moss_periods_per_year(asset_class: Any) -> int:
    """Annualization factor for daily returns: 365 for 24/7 crypto, 252 otherwise."""
    value = getattr(asset_class, "value", asset_class)
    if str(value or "").upper() == AssetClass.CRYPTO.value.upper():
        return _MOSS_CRYPTO_PERIODS
    return _MOSS_EXCHANGE_PERIODS


def _moss_history(df: Any, symbol: str, periods: int = _MOSS_EXCHANGE_PERIODS) -> list[dict[str, Any]]:
    rets = df["close"].pct_change().dropna()
    window = min(20, max(5, len(rets) // 2))
    rolling = (rets.rolling(window=window).std() * (periods ** 0.5)).dropna()
    rows: list[dict[str, Any]] = []
    for idx, value in rolling.tail(90).items():
        rows.append({
            "date": _date_label(idx),
            "symbol": symbol,
            "vol": float(value),
            "vol_pct": float(value) * 100,
            "window": window,
        })
    return rows


def _date_label(value: Any) -> str:
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)


def _moss_template(symbols: list[str], days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, symbol in enumerate(dict.fromkeys(symbols)):
        upper = symbol.upper()
        if upper.endswith("=X"):
            base_vol = 0.11
            last_close = 1.08 + idx * 0.01
            asset_class = "fx"
        elif upper.endswith(("USDT", "USD")) and not upper.endswith("=F"):
            base_vol = 0.58
            last_close = 78000.0 - idx * 950
            asset_class = "crypto"
        elif upper.endswith("=F"):
            base_vol = 0.26
            last_close = 2350.0 + idx * 11
            asset_class = "commodity"
        elif upper.endswith(("EUR", "JPY", "GBP", "CHF", "CAD", "AUD")) and len(upper) == 6:
            base_vol = 0.11
            last_close = 1.08 + idx * 0.01
            asset_class = "fx"
        else:
            base_vol = 0.34
            last_close = 100.0 + idx * 7.5
            asset_class = "equity"
        vol = round(max(0.05, base_vol - idx * 0.012), 4)
        rows.append({
            "symbol": symbol,
            "asset_class": asset_class,
            "vol_annualized": vol,
            "vol": vol,
            "vol_pct": vol * 100,
            "samples": max(20, min(days, 252) - 1),
            "last_close": round(last_close, 4),
        })
    rows.sort(key=lambda item: item["vol_annualized"], reverse=True)
    return rows


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
