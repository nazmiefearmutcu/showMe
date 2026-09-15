"""EQS — Equity Screener.

Plan §7.5: accepts a SQL-like DSL and runs it over the universe. This version
does not use pyparsing; it uses a small hand-written recursive-descent parser
(one of the places the spec explicitly left to the coder).

DSL examples:
    marketCap > 1000000000 AND pe < 15 AND sector = "Technology"
    rsi(14) < 30 AND volume > 1000000
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.des import _normalize_dividend_yield


# ── Mini DSL ──
@dataclass
class Cond:
    field: str
    op: str
    value: Any


@dataclass
class And:
    parts: list


@dataclass
class Or:
    parts: list


_TOKEN = re.compile(
    r'\s*(?:'
    r'(\()|(\))'                                              # 1, 2 parens
    r'|("(?:[^"\\]|\\.)*")'                                  # 3 quoted str
    r'|(\bAND\b|\bOR\b|\band\b|\bor\b|\bAnd\b|\bOr\b)'        # 4 BOOL — first
    r'|([<>]=?|!=|==|=)'                                     # 5 comparison
    r'|([A-Za-z_][\w\.]*\s*\([^)]*\)|[A-Za-z_][\w\.]*)'      # 6 func/ident
    r'|(-?\d+(?:\.\d+)?)'                                    # 7 number
    r')'
)


def _tokenize(s: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m:
            i += 1
            continue
        for idx, kind in enumerate(("LP", "RP", "STR", "BOOL", "OP", "ID", "NUM"), 1):
            if m.group(idx):
                out.append((kind, m.group(idx)))
                break
        i = m.end()
    return out


def _parse(tokens: list[tuple[str, str]], pos: int = 0) -> tuple[Any, int]:
    """Parse OR > AND > primary."""
    left, pos = _parse_and(tokens, pos)
    nodes = [left]
    while pos < len(tokens) and tokens[pos][0] == "BOOL" and tokens[pos][1].upper() == "OR":
        right, pos = _parse_and(tokens, pos + 1)
        nodes.append(right)
    return (nodes[0] if len(nodes) == 1 else Or(nodes), pos)


def _parse_and(tokens: list[tuple[str, str]], pos: int) -> tuple[Any, int]:
    left, pos = _parse_primary(tokens, pos)
    nodes = [left]
    while pos < len(tokens) and tokens[pos][0] == "BOOL" and tokens[pos][1].upper() == "AND":
        right, pos = _parse_primary(tokens, pos + 1)
        nodes.append(right)
    return (nodes[0] if len(nodes) == 1 else And(nodes), pos)


def _parse_primary(tokens: list[tuple[str, str]], pos: int) -> tuple[Any, int]:
    if pos < len(tokens) and tokens[pos][0] == "LP":
        node, pos = _parse(tokens, pos + 1)
        if pos < len(tokens) and tokens[pos][0] == "RP":
            pos += 1
        return node, pos
    if pos + 2 >= len(tokens):
        raise ValueError(
            f"Invalid query segment at position {pos}: expected 'field operator value'"
        )
    field = tokens[pos][1]; pos += 1
    op = tokens[pos][1]; pos += 1
    raw = tokens[pos][1]; pos += 1
    val: Any
    if raw.startswith('"'):
        val = raw[1:-1]
    else:
        try:
            val = float(raw) if "." in raw else int(raw)
        except ValueError:
            val = raw
    return Cond(field=field, op=op, value=val), pos


def _eval(node: Any, row: dict[str, Any]) -> bool:
    if isinstance(node, Cond):
        v = row.get(node.field)
        if v is None:
            return False
        try:
            if node.op in ("=", "=="): return v == node.value
            if node.op == "!=": return v != node.value
            if node.op == "<": return v < node.value
            if node.op == "<=": return v <= node.value
            if node.op == ">": return v > node.value
            if node.op == ">=": return v >= node.value
        except TypeError:
            return False
        return False
    if isinstance(node, And):
        return all(_eval(p, row) for p in node.parts)
    if isinstance(node, Or):
        return any(_eval(p, row) for p in node.parts)
    return False


# Query aliases → the real column names the screener DataFrame exposes.
# The pane presets send ``dividendYield`` while the live/template frame names
# the column ``dividend_yield``; without this fold every predicate on it
# matched zero rows (reported as "MATCHED 0 of 11 scanned" while the universe
# chip said 503 symbols). Same class of alias for the other known spellings.
_QUERY_ALIASES: dict[str, str] = {
    "dividendyield": "dividend_yield",
    "dividend_yield_ttm": "dividend_yield",
    "divyield": "dividend_yield",
    "div_yield": "dividend_yield",
    "marketcap": "marketCap",
    "market_cap": "marketCap",
    "pe_ratio": "pe",
    "pe_ttm": "pe",
    "trailingpe": "pe",
    "price_to_book": "pb",
    "pb_ratio": "pb",
    "price_to_sales": "ps",
    "ps_ratio": "ps",
}


def normalize_query_aliases(query: str) -> str:
    """Fold known field aliases onto the screener's real column names."""
    rewritten = str(query or "")
    for old, new in _QUERY_ALIASES.items():
        rewritten = re.sub(rf"\b{re.escape(old)}\b", new, rewritten, flags=re.I)
    return rewritten


