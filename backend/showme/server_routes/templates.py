"""Routes: /api/templates/* — list, get, instantiate."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Response

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.templates")


# H-API-5: enforce ``symbol`` is a single non-empty trimmed string. Reject
# lists (the old ``str([list])`` coercion turned them into
# ``"['BTC', 'ETH']"``), control chars, newline injection, and empty input.
# MEDIUM (whitespace symbol reject): trim + reject empty.
# LOW (control char reject): reject anything outside printable ASCII.
_SYMBOL_FORMAT_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")


def _coerce_symbol(raw: Any) -> str:
    """Coerce ``raw`` to a clean symbol string or raise HTTPException(422).

    Pulled out as a helper so the templates and (future) other routes can
    share the contract. Accepted shape: ``BASE/QUOTE`` where each side is
    ``[A-Z0-9]+``.
    """
    if isinstance(raw, (list, tuple, dict, bool)):
        raise HTTPException(
            422, detail="symbol must be a string, not a list/object",
        )
    if not isinstance(raw, str):
        raise HTTPException(422, detail="symbol must be a string")
    # Reject newline / tab / control chars (defense-in-depth, log injection).
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in raw):
        raise HTTPException(422, detail="symbol contains control characters")
    cleaned = raw.strip().upper()
    if not cleaned:
        raise HTTPException(422, detail="symbol cannot be empty / whitespace")
    if not _SYMBOL_FORMAT_RE.fullmatch(cleaned):
        raise HTTPException(
            422,
            detail=f"symbol format must be BASE/QUOTE (got {raw!r})",
        )
    return cleaned


_CATALOG = None
_CATALOG_ERROR: str | None = None  # Faz 2 / H-19 — surfaced via 500


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "catalog" / "templates.yml"


def _indicator_catalog_ids() -> set[str]:
    """Return the set of known indicator ids for spec validation.

    Mirrors the ``_catalog_ids`` helper in ``strategies.py`` so the
    template instantiate path enforces the SAME catalog contract that
    the strategies create/update routes already enforce — an
    instantiated spec must only reference real catalog indicators.
    A failed catalog load degrades to an empty set (validation skipped)
    so a broken indicator catalog never blocks instantiation that the
    strategies routes would otherwise allow.
    """
    try:
        from showme.indicators.catalog.loader import load_indicator_catalog
        cat = load_indicator_catalog(
            Path(__file__).resolve().parents[1]
            / "indicators" / "catalog" / "indicators.yml"
        )
        return {e.id for e in cat.entries}
    except Exception as exc:  # noqa: BLE001
        LOG.warning("indicator catalog unavailable for validation: %s", exc)
        return set()


def _get_catalog():
    """Return the cached catalog or raise HTTPException(500) on failure.

    Faz 2 / H-19 — the old code swallowed the YAML load error and
    returned an empty ``TemplateCatalog()``; the UI then rendered "no
    templates" with no hint that the catalog file was broken on disk.
    Now we cache the formatted error message and bubble it as a 500
    with informative ``detail`` on every subsequent call.
    """
    global _CATALOG, _CATALOG_ERROR
    if _CATALOG is None and _CATALOG_ERROR is None:
        from showme.templates.loader import load_template_catalog
        try:
            _CATALOG = load_template_catalog(_catalog_path())
        except Exception as exc:  # noqa: BLE001
            _CATALOG_ERROR = f"{type(exc).__name__}: {exc}"
            LOG.error("template catalog failed to load: %s", _CATALOG_ERROR)
    if _CATALOG_ERROR is not None:
        raise HTTPException(
            500,
            detail=f"template catalog failed to load: {_CATALOG_ERROR}",
        )
    return _CATALOG


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/templates")
    async def templates_list() -> list[dict[str, Any]]:
        return _get_catalog().to_payload()

    @router.get("/api/templates/{template_id}")
    async def templates_detail(template_id: str) -> dict[str, Any]:
        try:
            return _get_catalog().by_id(template_id).to_dict()
        except KeyError:
            raise HTTPException(404, detail=f"unknown template: {template_id}")

    @router.post("/api/templates/{template_id}/instantiate")
    async def templates_instantiate(
        template_id: str,
        response: Response,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from showme.strategies.spec import StrategySpec
        from showme.strategies.store import StrategyStore

        payload = payload or {}
        try:
            entry = _get_catalog().by_id(template_id)
        except KeyError:
            raise HTTPException(404, detail=f"unknown template: {template_id}")

        body = dict(entry.spec_template)
        if "name" in payload and payload["name"]:
            # H-API-5 — name must be a string, not a list/dict/bool.
            raw_name = payload["name"]
            if not isinstance(raw_name, str):
                raise HTTPException(422, detail="name must be a string")
            body["name"] = raw_name
        if "symbol" in payload and payload["symbol"]:
            # H-API-5 — coerce + validate. Old code did ``str(payload["symbol"])``
            # which turned ``["BTC","ETH"]`` into ``"['BTC', 'ETH']"`` —
            # silent data corruption.
            symbol = _coerce_symbol(payload["symbol"])
            af = dict(body.get("asset_filter") or {})
            af["symbols"] = [symbol]
            body["asset_filter"] = af
        # Strip server-controlled fields if they snuck in.
        for k in ("id", "created_at", "updated_at"):
            body.pop(k, None)

        # MEDIUM (recommended_timeframe warning header): if the template
        # exposes a recommended_timeframe and the caller's body / template
        # combination would deviate, surface a non-fatal X-Showme-Warning.
        # (Currently the symbol is the only caller override; future
        # ``timeframe`` overrides will benefit from the same header.)
        rec_tf = getattr(entry, "recommended_timeframe", None)
        body_tf = body.get("timeframe")
        if rec_tf and body_tf and rec_tf != body_tf:
            response.headers["X-ShowMe-Warning"] = (
                f"template recommends timeframe={rec_tf} but spec has {body_tf}"
            )

        try:
            spec = StrategySpec(**body)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, detail=f"invalid template spec: {exc}")
        # Data-integrity parity with the strategies create/update routes:
        # the instantiated spec must reference only real catalog indicators.
        # Previously this path skipped the catalog check, so a template that
        # drifted from the indicator catalog could persist a strategy the
        # strategies routes would have rejected.
        cat_ids = _indicator_catalog_ids()
        if cat_ids:
            try:
                spec.validate_against_catalog(cat_ids)
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc))
        saved = StrategyStore.fresh().save(spec)
        return {
            "template_id": template_id,
            "strategy": saved.model_dump(),
        }

    app.include_router(router)
