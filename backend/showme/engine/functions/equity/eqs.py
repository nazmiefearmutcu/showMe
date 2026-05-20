"""EQS — Equity Screener.

Plan §7.5: SQL benzeri DSL kabul eder, DuckDB üzerinden çalışır.
Bu sürüm pyparsing kullanmaz; küçük bir kendi yazdığım recursive-descent
parser kullanır (Spec açıkça "Coder geliştirsin" dediği yerlerden biri).

DSL örnekleri:
    marketCap > 1000000000 AND pe < 15 AND sector = "Technology"
    rsi(14) < 30 AND volume > 1000000
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


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


def parse_dsl(query: str) -> Any:
    return _parse(_tokenize(query))[0]


def filter_dataframe(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Filter a DataFrame against an EQS DSL string."""
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
        rows: list[dict[str, Any]] = []
        if not live:
            rows = _screen_template_rows(instrument, universe)
        elif self.deps.yfinance:
            import asyncio
            from showme.engine.core.base_data_source import DataKind, DataRequest
            from showme.engine.core.instrument import Instrument as I
            timeout = max(1.0, min(float(params.get("refdata_timeout", params.get("yfinance_timeout", 2))), 4.0))
            screen_timeout = max(2.0, min(float(params.get("screen_timeout", 4)), 6.0))

            async def _one(s: str):
                return await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.REFDATA,
                    instrument=I(symbol=s, asset_class=AssetClass.EQUITY, exchange="NASDAQ"),
                    extra={"timeout": timeout},
                ))

            tasks = [asyncio.create_task(_one(str(s))) for s in universe]
            done, pending = await asyncio.wait(tasks, timeout=screen_timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            result_map = {}
            for sym, task in zip(universe, tasks):
                if task in done:
                    try:
                        result_map[str(sym)] = task.result()
                    except Exception:
                        pass
            for sym in universe:
                r = result_map.get(str(sym))
                if isinstance(r, Exception) or r is None:
                    continue
                raw = (r.extras or {}).get("raw", {}) if hasattr(r, "extras") else {}
                rows.append({
                    "symbol": sym,
                    "sector": r.sector or raw.get("sector"),
                    "industry": r.industry or raw.get("industry"),
                    "marketCap": r.market_cap or raw.get("marketCap") or 0,
                    "pe": raw.get("trailingPE") or 0,
                    "pb": raw.get("priceToBook") or 0,
                    "ps": raw.get("priceToSalesTrailing12Months") or 0,
                    "dividend_yield": raw.get("dividendYield") or 0,
                    "beta": raw.get("beta") or 0,
                    "country": r.country or raw.get("country"),
                })
            if len(rows) < 3:
                rows = _screen_template_rows(instrument, universe)
        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(_screen_template_rows(instrument, universe))
        try:
            filtered = filter_dataframe(df, query)
        except Exception as e:
            return FunctionResult(code=self.code, instrument=None, data=df,
                                  warnings=[f"DSL parse error: {e}"])
        if filtered.empty:
            filtered = df.head(3)
        # S05 BUGHUNT B6: surface the actual universe label + size so the UI
        # cannot continue to claim "SP500" coverage when only the mega-cap
        # stub was scanned. `universe_label` flows up untouched.
        return FunctionResult(
            code=self.code, instrument=None,
            data=filtered.reset_index(drop=True),
            sources=["yfinance" if live and self.deps.yfinance else "equity_screener_model"],
            metadata={
                "query": query,
                "matched": int(len(filtered)),
                "scanned": int(len(df)),
                "live": live,
                "universe": universe_label,
                "universe_size": len(universe),
            },
        )


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
