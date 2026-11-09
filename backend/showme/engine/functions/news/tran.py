"""TRAN — Earnings Transcript or Release Viewer (keyless, SEC EDGAR primary).

Reader pane for earnings-call / investor-event transcripts. The DEFAULT path
fetches REAL, keyless data — there is no synthetic happy-path:

  1. ``transcript_text`` param — a user-pasted transcript is parsed into
     speaker-attributed utterances (the highest-fidelity source we can get
     without a paid provider).
  2. SEC EDGAR (keyless) — resolve ticker -> CIK, find the most recent 8-K
     earnings filing and pull its earnings press release Exhibit 99.x text.
     That text is an EARNINGS RELEASE, not a call transcript: it is returned
     with ``document_type="earnings_press_release"``, unattributed (no speaker
     headers exist in it) and never labelled as a call transcript.
  3. Local transcripts archive — if a transcript was previously ingested for
     the symbol it is served verbatim.
  4. Optional Whisper transcription for a supplied ``audio_url`` / ``audio_path``.

When every real source genuinely fails (network outage), TRAN returns
``status="provider_unavailable"`` with an honest warning + next_actions and
``utterances=[]`` — it never fabricates a transcript.
"""

from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
_FILING_INDEX = "https://www.sec.gov/cgi-bin/browse-edgar"
_SEC_UA_ENV = "SEC_EDGAR_USER_AGENT"


def _sec_headers() -> dict[str, str]:
    """SEC fair-access User-Agent: the operator's real contact, never a placeholder.

    The contact comes from ``SEC_EDGAR_USER_AGENT``. When it is unset the request
    still goes out with a bare product name and the run reports the missing contact.
    """
    contact = os.environ.get(_SEC_UA_ENV, "").strip()
    return {"User-Agent": contact or "showMe research"}

_METHODOLOGY = (
    "TRAN serves earnings-call / investor-event transcript text from real, keyless "
    "sources. If transcript_text is supplied it is parsed verbatim into "
    "speaker-attributed utterances. Otherwise TRAN resolves the ticker to a CIK via "
    "SEC EDGAR's company-tickers map, locates the most recent 8-K earnings filing, "
    "and extracts the earnings press release exhibit (Exhibit 99.x) text — the "
    "official quarterly disclosure, NOT a call transcript (document_type="
    "'earnings_press_release'). Its paragraphs are segmented into ordered rows "
    "{section='document', speaker=null, role='', utterance, timestamp_seconds}: "
    "no speaker is attributed because the release has no speaker headers. A "
    "transcript is attributed only from explicit 'Name -- Role' / 'Name:' headers. "
    "A previously ingested "
    "transcript in the local archive is served verbatim when present. For events with "
    "only an audio_url/audio_path, Whisper is attempted when configured; when Whisper "
    "is missing the pane reports data_mode='not_configured' and never fabricates text. "
    "Section/speaker filters apply post-load. The pane is read-only."
)

_FIELD_DICT = {
    "symbol": "Echoed input symbol.",
    "status": "ok / empty / not_configured / provider_unavailable.",
    "event": "Earnings event metadata (quarter, quarter_basis, event_date, form, accession, source_url).",
    "utterances[].position": "1-based order of the utterance within the document.",
    "document_type": "transcript (pasted, archived or audio) or earnings_press_release (SEC 8-K EX-99.x).",
    "utterances[].section": "prepared_remarks / qa for transcripts; document for an earnings release.",
    "utterances[].speaker": "Speaker name from an explicit source header; null when the source has none.",
    "utterances[].role": "Role/title from that speaker's explicit header (CEO, CFO, Operator, Analyst); empty otherwise.",
    "utterances[].utterance": "Verbatim utterance / paragraph text.",
    "utterances[].timestamp_seconds": "Offset from event start when available (else null).",
    "data_mode": "live_official (SEC 8-K), user_supplied, cached_snapshot (archive), or not_configured.",
}

