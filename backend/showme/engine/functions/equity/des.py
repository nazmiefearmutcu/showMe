"""DES — Description (şirket özeti / coin profili).

DATA PIPELINE:
  EQUITY/ETF/FUND/REIT: yfinance (primary) → Finnhub /stock/profile2 → SEC EDGAR
  CRYPTO:               CoinGecko /coins/{id} → CryptoCompare → yfinance (BTC-USD)
  Cache:  refdata cache (12h)
  Latency: <500 ms warm
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import EXCHANGE_LEGEND


# yfinance ``info`` keys we promote onto the DES payload so the native pane
# can render P/E, beta, dividend yield, 52-week range, and live last-price
# without reaching into ``extras.raw``. Keep this list aligned with
# ``DESData`` in ``ui/src/functions/DES.tsx``.
_CRYPTO_PROVIDER_ORDER = ("coingecko", "cryptocompare", "yfinance")
_EQUITY_PROVIDER_ORDER = ("yfinance", "finnhub", "sec_edgar")


_PROMOTED_INFO_KEYS = (
    "regularMarketPrice",
    "currentPrice",
    "previousClose",
    "regularMarketPreviousClose",
    "regularMarketChangePercent",
    "regularMarketVolume",
    "regularMarketOpen",
    "regularMarketDayHigh",
    "regularMarketDayLow",
    "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow",
    "trailingPE",
    "forwardPE",
    "beta",
    "dividendYield",
    "trailingAnnualDividendYield",
    "longName",
    "shortName",
    "longBusinessSummary",
    "fullTimeEmployees",
    "marketCap",
    "sharesOutstanding",
    "floatShares",
    "firstTradeDateEpochUtc",
    "firstTradeDateMilliseconds",
)


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _normalize_dividend_yield(value: Any) -> float | None:
    """yfinance ``info.dividendYield`` ships in two flavors depending on the
    library version — decimal (0.0035 = 0.35%) and percent (0.35 = 0.35%).
    Normalize to a decimal fraction so the UI's ``*100`` is always correct.

    A real equity yield rarely exceeds 15%, and decimal form caps at 0.15.
    Anything above 0.2 is therefore the percent-form reading from a
    newer yfinance and must be divided by 100. Below that, we trust the
    value as-is — matching the older decimal contract."""
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0 or v != v:  # NaN
        return None
    return v / 100.0 if v > 0.2 else v


def _epoch_to_iso(value: Any) -> str | None:
    """Accept seconds or milliseconds since the Unix epoch and return the
    UTC date in ISO form. yfinance migrated from
    ``firstTradeDateEpochUtc`` (seconds) to ``firstTradeDateMilliseconds``
    (milliseconds), so DES has to handle both magnitudes."""
    if value in (None, "", 0):
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    # Heuristic: anything past the year 5000 (≈10^11) must be milliseconds.
    if ts > 1e11:
        ts /= 1000.0
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _looks_like_coingecko_payload(payload: dict[str, Any]) -> bool:
    """A CoinGecko ``/coins/{id}`` response always carries a ``market_data``
    sub-dict and a top-level ``id``/``symbol`` pair. Detecting the shape
    directly lets ``execute`` reshape the payload even when CoinGecko was
    not the *last* provider that appended itself to ``sources_used`` —
    a race that previously dropped circulating supply, ATH and genesis
    fields when CryptoCompare or yfinance succeeded after CoinGecko."""
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("market_data"), dict):
        return False
    return "id" in payload or "symbol" in payload or "categories" in payload


def _coingecko_to_des(payload: dict[str, Any], symbol_hint: str) -> dict[str, Any]:
    """Flatten the CoinGecko ``/coins/{id}`` response into the DES wire shape
    that the native pane already knows how to render. Crypto-specific
    fields (circulating supply, ATH/ATL, genesis date, consensus) ride
    alongside the generic price/market-cap surface so the React pane can
    decide what to show without a second round-trip."""
    if not isinstance(payload, dict):
        return {}
    md = payload.get("market_data") or {}
    description = (payload.get("description") or {}).get("en") or None
    homepage = ((payload.get("links") or {}).get("homepage") or [])
    website = next((url for url in homepage if url), None)
    repos = ((payload.get("links") or {}).get("repos_url") or {}).get("github") or []
    repo = next((url for url in repos if url), None)
    categories = [c for c in (payload.get("categories") or []) if c]

    def _md_usd(key: str) -> float | None:
        node = md.get(key)
        if isinstance(node, dict):
            value = node.get("usd")
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None
        if node in (None, ""):
            return None
        try:
            return float(node)
        except (TypeError, ValueError):
            return None

    current_price = _md_usd("current_price")
    high_24h = _md_usd("high_24h")
    low_24h = _md_usd("low_24h")
    high_52w = _md_usd("high_52w") or _md_usd("ath")
    low_52w = _md_usd("low_52w") or _md_usd("atl")
    change_pct = md.get("price_change_percentage_24h")
    prev_close = None
    if current_price is not None and change_pct not in (None, 0):
        try:
            prev_close = current_price / (1.0 + float(change_pct) / 100.0)
        except (TypeError, ValueError, ZeroDivisionError):
            prev_close = None

    return {
        "symbol": (payload.get("symbol") or symbol_hint or "").upper(),
        "name": payload.get("name"),
        "longName": payload.get("name"),
        "shortName": payload.get("symbol", "").upper() or None,
        "asset_class": "CRYPTO",
        "exchange": "CRYPTO",
        "exchange_name": "Cryptocurrency",
        "currency": "USD",
        "country": payload.get("country_origin") or None,
        "sector": "Cryptocurrency",
        "industry": (categories[0] if categories else None),
        "website": website,
        "description": description,
        "market_cap": _md_usd("market_cap"),
        "regularMarketPrice": current_price,
        "currentPrice": current_price,
        "previousClose": prev_close,
        "regularMarketChangePercent": (
            float(change_pct) if change_pct not in (None, "") else None
        ),
        "regularMarketVolume": _md_usd("total_volume"),
        "regularMarketDayHigh": high_24h,
        "regularMarketDayLow": low_24h,
        "fiftyTwoWeekHigh": high_52w,
        "fiftyTwoWeekLow": low_52w,
        # Crypto-specific surface — the React pane reads these directly.
        "circulating_supply": md.get("circulating_supply"),
        "total_supply": md.get("total_supply"),
        "max_supply": md.get("max_supply"),
        "all_time_high": _md_usd("ath"),
        "all_time_high_date": ((md.get("ath_date") or {}).get("usd") if isinstance(md.get("ath_date"), dict) else None),
        "all_time_low": _md_usd("atl"),
        "all_time_low_date": ((md.get("atl_date") or {}).get("usd") if isinstance(md.get("atl_date"), dict) else None),
        "genesis_date": payload.get("genesis_date"),
        "hashing_algorithm": payload.get("hashing_algorithm"),
        "block_time_in_minutes": payload.get("block_time_in_minutes"),
        "categories": categories,
        "rank": payload.get("market_cap_rank"),
        "github_repo": repo,
        "source": "coingecko",
    }


def _build_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    source = data.get("source") or "provider"
    market_cap = _coalesce(data.get("market_cap"), data.get("marketCap"))
    exchange_code = data.get("exchange")
    exchange_name = data.get("exchange_name") or exchange_code
    if str(data.get("asset_class") or "").upper() == "CRYPTO":
        return [
            {"field": "Name", "value": data.get("name") or data.get("longName"), "source_mode": source},
            {"field": "Symbol", "value": data.get("symbol"), "source_mode": source},
            {"field": "Market cap", "value": market_cap, "source_mode": source},
            {"field": "Rank", "value": data.get("rank"), "source_mode": source},
            {"field": "Circulating supply", "value": data.get("circulating_supply"), "source_mode": source},
            {"field": "Max supply", "value": data.get("max_supply"), "source_mode": source},
            {"field": "Genesis date", "value": data.get("genesis_date"), "source_mode": source},
            {"field": "Hashing algorithm", "value": data.get("hashing_algorithm"), "source_mode": source},
            {"field": "Website", "value": data.get("website"), "source_mode": source},
        ]
    employees = _coalesce(data.get("employees"), data.get("fullTimeEmployees"))
    return [
        {"field": "Name", "value": data.get("name") or data.get("longName") or data.get("shortName"), "source_mode": source},
        {"field": "Sector", "value": data.get("sector"), "source_mode": source},
        {"field": "Industry", "value": data.get("industry"), "source_mode": source},
        {"field": "Market cap", "value": market_cap, "source_mode": source},
        {"field": "Employees", "value": employees, "source_mode": source},
        {"field": "Exchange", "value": exchange_name, "raw_code": exchange_code, "source_mode": source},
        {"field": "Website", "value": data.get("website"), "source_mode": source},
        {"field": "Country", "value": data.get("country"), "source_mode": source},
    ]


def _promote_raw_fields(data: dict[str, Any], raw: dict[str, Any]) -> None:
    """Flatten the yfinance ``info`` fields we need onto ``data`` and mirror
    snake/camel aliases so the native pane finds them under either spelling."""
    if not isinstance(raw, dict):
        return
    for key in _PROMOTED_INFO_KEYS:
        if key not in raw:
            continue
        if data.get(key) in (None, ""):
            data[key] = raw[key]

    # Cross-fill canonical keys that the UI reads directly.
    if data.get("market_cap") in (None, ""):
        data["market_cap"] = _coalesce(raw.get("marketCap"), data.get("marketCap"))
    if data.get("employees") in (None, ""):
        data["employees"] = _coalesce(raw.get("fullTimeEmployees"), data.get("fullTimeEmployees"))
    if data.get("description") in (None, ""):
        data["description"] = _coalesce(raw.get("longBusinessSummary"), data.get("longBusinessSummary"))
    if data.get("ipo_date") in (None, ""):
        epoch = _coalesce(
            raw.get("firstTradeDateMilliseconds"),
            raw.get("firstTradeDateEpochUtc"),
            data.get("firstTradeDateMilliseconds"),
            data.get("firstTradeDateEpochUtc"),
        )
        iso = _epoch_to_iso(epoch)
        if iso:
            data["ipo_date"] = iso
            data.setdefault("ipoDate", iso)

    # Dividend yield: store the decimal form once so the UI's ``*100`` math
    # stays correct. ``trailingAnnualDividendYield`` is the more consistent
    # decimal field; ``dividendYield`` flips formats between yfinance
    # versions and is the fallback. Both go through the same normalization.
    raw_dy = _coalesce(
        raw.get("trailingAnnualDividendYield"),
        raw.get("dividendYield"),
        data.get("dividendYield"),
    )
    normalized = _normalize_dividend_yield(raw_dy)
    if normalized is not None:
        data["dividendYield"] = normalized

    # Synthesize regularMarketChangePercent if we have last + previousClose.
    if data.get("regularMarketChangePercent") in (None, ""):
        last = _coalesce(data.get("regularMarketPrice"), data.get("currentPrice"))
        prev = _coalesce(data.get("previousClose"), data.get("regularMarketPreviousClose"))
        try:
            if last is not None and prev not in (None, 0):
                data["regularMarketChangePercent"] = (float(last) / float(prev) - 1.0) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            pass


@FunctionRegistry.register
class DESFunction(BaseFunction):
    code = "DES"
    name = "Description"
    asset_classes = (
        AssetClass.EQUITY,
        AssetClass.ETF,
        AssetClass.FUND,
        AssetClass.REIT,
        AssetClass.CRYPTO,
    )
    category = "equity"
    description = "Şirket özeti / coin profili — market cap, açıklama, fundamental göstergeler."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("DES requires an instrument")
        warnings: list[str] = []
        sources_used: list[str] = []
        rd: Any = None
        provider_timeout = max(
            1.0,
            min(float(params.get("refdata_timeout", params.get("yfinance_timeout", 2.5))), 4.0),
        )
        deadline = asyncio.get_running_loop().time() + max(2.0, min(float(params.get("timeout", 6)), 8.0))
        is_crypto = instrument.asset_class == AssetClass.CRYPTO
        provider_order = _CRYPTO_PROVIDER_ORDER if is_crypto else _EQUITY_PROVIDER_ORDER
        for src_name in provider_order:
            src = getattr(self.deps, src_name, None)
            if src is None:
                continue
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0.75:
                warnings.append(f"{src_name}: skipped because DES latency budget was exhausted")
                break
            budget = max(0.75, min(provider_timeout, remaining))
            try:
                rd = await asyncio.wait_for(
                    src.fetch(
                        DataRequest(
                            kind=DataKind.REFDATA,
                            instrument=instrument,
                            extra={"timeout": budget},
                        )
                    ),
                    timeout=budget,
                )
                sources_used.append(src_name)
                if rd is not None:
                    break
            except Exception as e:
                warnings.append(f"{src_name}: {e}")

        if rd is None:
            data: dict[str, Any] = {
                "symbol": instrument.symbol,
                "name": instrument.name or instrument.symbol,
                "asset_class": instrument.asset_class.value,
                "sector": None,
                "industry": None,
                "market_cap": None,
                "employees": None,
                "exchange": instrument.exchange,
                "currency": instrument.currency,
                "country": None,
                "ipo_date": None,
                "description": None,
                "status": "provider_unavailable",
                "reason": "Reference data providers returned no usable company description within the latency budget.",
                "next_actions": [
                    "Retry DES after the reference data providers recover.",
                    "Increase refdata_timeout for an interactive profile lookup.",
                ],
            }
            sources_used = list(provider_order)
        elif is_crypto and "coingecko" in sources_used and isinstance(rd, dict) and _looks_like_coingecko_payload(rd):
            # CoinGecko ships a nested ``market_data`` / ``description`` /
            # ``links`` shape — translate to the shared DES wire schema
            # before the generic flattener runs. Detect the shape directly
            # so the reshape still fires when CoinGecko provided the data
            # but a later fallback (cryptocompare/yfinance) appended itself
            # to ``sources_used`` without overwriting ``rd``.
            data = _coingecko_to_des(rd, instrument.symbol)
        elif isinstance(rd, dict):
            data = dict(rd)
        else:
            # ReferenceData dataclass (or any object with __dict__).
            try:
                data = rd.__dict__.copy() if hasattr(rd, "__dict__") else dict(rd)
            except (TypeError, AttributeError):
                # Last-resort guard so a malformed provider object cannot
                # leak past the function boundary as a non-JSON dataclass.
                data = {
                    "symbol": instrument.symbol,
                    "status": "provider_unavailable",
                    "reason": "Provider returned an object that could not be serialized.",
                }
                warnings.append(f"{type(rd).__name__}: could not coerce to dict")

        # Pull yfinance ``info`` out of extras.raw and flatten the fields the
        # UI cares about — then drop the raw blob so we don't ship 50KB+ of
        # provider-internal keys to the renderer.
        raw = {}
        extras = data.get("extras")
        if isinstance(extras, dict):
            raw = extras.get("raw") if isinstance(extras.get("raw"), dict) else {}
        _promote_raw_fields(data, raw)
        if extras is not None:
            # Preserve auxiliary extras (recommendations, upgrades_downgrades,
            # info_error) but always strip the heavy ``raw`` blob.
            slim_extras = {k: v for k, v in extras.items() if k != "raw"}
            if "info_error" in raw:
                slim_extras["info_error"] = raw["info_error"]
            data["extras"] = slim_extras or None
            if data["extras"] is None:
                data.pop("extras", None)

        if data.get("exchange"):
            data["exchange_name"] = EXCHANGE_LEGEND.get(
                str(data.get("exchange") or ""), data.get("exchange")
            )

        data["rows"] = _build_rows(data)
        data.setdefault(
            "methodology",
            "DES is a live company profile assembled from yfinance, Finnhub, and SEC reference "
            "data in priority order. Exchange codes are expanded for readability; "
            "dividend yield is normalised to a decimal fraction.",
        )
        data.setdefault("field_dictionary", _des_field_dictionary())

        if warnings:
            data.setdefault("provider_errors", list(warnings))

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=data,
            sources=sources_used,
            metadata={"asset_class": instrument.asset_class.value, "provider_errors": warnings},
        )

    def _render_html(self, r: FunctionResult) -> str:
        rd = r.data or {}
        get = rd.get if isinstance(rd, dict) else lambda *_: None
        market_cap = get("market_cap") or get("marketCap") or 0
        return f"""
