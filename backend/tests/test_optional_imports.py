"""Optional third-party packages must not break module import.

``python-binance`` is an optional extra (it is only needed for a Binance
connection). Before 2026-11-07 ``engine/api/binance_client.py`` imported it
unconditionally, so on a clean install ``engine.data.market_data``,
``engine.trading.execution_engine`` and ``engine.services.bot_service`` —
and every test that touches them — failed at import time. The contract now:
the modules import without the package, and only an actual Binance
connection attempt fails, with an explicit, typed reason.
"""
from __future__ import annotations

import importlib
import sys

import pytest

_BLOCKED = ("binance", "binance.client", "binance.exceptions")
_DEPENDENTS = (
    "showme.engine.api.binance_client",
    "showme.engine.data.market_data",
    "showme.engine.trading.execution_engine",
    "showme.engine.services.bot_service",
)


@pytest.fixture
def no_binance(monkeypatch):
    """Simulate an environment where python-binance is not installed."""
    for name in _BLOCKED:
        # A ``None`` entry in sys.modules makes ``import name`` raise ImportError.
        monkeypatch.setitem(sys.modules, name, None)
    for name in _DEPENDENTS:
        # Force a fresh import under the blocked environment; monkeypatch
        # restores the original module objects afterwards.
        monkeypatch.delitem(sys.modules, name, raising=False)


@pytest.mark.parametrize("module_name", _DEPENDENTS)
def test_module_imports_without_python_binance(no_binance, module_name):
    module = importlib.import_module(module_name)
    assert module is not None


def test_binance_client_reports_missing_package_on_initialize(no_binance):
    binance_client = importlib.import_module("showme.engine.api.binance_client")
    assert binance_client.BINANCE_AVAILABLE is False

    client = binance_client.BinanceClient({"mode": "paper"})  # construction stays cheap
    with pytest.raises(binance_client.BinanceUnavailableError, match="python-binance"):
        client.initialize()


def test_fallback_exception_types_are_catchable(no_binance):
    binance_client = importlib.import_module("showme.engine.api.binance_client")
    for exc_type in (binance_client.BinanceAPIException, binance_client.BinanceRequestException):
        assert issubclass(exc_type, Exception)
        with pytest.raises(exc_type):
            raise exc_type("boom")