_RELEASE_WARNING = (
    "Source is the company's 8-K earnings press release (Exhibit 99.x), not an "
    "earnings call transcript: no speaker headers exist, so no speaker is attributed."
)

# Financial-statement and boilerplate words that look like "Name:" headers in a
# press release table (e.g. "Operating expenses: ..."). A real speaker name never
# contains them.
_NON_NAME_TOKENS = {
    "operating", "expense", "expenses", "asset", "assets", "liability",
    "liabilities", "revenue", "revenues", "income", "note", "notes", "editors",
    "total", "net", "gross", "cash", "current", "non-current", "other",
    "research", "development", "selling", "general", "administrative", "stock",
    "shareholders", "equity", "earnings", "financial", "statement", "statements",
    "balance", "sheet", "products", "services", "segment", "segments", "quarter",
    "fiscal", "year", "ended", "condensed", "consolidated", "margin", "tax",
    "taxes", "dividends", "debt", "deferred", "retained", "common", "shares",
    "per", "share", "data", "unaudited", "audited", "table", "summary",
    "highlights", "safe", "harbor", "forward-looking",
}

_OK_STATUSES = {"ok", "empty"}


@FunctionRegistry.register
class TRANFunction(BaseFunction):
    code = "TRAN"
    name = "Earnings Transcript or Release"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError(
                "TRAN requires an instrument — pass `symbol=<ticker>` or open the pane via "
                "the symbol search so an earnings call transcript can be located."
            )
        symbol = instrument.symbol.upper()
        warnings: list[str] = []
        sources: list[str] = []
        section_filter = str(params.get("section") or "all").strip().lower()
        speaker_filter = _as_list(params.get("speaker_filter"))

        # The requested quarter selects the filing / archive row. An unreadable
        # label is an input error, never silently replaced by the latest filing.
        requested_quarter: str | None = None
        quarter_raw = str(params.get("quarter") or "").strip()
        if quarter_raw:
            requested_quarter = _normalize_quarter(quarter_raw)
            if requested_quarter is None:
                return FunctionResult(
                    code=self.code,
                    instrument=instrument,
                    data={
                        "symbol": symbol,
                        "status": "input_error",
                        "event": {"symbol": symbol, "quarter": None},
                        "utterances": [],
                        "rows": [],
                        "whisper": None,
                        "data_mode": "not_configured",
                        "methodology": _METHODOLOGY,
                        "field_dictionary": _FIELD_DICT,
                        "next_actions": [
                            "Use a quarter label such as Q3 FY26 (Q1-Q4, FY, and a two- or "
                            "four-digit year), or leave the quarter empty for the latest filing.",
                        ],
                        "cards": _cards(symbol, {}, 0, 0, "not_configured"),
                    },
                    sources=["no_live_source"],
                    warnings=[f"quarter '{quarter_raw}' is not a recognised quarter label"],
                    metadata={"data_state": "input_error", "data_mode": "not_configured"},
                )

        utterances: list[dict[str, Any]] = []
        event: dict[str, Any] = {"symbol": symbol, "quarter": requested_quarter}
        data_mode = "not_configured"
        document_type = "transcript"

        # 1) User-pasted transcript — highest fidelity, fully real.
        pasted = params.get("transcript_text") or params.get("transcript")
        if isinstance(pasted, str) and pasted.strip():
            utterances = _parse_transcript_text(pasted)
            if utterances:
                data_mode = "user_supplied"
                sources.append("user_supplied")
                event.setdefault("title", f"{symbol} pasted transcript")
                event["source"] = "user_supplied"
                if requested_quarter:
                    # TRAN#3: the pasted text is never matched to a filing, so the
                    # requested label is what the user said, not a derived fiscal quarter.
                    event["quarter_basis"] = (
                        "user-stated quarter label, not verified: the pasted text was not "
                        "matched to any filing or fiscal calendar"
                    )

        # 2) Local archive (previously ingested verbatim transcript).
        if not utterances:
            try:
                from showme.engine.services import transcripts_archive as archive
                # transcripts_archive exposes list_for_symbol (not list_events);
                # the old name raised AttributeError and silently killed this
                # cached-transcript source via the broad except below.
                if requested_quarter:
                    archived = archive.list_for_symbol(symbol, limit=50)
                    events = [
                        e for e in archived
                        if _normalize_quarter(str(e.get("quarter") or "")) == requested_quarter
                    ][:1]
                else:
                    events = archive.list_for_symbol(symbol, limit=1)
                if events:
                    ev = events[0]
                    utterances = _coerce_archive_utterances(ev)
                    if utterances:
                        data_mode = "cached_snapshot"
                        sources.append("transcripts_archive")
                        event.update({
                            "title": ev.get("title"),
                            "event_date": ev.get("event_date"),
                            "quarter": ev.get("quarter") or event.get("quarter"),
                            "quarter_basis": "archive label as ingested; the fiscal basis was not verified",
                            "source": "transcripts_archive",
                            "event_id": ev.get("event_id"),
                        })
            except Exception as e:  # noqa: BLE001 - archive optional
                warnings.append(f"transcripts_archive: {str(e) or type(e).__name__}")

        # 3) DEFAULT keyless live source — SEC EDGAR 8-K earnings exhibit.
        sec_error: str | None = None
        sec_unreachable = False
        if not utterances:
            if not os.environ.get(_SEC_UA_ENV, "").strip():
                warnings.append(
                    f"sec_edgar: {_SEC_UA_ENV} is not set; SEC fair-access asks for a real "
                    "contact address in the User-Agent."
                )
            # Only pass the quarter when one was asked for, so the lookup keeps its
            # default (newest filing) signature otherwise.
            sec_kwargs: dict[str, Any] = {"quarter": requested_quarter} if requested_quarter else {}
            try:
                ev_meta, body = await asyncio.wait_for(
                    _fetch_sec_earnings_press_release(symbol, deps=self.deps, **sec_kwargs),
                    timeout=float(params.get("sec_timeout", 15) or 15),
                )
                if body:
                    utterances = _parse_transcript_text(
                        body, default_section="document", allow_speaker_headers=False,
                    )
                    if utterances:
                        data_mode = "live_official"
                        document_type = "earnings_press_release"
                        sources.append("sec_edgar")
                        event.update(ev_meta)
                        warnings.append(_RELEASE_WARNING)
            except asyncio.TimeoutError:
                sec_error = "SEC EDGAR request timed out"
                sec_unreachable = True
            except _SecLookupError as e:
                # The filing is not there (unknown ticker, quarter with no 8-K): not an outage.
                sec_error = str(e)
            except Exception as e:  # noqa: BLE001 - record network failure honestly
                sec_error = f"{type(e).__name__}: {e}"
                sec_unreachable = True
        if sec_error:
            warnings.append(f"sec_edgar: {sec_error}")

        # 4) Optional Whisper transcription of supplied audio.
        whisper_result = None
        audio_url = params.get("audio_url")
        audio_path = params.get("audio_path")
        # Surface the transient "still warming" state whenever audio was supplied,
        # independent of whether an earlier source already produced text — the
        # caller asked us to use Whisper and is owed an honest status. Load
        # failures are permanent; only "not available, no load error" is transient.
        if audio_url or audio_path:
            try:
                from showme.whisper_analyzer import WhisperAnalyzer  # noqa: PLC0415
                if not WhisperAnalyzer.is_available() and WhisperAnalyzer.load_error() is None:
                    warnings.append("whisper: large-v3 not yet warmed, retry in ~30s")
            except Exception:  # noqa: BLE001 - singleton optional
                pass
        if (audio_url or audio_path) and not utterances:
            if audio_url:
                try:
                    from showme.engine.services.transcription import transcribe_url
                    whisper_result = await transcribe_url(
                        audio_url, language=params.get("language"),
                        model_name=params.get("model", "base"),
                    )
                except Exception as e:  # noqa: BLE001 - whisper optional
                    warnings.append(f"whisper: {str(e) or type(e).__name__}")
            if audio_path and not whisper_result:
                try:
                    from showme.engine.services.transcription import transcribe
                    whisper_result = await transcribe(
                        audio_path, language=params.get("language"),
                        model_name=params.get("model", "base"),
                    )
                except Exception as e:  # noqa: BLE001 - whisper optional
                    warnings.append(f"whisper local: {str(e) or type(e).__name__}")
            if whisper_result:
                text = whisper_result.get("text") if isinstance(whisper_result, dict) else None
                if text:
                    utterances = _parse_transcript_text(str(text))
                    if utterances:
                        data_mode = "live_official"
                        sources.append("whisper")
                        event["source"] = "whisper"

        # Apply section + speaker filters post-load.
        utterances = _apply_filters(utterances, section_filter, speaker_filter)
        for idx, row in enumerate(utterances, start=1):
            row["position"] = idx

        rows = utterances
        speakers = sorted({str(r.get("speaker") or "").strip() for r in rows if r.get("speaker")})

        # No real source produced anything → honest provider_unavailable.
        if not rows:
            network_failed = sec_unreachable
            status = "provider_unavailable" if network_failed else "empty"
            if network_failed:
                reason = f"SEC EDGAR was unreachable for {symbol}: {sec_error}."
            else:
                quarter_note = f" for quarter {requested_quarter}" if requested_quarter else ""
                reason = (
                    f"No earnings press release / transcript could be retrieved for "
                    f"{symbol}{quarter_note}."
                )
                if sec_error:
                    reason = f"{reason} {sec_error}"
            next_actions = [
                "Paste an earnings-call transcript via transcript_text to render it here.",
                "Provide audio_url or audio_path so Whisper can transcribe the call.",
            ]
            if not network_failed:
                next_actions.insert(
                    0,
                    f"{symbol} may have no recent 8-K earnings exhibit on file; try another ticker or quarter.",
                )
            else:
                next_actions.insert(0, "Retry once network connectivity to SEC EDGAR is restored.")
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "symbol": symbol,
                    "status": status,
                    "event": event,
                    "utterances": [],
                    "rows": [],
                    "whisper": whisper_result,
                    "data_mode": "provider_unavailable" if network_failed else "not_configured",
                    "reason": reason,
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICT,
                    "next_actions": next_actions,
                    "cards": _cards(symbol, event, 0, 0, "provider_unavailable" if network_failed else "not_configured"),
                },
                sources=sources or (["sec_edgar"] if network_failed else ["no_live_source"]),
                warnings=warnings or ["no transcript source returned usable rows"],
                metadata={
                    "provider_errors": warnings,
                    "data_state": status,
                    "data_mode": "provider_unavailable" if network_failed else "not_configured",
                },
            )

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "symbol": symbol,
                "status": "ok",
                "event": event,
                "utterances": rows,
                "rows": rows,
                "whisper": whisper_result,
                "data_mode": data_mode,
                "document_type": document_type,
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICT,
                "cards": _cards(symbol, event, len(rows), len(speakers), data_mode),
            },
            sources=sources,
            warnings=warnings,
            metadata={
                "provider_errors": warnings,
                "data_state": "ok",
                "data_mode": data_mode,
                "document_type": document_type,
                "utterance_count": len(rows),
                "speakers_count": len(speakers),
            },
        )


