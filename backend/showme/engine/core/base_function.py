"""BaseFunction ABC — Bloomberg-style function contract.

Every Bloomberg function (DES, FA, EE, ANR, EQS, ECO, WIRP, ...) becomes
a subclass implementing ``execute()`` and ``render()``. A global
``FunctionRegistry`` maps the function code (``"DES"``, ``"FA"``...) to the
class, so ``Command Palette`` and the URL routes (``/symbol/AAPL/FA``) can
look it up by string.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.utils.helpers import datetime_now


RenderFormat = Literal["json", "html", "cli", "markdown"]


@dataclass
class FunctionResult:
    """Output envelope returned by every BaseFunction.execute().

    The ``data`` field is intentionally typed as Any — different functions
    return DataFrames, dicts, lists. ``metadata`` provides provenance and
    freshness so the UI can show a "data age" badge.
    """
    code: str
    instrument: Instrument | None
    data: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime_now)
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the result.

        Pandas DataFrames are converted via ``to_dict(orient="records")``
        so the envelope can be encoded by FastAPI's default ``jsonable``
        path. Other ``data`` shapes are passed through verbatim.
        """
        try:
            import pandas as pd  # noqa: F401
            data = self.data
            if hasattr(data, "to_dict"):
                data = data.to_dict(orient="records") if hasattr(data, "to_dict") else data
        except Exception:
            data = self.data
        return {
            "code": self.code,
            "instrument": self.instrument.to_dict() if self.instrument else None,
            "data": data,
            "metadata": self.metadata,
            "fetched_at": self.fetched_at.isoformat(),
            "sources": self.sources,
            "warnings": self.warnings,
            "elapsed_ms": self.elapsed_ms,
        }


class BaseFunction(ABC):
    """Abstract Bloomberg-style function.

    Subclass attributes:
        code: 2-6 letter function code ("DES", "FA", "ECO", "WIRP")
        name: human readable
        asset_classes: which AssetClass values this function makes sense for
        category: "equity"|"bond"|"fx"|"commodity"|"macro"|"news"|"trade"|...
    """
    code: str
    name: str
    asset_classes: tuple[AssetClass, ...] = ()
    category: str = "misc"
    description: str = ""

    def __init__(self, deps: "FunctionDeps | None" = None) -> None:
        self.deps = deps or FunctionDeps()

    @abstractmethod
    async def execute(
        self, instrument: Instrument | None = None, **params: Any
    ) -> FunctionResult:
        """Run the function and return a :class:`FunctionResult` envelope.

        Subclasses may raise on irrecoverable provider failures, but the
        recommended convention is to return a ``FunctionResult`` whose
        ``data`` carries a ``status`` string from
        ``showme.function_contracts.ERROR_STATUSES``. The shared envelope
        layer turns that into the public ``payload.status``.
        """

    def render(
        self, result: FunctionResult, format: RenderFormat = "json"
    ) -> str:
        """Default renderer — JSON. Subclasses override for html/cli."""
        import json
        if format == "json":
            return json.dumps(result.to_dict(), default=str, indent=2)
        if format == "markdown":
            return self._render_markdown(result)
        if format == "cli":
            return self._render_cli(result)
        if format == "html":
            return self._render_html(result)
        return json.dumps(result.to_dict(), default=str)

    # Subclasses can override these for prettier output.
    def _render_markdown(self, r: FunctionResult) -> str:
        return f"# {self.code} — {self.name}\n\n```\n{r.data}\n```"

    def _render_cli(self, r: FunctionResult) -> str:
        return self._render_markdown(r)

    def _render_html(self, r: FunctionResult) -> str:
        # Default: very minimal HTML. Concrete functions override.
        body = (
            r.data.to_html(classes="showme-table") if hasattr(r.data, "to_html") else f"<pre>{r.data}</pre>"
        )
        sources = ", ".join(r.sources) if r.sources else "—"
        return (
            f'<section class="showme-fn" data-code="{self.code}">'
            f'<h2>{self.code} — {self.name}</h2>'
            f'<div class="showme-fn-body">{body}</div>'
            f'<footer class="showme-fn-meta">sources: {sources} · fetched: {r.fetched_at:%Y-%m-%d %H:%M}</footer>'
            f'</section>'
        )

    async def execute_timed(
        self, instrument: Instrument | None = None, **params: Any
    ) -> FunctionResult:
        """Execute with elapsed-time stamping."""
        t0 = time.perf_counter()
        result = await self.execute(instrument=instrument, **params)
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        return result


