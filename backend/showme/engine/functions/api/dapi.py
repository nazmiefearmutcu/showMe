"""DAPI — Data API for Excel/external clients (REST surface specification).

Two-tier resolution:
  1. If the running sidecar wired a live route-table provider into
     ``FunctionDeps.dapi_route_provider`` (set by server.py at startup),
     DAPI returns the actual FastAPI routes — guaranteed in sync.
  2. Otherwise DAPI falls back to the curated manifest below, which is
     kept aligned with ``backend/showme/server_routes/*.py``. Audit gate:
     ``backend/tests/test_dapi.py::test_curated_manifest_matches_routes``
     ensures the curated list does not drift from the real router table.

Filter resolution (2026-09 fix): the routed ``/api/fn/{code}`` layer merges
generic agent defaults into EVERY call — for a CRYPTO desk that bundle carries
``query="bitcoin cryptocurrency"``, which is a news topic, not a route filter.
DAPI used to apply it as its own filter and silently returned zero rows (the
pane showed "ROUTES 0/46" and blamed an attaching engine). The manifest is
never silently emptied: explicit filters use ``path_filter`` (or ``filter``),
and a routed legacy ``query`` that matches no route is ignored and reported
via ``warnings`` + ``summary.ignored_filter``.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


# Curated manifest — keep aligned with ``backend/showme/server_routes/*.py``.
# Each row's ``path`` MUST match the FastAPI route exactly (no /api/v1 prefix,
# the live sidecar mounts everything under /api directly).
DAPI_CURATED_ROUTES: list[dict[str, str]] = [
    # ── health / sidecar ──
    {"method": "GET", "path": "/api/health", "purpose": "Sidecar and engine health check.", "request_body": "-", "response_shape": "{ ok, engine }", "mutates_state": "no", "example": "/api/health"},
    {"method": "GET", "path": "/api/sidecar/info", "purpose": "Sidecar version, build metadata, runtime info.", "request_body": "-", "response_shape": "{ version, build, runtime }", "mutates_state": "no", "example": "/api/sidecar/info"},
    {"method": "GET", "path": "/api/sidecar/ticker", "purpose": "Cheap heartbeat for native UI keep-alive.", "request_body": "-", "response_shape": "{ tick, monotonic }", "mutates_state": "no", "example": "/api/sidecar/ticker"},
    # ── function dispatch ──
    {"method": "GET", "path": "/api/function-index", "purpose": "Registered function catalog used by the native sidebar.", "request_body": "-", "response_shape": "FunctionIndexEntry[]", "mutates_state": "no", "example": "/api/function-index"},
    {"method": "GET/POST", "path": "/api/fn/{code}", "purpose": "Run any ShowMe function with JSON params.", "request_body": "{ symbol?, asset_class?, params... }", "response_shape": "FunctionCallResult", "mutates_state": "depends on function", "example": "/api/fn/BQL"},
    # ── quote / symbol ──
    {"method": "GET", "path": "/api/quote/{symbol}", "purpose": "Fast quote lookup for a symbol.", "request_body": "-", "response_shape": "{ symbol, price, change, source }", "mutates_state": "no", "example": "/api/quote/AAPL"},
    {"method": "GET", "path": "/api/symbol/resolve", "purpose": "Resolve user input to a canonical symbol/asset class.", "request_body": "-", "response_shape": "{ symbol, asset_class, source }", "mutates_state": "no", "example": "/api/symbol/resolve?q=btc"},
    # ── portfolio / state ──
    {"method": "GET", "path": "/api/state/positions", "purpose": "Local portfolio position snapshot.", "request_body": "-", "response_shape": "Position[]", "mutates_state": "no", "example": "/api/state/positions"},
    {"method": "GET", "path": "/api/state/trades", "purpose": "Local trade-log snapshot.", "request_body": "-", "response_shape": "Trade[]", "mutates_state": "no", "example": "/api/state/trades"},
    {"method": "GET", "path": "/api/state/migrations", "purpose": "Migration status for persisted local state.", "request_body": "-", "response_shape": "{ applied, pending }", "mutates_state": "no", "example": "/api/state/migrations"},
    {"method": "GET", "path": "/api/llm/cost", "purpose": "Aggregate LLM cost telemetry for local sessions.", "request_body": "-", "response_shape": "{ total_usd, by_model }", "mutates_state": "no", "example": "/api/llm/cost"},
    {"method": "POST", "path": "/api/portfolio/positions/{symbol}/close", "purpose": "Preview or close a local portfolio position.", "request_body": "{ quantity?, dry_run? }", "response_shape": "{ closed, realized_pnl, remaining_qty }", "mutates_state": "yes unless dry_run=true", "example": "/api/portfolio/positions/BTCUSDT/close"},
    # ── broker (paper) ──
    {"method": "GET", "path": "/api/broker/info", "purpose": "Paper broker identity/status.", "request_body": "-", "response_shape": "{ broker, mode }", "mutates_state": "no", "example": "/api/broker/info"},
    {"method": "GET", "path": "/api/broker/positions", "purpose": "Paper broker position snapshot.", "request_body": "-", "response_shape": "Position[]", "mutates_state": "no", "example": "/api/broker/positions"},
    {"method": "POST", "path": "/api/broker/positions/{symbol}/close", "purpose": "Close a paper broker position.", "request_body": "{ quantity?, dry_run? }", "response_shape": "{ closed, realized_pnl }", "mutates_state": "yes unless dry_run=true", "example": "/api/broker/positions/AAPL/close"},
    {"method": "GET", "path": "/api/broker/orders", "purpose": "Paper broker order blotter.", "request_body": "-", "response_shape": "Order[]", "mutates_state": "no", "example": "/api/broker/orders"},
    {"method": "POST", "path": "/api/broker/orders", "purpose": "Create a paper order.", "request_body": "{ symbol, side, qty, type, tif }", "response_shape": "Order", "mutates_state": "yes", "example": "/api/broker/orders"},
    {"method": "DELETE", "path": "/api/broker/orders/{order_id}", "purpose": "Cancel an open paper order.", "request_body": "-", "response_shape": "{ cancelled, order_id }", "mutates_state": "yes", "example": "/api/broker/orders/{order_id}"},
    # ── scanner ──
    {"method": "GET", "path": "/api/scanner/universes", "purpose": "List available scanner universes.", "request_body": "-", "response_shape": "Universe[]", "mutates_state": "no", "example": "/api/scanner/universes"},
    {"method": "POST", "path": "/api/scanner/run", "purpose": "Run a scanner job synchronously.", "request_body": "{ universe, filters? }", "response_shape": "ScanResult", "mutates_state": "no", "example": "/api/scanner/run"},
    # ── MIS (Multi-Indicator Scan) ──
    {"method": "GET", "path": "/api/mis/markets", "purpose": "List MIS market presets (CRYPTO/EQUITY/...).", "request_body": "-", "response_shape": "MarketPreset[]", "mutates_state": "no", "example": "/api/mis/markets"},
    {"method": "GET", "path": "/api/mis/indicators", "purpose": "List MIS indicators with weights.", "request_body": "-", "response_shape": "Indicator[]", "mutates_state": "no", "example": "/api/mis/indicators"},
    {"method": "GET", "path": "/api/mis/config", "purpose": "Read current MIS calibration.", "request_body": "-", "response_shape": "MISConfig", "mutates_state": "no", "example": "/api/mis/config"},
    {"method": "PUT", "path": "/api/mis/config", "purpose": "Update MIS calibration.", "request_body": "MISConfig", "response_shape": "MISConfig", "mutates_state": "yes", "example": "/api/mis/config"},
    {"method": "POST", "path": "/api/mis/scan", "purpose": "Run MIS consensus scan.", "request_body": "{ market, tfs?, limit? }", "response_shape": "MISRow[]", "mutates_state": "no", "example": "/api/mis/scan"},
    # ── INSTANT line ──
    {"method": "GET", "path": "/api/instant/status", "purpose": "INSTANT line status.", "request_body": "-", "response_shape": "{ ok, sources }", "mutates_state": "no", "example": "/api/instant/status"},
    {"method": "GET", "path": "/api/instant/events", "purpose": "INSTANT recent events.", "request_body": "-", "response_shape": "InstantEvent[]", "mutates_state": "no", "example": "/api/instant/events"},
    {"method": "GET", "path": "/api/instant/health", "purpose": "INSTANT health probe.", "request_body": "-", "response_shape": "{ ok }", "mutates_state": "no", "example": "/api/instant/health"},
    {"method": "GET", "path": "/api/instant/performance", "purpose": "INSTANT latency/perf stats.", "request_body": "-", "response_shape": "{ latency_ms_p50, p95 }", "mutates_state": "no", "example": "/api/instant/performance"},
    {"method": "POST", "path": "/api/instant/backfill", "purpose": "Trigger INSTANT backfill for missed events.", "request_body": "{ since?, source? }", "response_shape": "{ inserted, scanned }", "mutates_state": "yes", "example": "/api/instant/backfill"},
    # ── watchlists ──
    {"method": "GET", "path": "/api/watchlists", "purpose": "List local watchlists.", "request_body": "-", "response_shape": "Watchlist[]", "mutates_state": "no", "example": "/api/watchlists"},
    {"method": "PUT", "path": "/api/watchlists/{name}", "purpose": "Create/replace a watchlist.", "request_body": "{ symbols, meta? }", "response_shape": "Watchlist", "mutates_state": "yes", "example": "/api/watchlists/default"},
    {"method": "DELETE", "path": "/api/watchlists/{name}", "purpose": "Delete a watchlist.", "request_body": "-", "response_shape": "{ deleted }", "mutates_state": "yes", "example": "/api/watchlists/default"},
    # ── agent / ASK ──
    {"method": "POST", "path": "/api/agent/best-symbol", "purpose": "Rank open function set for a chosen symbol.", "request_body": "{ symbol }", "response_shape": "RankedFn[]", "mutates_state": "no", "example": "/api/agent/best-symbol"},
    {"method": "POST", "path": "/api/ask", "purpose": "Conversational research assistant.", "request_body": "{ q, history? }", "response_shape": "{ answer, citations }", "mutates_state": "no", "example": "/api/ask"},
    # ── veryfinder ──
    {"method": "GET", "path": "/api/veryfinder/health", "purpose": "VeryFinder health probe.", "request_body": "-", "response_shape": "{ ok }", "mutates_state": "no", "example": "/api/veryfinder/health"},
    {"method": "GET", "path": "/api/veryfinder/query", "purpose": "VeryFinder lookup.", "request_body": "-", "response_shape": "VeryFinderHit[]", "mutates_state": "no", "example": "/api/veryfinder/query?q=mil"},
    {"method": "POST", "path": "/api/veryfinder/article", "purpose": "Submit an article for VeryFinder analysis.", "request_body": "{ url|text }", "response_shape": "VeryFinderArticle", "mutates_state": "yes", "example": "/api/veryfinder/article"},
    {"method": "POST", "path": "/api/veryfinder/batch", "purpose": "Batch VeryFinder analyses.", "request_body": "Article[]", "response_shape": "VeryFinderArticle[]", "mutates_state": "yes", "example": "/api/veryfinder/batch"},
    # ── X sentiment ──
    {"method": "GET", "path": "/api/x/health", "purpose": "X (Twitter) scraper health probe.", "request_body": "-", "response_shape": "{ ok }", "mutates_state": "no", "example": "/api/x/health"},
    {"method": "POST", "path": "/api/x/analyze", "purpose": "Analyse X posts for a symbol.", "request_body": "{ symbol, limit? }", "response_shape": "XSentiment", "mutates_state": "no", "example": "/api/x/analyze"},
    {"method": "POST", "path": "/api/x/classify", "purpose": "Classify ad-hoc posts.", "request_body": "{ posts }", "response_shape": "XClassification[]", "mutates_state": "no", "example": "/api/x/classify"},
    {"method": "GET", "path": "/api/x/symbol_chip", "purpose": "Compact symbol-level sentiment chip data.", "request_body": "-", "response_shape": "{ bullish, mentions }", "mutates_state": "no", "example": "/api/x/symbol_chip?symbol=AAPL"},
    {"method": "GET", "path": "/api/x/instant_events", "purpose": "X-derived events for INSTANT feed.", "request_body": "-", "response_shape": "InstantEvent[]", "mutates_state": "no", "example": "/api/x/instant_events"},
    # ── streaming ──
    {"method": "GET", "path": "/api/stream/stats", "purpose": "WebSocket stream statistics.", "request_body": "-", "response_shape": "{ connections, by_topic }", "mutates_state": "no", "example": "/api/stream/stats"},
    # ── proxy ──
    {"method": "GET/POST/DELETE", "path": "/api/proxy/{path:path}", "purpose": "Auth-aware proxy to a configured upstream (legacy stub returns 410).", "request_body": "(passthrough)", "response_shape": "(passthrough)", "mutates_state": "depends", "example": "/api/proxy/some/upstream"},
    # ── assistant ──
    {"method": "POST", "path": "/api/assistant/strategy-from-text", "purpose": "Parse natural-language text into a strategy spec (optionally persisting it).", "request_body": "{ text, save? }", "response_shape": "{ spec, notes, saved_id }", "mutates_state": "yes when save=true", "example": "/api/assistant/strategy-from-text"},
    {"method": "POST", "path": "/api/assistant/explain-strategy", "purpose": "Plain-language explanation for a stored strategy id.", "request_body": "{ strategy_id }", "response_shape": "{ explanation }", "mutates_state": "no", "example": "/api/assistant/explain-strategy"},
    # ── bars ──
    {"method": "GET", "path": "/api/bars", "purpose": "OHLCV bars (last N, ascending) for the chart engine; honest empty + reason on provider failure.", "request_body": "-", "response_shape": "{ symbol, interval, bars[], source, asOf, reason? }", "mutates_state": "no", "example": "/api/bars?symbol=BTCUSDT&interval=1m&limit=500"},
    # ── bots ──
    {"method": "GET", "path": "/api/bots", "purpose": "List configured bots with supervision health (running state, last event/action).", "request_body": "-", "response_shape": "{ records[] }", "mutates_state": "no", "example": "/api/bots"},
    {"method": "POST", "path": "/api/bots", "purpose": "Create a bot (forced to shadow mode and disabled on create).", "request_body": "BotRecord fields", "response_shape": "BotRecord", "mutates_state": "yes", "example": "/api/bots"},
    {"method": "GET", "path": "/api/bots/feed", "purpose": "Newest signals aggregated across all bots.", "request_body": "-", "response_shape": "{ generated_at, signals[], per_bot_signal_count }", "mutates_state": "no", "example": "/api/bots/feed?limit=50"},
    {"method": "GET", "path": "/api/bots/performance", "purpose": "Bot performance leaderboard (simulated order sizing, honest provenance).", "request_body": "-", "response_shape": "{ records[], generated_at }", "mutates_state": "no", "example": "/api/bots/performance"},
    {"method": "GET", "path": "/api/bots/{bot_id}", "purpose": "Single bot record plus KAOS per-venue lane status.", "request_body": "-", "response_shape": "BotRecord", "mutates_state": "no", "example": "/api/bots/<bot_id>"},
    {"method": "PUT", "path": "/api/bots/{bot_id}", "purpose": "Update a bot (runtime fields stripped; live mode needs trade perm + label confirmation).", "request_body": "BotRecord fields", "response_shape": "BotRecord", "mutates_state": "yes", "example": "/api/bots/<bot_id>"},
    {"method": "DELETE", "path": "/api/bots/{bot_id}", "purpose": "Delete a bot (disables its runner task first).", "request_body": "-", "response_shape": "{ ok }", "mutates_state": "yes", "example": "/api/bots/<bot_id>"},
    {"method": "POST", "path": "/api/bots/{bot_id}/enable", "purpose": "Enable a bot after broker/credential and live-label checks.", "request_body": "{ confirm_account_label? }", "response_shape": "BotRecord", "mutates_state": "yes", "example": "/api/bots/<bot_id>/enable"},
    {"method": "POST", "path": "/api/bots/{bot_id}/disable", "purpose": "Disable a running bot (cancels its task).", "request_body": "-", "response_shape": "BotRecord", "mutates_state": "yes", "example": "/api/bots/<bot_id>/disable"},
    {"method": "GET", "path": "/api/bots/{bot_id}/performance", "purpose": "Per-bot performance detail with trades and a simulated equity curve.", "request_body": "-", "response_shape": "{ metrics, trades[], equity_curve[], starting_equity }", "mutates_state": "no", "example": "/api/bots/<bot_id>/performance"},
    {"method": "GET", "path": "/api/bots/{bot_id}/signals", "purpose": "Per-bot signal log (FIFO-capped) plus last processed event.", "request_body": "-", "response_shape": "{ bot_id, signals[], last_processed_event }", "mutates_state": "no", "example": "/api/bots/<bot_id>/signals"},
    # ── exchange / credentials ──
    {"method": "GET", "path": "/api/exchange/catalog", "purpose": "Exchange catalog: supported venues and their required secret fields.", "request_body": "-", "response_shape": "ExchangeEntry[]", "mutates_state": "no", "example": "/api/exchange/catalog"},
    {"method": "GET", "path": "/api/exchange/credentials", "purpose": "List stored exchange credentials (secrets are never returned).", "request_body": "-", "response_shape": "{ records[] }", "mutates_state": "no", "example": "/api/exchange/credentials"},
    {"method": "POST", "path": "/api/exchange/credentials", "purpose": "Store a credential after a live auth test (skippable).", "request_body": "{ exchange_id, account_label, secrets, permissions?, skip_test? }", "response_shape": "CredentialRecord", "mutates_state": "yes", "example": "/api/exchange/credentials"},
    {"method": "GET", "path": "/api/exchange/credentials/{credential_id}/dependents", "purpose": "Bots referencing a credential (delete-confirmation warning).", "request_body": "-", "response_shape": "{ credential_id, bot_count, bot_ids[], bots[] }", "mutates_state": "no", "example": "/api/exchange/credentials/<id>/dependents"},
    {"method": "DELETE", "path": "/api/exchange/credentials/{credential_id}", "purpose": "Delete a credential; force=true cascade-disables referencing bots first.", "request_body": "-", "response_shape": "{ ok, cascade[], bots_affected }", "mutates_state": "yes", "example": "/api/exchange/credentials/<id>?force=true"},
    {"method": "PATCH", "path": "/api/exchange/credentials/{credential_id}", "purpose": "Update credential permissions (trade escalation needs label confirmation).", "request_body": "{ permissions?, confirm_account_label? }", "response_shape": "CredentialRecord", "mutates_state": "yes", "example": "/api/exchange/credentials/<id>"},
    {"method": "POST", "path": "/api/exchange/credentials/{credential_id}/test", "purpose": "Live auth test against the venue; stamps last_verified only on success.", "request_body": "-", "response_shape": "{ ok, account?, last_verified?, error? }", "mutates_state": "no", "example": "/api/exchange/credentials/<id>/test"},
    # ── indicators ──
    {"method": "GET", "path": "/api/indicators/catalog", "purpose": "Indicator catalog: ids, parameters and defaults.", "request_body": "-", "response_shape": "IndicatorEntry[]", "mutates_state": "no", "example": "/api/indicators/catalog"},
    {"method": "GET", "path": "/api/indicators/{indicator_id}", "purpose": "Detail for one indicator catalog id.", "request_body": "-", "response_shape": "IndicatorEntry", "mutates_state": "no", "example": "/api/indicators/rsi"},
    # ── integrations ──
    {"method": "GET", "path": "/api/integrations/github/search", "purpose": "GitHub code search; degrades honestly when anonymous access is blocked.", "request_body": "-", "response_shape": "{ q, language, hits[], metadata }", "mutates_state": "no", "example": "/api/integrations/github/search?q=showme"},
    {"method": "POST", "path": "/api/integrations/hf/classify", "purpose": "Classifier inference for ad-hoc text.", "request_body": "{ text }", "response_shape": "{ label, score, ... }", "mutates_state": "no", "example": "/api/integrations/hf/classify"},
    {"method": "POST", "path": "/api/integrations/hf/explain", "purpose": "Plain-language explanation for a strategy id or raw spec.", "request_body": "{ strategy_id | spec }", "response_shape": "{ explanation }", "mutates_state": "no", "example": "/api/integrations/hf/explain"},
    # ── manifest ──
    {"method": "GET", "path": "/api/manifest", "purpose": "List every registered FunctionManifest seed.", "request_body": "-", "response_shape": "FunctionManifest[]", "mutates_state": "no", "example": "/api/manifest"},
    {"method": "GET", "path": "/api/manifest/{code}", "purpose": "Full manifest for one function code.", "request_body": "-", "response_shape": "FunctionManifest", "mutates_state": "no", "example": "/api/manifest/DAPI"},
    # ── MIS progress ──
    {"method": "GET", "path": "/api/mis/scan/progress", "purpose": "Pollable live progress for an in-flight MIS scan (idle/running/done/error).", "request_body": "-", "response_shape": "{ status, ... }", "mutates_state": "no", "example": "/api/mis/scan/progress"},
    # ── portfolio ──
    {"method": "GET", "path": "/api/portfolio/aggregate", "purpose": "Aggregate positions/orders across registered broker credentials.", "request_body": "-", "response_shape": "{ ... }", "mutates_state": "no", "example": "/api/portfolio/aggregate"},
    {"method": "POST", "path": "/api/portfolio/positions", "purpose": "Add a manual position to the local portfolio book.", "request_body": "{ symbol, quantity, avg_cost, account?, notes? }", "response_shape": "{ ok, position, positions_count }", "mutates_state": "yes", "example": "/api/portfolio/positions"},
    # ── strategies ──
    {"method": "GET", "path": "/api/strategies", "purpose": "List stored strategy specs.", "request_body": "-", "response_shape": "{ records[] }", "mutates_state": "no", "example": "/api/strategies"},
    {"method": "POST", "path": "/api/strategies", "purpose": "Create a strategy spec (indicator-catalog validated).", "request_body": "StrategySpec", "response_shape": "StrategySpec", "mutates_state": "yes", "example": "/api/strategies"},
    {"method": "GET", "path": "/api/strategies/{strategy_id}", "purpose": "Single strategy spec.", "request_body": "-", "response_shape": "StrategySpec", "mutates_state": "no", "example": "/api/strategies/<id>"},
    {"method": "PUT", "path": "/api/strategies/{strategy_id}", "purpose": "Update a strategy spec.", "request_body": "StrategySpec", "response_shape": "StrategySpec", "mutates_state": "yes", "example": "/api/strategies/<id>"},
    {"method": "DELETE", "path": "/api/strategies/{strategy_id}", "purpose": "Delete a strategy; force=true cascade-disables dependent bots first.", "request_body": "-", "response_shape": "{ ok, cascade[], bots_affected }", "mutates_state": "yes", "example": "/api/strategies/<id>?force=true"},
    {"method": "GET", "path": "/api/strategies/{strategy_id}/dependents", "purpose": "Bots referencing a strategy (cascade-delete warning).", "request_body": "-", "response_shape": "{ strategy_id, bot_count, bot_ids[], bots[] }", "mutates_state": "no", "example": "/api/strategies/<id>/dependents"},
    {"method": "POST", "path": "/api/strategies/{strategy_id}/preview", "purpose": "Run evaluate() against a deterministic synthetic price series.", "request_body": "{ symbol?, timeframe?, limit? }", "response_shape": "{ ... }", "mutates_state": "no", "example": "/api/strategies/<id>/preview"},
]


def _resolve_routes(provider: Any) -> list[dict[str, Any]] | None:
    """If the sidecar wired in a live ``deps.dapi_route_provider`` callable
    or list, prefer that over the curated table. The provider must yield
    rows in the same shape as ``DAPI_CURATED_ROUTES``."""
    if provider is None:
        return None
    try:
        candidate = provider() if callable(provider) else provider
    except Exception:
        return None
    if isinstance(candidate, list) and all(isinstance(r, dict) for r in candidate):
        return [dict(r) for r in candidate]
    return None


#: Explicit filter keys. The routed ``/api/fn`` merge never injects these,
#: so they are safe for callers that want to narrow the route table.
EXPLICIT_FILTER_KEYS = ("path_filter", "filter")

#: Sentinel the routed ``/api/fn`` layer adds to every merged call
#: (``_agent_runtime._route_function_params``). Direct engine calls do not
#: carry it, so DAPI can tell an explicit invocation from a routed one.
ROUTED_CALL_SENTINEL = "__explicit_symbol"


def _row_matches(row: dict[str, Any], query: str) -> bool:
    """Substring match on path or purpose (the documented filter contract)."""
    return (
        query in str(row.get("path", "")).lower()
        or query in str(row.get("purpose", "")).lower()
    )


def _is_mutating(row: dict[str, Any]) -> bool:
    """True when a route can change local state (``yes`` or ``depends``)."""
    return str(row.get("mutates_state", "")).strip().lower().startswith(("yes", "depends"))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _explicit_filter(params: dict[str, Any]) -> str:
    """Return the caller-supplied route filter (collision-free keys first)."""
    for key in EXPLICIT_FILTER_KEYS:
        raw = params.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip().lower()
    return ""


def _resolve_query(
    params: dict[str, Any],
    endpoints: list[dict[str, Any]],
) -> tuple[str, str | None, list[str]]:
    """Resolve the effective filter without ever silently emptying the table.

    Returns ``(query, ignored_query, warnings)``. ``path_filter``/``filter``
    are always honored. The legacy ``query`` alias is honored unless the call
    was routed AND the value matches no mounted route — that is the generic
    agent default the routing layer injects (a news query), which must not be
    mistaken for user intent.
    """
    query = _explicit_filter(params)
    if query:
        return query, None, []
    legacy = str(params.get("query") or "").strip().lower()
    if not legacy:
        return "", None, []
    if ROUTED_CALL_SENTINEL in params and not any(
        _row_matches(row, legacy) for row in endpoints
    ):
        warning = (
            f"Ignored query filter '{legacy}': the routed /api/fn layer merges "
            "the desk's generic agent defaults (news query) into every call and "
            "this value matches no mounted route. The route manifest is never "
            "silently emptied — pass path_filter=... (or filter=...) for an "
            "explicit route filter."
        )
        return "", legacy, [warning]
    return legacy, None, []


@FunctionRegistry.register
class DAPIFunction(BaseFunction):
    code = "DAPI"
    name = "ShowMe Data API"
    category = "api"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        live = _resolve_routes(getattr(self.deps, "dapi_route_provider", None))
        endpoints = live if live is not None else [dict(row) for row in DAPI_CURATED_ROUTES]
        source_mode = "live_router_introspection" if live is not None else "curated_manifest"
        query, ignored_filter, warnings = _resolve_query(params, endpoints)
        rows = [row for row in endpoints if not query or _row_matches(row, query)]
        if _truthy(params.get("mutates_only")):
            rows = [row for row in rows if _is_mutating(row)]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "rows": rows,
                "summary": {
                    "base_url": "http://127.0.0.1:<sidecar-port>",
                    "endpoints": len(rows),
                    "total_routes": len(endpoints),
                    # F9 [L]: the pane's "mutating" filter also counts
                    # "depends ..." rows, so the summary must agree with the
                    # filter it labels (yes + depends), not just "yes".
                    "state_changing": sum(1 for row in rows if _is_mutating(row)),
                    "filter": query or "all",
                    # Routed-call honesty: when the generic agent-default
                    # query was ignored, surface exactly which value was
                    # dropped (never a silent zero-row response).
                    "ignored_filter": ignored_filter,
                    "source_mode": source_mode,
                },
                "methodology": (
                    "DAPI surfaces the ShowMe sidecar's REST manifest. When the running sidecar "
                    "publishes a live route-introspection callable (deps.dapi_route_provider), DAPI "
                    "returns the actual FastAPI router table so Excel/external clients see the same "
                    "shape the engine serves. Otherwise it falls back to the curated manifest in "
                    "showme/engine/functions/api/dapi.py::DAPI_CURATED_ROUTES — kept aligned with "
                    "backend/showme/server_routes/*.py and audited by tests/test_dapi.py. "
                    "Filtering: pass path_filter=... (or filter=...) to narrow by substring on "
                    "path/purpose; legacy query=... is honored for direct calls and for routed "
                    "calls only when it matches a route — the /api/fn routing layer injects a "
                    "generic news query into every call, and an ignored injected value is reported "
                    "in warnings + summary.ignored_filter instead of silently emptying the table. "
                    "Auth: X-ShowMe-Token (or Authorization: Bearer ...) gates /api/* when "
                    "SHOWME_AUTH_TOKEN is set; /api/health and the sidecar info endpoints stay open."
                ),
                "field_dictionary": {
                    "method": "HTTP verb; slash-joined when a single path accepts multiple verbs.",
                    "path": "Mounted sidecar route.",
                    "purpose": "User-facing action exposed by the route.",
                    "request_body": "JSON body shape when required.",
                    "response_shape": "High-level response contract.",
                    "mutates_state": "Whether the endpoint can change local portfolio/broker state.",
                    "source_mode": "curated_manifest vs live_router_introspection.",
                    "summary.ignored_filter": (
                        "Routed agent-default query dropped because it matched no route "
                        "(null when no filter was ignored)."
                    ),
                },
            },
            warnings=warnings,
            sources=["showme_fastapi_routes_live" if live is not None else "showme_fastapi_routes_curated"],
        )