# --------------------------------------------------------------------------- #
# SEC EDGAR — keyless earnings press-release (Exhibit 99.x of the latest 8-K).
# --------------------------------------------------------------------------- #
class _SecLookupError(Exception):
    """Raised for resolvable EDGAR conditions (no CIK / no exhibit found)."""


_TICKER_CIK_CACHE: dict[str, str] = {}


async def _http_client() -> Any:
    from showme.providers._http import get_client
    return await get_client()


async def _resolve_cik(symbol: str, deps: Any) -> str:
    # Prefer the wired SEC adapter (it caches the ticker map process-wide).
    adapter = getattr(deps, "sec_edgar", None)
    if adapter is not None and hasattr(adapter, "lookup_cik"):
        try:
            cik = await adapter.lookup_cik(symbol)
            if cik:
                return str(cik).zfill(10)
        except Exception:  # noqa: BLE001 - fall through to direct fetch
            pass
    if symbol in _TICKER_CIK_CACHE:
        return _TICKER_CIK_CACHE[symbol]
    client = await _http_client()
    resp = await client.get(_TICKERS_URL, headers=_sec_headers())
    resp.raise_for_status()
    payload = resp.json()
    iterable = payload.values() if isinstance(payload, dict) else payload
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        t = entry.get("ticker")
        c = entry.get("cik_str")
        if t is None or c is None:
            continue
        _TICKER_CIK_CACHE[str(t).upper()] = "".join(ch for ch in str(c) if ch.isdigit()).zfill(10)
    cik = _TICKER_CIK_CACHE.get(symbol)
    if not cik:
        raise _SecLookupError(f"{symbol} is not in SEC EDGAR's company-tickers map (non-US or non-filer?)")
    return cik