@dataclass
class FunctionDeps:
    """Container of typed dependencies handed to every function.

    Concrete data adapters are wired in by ``src/services/function_factory.py``.
    Here we keep the typed slots so unit tests can pass mocks.
    """
    yfinance: Any = None
    finnhub: Any = None
    alphavantage: Any = None
    polygon: Any = None
    eodhd: Any = None
    sec_edgar: Any = None
    sec_13f: Any = None
    sec_efts: Any = None
    seekingalpha: Any = None
    finra: Any = None
    fred: Any = None
    worldbank: Any = None
    ecb: Any = None
    eia: Any = None
    tradingeconomics: Any = None
    openfigi: Any = None
    gdelt: Any = None
    benzinga: Any = None
    finnhub_news: Any = None
    rss: Any = None
    binance: Any = None
    ccxt: Any = None
    coingecko: Any = None
    cryptocompare: Any = None
    ccxt_failover: Any = None
    notion: Any = None
    granola: Any = None
    polymarket: Any = None
    treasury_auctions: Any = None
    imf: Any = None
    oecd: Any = None
    exchangerate_host: Any = None
    stooq: Any = None
    openweather: Any = None
    stocktwits: Any = None
    reddit: Any = None
    sentinelhub: Any = None
    cme_fedwatch: Any = None
    damodaran: Any = None
    glassnode: Any = None
    etherscan: Any = None
    mempool: Any = None
    opensky: Any = None
    market_store: Any = None      # DuckDB persistent store
    market_cache: Any = None      # in-memory L1 cache
    symbol_registry: Any = None
    llm_router: Any = None
    # DAPI live route-table provider — populated by server.py at startup so
    # the DAPI function can return the actual FastAPI router manifest
    # instead of the curated fallback. Callable or pre-materialised list.
    dapi_route_provider: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        """Return the named adapter (or ``None`` when not wired)."""
        return getattr(self, key, None) or self.extras.get(key)


class FunctionRegistry:
    """Singleton-ish registry mapping function codes to BaseFunction classes.

    ``register`` is typically called from each function module's bottom.
    The dashboard's ``/symbol/<sym>/<code>`` route looks up here.
    """
    _instances: dict[str, type[BaseFunction]] = {}

    @classmethod
    def register(cls, fn_cls: type[BaseFunction]) -> type[BaseFunction]:
        """Register a BaseFunction subclass keyed on its uppercased ``code``.

        Raises ``ValueError`` if ``code`` is missing or if another class is
        already registered under the same code (per ARCH-10 P1 — duplicate
        registrations silently overwrote each other and made the loser dead
        code). Re-registering the same class object is a no-op so module
        re-imports during tests stay safe.
        """
        if not getattr(fn_cls, "code", None):
            raise ValueError(f"{fn_cls.__name__} missing 'code' attribute")
        upper = fn_cls.code.upper()
        existing = cls._instances.get(upper)
        if existing is not None and existing is not fn_cls:
            raise ValueError(
                f"FunctionRegistry: code '{upper}' is already registered by "
                f"{existing.__module__}.{existing.__name__}; cannot register "
                f"{fn_cls.__module__}.{fn_cls.__name__}"
            )
        cls._instances[upper] = fn_cls
        return fn_cls

    @classmethod
    def get(cls, code: str) -> type[BaseFunction] | None:
        """Return the ``BaseFunction`` subclass for ``code``, or ``None`` if unknown.

        Lookup is case-insensitive — both ``"DES"`` and ``"des"`` resolve
        to the same class.
        """
        return cls._instances.get(code.upper())

    @classmethod
    def list_all(cls) -> list[type[BaseFunction]]:
        """Return every registered ``BaseFunction`` subclass."""
        return list(cls._instances.values())

    @classmethod
    def by_asset_class(cls, ac: AssetClass) -> list[type[BaseFunction]]:
        """Return classes whose ``asset_classes`` tuple includes ``ac``."""
        return [f for f in cls._instances.values() if ac in f.asset_classes]

    @classmethod
    def by_category(cls, category: str) -> list[type[BaseFunction]]:
        """Return classes filed under ``category`` (e.g. ``"equity"``)."""
        return [f for f in cls._instances.values() if f.category == category]

    @classmethod
    def codes(cls) -> list[str]:
        """Return every registered uppercased function code, sorted."""
        return sorted(cls._instances.keys())
