"""WIRP — World Interest Rate Probability.

Probabilities come only from a real market-implied source:

1. ``deps.cme_fedwatch`` adapter when wired — the canonical FedWatch feed.

Without that adapter there is no keyless fed funds / SOFR futures feed, so the
keyless path reports honest anchor values only: the FRED target range
(``DFEDTARU`` / ``DFEDTARL``), EFFR (``DFF``) and the 13-week T-bill yield
(``^IRX``, yfinance). A T-bill yield is a bill basis, not a policy-rate
expectation, so no hike/cut odds are derived from it. That state is reported
as ``provider_unavailable`` with zero rows.

ECB / BoE have no keyless market-implied source either and are reported as
``provider_unavailable``. Nothing is padded with constants.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

FRED_TARGET_UPPER_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"
FRED_TARGET_LOWER_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARL"
FRED_EFFR_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"



@FunctionRegistry.register
class WIRPFunction(BaseFunction):
    code = "WIRP"
    name = "World Interest Rate Probability"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        central_bank = str(params.get("central_bank") or params.get("bank") or "FED").upper()
        meetings_limit = _int_param(params.get("meetings"), default=4, floor=1, ceiling=8)

        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        sources: list[str] = []
        status = "ok"
        # Neutral until a real source produces rows: no label may claim a live
        # futures feed before one has.
        data_mode = "provider_unavailable"
        source_mode = "provider_unavailable"
        anchor: dict[str, Any] = {}

        if central_bank != "FED":
            # No robust keyless market-implied rate source exists for ECB/BoE/etc.
            # Be honest instead of fabricating a probability distribution.
            status = "provider_unavailable"
            data_mode = "provider_unavailable"
            source_mode = "provider_unavailable"
            warnings.append(
                f"{central_bank}: no keyless market-implied policy-rate source is "
                "wired; only the Fed row is computed from live data. "
                "Select FED for live probabilities."
            )
            return _result(
                self.code, central_bank, rows, status, data_mode, source_mode,
                anchor, warnings, sources, meetings_limit,
            )

        # ── (1) canonical CME FedWatch adapter, when wired ──────────────────
        adapter = getattr(self.deps, "cme_fedwatch", None)
        if adapter is not None:
            try:
                payload = await adapter.probabilities()
                rows = _rows_from_cme(payload, central_bank)
            except Exception as exc:  # noqa: BLE001
                rows = []
                warnings.append(
                    f"cme_fedwatch adapter error: {exc.__class__.__name__}: {exc}"
                )
            if rows:
                sources.append("cme_fedwatch")
                source_mode = "cme_fedwatch"
                data_mode = "live_official"
                return _result(
                    self.code, central_bank, rows, "ok", data_mode, source_mode,
                    anchor, warnings, sources, meetings_limit,
                )

        # ── (2) live keyless market data (the de-garbage default path) ──────
        # The FRED target range is the load-bearing input. ``^IRX`` only
        # *refines* the near-term anchor, so a slow/failed IRX pull must not
        # take the whole path down — fetch the FRED legs in their own try, and
        # the (already non-raising) IRX call separately.
        try:
            timeout = float(params.get("timeout", 8.0) or 8.0)
        except (TypeError, ValueError):
            timeout = 8.0
        # HNT-06: the whole function runs under a ~14 s worker budget. The
        # FRED legs and the (optional, already non-raising) ^IRX refinement
        # used to run sequentially with independent timeouts (8 s + 20 s),
        # so a slow IRX pull got the entire function cancelled at the
        # deadline instead of degrading the anchor. Track elapsed time and
        # cap IRX at the remaining budget.
        fred_started = time.monotonic()
        try:
            upper, lower, effr = await asyncio.gather(
                _fetch_fred_latest(FRED_TARGET_UPPER_CSV, timeout=timeout),
                _fetch_fred_latest(FRED_TARGET_LOWER_CSV, timeout=timeout),
                _fetch_fred_latest(FRED_EFFR_CSV, timeout=timeout),
            )
        except Exception as exc:  # noqa: BLE001 — FRED outage is the real failure
            upper = lower = effr = None
            warnings.append(
                "FRED target-range source unavailable: "
                f"{exc.__class__.__name__}: {exc}"
            )

        irx_budget = min(20.0, max(1.0, 13.0 - (time.monotonic() - fred_started)))
        try:
            implied_rate, irx_asof = await asyncio.wait_for(
                _fetch_irx_implied_rate(), timeout=irx_budget
            )
        except asyncio.TimeoutError:
            implied_rate, irx_asof = None, None
            warnings.append(
                f"^IRX implied-rate refinement unavailable: timed out after {irx_budget:.1f}s"
            )
        except Exception as exc:  # noqa: BLE001 — already non-raising, belt+braces
            implied_rate, irx_asof = None, None
            warnings.append(
                f"^IRX implied-rate refinement unavailable: {exc.__class__.__name__}: {exc}"
            )

        target_mid = None
        if upper is not None and lower is not None:
            target_mid = (upper[1] + lower[1]) / 2.0

        irx_available = implied_rate is not None
        # Keyless inputs are reference rates, not a market policy path. The
        # target midpoint is never substituted from EFFR or the T-bill yield.
        anchor: dict[str, Any] = {
            "current_target_mid": round(target_mid, 4) if target_mid is not None else None,
            "current_target_upper": round(upper[1], 4) if upper else None,
            "current_target_lower": round(lower[1], 4) if lower else None,
            "effr": round(effr[1], 4) if effr else None,
            "effr_as_of": effr[0] if effr else None,
            "tbill_13w_pct": round(implied_rate, 4) if irx_available else None,
            "tbill_as_of": irx_asof,
            "tbill_minus_target_mid_bp": (
                round((implied_rate - target_mid) * 100.0, 2)
                if irx_available and target_mid is not None
                else None
            ),
            "basis_note": (
                "The 13-week T-bill yield and EFFR are reference rates, not a market "
                "policy-rate expectation; hike/cut odds are not derived from them."
            ),
        }
        if upper or lower or effr:
            sources.append("fred")
        if irx_available:
            sources.append("yfinance")

        if target_mid is None and not irx_available:
            warnings.append(
                "live keyless sources returned no usable target range or 13-week T-bill rate"
            )
        warnings.append(
            "Hike/cut probabilities unavailable: no CME FedWatch adapter is wired and no fed funds or "
            "SOFR futures feed is wired here. Showing the FRED target range, EFFR and 13-week T-bill "
            "basis only."
        )
        return _result(
            self.code, central_bank, [], "provider_unavailable", "provider_unavailable",
            "provider_unavailable", anchor, warnings, sources, meetings_limit,
        )


def _result(
    code: str,
    central_bank: str,
    rows: list[dict[str, Any]],
    status: str,
    data_mode: str,
    source_mode: str,
    anchor: dict[str, Any],
    warnings: list[str],
    sources: list[str],
    meetings_limit: int,
) -> FunctionResult:
    rows = rows[:meetings_limit]

    surface = []
    for row in rows:
        for scenario in ("cut_25bp", "hold", "hike_25bp"):
            surface.append({
                "meeting": row["date"],
                "scenario": scenario,
                "probability": row[scenario],
                "value": row[scenario] * 100,
                "central_bank": row["central_bank"],
            })

    methodology = (
        "WIRP shows market-implied probabilities of the next central-bank decisions. "
        "For each meeting cut+hold+hike sum to 1 and implied_change_bp is "
        "(-25 * cut_25bp) + (25 * hike_25bp). Probabilities come only from the CME "
        "FedWatch adapter when it is wired. The keyless path reports the FRED target "
        "range, EFFR (FRED DFF) and the 13-week T-bill (^IRX) as reference anchors and "
        "does not derive hike/cut odds from them. ECB/BoE have no robust keyless "
        "implied-rate source and are reported as provider_unavailable rather than padded."
    )

    cards: list[dict[str, Any]] = [
        {"label": "Central bank", "value": central_bank},
        {"label": "Meetings", "value": len(rows)},
        {"label": "Mode", "value": data_mode},
    ]
    if anchor.get("current_target_mid") is not None:
        cards.append({"label": "Target mid %", "value": anchor["current_target_mid"]})
    if anchor.get("tbill_13w_pct") is not None:
        cards.append({"label": "13w T-bill %", "value": anchor["tbill_13w_pct"]})

    return FunctionResult(
        code=code,
        instrument=None,
        data={
            "status": status,
            "central_bank": central_bank,
            "rows": rows,
            "surface": surface,
            "anchor": anchor,
            "cards": cards,
            "methodology": methodology,
            "field_dictionary": {
                "central_bank": "Central bank code (FED/ECB/BOE).",
                "date": "Forward policy-meeting decision date (UTC).",
                "cut_25bp": "Probability of a 25 bp (or deeper) cut.",
                "hold": "Probability of no policy-rate change.",
                "hike_25bp": "Probability of a 25 bp (or deeper) hike.",
                "implied_change_bp": (
                    "Probability-weighted expected policy-rate move in basis points vs the "
                    "current-target anchor at that meeting. Cumulative to that meeting, not an "
                    "incremental move, so it must not be summed across meetings."
                ),
            },
            "source_mode": source_mode,
            "data_mode": data_mode,
            "provenance": {"sources": list(sources)},
        },
        sources=list(sources),
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Live data fetch
# --------------------------------------------------------------------------- #
async def _fetch_fred_latest(url: str, timeout: float = 8.0) -> tuple[str, float] | None:
    """Return the most recent ``(date, value)`` from a FRED single-series CSV.

    FRED CSV rows look like ``2026-05-28,4.50`` with placeholder ``.`` for
    missing observations (e.g. weekends/holidays). We skip placeholders and
    return the last real value, or ``None`` if the series is empty.
    """
    from showme.providers._http import get_client

    client = await get_client()
    # FRED's fredgraph.csv endpoint is frequently slow to first byte; the
    # shared client's 20 s default sometimes times out on cold cache. Give it
    # a more generous budget so the live path isn't spuriously downgraded.
    resp = await client.get(url, timeout=timeout)
    resp.raise_for_status()
    last: tuple[str, float] | None = None
    for line in resp.text.strip().splitlines():
        if "," not in line:
            continue
        date_str, _, value_str = line.partition(",")
        value_str = value_str.strip()
        if value_str in (".", "", "value", "VALUE") or date_str.lower() in ("date", "observation_date"):
            continue
        try:
            last = (date_str.strip(), float(value_str))
        except ValueError:
            continue
    return last


async def _fetch_irx_implied_rate() -> tuple[float | None, str | None]:
    """Return the latest 13-week T-bill yield (``^IRX``) as a near-term rate.

    yfinance is synchronous so we offload to a worker thread. Returns
    ``(rate_percent, as_of_iso)`` — ``rate`` is already in percent.

    This call is *non-raising*: a cold ``^IRX`` pull can be slow and the
    whole live path must not die just because the optional market-implied
    refinement timed out. On any timeout/error we return ``(None, None)``
    so ``execute()`` simply omits the ^IRX anchor and reports the FRED/EFFR
    values it has, without substituting the T-bill yield for anything else.
    """

    def _pull() -> tuple[float | None, str | None]:
        try:
            import yfinance as yf

            hist = yf.Ticker("^IRX").history(period="10d", interval="1d")
            if hist is None or hist.empty or "Close" not in hist:
                return None, None
            closes = hist["Close"].dropna()
            if closes.empty:
                return None, None
            value = float(closes.iloc[-1])
            try:
                as_of = closes.index[-1].date().isoformat()
            except Exception:  # noqa: BLE001
                as_of = None
            return value, as_of
        except Exception:  # noqa: BLE001 — map any yfinance/network error to None
            return None, None

    try:
        return await asyncio.wait_for(asyncio.to_thread(_pull), timeout=20.0)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        return None, None


# --------------------------------------------------------------------------- #
# Bucket helper (pure math; not used by the keyless path)
# --------------------------------------------------------------------------- #
def _normal_cdf(x: float) -> float:
    """Standard normal CDF via the error function (stdlib only)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bucket_probabilities(move_bp: float, sigma_bp: float) -> tuple[float, float, float]:
    """Discretize a point move (bp) into (cut, hold, hike) probabilities.

    Standard market convention: hold = P(|move| < 12.5 bp), cut = mass below
    -12.5 bp, hike = mass above +12.5 bp. Modeled as a normal centered on the
    implied move with std ``sigma_bp``. Always sums to exactly 1.
    """
    if sigma_bp <= 0:
        sigma_bp = 1e-6
    lo = (-12.5 - move_bp) / sigma_bp
    hi = (12.5 - move_bp) / sigma_bp
    hold = _normal_cdf(hi) - _normal_cdf(lo)
    cut = _normal_cdf(lo)
    hike = 1.0 - _normal_cdf(hi)
    # Guard tiny negative float dust and renormalize.
    cut = max(cut, 0.0)
    hold = max(hold, 0.0)
    hike = max(hike, 0.0)
    total = cut + hold + hike
    if total <= 0:
        return 0.0, 1.0, 0.0
    return cut / total, hold / total, hike / total