def parse_dsl(query: str) -> Any:
    return _parse(_tokenize(normalize_query_aliases(query)))[0]


def filter_dataframe(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Filter a DataFrame against an EQS DSL string (aliases folded)."""
    ast = parse_dsl(query)
    mask = df.apply(lambda r: _eval(ast, r.to_dict()), axis=1)
    return df[mask]


# ── Function ──
@FunctionRegistry.register
class EQSFunction(BaseFunction):
    code = "EQS"
    name = "Equity Screener"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "screen"
    description = (
        "DSL-based equity screener. Örnek: marketCap > 1000000000 AND pe < 15 "
        "AND sector = \"Technology\""
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        query = params.get("query", "marketCap > 0")
        live = _truthy(params.get("live_screen") or params.get("deep"))
        # Without a DuckDB-materialised view we operate on a small in-memory
        # universe seeded by yfinance. The default is a "Mega-cap 15" basket
        # NOT the actual S&P 500 — see _resolve_universe for label aliasing.
        # S05 BUGHUNT B6: previously the UI sent universe="SP500" → the
        # backend silently fell through to this 15-symbol stub but the pane
        # footer kept showing "universe · SP500", overstating coverage by
        # ~485 symbols. Now we resolve the textual label up-front so the
        # response payload reflects what we actually scanned.
        universe_param = params.get("universe")
        universe, universe_label = _resolve_universe(universe_param)
        template_mode = not live
        rows: list[dict[str, Any]] = []
        if template_mode:
            rows = _screen_template_rows(instrument, universe)
        elif self.deps.yfinance:
            rows = await self._live_equity_rows(universe, params)
        # F6 honesty fix: the live_screen=True path must never substitute the
        # 5-row template stub. Previously `rows < 3` silently loaded template
        # rows and still attributed them to `sources=["yfinance"]`. The
        # manifest's own semantic test
        # (eqs_provider_unavailable_returns_empty_rows_not_synthetic) requires
        # an honest provider_unavailable envelope with no fabricated rows.
        if live and not rows:
            reason = (
                "Live screen produced no symbol rows; the template stub is "
                "not substituted on the live path."
            )
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "query": query,
                    "matched": 0,
                    "scanned": len(universe),
                    "reason": reason,
                    "next_actions": [
                        "Retry the screen, or shrink the universe so live rows can complete in time.",
                        "Verify the yfinance provider connection.",
                    ],
                },
                sources=[],
                warnings=[reason],
                metadata={
                    "query": query,
                    "matched": 0,
                    "scanned": len(universe),
                    "live": False,
                    "fallback": True,
                    "data_mode": "provider_unavailable",
                    "universe": universe_label,
                    "universe_size": len(universe),
                },
            )
        if not rows:
            rows = _screen_template_rows(instrument, universe)
        df = pd.DataFrame(rows)
        try:
            filtered = filter_dataframe(df, query)
        except Exception as e:
            # C3 fix: previously returned raw DataFrame as ``data`` which
            # broke every UI consumer (they expect the dict envelope). Now
            # we return the same shape the success path emits, just with
            # zero rows and a structured error marker.
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "rows": [],
                    "status": "dsl_parse_error",
                    "error": str(e),
                    "data": None,
                    "query": query,
                    "matched": 0,
                    "scanned": int(len(df)),
                },
                warnings=[f"DSL parse error: {e}"],
                metadata={
                    "query": query,
                    "matched": 0,
                    "scanned": int(len(df)),
                    "live": live,
                    "universe": universe_label,
                    "universe_size": len(universe),
                },
            )
        if filtered.empty:
            # F6 honesty fix: previously `filtered = df.head(3)` shipped rows
            # that do NOT satisfy the query and reported them as MATCHED 3.
            # A screener must never present non-matching rows as matches.
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "no_matches",
                    "rows": [],
                    "query": query,
                    "matched": 0,
                    "scanned": int(len(df)),
                },
                sources=["yfinance"] if live else ["equity_screener_model"],
                metadata={
                    "query": query,
                    "matched": 0,
                    "scanned": int(len(df)),
                    "live": live,
                    "template": template_mode,
                    "data_mode": "delayed_reference" if live else "modeled",
                    "universe": universe_label,
                    "universe_size": len(universe),
                },
            )
        # S05 BUGHUNT B6: surface the actual universe label + size so the UI
        # cannot continue to claim "SP500" coverage when only the mega-cap
        # stub was scanned. `universe_label` flows up untouched.
        warnings: list[str] = []
        if template_mode:
            warnings.append(
                "Template mode: rows are model fixtures, not live market data."
            )
        return FunctionResult(
            code=self.code, instrument=None,
            data=filtered.reset_index(drop=True),
            sources=["yfinance"] if live else ["equity_screener_model"],
            warnings=warnings,
            metadata={
                "query": query,
                "matched": int(len(filtered)),
                "scanned": int(len(df)),
                "live": live,
                "template": template_mode,
                "data_mode": "delayed_reference" if live else "modeled",
                "universe": universe_label,
                "universe_size": len(universe),
            },
        )

    async def _live_equity_rows(
        self,
        universe: list[str],
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Live rows for the requested universe.

        Preferred path: the provider's batched Yahoo fundamentals fills the
        whole universe in a handful of calls, so ``scanned`` reflects the real
        500+ symbol universe instead of the ~11 symbols that used to slip
        inside the per-symbol, rate-limited budget. ``beta``/``industry``/
        ``ps`` are not part of the batch payload, so a bounded rotated REFDATA
        slice refreshes them into a process cache whenever the active query
        actually references them. Without batch support (or when it hard
        fails) the legacy per-symbol REFDATA fan-out runs unchanged.
        """
        provider = self.deps.yfinance
        batch_fetch = getattr(provider, "fetch_refdata_batch", None)
        batch_rows: dict[str, dict[str, Any]] = {}
        if callable(batch_fetch):
            batch_rows = _batch_cache_read(universe)
            missing = [s for s in universe if str(s).upper() not in batch_rows]
            if missing:
                try:
                    fresh = await batch_fetch(missing) or {}
                except Exception:  # noqa: BLE001 — fall back per symbol below
                    fresh = {}
                fresh = {
                    str(key).upper(): value
                    for key, value in fresh.items()
                    if isinstance(value, dict)
                }
                if fresh:
                    _batch_cache_write(fresh)
                    batch_rows.update(fresh)
        if batch_rows:
            await self._refresh_refdata_slice(
                universe, str(params.get("query") or ""), params
            )
            master = _security_master_by_symbol()
            rows: list[dict[str, Any]] = []
            for sym in universe:
                key = str(sym).upper()
                batch = batch_rows.get(key)
                ref = _refdata_cache_read(key)
                if batch is None and ref is None:
                    # The provider has no row for this symbol (delisted or
                    # outside its coverage) — an honest gap, never a stub.
                    continue
                rows.append(_compose_live_row(key, batch, ref, master.get(key)))
            return rows
        return await self._per_symbol_rows(universe, params)

    async def _per_symbol_rows(
        self,
        universe: list[str],
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Legacy per-symbol REFDATA fan-out (no batch provider support)."""
        timeout = max(1.0, min(_param_float(params, "refdata_timeout", 2.0), 4.0))
        screen_timeout = max(2.0, min(_param_float(params, "screen_timeout", 4.0), 6.0))

        async def _one(s: str):
            return await self.deps.yfinance.fetch(DataRequest(
                kind=DataKind.REFDATA,
                instrument=Instrument(symbol=s, asset_class=AssetClass.EQUITY, exchange="NASDAQ"),
                extra={"timeout": timeout},
            ))

        tasks = [asyncio.create_task(_one(str(s))) for s in universe]
        done, pending = await asyncio.wait(tasks, timeout=screen_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        rows: list[dict[str, Any]] = []
        for sym, task in zip(universe, tasks):
            if task not in done:
                continue
            try:
                result = task.result()
            except Exception:  # noqa: BLE001 — one dead symbol must not kill the scan
                continue
            if result is None:
                continue
            raw = (result.extras or {}).get("raw", {}) if hasattr(result, "extras") else {}
            rows.append({
                "symbol": sym,
                "sector": result.sector or raw.get("sector"),
                "industry": result.industry or raw.get("industry"),
                "marketCap": result.market_cap or raw.get("marketCap"),
                "pe": _to_float(raw.get("trailingPE")),
                "pb": _to_float(raw.get("priceToBook")),
                "ps": _to_float(raw.get("priceToSalesTrailing12Months")),
                "dividend_yield": _normalize_dividend_yield(raw.get("dividendYield")),
                "beta": _to_float(raw.get("beta")),
                "country": result.country or raw.get("country"),
            })
        return rows

    async def _refresh_refdata_slice(
        self,
        universe: list[str],
        query: str,
        params: dict[str, Any],
    ) -> None:
        """Cache REFDATA-only fields (beta/industry/ps) in rotated slices.

        The batch endpoint covers marketCap/PE/PB/yield but not beta; queries
        that reference those fields would otherwise run with unknown values
        forever. Each call refreshes a bounded slice of uncached symbols into a
        process-local cache, so repeated runs progressively cover the universe
        without ever inventing a number.
        """
        normalized = normalize_query_aliases(query or "").lower()
        if not any(
            re.search(rf"\b{token}\b", normalized)
            for token in ("beta", "industry", "ps")
        ):
            return
        budget = int(max(0.0, min(_param_float(params, "refdata_budget", 24.0), 64.0)))
        if budget <= 0:
            return
        pending = [
            str(s).upper() for s in universe
            if _refdata_cache_read(str(s).upper()) is None
        ]
        if not pending:
            return
        global _EQS_REFDATA_CURSOR
        start = _EQS_REFDATA_CURSOR % len(pending)
        window = pending[start:start + budget]
        _EQS_REFDATA_CURSOR = (start + budget) % max(1, len(pending))
        per_timeout = max(1.0, min(_param_float(params, "refdata_timeout", 2.0), 3.0))
        slice_timeout = max(1.0, min(_param_float(params, "refdata_screen_timeout", 3.0), 5.0))
        semaphore = asyncio.Semaphore(6)

        async def _one(symbol: str):
            async with semaphore:
                return symbol, await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA,
                    instrument=Instrument(
                        symbol=symbol,
                        asset_class=AssetClass.EQUITY,
                        exchange="NASDAQ",
                    ),
                    extra={"timeout": per_timeout, "bypass_rate_limit": True},
                ))

        tasks = [asyncio.create_task(_one(symbol)) for symbol in window]
        done, pending_tasks = await asyncio.wait(tasks, timeout=slice_timeout)
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        for task in done:
            try:
                symbol, refdata = task.result()
            except Exception:  # noqa: BLE001
                continue
            raw = (refdata.extras or {}).get("raw", {}) if hasattr(refdata, "extras") else {}
            fields = _normalize_raw_fields(raw)
            if any(value is not None for value in fields.values()):
                _refdata_cache_write(symbol, fields)


# ── Live row plumbing (batch cache + REFDATA slice cache) ──
_EQS_BATCH_CACHE_TTL_S = 300.0
_EQS_REFDATA_CACHE_TTL_S = 6 * 3600.0
_EQS_BATCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_EQS_REFDATA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_EQS_REFDATA_CURSOR = 0
_SECURITY_MASTER_INDEX: dict[str, dict[str, Any]] | None = None


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _param_float(params: dict[str, Any], name: str, default: float) -> float:
    try:
        return float(params.get(name, default))
    except (TypeError, ValueError):
        return default


def _normalize_raw_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """REFDATA ``raw`` dict → the screener's column vocabulary.

    ``dividend_yield`` is normalised to a decimal fraction (DES helper) so the
    live column and the seeded rows share ONE convention: 1.93 (percent form
    from newer yfinance) becomes 0.0193, and a preset comparing ``> 0.04``
    keeps its documented meaning.
    """
    raw = raw or {}
    return {
        "marketCap": _to_float(raw.get("marketCap")),
        "pe": _to_float(raw.get("trailingPE")),
        "pb": _to_float(raw.get("priceToBook")),
        "ps": _to_float(raw.get("priceToSalesTrailing12Months")),
        "dividend_yield": _normalize_dividend_yield(raw.get("dividendYield")),
        "beta": _to_float(raw.get("beta")),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "country": raw.get("country"),
    }


# The SECF security master labels S&P members with GICS-style sector names
# ("Information Technology"), while yfinance — and therefore the EQS template
# rows and pane presets — uses the Yahoo vocabulary ("Technology"). Fold the
# master onto the Yahoo names so `sector = "Technology"` matches the whole
# universe instead of only the REFDATA-sliced rows.
_MASTER_SECTOR_ALIASES = {
    "Information Technology": "Technology",
    "Health Care": "Healthcare",
    "Consumer Discretionary": "Consumer Cyclical",
    "Consumer Staples": "Consumer Defensive",
    "Financials": "Financial Services",
    "Materials": "Basic Materials",
}


def _normalize_sector_name(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return _MASTER_SECTOR_ALIASES.get(value, value)


def _compose_live_row(
    symbol: str,
    batch: dict[str, Any] | None,
    ref: dict[str, Any] | None,
    master: dict[str, Any] | None,
) -> dict[str, Any]:
    """One live row: batch numbers, REFDATA enrichment, master identity."""
    batch = batch or {}
    ref = ref or {}
    master = master or {}
    market_cap = _to_float(batch.get("marketCap"))
    if market_cap is None:
        market_cap = ref.get("marketCap")
    pe = _to_float(batch.get("trailingPE"))
    if pe is None:
        pe = ref.get("pe")
    pb = _to_float(batch.get("priceToBook"))
    if pb is None:
        pb = ref.get("pb")
    dividend_yield = _normalize_dividend_yield(batch.get("dividendYield"))
    if dividend_yield is None:
        dividend_yield = ref.get("dividend_yield")
    beta = ref.get("beta")
    if beta is None:
        beta = _to_float(batch.get("beta"))
    return {
        "symbol": symbol,
        "sector": (
            ref.get("sector")
            or _normalize_sector_name(master.get("sector"))
            or batch.get("sector")
        ),
        "industry": ref.get("industry") or batch.get("industry"),
        "marketCap": market_cap,
        "pe": pe,
        "pb": pb,
        "ps": ref.get("ps"),
        "dividend_yield": dividend_yield,
        "beta": beta,
        "country": ref.get("country") or master.get("country") or batch.get("country"),
    }


def _batch_cache_read(symbols: list[str]) -> dict[str, dict[str, Any]]:
    now = time.monotonic()
    out: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        key = str(symbol).upper()
        entry = _EQS_BATCH_CACHE.get(key)
        if entry and entry[0] > now:
            out[key] = entry[1]
    return out


def _batch_cache_write(payload: dict[str, dict[str, Any]]) -> None:
    expires_at = time.monotonic() + _EQS_BATCH_CACHE_TTL_S
    for symbol, raw in payload.items():
        if isinstance(raw, dict) and raw:
            _EQS_BATCH_CACHE[str(symbol).upper()] = (expires_at, raw)


def _refdata_cache_read(symbol: str) -> dict[str, Any] | None:
    entry = _EQS_REFDATA_CACHE.get(str(symbol).upper())
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


def _refdata_cache_write(symbol: str, fields: dict[str, Any]) -> None:
    _EQS_REFDATA_CACHE[str(symbol).upper()] = (
        time.monotonic() + _EQS_REFDATA_CACHE_TTL_S,
        fields,
    )


def _security_master_by_symbol() -> dict[str, dict[str, Any]]:
    """Bundled SECF master keyed by symbol (sector/country identity)."""
    global _SECURITY_MASTER_INDEX
    if _SECURITY_MASTER_INDEX is None:
        from showme.engine.functions.screen._funcs import _load_security_master

        _SECURITY_MASTER_INDEX = {
            str(row.get("symbol") or "").upper(): row
            for row in _load_security_master()
            if row.get("symbol")
        }
    return _SECURITY_MASTER_INDEX


# S05 BUGHUNT B6: resolve a universe-name string ("SP500", "MEGA15", "TECH10",
# explicit comma list, or already-a-list) into a concrete symbol list AND a
# label that accurately describes what we scanned. The 15-symbol stub keeps
# its existing constituents but is now labeled "MEGA15" instead of riding
# under whatever label the caller provided. SP500 + NDX100 + DOW30 fall back
# to the same MEGA15 stub today because we do not yet bundle the full
# constituent files; the label is degraded so downstream renderers can show
# the truth instead of the request.
_UNIVERSE_PRESETS: dict[str, list[str]] = {
    "MEGA15": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM",
        "V", "WMT", "PG", "UNH", "MA", "HD", "DIS",
    ],
    "TECH10": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
        "AVGO", "ORCL",
    ],
}
_UNIVERSE_FALLBACK_LABEL = "MEGA15 (stub for SP500/NDX/DOW until constituents bundle)"


def _resolve_universe(value: Any) -> tuple[list[str], str]:
    if isinstance(value, list):
        cleaned = [str(s).strip().upper() for s in value if str(s).strip()]
        if cleaned:
            return cleaned, f"custom ({len(cleaned)} symbols)"
        return _UNIVERSE_PRESETS["MEGA15"], "MEGA15"
    if isinstance(value, str):
        token = value.strip().upper()
        if token in _UNIVERSE_PRESETS:
            return _UNIVERSE_PRESETS[token], token
        if token in {"SP500", "S&P500", "S&P 500", "NDX100", "NDX", "NASDAQ100", "DJIA", "DOW30"}:
            return _UNIVERSE_PRESETS["MEGA15"], _UNIVERSE_FALLBACK_LABEL
        if "," in token:
            cleaned = [s.strip().upper() for s in token.split(",") if s.strip()]
            if cleaned:
                return cleaned, f"custom ({len(cleaned)} symbols)"
        if token:
            return [token], f"single ({token})"
    return _UNIVERSE_PRESETS["MEGA15"], "MEGA15"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _screen_template_rows(
    instrument: Instrument | None,
    universe: list[str],
) -> list[dict[str, Any]]:
    rows = [
        {"symbol": "AAPL", "sector": "Technology", "industry": "Consumer Electronics",
         "marketCap": 3_000_000_000_000, "pe": 28.4, "pb": 41.0, "ps": 7.2,
         "dividend_yield": 0.005, "beta": 1.2, "country": "US"},
        {"symbol": "MSFT", "sector": "Technology", "industry": "Software",
         "marketCap": 3_200_000_000_000, "pe": 34.0, "pb": 11.8, "ps": 12.1,
         "dividend_yield": 0.008, "beta": 0.9, "country": "US"},
        {"symbol": "BTCUSDT", "sector": "Crypto", "industry": "Digital Assets",
         "marketCap": 1_500_000_000_000, "pe": 0.0, "pb": 0.0, "ps": 0.0,
         "dividend_yield": 0.0, "beta": 1.8, "country": "Global"},
        {"symbol": "EURUSD", "sector": "FX", "industry": "Major Pair",
         "marketCap": 1_000_000_000_000, "pe": 0.0, "pb": 0.0, "ps": 0.0,
         "dividend_yield": 0.0, "beta": 0.4, "country": "Global"},
        {"symbol": "GC=F", "sector": "Commodity", "industry": "Metals",
         "marketCap": 500_000_000_000, "pe": 0.0, "pb": 0.0, "ps": 0.0,
         "dividend_yield": 0.0, "beta": 0.2, "country": "Global"},
    ]
    if instrument and instrument.symbol:
        sym = instrument.symbol.upper()
        if not any(row["symbol"].upper() == sym for row in rows):
            rows.insert(0, {"symbol": sym, "sector": instrument.asset_class.value,
                            "industry": "Selected Instrument", "marketCap": 10_000_000_000,
                            "pe": 0.0, "pb": 0.0, "ps": 0.0,
                            "dividend_yield": 0.0, "beta": 1.0, "country": "Global"})
    for sym in universe[:5]:
        if not any(row["symbol"].upper() == str(sym).upper() for row in rows):
            rows.append({"symbol": str(sym).upper(), "sector": "Template",
                         "industry": "Screen Universe", "marketCap": 5_000_000_000,
                         "pe": 15.0, "pb": 2.0, "ps": 3.0,
                         "dividend_yield": 0.0, "beta": 1.0, "country": "Global"})
    return rows
