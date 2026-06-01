"""TRAN — Earnings Call Transcript Viewer (keyless, SEC EDGAR primary).

Reader pane for earnings-call / investor-event transcripts. The DEFAULT path
fetches REAL, keyless data — there is no synthetic happy-path:

  1. ``transcript_text`` param — a user-pasted transcript is parsed into
     speaker-attributed utterances (the highest-fidelity source we can get
     without a paid provider).
  2. SEC EDGAR (keyless) — resolve ticker -> CIK, find the most recent 8-K
     earnings filing and pull its earnings press release Exhibit 99.x text,
     then segment it into prepared-remarks utterances. This is the official,
     public, primary disclosure for the quarter and needs no API key.
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
import re
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
_FILING_INDEX = "https://www.sec.gov/cgi-bin/browse-edgar"
_UA = {"User-Agent": "showMe research contact@example.com"}

_METHODOLOGY = (
    "TRAN serves earnings-call / investor-event transcript text from real, keyless "
    "sources. If transcript_text is supplied it is parsed verbatim into "
    "speaker-attributed utterances. Otherwise TRAN resolves the ticker to a CIK via "
    "SEC EDGAR's company-tickers map, locates the most recent 8-K earnings filing, "
    "and extracts the earnings press release exhibit (Exhibit 99.x) text — the "
    "official quarterly disclosure — segmenting it into ordered utterances "
    "{section, speaker, role, utterance, timestamp_seconds}. A previously ingested "
    "transcript in the local archive is served verbatim when present. For events with "
    "only an audio_url/audio_path, Whisper is attempted when configured; when Whisper "
    "is missing the pane reports data_mode='not_configured' and never fabricates text. "
    "Section/speaker filters apply post-load. The pane is read-only."
)

_FIELD_DICT = {
    "symbol": "Echoed input symbol.",
    "status": "ok / empty / not_configured / provider_unavailable.",
    "event": "Earnings event metadata (quarter, event_date, form, accession, source_url).",
    "utterances[].position": "1-based order of the utterance within the document.",
    "utterances[].section": "prepared_remarks / qa.",
    "utterances[].speaker": "Speaker name (or section heading) captured from the source.",
    "utterances[].role": "Role/title when detectable (CEO, CFO, Operator, Analyst).",
    "utterances[].utterance": "Verbatim utterance / paragraph text.",
    "utterances[].timestamp_seconds": "Offset from event start when available (else null).",
    "data_mode": "live_official (SEC 8-K), user_supplied, cached_snapshot (archive), or not_configured.",
}

_OK_STATUSES = {"ok", "empty"}


@FunctionRegistry.register
class TRANFunction(BaseFunction):
    code = "TRAN"
    name = "Earnings Call Transcripts"
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

        utterances: list[dict[str, Any]] = []
        event: dict[str, Any] = {"symbol": symbol, "quarter": params.get("quarter") or None}
        data_mode = "not_configured"

        # 1) User-pasted transcript — highest fidelity, fully real.
        pasted = params.get("transcript_text") or params.get("transcript")
        if isinstance(pasted, str) and pasted.strip():
            utterances = _parse_transcript_text(pasted)
            if utterances:
                data_mode = "user_supplied"
                sources.append("user_supplied")
                event.setdefault("title", f"{symbol} pasted transcript")
                event["source"] = "user_supplied"

        # 2) Local archive (previously ingested verbatim transcript).
        if not utterances:
            try:
                from showme.engine.services import transcripts_archive as archive
                # transcripts_archive exposes list_for_symbol (not list_events);
                # the old name raised AttributeError and silently killed this
                # cached-transcript source via the broad except below.
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
                            "source": "transcripts_archive",
                            "event_id": ev.get("event_id"),
                        })
            except Exception as e:  # noqa: BLE001 - archive optional
                warnings.append(f"transcripts_archive: {e}")

        # 3) DEFAULT keyless live source — SEC EDGAR 8-K earnings exhibit.
        sec_error: str | None = None
        if not utterances:
            try:
                ev_meta, body = await asyncio.wait_for(
                    _fetch_sec_earnings_press_release(symbol, deps=self.deps),
                    timeout=float(params.get("sec_timeout", 15) or 15),
                )
                if body:
                    utterances = _parse_transcript_text(body)
                    if utterances:
                        data_mode = "live_official"
                        sources.append("sec_edgar")
                        event.update(ev_meta)
            except asyncio.TimeoutError:
                sec_error = "SEC EDGAR request timed out"
            except _SecLookupError as e:
                sec_error = str(e)
            except Exception as e:  # noqa: BLE001 - record network failure honestly
                sec_error = f"{type(e).__name__}: {e}"
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
                    warnings.append(f"whisper: {e}")
            if audio_path and not whisper_result:
                try:
                    from showme.engine.services.transcription import transcribe
                    whisper_result = await transcribe(
                        audio_path, language=params.get("language"),
                        model_name=params.get("model", "base"),
                    )
                except Exception as e:  # noqa: BLE001 - whisper optional
                    warnings.append(f"whisper local: {e}")
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
            network_failed = bool(sec_error)
            status = "provider_unavailable" if network_failed else "empty"
            reason = (
                f"No earnings press release / transcript could be retrieved for {symbol}."
                if not network_failed else
                f"SEC EDGAR was unreachable for {symbol}: {sec_error}."
            )
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
    resp = await client.get(_TICKERS_URL, headers=_UA)
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


async def _fetch_sec_earnings_press_release(symbol: str, deps: Any) -> tuple[dict[str, Any], str]:
    """Return (event_meta, press_release_text) for the latest 8-K earnings exhibit."""
    cik = await _resolve_cik(symbol, deps)
    cik_nozero = str(int(cik))
    client = await _http_client()
    resp = await client.get(_SUBMISSIONS_URL.format(cik=cik), headers=_UA)
    resp.raise_for_status()
    sub = resp.json()
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
            "quarter": _infer_quarter(dates[idx] if idx < len(dates) else None),
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
        ir = await client.get(index_url, headers=_UA)
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
            lr = await client.get(listing_url, headers=_UA)
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
    dr = await client.get(doc_url, headers=_UA)
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


def _parse_transcript_text(raw: str) -> list[dict[str, Any]]:
    text = _html_to_text(raw) if "<" in raw and ">" in raw else raw
    text = re.sub(r"\r\n?", "\n", text)
    blocks = [b.strip() for b in re.split(r"\n{2,}", text) if b.strip()]
    if len(blocks) <= 1:
        # Single blob — split on sentence-ish lines so we still get rows.
        blocks = [ln.strip() for ln in text.split("\n") if ln.strip()]
    rows: list[dict[str, Any]] = []
    section = "prepared_remarks"
    current_speaker = "Management"
    current_role = ""
    for block in blocks:
        low = block.lower()
        if any(m in low for m in _QA_MARKERS) and len(block) < 80:
            section = "qa"
            continue
        m = _SPEAKER_RE.match(block)
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
        # Body block attributed to the active speaker.
        utterance = block.strip()
        if not utterance:
            continue
        rows.append({
            "section": section,
            "speaker": current_speaker,
            "role": current_role or _role_for(utterance),
            "utterance": utterance[:4000],
            "timestamp_seconds": None,
        })
    return rows[:500]


def _looks_like_name(head: str) -> bool:
    parts = head.split()
    if not 1 <= len(parts) <= 6:
        return False
    if head.lower() in _ROLE_HINTS:
        return True
    # Mostly capitalised tokens with no terminal punctuation.
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
                "speaker": r.get("speaker") or "Management",
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


def _infer_quarter(report_date: str | None) -> str | None:
    if not report_date:
        return None
    try:
        dt = datetime.strptime(report_date[:10], "%Y-%m-%d")
    except Exception:
        return None
    q = (dt.month - 1) // 3 + 1
    return f"Q{q} FY{str(dt.year)[2:]}"


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