# --------------------------------------------------------------------------- #
# CME FedWatch adapter normalisation (priority-1 source when wired)
# --------------------------------------------------------------------------- #
def _rows_from_cme(payload: dict[str, Any] | None, central_bank: str) -> list[dict[str, Any]]:
    """Bucket the CME normalised payload into cut/hold/hike per meeting.

    The CME normaliser emits ``{"meetings": [{"date": ..., "ranges": {bin: pct}}]}``
    where each ``bin`` is a textual target range and ``pct`` is the
    market-implied probability that the FOMC ends the meeting inside that
    range. We anchor on the modal range of the first meeting as "today's"
    target, then bucket every meeting by relation to it (below ➜ cut, equal ➜
    hold, above ➜ hike) and renormalise so cut+hold+hike == 1.
    """
    if not payload or not isinstance(payload, dict):
        return []
    meetings = payload.get("meetings") or []
    if not isinstance(meetings, list) or not meetings:
        return []

    parsed_meetings: list[tuple[str, list[tuple[float, str, float]]]] = []
    for meeting in meetings:
        if not isinstance(meeting, dict):
            continue
        date_str = str(meeting.get("date") or "").strip()
        ranges = meeting.get("ranges") or {}
        if not date_str or not isinstance(ranges, dict) or not ranges:
            continue
        entries: list[tuple[float, str, float]] = []
        for bin_text, raw_pct in ranges.items():
            mid = _range_midpoint(str(bin_text))
            try:
                pct = float(raw_pct)
            except (TypeError, ValueError):
                continue
            if mid is None or pct < 0:
                continue
            entries.append((mid, str(bin_text), pct))
        if entries:
            parsed_meetings.append((date_str, entries))

    if not parsed_meetings:
        return []

    first_entries = parsed_meetings[0][1]
    anchor_mid, _, _ = max(first_entries, key=lambda item: item[2])

    rows: list[dict[str, Any]] = []
    for date_str, entries in parsed_meetings:
        cut_raw = sum(pct for mid, _, pct in entries if mid < anchor_mid - _MID_EPS)
        hold_raw = sum(pct for mid, _, pct in entries if abs(mid - anchor_mid) <= _MID_EPS)
        hike_raw = sum(pct for mid, _, pct in entries if mid > anchor_mid + _MID_EPS)
        bucket_total = cut_raw + hold_raw + hike_raw
        if bucket_total <= 0:
            continue
        cut = cut_raw / bucket_total
        hike = hike_raw / bucket_total
        # Round cut/hike then derive hold as the exact remainder so the three
        # always sum to 1.0 (independent 6 dp rounding can drift ~2e-6).
        cut_r = round(cut, 6)
        hike_r = round(hike, 6)
        hold_r = round(1.0 - cut_r - hike_r, 6)
        rows.append({
            "central_bank": central_bank,
            "date": date_str,
            "cut_25bp": cut_r,
            "hold": hold_r,
            "hike_25bp": hike_r,
            "implied_change_bp": round((-25 * cut_r) + (25 * hike_r), 2),
            "source_mode": "cme_fedwatch",
        })
    return rows


_MID_EPS = 1e-9


def _range_midpoint(text: str) -> float | None:
    """Best-effort midpoint extraction from a CME range bin label.

    Accepts the shapes CME uses — ``"4.25-4.50"``, ``"425-450"``,
    ``"425 - 450 bps"``, ``"4.50%"``. Returns the midpoint in *percent*
    (4.25-4.50 → 4.375) or ``None`` if the label can't be parsed.
    """
    if not text:
        return None
    cleaned = (
        text.replace("bps", "")
        .replace("bp", "")
        .replace("%", "")
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )
    if not cleaned:
        return None
    parts = [p.strip() for p in cleaned.split("-") if p.strip()]
    if not parts:
        return None
    nums: list[float] = []
    for part in parts:
        try:
            nums.append(float(part))
        except ValueError:
            return None
    if not nums:
        return None
    midpoint = sum(nums) / len(nums)
    if any(n >= 50 for n in nums):
        midpoint = midpoint / 100.0
    return midpoint


def _int_param(value: Any, *, default: int, floor: int, ceiling: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))