<section class="showme-fn fn-des" data-code="DES">
  <header class="fn-header">
    <div class="fn-symbol">{get('symbol') or ''}</div>
    <div class="fn-name">{get('name') or get('longName') or ''}</div>
  </header>
  <div class="fn-grid grid-2">
    <div class="card"><label>Sektör</label><span>{get('sector') or '—'}</span></div>
    <div class="card"><label>Endüstri</label><span>{get('industry') or '—'}</span></div>
    <div class="card"><label>Market Cap</label><span>{(market_cap or 0)/1e9:.2f}B</span></div>
    <div class="card"><label>Çalışan</label><span>{get('employees') or '—'}</span></div>
    <div class="card"><label>Borsa</label><span>{get('exchange_name') or get('exchange') or '—'}</span></div>
    <div class="card"><label>Para</label><span>{get('currency') or '—'}</span></div>
    <div class="card"><label>Ülke</label><span>{get('country') or '—'}</span></div>
    <div class="card"><label>IPO</label><span>{get('ipo_date') or '—'}</span></div>
  </div>
  <p class="fn-summary">{get('description') or ''}</p>
  <footer class="fn-footer">sources: {', '.join(r.sources)} · {r.fetched_at:%Y-%m-%d %H:%M}</footer>
</section>"""


def _des_field_dictionary() -> dict[str, str]:
    return {
        "market_cap": "Latest provider market capitalization in quote currency.",
        "employees": "Full-time employees, when reported by provider.",
        "description": "Business summary from the reference-data provider.",
        "exchange_name": "Human-readable exchange name expanded from provider code.",
        "trailingPE": "Price/earnings (TTM) reported by yfinance ``info``.",
        "forwardPE": "Forward P/E based on next-period consensus EPS.",
        "beta": "Five-year monthly beta vs. the index reported by yfinance.",
        "dividendYield": "Dividend yield as a decimal fraction (multiply by 100 for percent).",
        "fiftyTwoWeekHigh": "Highest regular-session price in the trailing 52 weeks.",
        "fiftyTwoWeekLow": "Lowest regular-session price in the trailing 52 weeks.",
        "regularMarketPrice": "Latest regular-session last price.",
        "previousClose": "Previous regular-session close used to derive change percent.",
        # Crypto-specific fields exposed when ``asset_class == 'CRYPTO'``.
        "circulating_supply": "Coins currently in circulation per CoinGecko.",
        "total_supply": "Total minted coin supply.",
        "max_supply": "Maximum coin supply hard-cap (None for inflationary chains).",
        "all_time_high": "All-time-high price in USD per CoinGecko.",
        "all_time_high_date": "ISO timestamp of the all-time-high in USD.",
        "all_time_low": "All-time-low price in USD per CoinGecko.",
        "all_time_low_date": "ISO timestamp of the all-time-low in USD.",
        "genesis_date": "First-block / genesis date.",
        "hashing_algorithm": "Consensus hashing algorithm (e.g. SHA-256).",
        "block_time_in_minutes": "Average block time in minutes.",
        "categories": "CoinGecko categories the asset belongs to.",
        "rank": "CoinGecko market-cap rank.",
    }
