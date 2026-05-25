"""HVT — Historical realized-volatility table.

Side-by-side realized-vol estimators across user-selectable rolling
windows. Ships four estimators (close-to-close, Parkinson, Garman-Klass,
Yang-Zhang) so a trader can compare same-window estimators that weight
OHLC information differently.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
    ColumnSpec,
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def hvt() -> FunctionManifest:
    return FunctionManifest(
        code="HVT",
        name="Historical Volatility Trends",
        category=Category.DERIVATIVES,
        intent=(
            "Compare four realized-volatility estimators (close-to-close, "
            "Parkinson, Garman-Klass, Yang-Zhang) across configurable rolling "
            "windows for a chosen instrument."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.INDEX,
            AssetClass.FX,
            AssetClass.COMMODITY,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Instrument ticker or canonical pair.",
            ),
            InputSpec(
                name="windows",
                label="Rolling windows",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Trailing trading-day windows to evaluate.",
                options=[10, 20, 30, 60, 90, 120, 180, 252],
                unit="days",
            ),
            InputSpec(
                name="estimators",
                label="Estimators",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Which realized-vol estimators to compute.",
                options=["close_to_close", "parkinson", "garman_klass", "yang_zhang"],
            ),
            InputSpec(
                name="annualization_factor",
                label="Annualization",
                control=ControlKind.NUMBER,
                required=True,
                description="Trading days per year for the sqrt-time scaling.",
                min=200,
                max=365,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="lookback_days",
                label="History window",
                control=ControlKind.NUMBER,
                required=True,
                description="Calendar days of daily OHLC history to load.",
                min=30,
                max=1095,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "symbol": "SPY",
            "windows": [30, 60, 90, 252],
            "estimators": ["close_to_close", "parkinson", "garman_klass", "yang_zhang"],
            "annualization_factor": 252,
            "lookback_days": 365,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=300,
            scope="per_input",
            persist=False,
        ),
        output_contract=OutputContract(
            must_have=["symbol", "spot", "as_of", "rows", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="iso8601", label="Date"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Annualized realized vol"),
            panes=[
                PaneGrammar(name="rolling_vol", series_kind="line", height_pct=100),
            ],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="estimator", label="Estimator", kind="tag"),
                ColumnSpec(key="window_days", label="Window", kind="number", unit="days", format="%.0f"),
                ColumnSpec(key="realized_vol_pct", label="RV (%)", kind="percent", format="%.2f"),
                ColumnSpec(key="realized_vol", label="RV (dec.)", kind="number", format="%.4f"),
                ColumnSpec(key="samples", label="Samples", kind="number", format="%.0f"),
                ColumnSpec(key="formula", label="Formula", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="spot", label="Spot", kind="big_number", unit="$"),
                CardSlot(key="current_realized_vol_pct", label="RV (latest)", kind="kpi", unit="%"),
                CardSlot(key="history_window_days", label="Roll window", kind="badge", unit="days"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "Pull daily OHLC for the symbol over the lookback window. For each "
            "(estimator, rolling-window) pair compute an annualized realized "
            "volatility using sqrt(annualization_factor) scaling. "
            "close_to_close = stdev(log close-to-close returns); Parkinson uses "
            "the high/low range; Garman-Klass extends Parkinson with the "
            "open/close term; Yang-Zhang combines overnight return variance, "
            "open-to-close variance, and the Rogers-Satchell drift-independent "
            "term to handle opening gaps. The first row of the rolling line "
            "chart is the historical track for the primary estimator at the "
            "shortest window; the table holds every (estimator, window) pair."
        ),
        formula_dict={
            "close_to_close": Formula(
                expression=r"\sigma_{CC} = \sqrt{\tfrac{A}{n} \sum_{t=1}^{n} r_t^2}, \quad r_t = \ln(C_t / C_{t-1})",
                variables={
                    "C_t": "Close on day t",
                    "n": "Window length in trading days",
                    "A": "annualization_factor (e.g. 252)",
                },
                notes="Classic Parkinson (1980) close-to-close estimator.",
            ),
            "parkinson": Formula(
                expression=r"\sigma_{Park} = \sqrt{\frac{A}{4 n \ln 2} \sum_{t=1}^{n} \left( \ln(H_t / L_t) \right)^2}",
                variables={
                    "H_t": "Daily high",
                    "L_t": "Daily low",
                    "n": "Window length",
                    "A": "annualization_factor",
                },
                notes="Parkinson (1980); ~5× more efficient than close-to-close under GBM, ignores opening gaps.",
            ),
            "garman_klass": Formula(
                expression=(
                    r"\sigma_{GK} = \sqrt{\frac{A}{n} \sum_{t=1}^{n} \left( "
                    r"\tfrac{1}{2} (\ln(H_t/L_t))^2 - (2 \ln 2 - 1) (\ln(C_t/O_t))^2 "
                    r"\right)}"
                ),
                variables={
                    "O_t": "Daily open",
                    "C_t": "Daily close",
                    "H_t": "Daily high",
                    "L_t": "Daily low",
                },
                notes="Garman-Klass (1980) extends Parkinson by adding the open/close term.",
            ),
            "yang_zhang": Formula(
                expression=(
                    r"\sigma_{YZ}^2 = \sigma_{ON}^2 + k \sigma_{OC}^2 + (1-k) \sigma_{RS}^2, "
                    r"\quad k = \frac{0.34}{1.34 + (n+1)/(n-1)}"
                ),
                variables={
                    "sigma_ON": "Overnight return variance",
                    "sigma_OC": "Open-to-close variance",
                    "sigma_RS": "Rogers-Satchell drift-independent term",
                    "k": "Yang-Zhang weighting parameter",
                },
                notes=(
                    "Yang-Zhang (2000) combines overnight, open-to-close, and "
                    "Rogers-Satchell terms — robust to opening gaps and drift."
                ),
            ),
        },
        field_dict={
            "spot": FieldDef(unit="$", description="Latest close.", source="quote provider"),
            "rows[].estimator": FieldDef(description="Estimator name.", source="config"),
            "rows[].window_days": FieldDef(unit="days", description="Rolling window length.", source="config"),
            "rows[].realized_vol": FieldDef(unit="decimal", description="Annualized realized vol as a decimal.", source="computed"),
            "rows[].realized_vol_pct": FieldDef(unit="%", description="Annualized realized vol in percent.", source="computed"),
            "rows[].samples": FieldDef(unit="days", description="Daily returns used for the estimator.", source="computed"),
            "history[].date": FieldDef(unit="iso8601", description="Bar date.", source="provider"),
            "history[].vol": FieldDef(unit="decimal", description="Rolling realized vol (decimal).", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="hvt_returns_all_four_estimators",
                description=(
                    "Given the default symbol and windows, rows include at least one entry "
                    "per estimator (close_to_close, parkinson, garman_klass, yang_zhang) at "
                    "each requested window."
                ),
                inputs={
                    "symbol": "SPY",
                    "windows": [30, 60, 90, 252],
                    "estimators": ["close_to_close", "parkinson", "garman_klass", "yang_zhang"],
                },
                assertions=[
                    "rows_cover_every_estimator",
                    "rows_cover_every_window",
                    "realized_vol_finite",
                ],
            ),
            SemanticTest(
                name="hvt_parkinson_matches_reference_close_form",
                description=(
                    "For a hand-pinned (H, L) sequence the Parkinson estimator matches the "
                    "closed-form value to within 1e-6."
                ),
                inputs={
                    "highs": [101, 102, 103, 104, 105],
                    "lows": [100, 101, 102, 103, 104],
                    "annualization_factor": 252,
                },
                assertions=["parkinson_matches_reference_within_1e-6"],
            ),
            SemanticTest(
                name="hvt_no_history_returns_provider_unavailable_not_silent_zero",
                description=(
                    "Without daily OHLC history the function returns status=provider_unavailable "
                    "with a reason — never a row of zero-vol estimators pretending to be live."
                ),
                inputs={"symbol": "ZZZ_NOT_REAL"},
                assertions=[
                    "status_is_provider_unavailable_or_not_configured",
                    "rows_empty_or_reference_labelled",
                    "reason_explains_missing_history",
                ],
            ),
        ],
    )


__all__ = ["hvt"]
