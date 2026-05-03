"""DES — Description (şirket özeti).

DATA PIPELINE:
  Source: yfinance (primary), Finnhub /stock/profile2 (secondary), SEC EDGAR (tertiary)
  Cache:  refdata cache (12h)
  Latency: <500 ms warm
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class DESFunction(BaseFunction):
    code = "DES"
    name = "Description"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.FUND, AssetClass.REIT)
    category = "equity"
    description = "Şirket özeti — sektör, market cap, çalışan sayısı, IPO tarihi, kısa açıklama."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("DES requires an instrument")
        warnings: list[str] = []
        sources_used: list[str] = []
        rd = None
        provider_timeout = max(1.0, min(float(params.get("refdata_timeout", params.get("yfinance_timeout", 2.5))), 4.0))
        deadline = asyncio.get_running_loop().time() + max(2.0, min(float(params.get("timeout", 6)), 8.0))
        # Try chain: yfinance → finnhub → sec_edgar
        for src_name in ("yfinance", "finnhub", "sec_edgar"):
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
            rd = {
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
                "description": "Reference data provider unavailable for this symbol.",
                "status": "provider_unavailable",
                "reason": "Reference data providers returned no usable company description within the latency budget.",
                "next_actions": [
                    "Retry DES after yfinance/Finnhub/SEC reference providers recover.",
                    "Increase refdata_timeout for an interactive company profile lookup.",
                ],
            }
            sources_used = ["yfinance", "finnhub", "sec_edgar"]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=rd,
            sources=sources_used,
            metadata={"asset_class": instrument.asset_class.value, "provider_errors": warnings},
        )

    def _render_html(self, r: FunctionResult) -> str:
        rd = r.data
        if rd is None:
            return f"<section class='showme-fn'><h2>{self.code}</h2><p class='warn'>No data</p></section>"
        return f"""
<section class="showme-fn fn-des" data-code="DES">
  <header class="fn-header">
    <div class="fn-symbol">{rd.symbol}</div>
    <div class="fn-name">{rd.name or ''}</div>
  </header>
  <div class="fn-grid grid-2">
    <div class="card"><label>Sektör</label><span>{rd.sector or '—'}</span></div>
    <div class="card"><label>Endüstri</label><span>{rd.industry or '—'}</span></div>
    <div class="card"><label>Market Cap</label><span>{(rd.market_cap or 0)/1e9:.2f}B</span></div>
    <div class="card"><label>Çalışan</label><span>{rd.employees or '—'}</span></div>
    <div class="card"><label>Borsa</label><span>{rd.exchange or '—'}</span></div>
    <div class="card"><label>Para</label><span>{rd.currency or '—'}</span></div>
    <div class="card"><label>Ülke</label><span>{rd.country or '—'}</span></div>
    <div class="card"><label>IPO</label><span>{rd.ipo_date or '—'}</span></div>
  </div>
  <p class="fn-summary">{rd.description or ''}</p>
  <footer class="fn-footer">sources: {', '.join(r.sources)} · {r.fetched_at:%Y-%m-%d %H:%M}</footer>
</section>"""
