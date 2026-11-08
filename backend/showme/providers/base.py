"""DataMode enum + ProviderAdapter ABC + AdapterError exception.

This module defines the contract every provider adapter in
``showme.providers`` must satisfy. The interface is deliberately small:
adapters expose a set of named capabilities, report their authentication +
quota + latency state, and resolve to a canonical ``DataMode`` so the rest
of the app can decide what badge / disclaimer to render.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Literal

from urllib.parse import quote, quote_plus

import httpx

__all__ = [
    "DataMode",
    "ProviderAdapter",
    "AdapterError",
    "redact_secrets",
    "get_redacted",
    "raise_for_status_redacted",
]


class DataMode(str, Enum):
    """Canonical effective-data-source state for any adapter.

    Values are strings so the enum serialises straight through to JSON
    without a custom encoder. The exact string spellings are part of the
    public contract — see ``test_data_mode_values_stable``.
    """

    LIVE_OFFICIAL = "live_official"
    LIVE_EXCHANGE = "live_exchange"
    DELAYED_REFERENCE = "delayed_reference"
    MODELED = "modeled"
    CACHED_SNAPSHOT = "cached_snapshot"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NOT_CONFIGURED = "not_configured"


class AdapterError(RuntimeError):
    """Raised by adapters when an upstream call fails in a structured way.

    Adapters MUST set ``self._last_error`` to the underlying exception
    (this one or the original) so ``mode()`` can resolve to
    ``provider_unavailable`` on subsequent reads.
    """


# Query-string credentials used by the free providers (FRED ``api_key``,
# Alpha Vantage ``apikey``, Finnhub/EODHD ``token``/``api_token``, OWM
# ``appid``, EIA ``api_key``). An HTTP error message embeds the full request
# URL, so the key must be masked before it reaches an exception or a log.
_SECRET_PARAM_RE = re.compile(
    r"(?i)(?<![A-Za-z])(api_key|apikey|api_token|token|appid)=([^&\s'\"<>)]+)"
)


# A key in a URL is anchored by ``?`` or ``&``. This also covers TradingEconomics'
# ``c=<key>`` without masking unrelated ``c=`` text elsewhere in a message.
_URL_CREDENTIAL_RE = re.compile(
    r"(?i)([?&](?:c|api_key|apikey|api_token|token|appid)=)([^&\s'\"<>)]+)"
)


def _secret_variants(secret: str) -> list[str]:
    """The raw key plus the percent-encoded forms httpx may put in a URL."""
    variants = {secret, quote(secret, safe=""), quote_plus(secret, safe="")}
    return sorted(variants, key=len, reverse=True)


def redact_secrets(text: Any, *secrets: str | None) -> str:
    """Mask API keys in ``text``: literal and encoded key values, and ``key=...`` query pairs."""
    out = str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            for variant in _secret_variants(secret):
                out = out.replace(variant, "***")
    out = _URL_CREDENTIAL_RE.sub(lambda m: f"{m.group(1)}***", out)
    return _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}=***", out)


class _RedactHttpxLogLines(logging.Filter):
    """httpx logs every request URL at INFO, so keys in query strings reach the log file.

    Redacting here covers all callers, including ones that never see the key.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — never block a log record
            return True
        clean = redact_secrets(message)
        if clean != message:
            record.msg, record.args = clean, ()
        return True


logging.getLogger("httpx").addFilter(_RedactHttpxLogLines())


def _redacted_http_error(exc: httpx.HTTPStatusError, secrets: tuple[str | None, ...]) -> httpx.HTTPStatusError:
    """Copy of an HTTP status error whose message, request and response hold no key."""
    request = exc.request
    safe_url = redact_secrets(str(request.url), *secrets)
    safe_request = httpx.Request(request.method, safe_url)
    safe_response = httpx.Response(exc.response.status_code, request=safe_request)
    return httpx.HTTPStatusError(
        redact_secrets(str(exc), *secrets),
        request=safe_request,
        response=safe_response,
    )


def raise_for_status_redacted(response: httpx.Response, *secrets: str | None) -> None:
    """``response.raise_for_status()`` with the key masked in the error text.

    The re-raised error is built outside the ``except`` block so the original
    (key-bearing) exception is not kept as ``__context__``.
    """
    failure: httpx.HTTPStatusError | None = None
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        failure = exc
    if failure is not None:
        raise _redacted_http_error(failure, secrets) from None


async def get_redacted(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    secrets: tuple[str | None, ...] = (),
) -> httpx.Response:
    """GET ``url`` and raise on HTTP errors without leaking ``secrets``.

    Transport errors are re-raised with the same type and a redacted message.
    """
    failure: httpx.HTTPError | None = None
    response: httpx.Response | None = None
    try:
        response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        failure = exc
    if failure is not None:
        message = redact_secrets(str(failure), *secrets)
        try:
            redacted: httpx.HTTPError = type(failure)(message)
        except TypeError:
            redacted = httpx.HTTPError(message)
        raise redacted from None
    raise_for_status_redacted(response, *secrets)  # type: ignore[arg-type]
    return response  # type: ignore[return-value]


_AuthState = Literal["ok", "missing_key", "invalid_key", "not_required"]


class ProviderAdapter(ABC):
    """Abstract base for every upstream-data adapter."""

    name: ClassVar[str]
    nominal_mode: ClassVar[DataMode] = DataMode.LIVE_OFFICIAL

    def __init__(self) -> None:
        # State carried across calls. Subclasses MUST update these from
        # inside their request methods (success -> _last_latency_ms set,
        # _last_error cleared; failure -> _last_error set).
        self._last_latency_ms: int | None = None
        self._last_error: Exception | None = None

    # ---- contract -----------------------------------------------------

    @abstractmethod
    def capabilities(self) -> set[str]:
        """Named capabilities this adapter exposes.

        e.g. ``{"company_submissions", "xbrl_facts"}`` for SEC EDGAR.
        """

    def auth_state(self) -> _AuthState:
        """Default 'not_required'; override if adapter needs credentials."""
        return "not_required"

    def quota_state(self) -> dict[str, Any]:
        """Best-effort remaining requests / reset window. Empty when unknown."""
        return {}

    def last_latency_ms(self) -> int | None:
        """Latency of most recent successful upstream call, ms."""
        return self._last_latency_ms

    def mode(self) -> DataMode:
        """Resolve the current effective DataMode.

        Resolution order:
          1. If ``auth_state()`` indicates a credential problem
             (``missing_key`` / ``invalid_key``) → ``NOT_CONFIGURED``.
          2. Else if the most recent call recorded an error
             (``self._last_error is not None``) → ``PROVIDER_UNAVAILABLE``.
          3. Else the adapter's nominal mode (defaults to ``LIVE_OFFICIAL``).
        """
        auth = self.auth_state()
        if auth in ("missing_key", "invalid_key"):
            return DataMode.NOT_CONFIGURED
        if self._last_error is not None:
            return DataMode.PROVIDER_UNAVAILABLE
        return self.nominal_mode

    # ---- helpers for subclasses --------------------------------------

    def _record_success(self, latency_ms: int) -> None:
        """Record a successful upstream call. Clears any prior error."""
        self._last_latency_ms = int(latency_ms)
        self._last_error = None

    def _record_failure(self, exc: Exception) -> None:
        """Record a failed upstream call. ``mode()`` will flip to UNAVAILABLE.

        The stored error never carries an API key from a query string.
        """
        message = redact_secrets(exc)
        self._last_error = exc if message == str(exc) else AdapterError(message)
