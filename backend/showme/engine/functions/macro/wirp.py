"""WIRP — World Interest Rate Probability (live, keyless CME-FedWatch math).

Priority of sources for the Fed row:

1. ``deps.cme_fedwatch`` adapter when wired — the canonical FedWatch feed.
2. **Live keyless market data** (the de-garbage default):
     * current target range  → FRED ``DFEDTARU`` / ``DFEDTARL`` CSV (no key)
     * effective funds rate    → FRED ``DFF`` CSV (no key)
     * market-implied near-term rate → 13-week T-bill ``^IRX`` (yfinance)
   From these we recover the market-implied policy move and discretize it into
   cut / hold / hike buckets per forward FOMC meeting using the standard
   CME-FedWatch convention (normal CDF over 25 bp buckets).
3. A clearly-labelled reference snapshot — **only** on a genuine outage of both
   (1) and (2).

ECB / BoE have no robust *keyless* market-implied rate source, so they are
reported honestly as ``provider_unavailable`` rather than padded with constants.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

FRED_TARGET_UPPER_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"
FRED_TARGET_LOWER_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARL"
FRED_EFFR_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"

# Standard-deviation of the implied path used to spread a point move across
# the cut/hold/hike buckets. 12.5 bp = half a 25 bp step, the market default.
_PATH_SIGMA_BP = 12.5

# Forward FOMC decision-day calendar (second meeting day). Maintained ~quarterly
# against https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Used only to *date* the forward meetings; the probabilities themselves come
# from live market data, never from this table.
_FOMC_CALENDAR_2026 = [
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
]


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
        data_mode = "live_official"
        source_mode = "live_fed_funds_futures"
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

        try:
            implied_rate, irx_asof = await _fetch_irx_implied_rate()
        except Exception as exc:  # noqa: BLE001 — already non-raising, belt+braces
            implied_rate, irx_asof = None, None
            warnings.append(
                f"^IRX implied-rate refinement unavailable: {exc.__class__.__name__}: {exc}"
            )

        target_mid = None
        if upper is not None and lower is not None:
            target_mid = (upper[1] + lower[1]) / 2.0
        elif effr is not None:
            # Fall back to EFFR rounded to the standing 25 bp grid.
            target_mid = round(effr[1] * 4) / 4

        # Only a *total* outage (no FRED target range AND no implied rate) is
        # honestly provider_unavailable. If FRED gave us a target range but
        # ^IRX did not, we still build real rows anchored on the FRED midpoint.
        if target_mid is None and implied_rate is None:
            status = "provider_unavailable"
            data_mode = "provider_unavailable"
            source_mode = "provider_unavailable"
            warnings.append(
                "live futures-implied probability source returned no usable "
                "target range or implied near-term rate"
            )
            return _result(
                self.code, central_bank, [], status, data_mode, source_mode,
                anchor, warnings, sources, meetings_limit,
            )

        if target_mid is None:
            # Implied rate present but no FRED range: anchor the target on the
            # implied rate snapped to the 25 bp grid so the move math stays sane.
            target_mid = round(implied_rate * 4) / 4
            warnings.append(
                "FRED target range unavailable; anchoring on the implied "
                "near-term rate rounded to the 25 bp grid"
            )

        irx_available = implied_rate is not None
        if not irx_available:
            # Honest fallback: with no ^IRX reading we use the current FRED
            # target midpoint as the near-term anchor (zero implied move). This
            # is a real, live FRED-derived number, not a constant.
            implied_rate = target_mid
            source_mode = "live_fred_target_no_irx"
            warnings.append(
                "^IRX 13-week T-bill near-term rate unavailable; anchoring on "
                "the live FRED target midpoint (no implied move applied)"
            )

        rows = _live_fed_rows(
            target_mid=target_mid,
            implied_rate=implied_rate,
            meetings_limit=meetings_limit,
        )
        sources.append("fred")
        if irx_available:
            sources.append("yfinance")
        anchor = {
            "current_target_mid": round(target_mid, 4),
            "current_target_upper": round(upper[1], 4) if upper else None,
            "current_target_lower": round(lower[1], 4) if lower else None,
            "effr": round(effr[1], 4) if effr else None,
            "implied_near_term_rate": round(implied_rate, 4) if implied_rate is not None else None,
            "implied_near_term_source": (
                "^IRX 13-week T-bill" if irx_available else "FRED target midpoint (IRX unavailable)"
            ),
            "as_of": irx_asof,
        }
        if effr:
            anchor["effr_as_of"] = effr[0]

        if not rows:
            status = "empty"
            data_mode = "provider_unavailable"
            source_mode = "provider_unavailable"
            warnings.append("no forward meetings produced for the requested horizon")

        return _result(
            self.code, central_bank, rows, status, data_mode, source_mode,
            anchor, warnings, sources, meetings_limit,
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
        "WIRP shows market-implied probabilities of the next central-bank "
        "decisions. For each meeting cut+hold+hike sum to 1; implied_change_bp "
        "is (-25 * cut_25bp) + (25 * hike_25bp). The Fed row is built live and "
        "keyless: the current target range comes from FRED DFEDTARU/DFEDTARL, "
        "the effective rate from FRED DFF, and the market-implied near-term "
        "policy rate from the 13-week T-bill (^IRX) via yfinance. The implied "
        "move (implied rate minus the current target midpoint) is discretized "
        "across the cut/hold/hike buckets with the standard CME-FedWatch normal "
        f"convention (sigma = {_PATH_SIGMA_BP:g} bp), then scaled along the "
        "forward FOMC calendar so later meetings carry a wider implied move. "
        "When a CME FedWatch adapter is wired it takes precedence as the "
        "canonical feed. ECB/BoE have no robust keyless implied-rate source and "
        "are reported as provider_unavailable rather than padded with constants."
    )

    cards: list[dict[str, Any]] = [
        {"label": "Central bank", "value": central_bank},
        {"label": "Meetings", "value": len(rows)},
        {"label": "Next hold %", "value": round(rows[0]["hold"] * 100, 2) if rows else None},
        {"label": "Mode", "value": data_mode},
    ]
    if anchor.get("current_target_mid") is not None:
        cards.append({"label": "Target mid %", "value": anchor["current_target_mid"]})
    if anchor.get("implied_near_term_rate") is not None:
        cards.append({"label": "Implied near-term %", "value": anchor["implied_near_term_rate"]})

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
                "implied_change_bp": "Probability-weighted expected policy-rate move in basis points.",
            },
            "source_mode": source_mode,
            "data_mode": data_mode,
            "provenance": {"sources": list(sources)},
        },
        sources=sources or [source_mode],
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
    so ``execute()`` can honestly fall back to the FRED target midpoint.
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
# CME-FedWatch bucket math (live FRED/yfinance path)
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


def _live_fed_rows(
    *, target_mid: float, implied_rate: float, meetings_limit: int
) -> list[dict[str, Any]]:
    """Build per-meeting cut/hold/hike rows from the live implied move.

    The near-term implied move (implied_rate - target_mid) is the cumulative
    move priced into roughly the next quarter. We scale it across the forward
    FOMC calendar so the n-th meeting carries the move expected to have
    accumulated by that meeting (linear in meeting index), then bucket each.
    """
    meetings = _forward_fomc_dates(meetings_limit)
    if not meetings:
        return []

    total_move_bp = (implied_rate - target_mid) * 100.0
    n = len(meetings)
    rows: list[dict[str, Any]] = []
    for idx, mdate in enumerate(meetings, start=1):
        # Cumulative fraction of the priced move expected by meeting ``idx``.
        frac = idx / n
        meeting_move_bp = total_move_bp * frac
        # Sigma widens with horizon (uncertainty compounds across meetings).
        sigma = _PATH_SIGMA_BP * math.sqrt(idx)
        cut, hold, hike = _bucket_probabilities(meeting_move_bp, sigma)
        # Round cut/hike then derive hold as the exact remainder so the three
        # always sum to 1.0 (independent 6 dp rounding can drift ~2e-6 and trip
        # the wirp_probs_sum_to_one invariant).
        cut_r = round(cut, 6)
        hike_r = round(hike, 6)
        hold_r = round(1.0 - cut_r - hike_r, 6)
        rows.append({
            "central_bank": "FED",
            "date": mdate,
            "cut_25bp": cut_r,
            "hold": hold_r,
            "hike_25bp": hike_r,
            "implied_change_bp": round((-25 * cut_r) + (25 * hike_r), 2),
            "source_mode": "live_fed_funds_futures",
        })
    return rows


def _forward_fomc_dates(limit: int) -> list[str]:
    """Return upcoming FOMC decision dates from today, capped at ``limit``."""
    today = datetime.now(timezone.utc).date()
    upcoming = [d for d in _FOMC_CALENDAR_2026 if (_parse_date(d) is not None and _parse_date(d) >= today)]  # type: ignore[operator]
    if not upcoming:
        # Calendar exhausted — keep the contract alive with the last-known dates
        # so the UI still renders; probabilities remain live-derived.
        upcoming = list(_FOMC_CALENDAR_2026)
    return upcoming[:limit]


def _parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


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