async def _fetch_sec_earnings_press_release(
    symbol: str, deps: Any, quarter: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Return (event_meta, press_release_text) for an 8-K earnings exhibit.

    Without ``quarter`` this is the newest earnings 8-K. With ``quarter`` (a
    normalised fiscal label such as ``Q1 FY26``) only 8-Ks whose report date
    releases that fiscal quarter are considered, using the SEC fiscal year end.
    No match is a lookup error, not the latest filing; no fiscal year end is a
    lookup error too, since the requested period cannot be placed.
    """
    cik = await _resolve_cik(symbol, deps)
    cik_nozero = str(int(cik))
    client = await _http_client()
    resp = await client.get(_SUBMISSIONS_URL.format(cik=cik), headers=_sec_headers())
    resp.raise_for_status()
    sub = resp.json()
    fiscal_year_end = (sub or {}).get("fiscalYearEnd")
    fiscal_known = _parse_fye_month(fiscal_year_end) is not None
    if quarter and not fiscal_known:
        raise _SecLookupError(
            f"SEC submissions for {symbol} (CIK {cik}) carry no fiscal year end, so fiscal "
            f"quarter {quarter} cannot be matched to an 8-K report date."
        )
    recent = ((sub or {}).get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []
    dates = recent.get("reportDate") or []
    fdates = recent.get("filingDate") or []
    items = recent.get("items") or []

    # Walk filings newest-first; an earnings 8-K carries item 2.02
    # (Results of Operations) and an Exhibit 99.x press release.
    candidates: list[int] = []
    for i, form in enumerate(forms):
        if str(form).upper().startswith("8-K"):
            item_str = str(items[i]) if i < len(items) else ""
            # Prefer item 2.02; otherwise still consider 8-Ks as fallback.
            score = 2 if "2.02" in item_str else 1
            candidates.append((score, i))  # type: ignore[arg-type]
    candidates.sort(key=lambda x: (-x[0], x[1]))  # type: ignore[index]
    if quarter:
        candidates = [
            c for c in candidates  # type: ignore[misc]
            if _fiscal_quarter(dates[c[1]] if c[1] < len(dates) else None, fiscal_year_end) == quarter
        ]
        if not candidates:
            raise _SecLookupError(
                f"No 8-K filing for {symbol} reports fiscal quarter {quarter} among the recent "
                f"filings (CIK {cik})."
            )
    if not candidates:
        raise _SecLookupError(f"No recent 8-K filing found for {symbol} (CIK {cik}).")

    for _, idx in candidates[:6]:  # type: ignore[misc]
        accession = str(accessions[idx]) if idx < len(accessions) else ""
        if not accession:
            continue
        acc_nodash = accession.replace("-", "")
        meta = {
            "symbol": symbol,
            "form": str(forms[idx]),
            "accession": accession,
            "event_date": (dates[idx] if idx < len(dates) and dates[idx] else (fdates[idx] if idx < len(fdates) else None)),
            "filing_date": fdates[idx] if idx < len(fdates) else None,
            "quarter": _fiscal_quarter(dates[idx] if idx < len(dates) else None, fiscal_year_end),
            "quarter_basis": _QUARTER_BASIS if fiscal_known else _NO_FISCAL_BASIS,
            "source": "sec_edgar",
            "title": f"{symbol} {str(forms[idx])} earnings press release",
        }
        body = await _fetch_exhibit_text(client, cik_nozero, acc_nodash, accession)
        if body:
            meta["source_url"] = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{acc_nodash}/"
            )
            return meta, body
    raise _SecLookupError(
        f"Found 8-K filings for {symbol} but no readable Exhibit 99.x earnings text was extractable."
    )


async def _fetch_exhibit_text(client: Any, cik_nozero: str, acc_nodash: str, accession: str) -> str:
    """Pull the filing index, find the Exhibit 99.x doc, fetch + clean its text."""
    index_url = (
        f"https://data.sec.gov/Archives/edgar/data/{cik_nozero}/{acc_nodash}/"
        f"{accession}-index.json"
    )
    doc_name: str | None = None
    try:
        ir = await client.get(index_url, headers=_sec_headers())
        if ir.status_code == 200:
            j = ir.json()
            entries = ((j or {}).get("directory") or {}).get("item") or []
            ex99: list[str] = []
            html_docs: list[str] = []
            for it in entries:
                name = str(it.get("name") or "")
                low = name.lower()
                if not low.endswith((".htm", ".html", ".txt")):
                    continue
                if "ex99" in low or "ex-99" in low or "exhibit99" in low or "ex_99" in low:
                    ex99.append(name)
                elif low.endswith((".htm", ".html")):
                    html_docs.append(name)
            doc_name = ex99[0] if ex99 else (html_docs[0] if html_docs else None)
    except Exception:  # noqa: BLE001 - fall back to FilingSummary scan below
        doc_name = None

    if not doc_name:
        # Fallback: read the plain directory listing (no auth needed).
        listing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{acc_nodash}/"
        try:
            lr = await client.get(listing_url, headers=_sec_headers())
            if lr.status_code == 200:
                names = re.findall(r'href="([^"]+\.(?:htm|html|txt))"', lr.text, flags=re.I)
                ex = [n for n in names if re.search(r"ex.?-?99", n, re.I)]
                doc_name = (ex or [n for n in names if n.lower().endswith((".htm", ".html"))] or [None])[0]
                if doc_name:
                    doc_name = doc_name.split("/")[-1]
        except Exception:  # noqa: BLE001
            doc_name = None

    if not doc_name:
        return ""

    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{acc_nodash}/{doc_name}"
    dr = await client.get(doc_url, headers=_sec_headers())
    if dr.status_code != 200:
        return ""
    return _html_to_text(dr.text)


# --------------------------------------------------------------------------- #
# Parsing helpers — turn raw text into speaker-attributed utterances.
# --------------------------------------------------------------------------- #
_ROLE_HINTS = {
    "operator": "Operator",
    "chief executive": "CEO",
    "ceo": "CEO",
    "chief financial": "CFO",
    "cfo": "CFO",
    "analyst": "Analyst",
    "president": "President",
    "chairman": "Chairman",
}
_QA_MARKERS = (
    "question-and-answer",
    "question and answer",
    "q&a",
    "questions and answers",
)
# "Tim Cook -- Chief Executive Officer" or "Tim Cook:" style speaker headers.
_SPEAKER_RE = re.compile(
    r"^([A-Z][A-Za-z.\-' ]{1,48})\s*(?:--|—|–|:)\s*(.*)$"
)


def _parse_transcript_text(
    raw: str,
    *,
    default_section: str = "prepared_remarks",
    allow_speaker_headers: bool = True,
) -> list[dict[str, Any]]:
    """Split text into utterances. Speaker and role come only from explicit headers.

    Text before any header, or any text in a source with no headers at all, gets
    ``speaker=None`` and ``role=""``: nobody is invented. ``default_section`` is
    the section label used until a Q&A marker appears. ``allow_speaker_headers``
    must be False for sources that have no speaker headers by definition (an
    earnings press release): then no line is parsed as a header at all.
    """
    text = _html_to_text(raw) if "<" in raw and ">" in raw else raw
    text = re.sub(r"\r\n?", "\n", text)
    blocks = [b.strip() for b in re.split(r"\n{2,}", text) if b.strip()]
    if len(blocks) <= 1:
        # Single blob — split on sentence-ish lines so we still get rows.
        blocks = [ln.strip() for ln in text.split("\n") if ln.strip()]
    rows: list[dict[str, Any]] = []
    section = default_section
    current_speaker: str | None = None
    current_role = ""
    for block in blocks:
        low = block.lower()
        if any(m in low for m in _QA_MARKERS) and len(block) < 80:
            section = "qa"
            continue
        m = _SPEAKER_RE.match(block) if allow_speaker_headers else None
        # A colon line is ambiguous: "Retail Sales: gains continue" is a table or outline
        # label as often as a name. An explicit "--" or dash line is the transcript's own
        # header syntax and is trusted as written; a colon line names a speaker only when
        # its label is a role word such as "Operator".
        colon_line = bool(m) and block[m.end(1):].lstrip().startswith(":")
        if m and colon_line and m.group(1).strip().lower() not in _ROLE_HINTS:
            m = None
        if m and _looks_like_name(m.group(1).strip()):
            head = m.group(1).strip()
            rest = m.group(2).strip()
            # A speaker header changes the active speaker. Most transcript
            # formats put the header on its own line and the utterance in the
            # next block; when the header line also carries inline text (after
            # a ``:`` or ``--``) that text is the first utterance.
            current_speaker = head
            current_role = _role_for(head + " " + rest)
            if rest:
                rows.append({
                    "section": section,
                    "speaker": current_speaker,
                    "role": current_role,
                    "utterance": rest[:4000],
                    "timestamp_seconds": None,
                })
            continue
        # Body block: attributed only to a speaker whose header was seen.
        utterance = block.strip()
        if not utterance:
            continue
        rows.append({
            "section": section,
            "speaker": current_speaker,
            "role": current_role if current_speaker else "",
            "utterance": utterance[:4000],
            "timestamp_seconds": None,
        })
    return rows[:500]


def _looks_like_name(head: str) -> bool:
    """A speaker header is a person's name: capitalised tokens, no statement words.

    One-token names ("Tim -- CEO") are valid headers; the statement-word
    denylist still rejects one-token table labels ("Revenue: 1,000").
    """
    parts = head.split()
    if not 1 <= len(parts) <= 6:
        return False
    if head.lower() in _ROLE_HINTS:
        return True
    if any(p.lower().strip(".,:;") in _NON_NAME_TOKENS for p in parts):
        return False
    # Financial acronyms (EPS, EBITDA, GAAP, FCF) are metrics, not name tokens.
    # Two-letter all-caps tokens are kept: they are ordinary initials ("AJ Brown").
    if any(len(p) >= 3 and p.isalpha() and p.isupper() for p in parts):
        return False
    capish = sum(1 for p in parts if p[:1].isupper())
    return capish >= max(1, len(parts) - 1)


def _role_for(text: str) -> str:
    low = text.lower()
    for hint, role in _ROLE_HINTS.items():
        if hint in low:
            return role
    return ""


def _coerce_archive_utterances(ev: dict[str, Any]) -> list[dict[str, Any]]:
    raw = ev.get("utterances") or ev.get("rows") or ev.get("sections")
    rows: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for r in raw:
            if not isinstance(r, dict):
                continue
            rows.append({
                "section": r.get("section") or "prepared_remarks",
                "speaker": r.get("speaker") or None,
                "role": r.get("role") or "",
                "utterance": str(r.get("utterance") or r.get("text") or "").strip(),
                "timestamp_seconds": r.get("timestamp_seconds"),
            })
        return [r for r in rows if r["utterance"]]
    text = ev.get("transcript") or ev.get("text")
    if isinstance(text, str) and text.strip():
        return _parse_transcript_text(text)
    return []


def _apply_filters(rows: list[dict[str, Any]], section: str, speakers: list[str]) -> list[dict[str, Any]]:
    out = rows
    if section in ("prepared_remarks", "qa"):
        out = [r for r in out if r.get("section") == section]
    if speakers:
        wanted = {s.strip().lower() for s in speakers if str(s).strip()}
        if wanted:
            out = [r for r in out if str(r.get("speaker") or "").strip().lower() in wanted]
    return out


def _cards(symbol: str, event: dict[str, Any], n_utter: int, n_speakers: int, mode: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "quarter": event.get("quarter"),
        "event_date": event.get("event_date"),
        "utterance_count": n_utter,
        "speakers_count": n_speakers,
        "data_mode": mode,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def _html_to_text(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)</(p|div|br|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_QUARTER_LABEL_RE = re.compile(r"^\s*Q([1-4])\s*(?:FY)?\s*'?\s*(\d{4}|\d{2})\s*$", re.IGNORECASE)


def _normalize_quarter(text: str | None) -> str | None:
    """'Q3 FY26' / 'q3 fy2026' / 'Q3 2026' / "Q3'26" -> 'Q3 FY26'; anything else -> None."""
    m = _QUARTER_LABEL_RE.match(text or "")
    if not m:
        return None
    return f"Q{m.group(1)} FY{m.group(2)[-2:]}"


_QUARTER_BASIS = (
    "fiscal quarter: the last fiscal quarter end before the 8-K report date, from the "
    "company's SEC fiscal year end (month-level)"
)
_NO_FISCAL_BASIS = (
    "no fiscal quarter label: the SEC submissions index carries no fiscal year end"
)


def _parse_fye_month(fiscal_year_end: Any) -> int | None:
    """SEC ``fiscalYearEnd`` is MMDD (e.g. '0926'); return the month or None."""
    text = str(fiscal_year_end or "").strip()
    if not re.fullmatch(r"\d{4}", text):
        return None
    month, day = int(text[:2]), int(text[2:])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return month


def _fiscal_quarter(report_date: str | None, fiscal_year_end: Any) -> str | None:
    """Fiscal quarter label (e.g. 'Q1 FY26') of the period an 8-K report date releases.

    The release reports the last fiscal quarter that ended before the report
    date. Fiscal quarter ends fall every three months from the fiscal year-end
    month. The fiscal year is named for the calendar year in which it ends.
    Returns None when the report date or the fiscal year end is unusable, so a
    caller never labels a period it cannot place.
    """
    fye_month = _parse_fye_month(fiscal_year_end)
    if fye_month is None or not report_date:
        return None
    try:
        dt = datetime.strptime(str(report_date)[:10], "%Y-%m-%d")
    except ValueError:
        return None
    year, month = dt.year, dt.month
    while True:  # walk back to the nearest fiscal quarter-end month (at most 3 steps)
        month -= 1
        if month == 0:
            month, year = 12, year - 1
        if (month - fye_month) % 3 == 0:
            break
    quarter = ((month - fye_month) % 12) // 3 or 4
    fy_year = year if month <= fye_month else year + 1
    return f"Q{quarter} FY{str(fy_year)[2:]}"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


__all__ = ["TRANFunction"]
