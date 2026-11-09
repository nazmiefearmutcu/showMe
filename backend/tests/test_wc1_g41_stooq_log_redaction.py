"""wc1-g41: Stooq API key must not reach the sidecar log through httpx (SEC-1 follow-up).

httpx logs every request URL at INFO on the ``httpx`` logger, including the
query string that carries ``apikey``. Offline: the HTTP layer is an httpx MockTransport.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest

from showme import chart_history


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_stooq_request_log_line_does_not_carry_api_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "STOOQ-LOG-SECRET-4d8e"
    monkeypatch.setenv(chart_history.STOOQ_API_KEY_ENV, secret)
    real_client = httpx.AsyncClient

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too many requests")

    class _MockClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(_handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(RuntimeError):
        _run(chart_history.fetch_stooq_history(
            symbol="AAPL", asset_class="EQUITY", interval="1d", days=365, bars=100,
        ))
    httpx_lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert any("stooq.com" in line for line in httpx_lines), "httpx request log not captured"
    assert all(secret not in line for line in httpx_lines)
    assert secret not in caplog.text


def test_httpx_logger_redacts_stooq_apikey_directly() -> None:
    logger = logging.getLogger("httpx")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.INFO)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            "HTTP Request: %s %s",
            "GET",
            "https://stooq.com/q/d/l/?s=aapl.us&i=d&apikey=DIRECT-SECRET-1",
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
    assert records, "record was not emitted"
    text = records[-1].getMessage()
    assert "DIRECT-SECRET-1" not in text
    assert "stooq.com/q/d/l/" in text
